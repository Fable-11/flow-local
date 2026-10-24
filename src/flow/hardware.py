"""Detect what the computer can do and recommend sensible first-run defaults.

A desktop with an NVIDIA GPU gets the big, fast, accurate setup. A laptop without one still works
well: it uses the smaller speech model on the CPU, the lighter cleanup model, and unloads models
sooner to save memory.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass, field

from flow.cleanup.llm import DEFAULT_MODEL, FALLBACK_MODEL

LOW_RAM_GB = 12.0
SMALL_VRAM_MB = 5000  # below this the 7B cleanup model and the speech model do not fit together


@dataclass(frozen=True)
class Hardware:
    has_cuda: bool
    ram_gb: float  # 0.0 if unknown
    vram_mb: int = 0  # 0 if unknown


@dataclass(frozen=True)
class Recommendation:
    llm_model: str
    memory_mode: str
    notes: list[str] = field(default_factory=list)

    def as_settings(self) -> dict[str, str]:
        return {"llm_model": self.llm_model, "memory_mode": self.memory_mode}


def system_ram_gb() -> float:
    """Installed physical memory in GB (0.0 if it cannot be read)."""
    if sys.platform != "win32":
        return 0.0

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]  # fmt: skip

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    try:
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys / 1024**3
    except (OSError, AttributeError):
        pass
    return 0.0


def detect() -> Hardware:
    from flow.stt.engine import cuda_available, gpu_memory_mb

    return Hardware(has_cuda=cuda_available(), ram_gb=system_ram_gb(), vram_mb=gpu_memory_mb() or 0)


def recommend(hw: Hardware) -> Recommendation:
    notes: list[str] = []
    llm = DEFAULT_MODEL
    if not hw.has_cuda:
        llm = FALLBACK_MODEL  # a 7B model on a CPU is too slow for dictation
        notes.append(
            "No NVIDIA graphics card found: speech recognition runs on the CPU with a smaller "
            "model (a few seconds per dictation) and the lighter cleanup model is used."
        )
    if hw.has_cuda and 0 < hw.vram_mb < SMALL_VRAM_MB:  # only a confirmed small card
        llm = FALLBACK_MODEL
        notes.append(
            f"{hw.vram_mb / 1024:.0f} GB of video memory: the lighter cleanup model is used "
            "so it fits next to the speech model."
        )
    low_ram = 0 < hw.ram_gb < LOW_RAM_GB
    if low_ram:
        llm = FALLBACK_MODEL
        notes.append(
            f"{hw.ram_gb:.0f} GB of memory: models unload after 2 idle minutes to keep the "
            "computer responsive (Settings > Memory)."
        )
    if llm == FALLBACK_MODEL:
        notes.append(
            f"{FALLBACK_MODEL} is released for non-commercial use (Qwen Research License). "
            "For commercial use pick a model with a permissive licence in Settings."
        )
    return Recommendation(llm_model=llm, memory_mode="low" if low_ram else "balanced", notes=notes)
