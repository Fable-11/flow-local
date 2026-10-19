"""Microphone capture at 16 kHz mono float32."""

from __future__ import annotations

import collections
import threading
import wave
from collections.abc import Callable

import numpy as np

SAMPLE_RATE = 16_000
BLOCK_SAMPLES = 800  # 50 ms per callback: smooth waveform, few wake-ups


CUE_FRAME = 320  # 20 ms
CUE_SPEECH_FLOOR = 0.02  # louder than any bleed from the soft start sound: it must be a voice


def blank_cue(audio: np.ndarray, start: int, length: int) -> None:
    """Silence the start sound that leaked into the microphone, but keep the user's voice.

    Plain muting clipped the first syllable of short words said right at the key press ("if",
    "queue", a spelled letter). Each 20 ms frame is only blanked when it is quiet like the cue;
    a frame clearly louder than both the cue bleed and the room noise before it is speech.
    """
    segment = audio[start : start + length]
    ambient = float(np.sqrt(np.mean(audio[:start] ** 2))) if start > 0 else 0.0
    threshold = max(CUE_SPEECH_FLOOR, 5.0 * ambient)
    for i in range(0, len(segment), CUE_FRAME):
        frame = segment[i : i + CUE_FRAME]
        if float(np.sqrt(np.mean(frame**2))) <= threshold:
            frame[:] = 0.0


PREROLL_KEEP_S = 0.3  # how much audio from before the key press may join the recording
PREROLL_TAIL_S = 0.1  # the stretch right before the key press that must hold a voice
PREROLL_FLOOR = 0.006


def select_preroll(pre: np.ndarray) -> np.ndarray:
    """Pick the part of the pre-roll that belongs to this dictation.

    The pre-roll exists so a word started a moment before the key press is not cut. But words
    said earlier, then a pause, then the key press, are not part of the dictation and must not
    leak in. So the pre-roll is only kept when someone is still speaking right at the key press,
    and then only the last 0.3 s of it.
    """
    if pre.size == 0:
        return pre
    tail = pre[-int(PREROLL_TAIL_S * SAMPLE_RATE) :]
    frame = int(0.05 * SAMPLE_RATE)
    frames = [pre[i : i + frame] for i in range(0, len(pre) - frame + 1, frame)] or [pre]
    ambient = min(float(np.sqrt(np.mean(f**2))) for f in frames)
    if float(np.sqrt(np.mean(tail**2))) <= max(PREROLL_FLOOR, 3.0 * ambient):
        return pre[:0]
    return pre[-int(PREROLL_KEEP_S * SAMPLE_RATE) :]


class Recorder:
    """Records from the default (or chosen) input device into memory.

    With ``keep_open`` the input stream stays running between dictations and a short rolling
    pre-roll is kept, so words spoken right as the hotkey goes down are not lost to stream
    start-up latency. Audio is only retained while a recording is active.
    """

    def __init__(
        self,
        device: int | str | None = None,
        gain: float = 1.0,
        on_level: Callable[[float], None] | None = None,
        keep_open: bool = True,
        preroll_s: float = 0.5,
    ) -> None:
        self.device = device
        self.gain = gain
        self.on_level = on_level
        self.keep_open = keep_open
        self._preroll_samples = int(preroll_s * SAMPLE_RATE)
        self._preroll: collections.deque[np.ndarray] = collections.deque()
        self._preroll_len = 0
        self._chunks: list[np.ndarray] = []
        self._mute: tuple[int, int] | None = None  # (start, length) of a cue to blank out
        self._recording = False
        self._lock = threading.Lock()
        self._stream = None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        chunk = indata[:, 0].copy() * self.gain
        np.clip(chunk, -1.0, 1.0, out=chunk)
        with self._lock:
            if self._recording:
                self._chunks.append(chunk)
            else:
                self._preroll.append(chunk)
                self._preroll_len += len(chunk)
                while self._preroll_len - len(self._preroll[0]) >= self._preroll_samples:
                    self._preroll_len -= len(self._preroll.popleft())
        if self.on_level and self._recording:  # no UI wake-ups while idle
            self.on_level(float(np.sqrt(np.mean(chunk**2))) if chunk.size else 0.0)

    def open(self) -> None:
        if self._stream is not None:
            return
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=self.device,
            blocksize=BLOCK_SAMPLES,
            callback=self._callback,
        )
        self._stream.start()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def start(self, mute_s: float = 0.0) -> None:
        """Begin recording. ``mute_s``: blank this many seconds right after the start, so a
        start beep played through the speakers is not transcribed."""
        self.open()
        with self._lock:
            heard = np.concatenate(self._preroll) if self._preroll else np.zeros(0, np.float32)
            pre = select_preroll(heard)
            self._chunks = [pre] if pre.size else []
            self._mute = (pre.size, int(mute_s * SAMPLE_RATE)) if mute_s > 0 else None
            self._preroll.clear()
            self._preroll_len = 0
            self._recording = True

    def snapshot(self) -> np.ndarray:
        with self._lock:
            return np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)

    def stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False
        audio = self.snapshot()
        if self._mute and audio.size:
            blank_cue(audio, *self._mute)
        self._mute = None
        if not self.keep_open:
            self.close()
        return audio


def load_wav(path: str) -> np.ndarray:
    """Load a 16-bit PCM WAV as 16 kHz mono float32 (linear resample if needed)."""
    with wave.open(path, "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("only 16-bit PCM WAV is supported")
    data = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if rate != SAMPLE_RATE:
        n = int(len(data) * SAMPLE_RATE / rate)
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data)
    return data.astype(np.float32)


def list_input_devices() -> list[tuple[int, str]]:
    import sounddevice as sd

    return [
        (i, d["name"]) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0
    ]
