"""Make quiet recordings usable: rumble filter, light noise reduction, automatic volume boost.

Speaking far from the microphone gives a recording whose speech is tiny compared with full scale.
The speech model copes poorly with that, and a fixed volume cut-off ("anything quieter than X is
silence") throws it away completely. This module measures the recording instead of assuming a
level: how loud the quiet frames (noise) and the loud frames (speech) are, how far above the
noise the speech sits, and boosts accordingly.

Pure numpy; about 10 ms of work per second of audio.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16_000
FRAME = int(0.02 * SAMPLE_RATE)  # 20 ms analysis frames

TARGET_PEAK = 0.5  # boosted recordings are brought to about this peak
NORMAL_PEAK = 0.25  # at or above this the recording is loud enough and is left alone
MAX_GAIN_DB = 40.0  # never boost more than 100x
ABSOLUTE_FLOOR = 0.0005  # peak below this is a muted or disconnected microphone
MIN_SNR_DB = 1.5  # speech must sit at least this far above the noise floor
DENOISE_ABOVE_GAIN_DB = 12.0  # light noise reduction only when a big boost would amplify noise


@dataclass(frozen=True)
class AudioStats:
    peak: float  # robust peak (99.8th percentile of |x|)
    noise_rms: float  # level of the quietest frames: the room and microphone noise
    speech_rms: float  # level of the loudest frames: the speech
    snr_db: float  # how far the speech is above the noise

    @property
    def too_quiet(self) -> bool:
        """Barely any signal at all: a muted microphone or nothing was said."""
        return self.peak < ABSOLUTE_FLOOR or self.snr_db < MIN_SNR_DB


@dataclass(frozen=True)
class Prepared:
    audio: np.ndarray
    stats: AudioStats  # measured on the recording BEFORE the boost
    gain_db: float  # boost applied, 0 if none
    denoised: bool

    @property
    def silent(self) -> bool:
        return self.stats.too_quiet


def _frame_rms(audio: np.ndarray) -> np.ndarray:
    n = len(audio) // FRAME
    if n == 0:
        return np.array([float(np.sqrt(np.mean(audio**2))) if audio.size else 0.0])
    frames = audio[: n * FRAME].reshape(n, FRAME)
    return np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))


def analyze(audio: np.ndarray) -> AudioStats:
    if audio.size == 0:
        return AudioStats(0.0, 0.0, 0.0, 0.0)
    rms = _frame_rms(audio)
    noise = float(np.percentile(rms, 10))
    speech = float(np.percentile(rms, 95))
    peak = float(np.percentile(np.abs(audio), 99.8))
    snr = 20 * np.log10((speech + 1e-9) / (noise + 1e-9))
    return AudioStats(peak, noise, speech, float(snr))


def highpass(audio: np.ndarray, cutoff_hz: float = 70.0) -> np.ndarray:
    """Remove DC offset and low rumble (desk thumps, fans) with a smooth FFT roll-off."""
    if audio.size < 64:
        return audio
    spec = np.fft.rfft(audio.astype(np.float64))
    freqs = np.fft.rfftfreq(len(audio), 1 / SAMPLE_RATE)
    gain = np.clip((freqs - cutoff_hz * 0.5) / (cutoff_hz * 0.5), 0.0, 1.0)  # 0 below half cutoff
    return np.fft.irfft(spec * gain, n=len(audio)).astype(np.float32)


def reduce_noise(audio: np.ndarray, strength: float = 1.6, floor: float = 0.12) -> np.ndarray:
    """Spectral gating: learn the noise spectrum from the quietest frames and attenuate it.

    Gentle on purpose (it is only used on recordings that need a big boost, where noise would
    otherwise be amplified together with the speech).
    """
    n_fft, hop = 512, 128
    if audio.size < n_fft * 4:
        return audio
    window = np.hanning(n_fft).astype(np.float64)
    pad = n_fft
    x = np.pad(audio.astype(np.float64), (pad, pad))
    count = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(count)[:, None]
    spec = np.fft.rfft(x[idx] * window, axis=1)
    mag = np.abs(spec)
    energy = mag.sum(axis=1)
    quiet = energy <= np.percentile(energy, 15)  # the quietest 15% of frames are the noise
    noise = np.median(mag[quiet], axis=0) if quiet.any() else mag.min(axis=0)
    gain = np.clip(1.0 - strength * noise[None, :] / (mag + 1e-12), floor, 1.0)
    # smooth over time so the gate does not flutter ("musical noise")
    kernel = np.array([0.25, 0.5, 0.25])
    gain = np.apply_along_axis(lambda g: np.convolve(g, kernel, mode="same"), 0, gain)
    clean = np.fft.irfft(spec * gain, n=n_fft, axis=1) * window
    out = np.zeros(len(x))
    norm = np.zeros(len(x))
    for i in range(count):  # overlap-add
        out[i * hop : i * hop + n_fft] += clean[i]
        norm[i * hop : i * hop + n_fft] += window**2
    out = out / np.maximum(norm, 1e-8)
    return out[pad : pad + len(audio)].astype(np.float32)


def auto_gain(audio: np.ndarray, stats: AudioStats) -> tuple[np.ndarray, float]:
    """Raise a quiet recording to a normal level. Never turns loud audio down."""
    if stats.peak <= 1e-9 or stats.peak >= NORMAL_PEAK:
        return audio, 0.0
    gain = TARGET_PEAK / stats.peak
    gain = min(gain, 10 ** (MAX_GAIN_DB / 20))
    if gain <= 1.0:
        return audio, 0.0
    boosted = np.clip(audio * gain, -1.0, 1.0).astype(np.float32)
    return boosted, float(20 * np.log10(gain))


def prepare(audio: np.ndarray, auto: bool = True) -> Prepared:
    """Analyse a recording and, if ``auto``, clean it up for the speech model."""
    stats = analyze(audio)
    if not auto or stats.too_quiet:
        return Prepared(audio, stats, 0.0, False)
    out = highpass(audio)
    stats = analyze(out)  # measure again without the rumble, so the gain is not wasted on it
    needed_db = 0.0
    if stats.peak < NORMAL_PEAK:
        needed_db = 20 * np.log10(TARGET_PEAK / max(stats.peak, 1e-9))
    denoised = False
    if needed_db >= DENOISE_ABOVE_GAIN_DB:
        out = reduce_noise(out)
        stats = analyze(out)
        denoised = True
    out, gain_db = auto_gain(out, stats)
    return Prepared(out, stats, gain_db, denoised)


def quiet_hint(stats: AudioStats) -> str:
    """A short, actionable message for the Flow Bar when nothing usable was heard."""
    if stats.peak < ABSOLUTE_FLOOR:
        return "Microphone silent: is it muted?"
    if stats.peak < 0.02:
        return "Too quiet: move closer or raise the mic level"
    return "No speech heard"


def describe(stats: AudioStats) -> str:
    """A plain-language verdict on a microphone test."""
    if stats.peak < ABSOLUTE_FLOOR:
        return "No signal at all: the microphone is muted, unplugged or not the selected device."
    if stats.snr_db < MIN_SNR_DB:
        return "Only background noise was heard. Speak while recording, or move closer."
    if stats.peak < 0.02:
        return (
            "Very quiet but usable: Flow Local boosts it automatically. "
            "Raising the mic level in Windows helps accuracy."
        )
    if stats.peak < 0.1:
        return "Quiet but good: Flow Local will boost it automatically."
    return "Good level."
