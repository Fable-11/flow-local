"""faster-whisper wrapper: hardware detection, persistent model, prompt building."""

from __future__ import annotations

import gc
import logging
import os
import re
import site
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from flow.guards import label_language
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


TINY_GPU_MB = 3500  # below this the big speech model does not fit next to anything else
SMALL_GPU_MB = 8300  # an 8 GB card: the speech model and the AI model must share it
_gpu_mb: int | None = None


def gpu_memory_mb() -> int | None:
    """Total video memory of the first NVIDIA GPU in MiB, or None when it cannot be read."""
    global _gpu_mb
    if _gpu_mb is None:
        try:
            import subprocess

            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=False,
            ).stdout
            _gpu_mb = int(out.strip().splitlines()[0])
        except Exception:  # noqa: BLE001 - no driver tools: fall back to the accurate setting
            _gpu_mb = 0
    return _gpu_mb or None


def choose_compute_type(precision: str = "auto", vram_mb: int | None = None) -> str:
    """float16 is the most exact; int8_float16 halves the speech model's video memory.

    "auto" uses the smaller one on cards with about 8 GB or less, where the AI model is also
    loaded, and the exact one on bigger cards.
    """
    if precision == "accurate":
        return "float16"
    if precision == "small":
        return "int8_float16"
    return "int8_float16" if vram_mb and vram_mb <= SMALL_GPU_MB else "float16"


def choose_model(preferred: str = "auto", precision: str = "auto") -> ModelChoice:
    if cuda_available():
        vram = gpu_memory_mb()
        name = "large-v3-turbo" if preferred == "auto" else preferred
        if preferred == "auto" and vram and vram < TINY_GPU_MB:
            name = "small"  # only on a confirmed reading: an unknown reading changes nothing
        return ModelChoice(name, "cuda", choose_compute_type(precision, vram))
    return ModelChoice("small" if preferred == "auto" else preferred, "cpu", "int8")


MIXED_MIN_AUDIO_S = 3.0  # shorter dictations are one language in practice
MIXED_MIN_CHUNK_S = 1.0  # language detection is unreliable on anything shorter
MIXED_PAUSE_MS = 350
MIXED_MIN_CONFIDENCE = 0.55


def merge_short_chunks(stamps: list[dict], min_samples: int) -> list[tuple[int, int]]:
    """Join speech spans (separated by pauses) so that every chunk is long enough to classify."""
    chunks: list[list[int]] = []
    for s in stamps:
        if chunks and (chunks[-1][1] - chunks[-1][0] < min_samples):
            chunks[-1][1] = s["end"]
        else:
            chunks.append([s["start"], s["end"]])
    if len(chunks) > 1 and chunks[-1][1] - chunks[-1][0] < min_samples:
        last = chunks.pop()
        chunks[-1][1] = last[1]
    return [(a, b) for a, b in chunks]


def split_by_pauses(audio: np.ndarray) -> list[tuple[int, int]]:
    """Sample ranges of the speech chunks in ``audio``, split at pauses of 0.35 s or more."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    stamps = get_speech_timestamps(
        audio,
        VadOptions(threshold=0.35, min_silence_duration_ms=MIXED_PAUSE_MS, speech_pad_ms=200),
    )
    return merge_short_chunks(stamps, int(MIXED_MIN_CHUNK_S * 16_000))


LANG_SURE = 0.85  # language-ID share (of English+Arabic) needed to overrule the setting
LANG_UNSURE = 0.15  # between LANG_UNSURE and 1 - LANG_UNSURE the audio is too unclear to trust
BETTER_BY = 0.1  # the second language must beat the first by this much average log-probability
INVENTED_BELOW = -0.3  # a stock phrase is only dropped when the model was also unsure of it
# What the model makes up when it is forced into the wrong language (or hears silence).
_INVENTED = {
    "اشتركوا في القناة", "اشترك في القناة", "اشتركوا بالقناة", "ترجمة نانسي قنقر",
    "شكرا على المشاهدة", "شكرا لكم على المشاهدة", "subscribe to the channel",
    "please subscribe", "thanks for watching", "thank you for watching",
}


def _normal(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text, flags=re.UNICODE).strip().lower()


_INVENTED_NORMAL = {_normal(s) for s in _INVENTED}


@dataclass(frozen=True)
class Decoded:
    text: str
    quality: float  # average log-probability of the words, higher is better
    language: str
    share: float  # language-ID share of the language used

    @property
    def invented(self) -> bool:
        return _normal(self.text) in _INVENTED_NORMAL and self.quality < INVENTED_BELOW


def segment_quality(segments: list) -> float:
    """Duration-weighted average log-probability, lowered for repetition and for silence."""
    if not segments:
        return -9.0
    total = weight = 0.0
    for s in segments:
        w = max(float(getattr(s, "end", 0.0)) - float(getattr(s, "start", 0.0)), 0.01)
        q = float(getattr(s, "avg_logprob", -0.3))
        if float(getattr(s, "compression_ratio", 1.0)) > 2.4:
            q -= 0.5  # looping text
        if float(getattr(s, "no_speech_prob", 0.0)) > 0.6:
            q -= 0.5
        total += q * w
        weight += w
    return total / weight


def choose_language(preferred: str | None, share_en: float) -> tuple[str, bool]:
    """(language to try first, whether the audio is too unclear to trust that choice).

    The audio decides. The setting only breaks ties: it is overruled when language-ID is sure
    the speech is in the other language.
    """
    if preferred == "ar":
        lean = "en" if share_en >= LANG_SURE else "ar"
    elif preferred == "en":
        lean = "ar" if share_en <= 1 - LANG_SURE else "en"
    else:
        lean = "en" if share_en >= 0.5 else "ar"
    return lean, LANG_UNSURE < share_en < 1 - LANG_UNSURE


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
        """Return (text, main_language, language_share).

        English and Arabic are both understood whatever ``language`` says. The recording is cut
        at pauses and the language of each part is taken from the audio, because a language fixed
        in advance makes the model invent text when the speech is in the other one.
        """
        if self._model is None:
            raise RuntimeError("speech model is not loaded")
        preferred = language if language in ALLOWED_LANGUAGES else None
        chunks = self._speech_chunks(audio)
        shares = [self._english_share(audio[a:b]) for a, b in chunks]
        if len(chunks) > 1 and None not in shares:
            plan = [choose_language(preferred, s) for s in shares]
            if len({lean for lean, _ in plan}) == 1 and not any(unsure for _, unsure in plan):
                # one language throughout: decode the recording once and keep its context
                lean = plan[0][0]
                whole = self._decode(audio, lean, initial_prompt, quiet, sum(shares) / len(shares))
                if not whole.invented and whole.text:
                    return whole.text, label_language(whole.text, lean), whole.share
        parts: list[str] = []
        weight: dict[str, int] = {}
        share = 1.0
        for (a, b), share_en in zip(chunks, shares, strict=True):
            done = self._decode_chunk(audio[a:b], preferred, initial_prompt, quiet, share_en)
            if done.text:
                parts.append(done.text)
                weight[done.language] = weight.get(done.language, 0) + (b - a)
                share = done.share
        main = max(weight, key=weight.get) if weight else (preferred or "en")
        joined = " ".join(parts).strip()
        return joined, label_language(joined, main), share

    def _speech_chunks(self, audio: np.ndarray) -> list[tuple[int, int]]:
        whole = [(0, len(audio))]
        if len(audio) < int(MIXED_MIN_AUDIO_S * 16_000):
            return whole
        try:
            return split_by_pauses(audio) or whole
        except Exception:  # noqa: BLE001 - never lose a dictation to the splitting step
            log.exception("could not split the recording at pauses")
            return whole

    def _english_share(self, chunk: np.ndarray) -> float | None:
        """English's share of the English+Arabic language-ID probability, or None if unavailable."""
        try:
            _lang, _prob, probs = self._model.detect_language(chunk, vad_filter=False)
            by_lang = dict(probs or [])
            en, ar = by_lang.get("en", 0.0), by_lang.get("ar", 0.0)
            return en / (en + ar) if en + ar > 0 else None
        except Exception:  # noqa: BLE001
            log.exception("language check failed; using the language setting")
            return None

    def _decode(
        self, chunk: np.ndarray, lang: str, prompt: str | None, quiet: bool, share: float
    ) -> Decoded:
        segments, _info = self._model.transcribe(
            chunk,
            language=lang,
            initial_prompt=prompt,
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
        segs = list(segments)
        text = " ".join(s.text.strip() for s in segs).strip()
        return Decoded(text, segment_quality(segs), lang, share if lang == "en" else 1 - share)

    def _decode_chunk(
        self,
        chunk: np.ndarray,
        preferred: str | None,
        prompt: str | None,
        quiet: bool,
        share_en: float | None,
    ) -> Decoded:
        if share_en is None:  # no language check: trust the setting (English when it is automatic)
            return self._decode(chunk, preferred or "en", prompt, quiet, 1.0)
        lean, unsure = choose_language(preferred, share_en)
        first = self._decode(chunk, lean, prompt, quiet, share_en)
        if not unsure and not first.invented:
            return first
        other = "ar" if lean == "en" else "en"
        second = self._decode(chunk, other, prompt, quiet, share_en)
        if first.invented and second.invented:
            return Decoded("", -9.0, lean, share_en)
        if first.invented or (not second.invented and second.quality > first.quality + BETTER_BY):
            return second
        return first
