"""faster-whisper wrapper: hardware detection, persistent model, prompt building."""

from __future__ import annotations

import gc
import logging
import os
import site
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from flow.stt.models import is_model_cached

# Privacy: never phone home from the model hub library.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("DO_NOT_TRACK", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

log = logging.getLogger(__name__)


# Auto-detect chooses between these. Whisper often mislabels very short audio ("Hello" as Russian,
# Arabic as Persian or Urdu), which garbles the text; this app is for Arabic and English.
ALLOWED_LANGUAGES = ("en", "ar")


def pick_allowed_language(detected: str, probs: list[tuple[str, float]] | None) -> str | None:
    """The language to force when auto-detect picked an unsupported one; None = keep it."""
    if detected in ALLOWED_LANGUAGES or not probs:
        return None
    by_lang = dict(probs)
    best = max(ALLOWED_LANGUAGES, key=lambda lang: by_lang.get(lang, 0.0))
    return best


class ModelNotDownloaded(RuntimeError):
    """The speech model is not on this computer and downloading was not allowed."""

    def __init__(self, name: str) -> None:
        super().__init__(f"speech model '{name}' is not downloaded")
        self.model_name = name


@dataclass(frozen=True)
class ModelChoice:
    name: str
    device: str
    compute_type: str


def add_cuda_dll_dirs() -> None:
    """Make pip-installed nvidia-* DLLs (cublas, cudnn) discoverable on Windows."""
    if os.name != "nt":
        return
    roots: list[Path] = []
    if getattr(sys, "frozen", False):  # PyInstaller build: libraries sit next to the exe
        roots.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)))
    try:
        roots += map(Path, site.getsitepackages())
    except AttributeError:  # frozen/embedded interpreters may lack this
        pass
    for root in roots:
        for bin_dir in (root / "nvidia").glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def cuda_available() -> bool:
    add_cuda_dll_dirs()
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


def choose_model(preferred: str = "auto") -> ModelChoice:
    if cuda_available():
        name = "large-v3-turbo" if preferred == "auto" else preferred
        return ModelChoice(name, "cuda", "float16")
    return ModelChoice("small" if preferred == "auto" else preferred, "cpu", "int8")


def build_initial_prompt(words: list[str], limit_chars: int = 400) -> str | None:
    """Join dictionary words (priority first) into a Whisper initial_prompt."""
    out: list[str] = []
    size = 0
    for w in words:
        if size + len(w) + 2 > limit_chars:
            break
        out.append(w)
        size += len(w) + 2
    return ", ".join(out) if out else None


class SttEngine:
    def __init__(self, choice: ModelChoice | None = None, model_dir: str | None = None) -> None:
        self.choice = choice or choose_model()
        self.model_dir = model_dir
        self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def unload(self) -> None:
        """Free the model (RAM and GPU memory). It is reloaded on demand with load()."""
        self._model = None
        gc.collect()

    def _cache(self) -> Path | None:
        return Path(self.model_dir) if self.model_dir else None

    def load(self, allow_download: bool = False) -> None:
        """Load the model. Downloads (one-time, uses the internet) only if ``allow_download``.

        Raises ModelNotDownloaded if the model is missing and downloading is not allowed.
        """
        from faster_whisper import WhisperModel

        add_cuda_dll_dirs()
        t0 = time.perf_counter()
        try:
            self._model = self._open(WhisperModel, self.choice, allow_download)
        except ModelNotDownloaded:
            raise
        except Exception:
            if self.choice.device != "cuda":
                raise
            log.exception("CUDA load failed, falling back to CPU")
            fallback = "small" if is_model_cached("small", self._cache()) else self.choice.name
            self.choice = ModelChoice(fallback, "cpu", "int8")
            self._model = self._open(WhisperModel, self.choice, allow_download)
        log.info("loaded %s in %.1fs", self.choice, time.perf_counter() - t0)
        self._warm_up()

    def _open(self, cls, choice: ModelChoice, allow_download: bool):  # noqa: ANN001, ANN202
        kwargs = dict(
            device=choice.device, compute_type=choice.compute_type, download_root=self.model_dir
        )
        if not is_model_cached(choice.name, self._cache()):
            if not allow_download:
                raise ModelNotDownloaded(choice.name)
            log.info("model %s not cached; downloading (one-time network use)", choice.name)
            return cls(choice.name, **kwargs)
        # cached model: load fully offline, no network call at all. Real failures (CUDA, memory,
        # corrupt files) propagate as themselves instead of being mistaken for "not downloaded".
        return cls(choice.name, local_files_only=True, **kwargs)

    def _warm_up(self) -> None:
        """Run one dummy decode so the first real dictation does not pay CUDA start-up cost."""
        t0 = time.perf_counter()
        silence = np.zeros(16_000, dtype=np.float32)
        segments, _ = self._model.transcribe(silence, language="en", vad_filter=False, beam_size=1)
        list(segments)
        log.info("warm-up took %.2fs", time.perf_counter() - t0)

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        initial_prompt: str | None = None,
        quiet: bool = False,
    ) -> tuple[str, str, float]:
        """Return (text, detected_language, language_probability)."""
        if self._model is None:
            raise RuntimeError("speech model is not loaded")

        def run(lang: str | None):  # noqa: ANN202
            segments, info = self._model.transcribe(
                audio,
                language=lang,
                initial_prompt=initial_prompt,
                beam_size=3,
                vad_filter=True,
                # generous padding so soft word starts/ends are not clipped by the VAD
                vad_parameters={
                    "threshold": 0.2 if quiet else 0.35,
                    "speech_pad_ms": 400,
                    "min_silence_duration_ms": 800,
                },
                condition_on_previous_text=False,
            )
            return " ".join(s.text.strip() for s in segments).strip(), info

        text, info = run(language)
        if language is None:
            forced = pick_allowed_language(info.language, getattr(info, "all_language_probs", None))
            if forced:  # auto-detect picked an unsupported language: redo it in en or ar
                log.info("language %s unsupported; re-transcribing as %s", info.language, forced)
                text, info = run(forced)
                return text, forced, info.language_probability
        return text, info.language, info.language_probability
