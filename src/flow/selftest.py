"""`python -m flow selftest`: does everything Flow Local needs actually work on this computer?

Safe to run and safe to paste: nothing is played aloud (the test voice goes to a file), the
clipboard is put back, no recording is made, and the report holds no user name, no device names,
no dictations and no window titles. Hardware names appear only with --hardware.
"""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SENTENCE = "please send the report tomorrow morning"
MIN_FREE_VRAM_MB = 2200  # the speech model (small form) plus working space


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail | skip
    detail: str = ""


def redact(text: str, home: Path | None = None, user: str | None = None) -> str:
    """Remove the Windows user name and home folder from text that may be pasted publicly."""
    home_text = str(home or Path.home())
    user = user or os.environ.get("USERNAME") or os.environ.get("USER") or ""
    text = text.replace(home_text, "~")
    if user and len(user) > 2:
        text = text.replace(user, "<user>")
    return text


# -- the checks --------------------------------------------------------------------------------
def check_python() -> Check:
    return Check("Python", "ok", f"{platform.python_version()} on {platform.system()}")


def check_microphones() -> Check:
    from flow.audio.capture import list_input_devices

    count = len(list_input_devices())
    if count == 0:
        return Check("Microphone", "fail", "no input device found: plug in or enable a microphone")
    return Check("Microphone", "ok", f"{count} input device(s) found")


def check_data_folder() -> Check:
    from flow.store.db import default_db_path

    folder = default_db_path().parent
    probe = folder / ".selftest"
    try:
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return Check("Data folder", "fail", f"cannot write to {redact(str(folder))}: {e}")
    return Check("Data folder", "ok", f"writable ({redact(str(folder))})")


def check_clipboard() -> Check:
    """Write a marker, read it back, and put the user's own clipboard back."""
    from flow.insert import clipboard

    marker = f"flow-selftest-{time.time_ns()}"
    with clipboard.preserved_clipboard() as holder:
        holder.seq = clipboard.set_text(marker)
        got = clipboard.get_text()
    if got != marker:
        return Check("Clipboard", "fail", "could not write and read the clipboard")
    return Check("Clipboard", "ok", "round trip works and your clipboard was put back")


def check_cleanup() -> Check:
    from flow.cleanup.rules import clean_rules

    out = clean_rules("um send it to Ahmed no no I mean Omar tomorrow")
    if out != "Send it to Omar tomorrow.":
        return Check("Built-in cleanup", "fail", "unexpected result from the cleanup rules")
    return Check("Built-in cleanup", "ok", "fillers, corrections and punctuation work")


def check_mixer() -> Check:
    from flow.audio.ducking import SystemSessions

    sessions = SystemSessions().sessions()
    return Check("Other sounds", "ok", f"Windows volume mixer reachable ({len(sessions)} programs)")


def check_ai() -> Check:
    from flow.aistatus import ai_status, ollama_exe
    from flow.cleanup.llm import OllamaClient
    from flow.config import Settings

    s = Settings()
    client = OllamaClient()
    reachable = client.available()
    model = client.resolve_model() if reachable else None
    loaded = bool(model) and client.is_loaded()
    st = ai_status(
        enabled=True, reachable=reachable, model=model, wanted=s.llm_model, loaded=loaded,
        installed=ollama_exe() is not None,
    )
    detail = st.text.removeprefix("AI cleanup: ")
    return Check("AI cleanup", "ok" if st.code in ("ready", "cold") else "warn", detail)


def _voice_to_file(path: Path) -> str | None:
    """Speak the test sentence into a WAV file with the Windows voice. None if it worked,
    otherwise the reason it could not."""
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo("
        "16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
        "[System.Speech.AudioFormat.AudioChannel]::Mono); "
        f"$s.SetOutputToWaveFile('{path}', $f); $s.Speak('{SENTENCE}'); $s.Dispose()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=60, check=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return f"no Windows voice available ({type(e).__name__})"
    return None if path.exists() and path.stat().st_size > 1000 else "the voice made no audio"


def check_speech(include_hardware: bool = False) -> Check:
    from flow.audio.capture import load_wav
    from flow.stt.engine import ModelChoice, SttEngine, choose_model, gpu_free_mb
    from flow.stt.models import is_model_cached

    choice = choose_model()
    note = ""
    if choice.device == "cuda":
        free = gpu_free_mb()
        if free is not None and free < MIN_FREE_VRAM_MB:
            choice = ModelChoice("small", "cpu", "int8")
            note = " (video memory is busy, so the CPU model was used)"
    if not is_model_cached(choice.name):
        return Check("Speech model", "skip", f"'{choice.name}' is not downloaded yet "
                     "(Settings > Models > Download now)")
    wav = Path(tempfile.gettempdir()) / f"flow_selftest_{os.getpid()}.wav"
    try:
        problem = _voice_to_file(wav)
        if problem:
            return Check("Speech model", "skip", problem)
        engine = SttEngine(choice)
        engine.load(allow_download=False)
        text, _lang, _share = engine.transcribe(load_wav(str(wav)))
    finally:
        wav.unlink(missing_ok=True)
    words = {w.strip(".,").lower() for w in text.split()}
    expected = set(SENTENCE.split())
    heard = len(words & expected) / len(expected)
    where = f"{choice.name} on {choice.device}" if include_hardware else "loaded"
    if heard >= 0.7:
        return Check("Speech model", "ok", f"{where}; understood the test sentence{note}")
    part = "understood only part of the test sentence"
    return Check("Speech model", "warn", f"{where}; {part}{note}")


def all_checks(include_hardware: bool = False) -> list[Callable[[], Check]]:
    return [
        check_python, check_microphones, check_data_folder, check_clipboard, check_cleanup,
        check_mixer, check_ai, lambda: check_speech(include_hardware),
    ]


def run(checks: list[Callable[[], Check]]) -> list[Check]:
    """Run every check; one that crashes is reported as failed and never stops the others."""
    results = []
    for check in checks:
        try:
            results.append(check())
        except Exception as e:  # noqa: BLE001
            name = getattr(check, "__name__", "check").replace("check_", "").replace("_", " ")
            results.append(Check(name.capitalize(), "fail", f"{type(e).__name__}: {e}"))
    return results


def report(results: list[Check], version: str) -> str:
    marks = {"ok": "[ok]  ", "warn": "[warn]", "fail": "[FAIL]", "skip": "[skip]"}
    lines = [f"Flow Local {version} self-check"]
    for r in results:
        lines.append(f"{marks[r.status]} {r.name}: {r.detail}")
    n = {k: sum(r.status == k for r in results) for k in marks}
    lines.append(
        f"Result: {n['ok']} ok, {n['warn']} warning(s), {n['skip']} skipped, {n['fail']} failed"
    )
    return redact("\n".join(lines))


def exit_code(results: list[Check]) -> int:
    return 1 if any(r.status == "fail" for r in results) else 0
