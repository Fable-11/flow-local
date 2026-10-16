"""Latency benchmark on loaded or recorded audio."""

from __future__ import annotations

import time

import numpy as np

from flow.stt.engine import SttEngine


def run_bench(audio: np.ndarray, runs: int = 3) -> dict[str, float | str]:
    eng = SttEngine()
    t0 = time.perf_counter()
    eng.load(allow_download=True)
    load_s = time.perf_counter() - t0
    eng.transcribe(audio[: 16_000 * 2])  # warm-up
    times = []
    for _ in range(runs):
        t = time.perf_counter()
        eng.transcribe(audio)
        times.append(time.perf_counter() - t)
    return {
        "model": eng.choice.name,
        "device": eng.choice.device,
        "load_s": round(load_s, 2),
        "audio_s": round(len(audio) / 16_000, 1),
        "best_s": round(min(times), 2),
        "mean_s": round(sum(times) / len(times), 2),
    }
