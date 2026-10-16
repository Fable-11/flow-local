"""Voice activity detection helpers (uses faster-whisper's bundled Silero VAD)."""

from __future__ import annotations

import numpy as np

from flow.audio.capture import SAMPLE_RATE


def trim_silence(audio: np.ndarray, threshold: float = 0.5, pad_s: float = 0.2) -> np.ndarray:
    """Return audio between first and last detected speech; empty array if no speech."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    stamps = get_speech_timestamps(audio, VadOptions(threshold=threshold))
    if not stamps:
        return audio[:0]
    pad = int(pad_s * SAMPLE_RATE)
    start = max(0, stamps[0]["start"] - pad)
    end = min(len(audio), stamps[-1]["end"] + pad)
    return audio[start:end]


def is_silent(audio: np.ndarray, rms_floor: float = 0.003) -> bool:
    """Cheap energy check to skip VAD/STT on dead-quiet buffers."""
    return audio.size == 0 or float(np.sqrt(np.mean(audio**2))) < rms_floor
