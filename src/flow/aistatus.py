"""What state is the AI cleanup in, in words a person can act on.

Dictation works without the AI model, using built-in rules, so a missing or sleeping model must
never be a surprise: when it is not working the Home page says so and says what to do. This module
holds the decision (pure, tested) and the two small helpers around it: finding Ollama and starting
it when the user presses the button. Nothing here starts Ollama by itself.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AiStatus:
    code: str  # ready | cold | no_server | no_model | off_setting
    text: str
    can_start: bool = False  # show the "Start Ollama" button


def ollama_exe() -> Path | None:
    """Ollama's program file, found only in the two usual places (never guessed or downloaded)."""
    found = shutil.which("ollama")
    if found:
        return Path(found)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidate = Path(local) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.exists():
            return candidate
    return None


def ai_status(
    *, enabled: bool, reachable: bool, model: str | None, wanted: str, loaded: bool, installed: bool
) -> AiStatus:
    """``model`` is the installed model that will be used (None if there is none), ``wanted`` the
    one the settings ask for."""
    if not enabled:
        return AiStatus("off_setting", "AI cleanup: switched off in Settings.")
    if not reachable:
        if installed:
            return AiStatus(
                "no_server",
                "AI cleanup: off because Ollama is not running. Dictation still works with the "
                "built-in cleanup.",
                can_start=True,
            )
        return AiStatus(
            "no_server",
            "AI cleanup: off. Dictation works with the built-in cleanup. For smarter cleanup "
            "install Ollama from ollama.com.",
        )
    if model is None:
        return AiStatus(
            "no_model",
            f"AI cleanup: Ollama is running but the model '{wanted}' is not installed. "
            f"Run: ollama pull {wanted}",
        )
    if not loaded:
        return AiStatus(
            "cold",
            "AI cleanup: resting. It wakes up when you dictate; the first dictation after a "
            "pause uses the built-in cleanup.",
        )
    return AiStatus("ready", "AI cleanup: ready.")


def start_ollama(exe: Path | None = None) -> bool:
    """Start Ollama's server in the background (no window). Called only from the user's click.

    Returns False when it cannot be found or started. It is not stopped when Flow Local quits,
    like an Ollama the user started themselves."""
    exe = exe or ollama_exe()
    if exe is None:
        return False
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    try:
        subprocess.Popen(  # noqa: S603 - a fixed program path and a fixed argument
            [str(exe), "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        return True
    except OSError:
        return False
