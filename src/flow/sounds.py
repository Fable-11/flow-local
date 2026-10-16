"""Soft audio cues (start / stop / error), synthesized in code: no sound files to ship.

Design goals: gentle, never startling. Each cue is a low, rounded "bloop": a sine that glides a
short way up (start) or down (stop), with a soft raised-cosine attack, an exponential decay like
a water drop, a faint octave overtone for warmth, and a low-pass filter that removes any edge.
"""

from __future__ import annotations

import io
import logging
import math
import os
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

RATE = 44_100
DESIGN_VERSION = 2  # bump when the sounds change, so older cached files are not reused


@dataclass(frozen=True)
class Tone:
    f_start: float  # Hz at the start of the tone
    f_end: float  # Hz at the end (an exponential glide between the two)
    duration: float  # seconds
    attack: float = 0.022  # raised-cosine fade-in: no click, no "tick"
    decay: float = 0.075  # exponential decay time constant (smaller = shorter pop)
    gain: float = 1.0
    overtone: float = 0.16  # level of the octave above, for warmth


# name -> tones played back to back
CUES: dict[str, list[Tone]] = {
    "start": [Tone(500.0, 760.0, 0.17)],  # soft rising bloop: "I'm listening"
    "stop": [Tone(690.0, 450.0, 0.17, gain=0.8)],  # soft falling bloop: "got it"
    "error": [Tone(330.0, 300.0, 0.15, gain=0.85), Tone(262.0, 235.0, 0.2, gain=0.8, decay=0.09)],
}

# A shorter, clickier alternative: still rounded (same attack and low-pass), just tighter.
POP_CUES: dict[str, list[Tone]] = {
    "start": [Tone(430.0, 570.0, 0.1, decay=0.035)],
    "stop": [Tone(530.0, 380.0, 0.1, decay=0.035, gain=0.8)],
    "error": CUES["error"],
}
STYLES: dict[str, dict[str, list[Tone]]] = {"soft": CUES, "pop": POP_CUES}

# "windows" style: the chimes Windows ships for speech recognition, read from the system at run
# time (nothing is copied into this project), shortened, softened and normalised.
WINDOWS = "windows"
WINDOWS_FILES = {
    "start": ("Speech On.wav", 0.22),  # (file in C:\Windows\Media, seconds kept)
    "stop": ("Speech Off.wav", 0.36),
    "error": ("Speech Misrecognition.wav", 0.22),
}
WINDOWS_LOWPASS_HZ = 2200.0  # originals sparkle up to 6 kHz: keep the tune, drop the edge
_windows_cache: dict[str, np.ndarray] = {}


def windows_media_dir() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Media"


def windows_available() -> bool:
    return all((windows_media_dir() / f).exists() for f, _s in WINDOWS_FILES.values())


def _windows_samples(name: str) -> np.ndarray:
    """The system chime for a cue: mono, 44.1 kHz, trimmed, low-passed, faded, peak = 1."""
    if name in _windows_cache:
        return _windows_cache[name]
    filename, keep = WINDOWS_FILES[name]
    with wave.open(str(windows_media_dir() / filename)) as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        if width != 2:
            raise ValueError(f"{filename}: only 16-bit audio is supported")
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    x = x[: int(rate * keep)]
    if rate != RATE:
        x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * RATE / rate)), np.arange(len(x)), x)
    x = _lowpass(x, WINDOWS_LOWPASS_HZ)
    fade = int(RATE * 0.07)  # long cosine release: the chime dies away instead of being cut
    x[-fade:] *= 0.5 * (1 + np.cos(np.pi * np.arange(fade) / fade))
    x[:64] *= np.linspace(0.0, 1.0, 64)  # no click if the file starts abruptly
    peak = float(np.abs(x).max()) or 1.0
    _windows_cache[name] = x / peak
    return _windows_cache[name]

LOWPASS_HZ = 2800.0  # nothing brighter than this: takes the edge off
PEAK = 0.42  # loudest sample at 100% volume, as a fraction of full scale

enabled = True  # set from the user's settings
volume = 0.4  # 0..1
style = "soft"  # key of STYLES

_paths: dict[tuple[str, int], str] = {}


def sounds_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FlowLocal" / "sounds"
    base.mkdir(parents=True, exist_ok=True)
    return base


def cue_file(name: str, vol: float, which: str | None = None) -> str:
    """Path of the WAV file for a cue at this volume, written on first use.

    Windows cannot play from memory asynchronously, so cues are played from small files.
    """
    which = which or style
    bucket = round(vol * 100 / 5) * 5  # share files between nearby volume settings
    key = (f"{which}/{name}", bucket)
    path = _paths.get(key)
    if path is None or not Path(path).exists():
        folder = sounds_dir()
        for old in folder.glob(f"{name}_*.wav"):  # files from earlier, sharper designs
            if f"_v{DESIGN_VERSION}_" not in old.name:
                old.unlink(missing_ok=True)
        target = folder / f"{name}_{which}_v{DESIGN_VERSION}_{bucket}.wav"
        target.write_bytes(synth(name, bucket / 100, which))
        path = _paths[key] = str(target)
    return path


def _tones(name: str, which: str | None = None) -> list[Tone]:
    return STYLES.get(which or style, CUES)[name]


def cue_duration(name: str, which: str | None = None) -> float:
    if (which or style) == WINDOWS:
        return len(_windows_samples(name)) / RATE
    return sum(t.duration for t in _tones(name, which))


def _render(tone: Tone) -> np.ndarray:
    n = int(RATE * tone.duration)
    t = np.arange(n) / RATE
    # exponential glide f(t) = f0 * (f1/f0)^(t/T); the phase is its running integral
    ratio = tone.f_end / tone.f_start
    freq = tone.f_start * ratio ** (t / tone.duration)
    phase = 2 * math.pi * np.cumsum(freq) / RATE
    wave_ = np.sin(phase) + tone.overtone * np.sin(2 * phase)
    attack_n = max(1, int(RATE * tone.attack))
    env = np.exp(-t / tone.decay)
    env[:attack_n] *= 0.5 * (1 - np.cos(np.pi * np.arange(attack_n) / attack_n))
    release_n = max(1, min(int(RATE * 0.02), n // 3))  # land on exactly zero
    env[-release_n:] *= 0.5 * (1 + np.cos(np.pi * np.arange(release_n) / release_n))
    return tone.gain * wave_ * env


def _lowpass(x: np.ndarray, cutoff_hz: float) -> np.ndarray:
    """Two cascaded one-pole filters (about -12 dB/octave above the cutoff)."""
    a = 1.0 - math.exp(-2 * math.pi * cutoff_hz / RATE)
    out = x
    for _ in range(2):
        y = np.empty_like(out)
        acc = 0.0
        for i, v in enumerate(out):
            acc += a * (v - acc)
            y[i] = acc
        out = y
    return out


def synth_samples(name: str, vol: float, which: str | None = None) -> np.ndarray:
    """The cue as float samples in -1..1 (before 16-bit quantisation)."""
    if (which or style) == WINDOWS:
        return _windows_samples(name) * PEAK * max(0.0, min(1.0, vol))
    audio = np.concatenate([_render(t) for t in _tones(name, which)])
    audio = _lowpass(audio, LOWPASS_HZ)
    top = float(np.max(np.abs(audio))) or 1.0
    return audio / top * PEAK * max(0.0, min(1.0, vol))


def synth(name: str, vol: float, which: str | None = None) -> bytes:
    """WAV bytes (mono, 16-bit) for a cue at the given volume (0..1)."""
    pcm = np.round(synth_samples(name, vol, which) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def configure(is_enabled: bool, volume_percent: int, sound_style: str = "soft") -> None:
    global enabled, volume, style
    enabled = bool(is_enabled)
    volume = max(0, min(100, int(volume_percent))) / 100
    usable = sound_style in STYLES or (sound_style == WINDOWS and windows_available())
    style = sound_style if usable else "soft"


def play(name: str, force: bool = False) -> bool:
    """Play a cue without blocking. Returns False if sounds are off or playback failed."""
    if (not enabled and not force) or sys.platform != "win32":
        return False
    try:
        import winsound

        winsound.PlaySound(cue_file(name, volume), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return True
    except Exception:  # noqa: BLE001 - a missing sound device must never break dictation
        log.warning("could not play sound %r", name, exc_info=True)
        return False
