"""Detect whether a Whisper model is already downloaded (no network access)."""

from __future__ import annotations

import os
from pathlib import Path


def hf_cache_dir() -> Path:
    env = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if env:
        return Path(env)
    home = os.environ.get("HF_HOME")
    if home:
        return Path(home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def is_model_cached(name: str, cache: Path | None = None) -> bool:
    """True if a faster-whisper repo for ``name`` with weights is in the local cache."""
    cache = cache or hf_cache_dir()
    if not cache.exists():
        return False
    wanted = f"faster-whisper-{name}".lower()
    for repo in cache.glob("models--*"):
        if repo.name.lower().endswith(wanted) or repo.name.lower().endswith("--" + wanted):
            if any(repo.glob("snapshots/*/model.bin")):
                return True
    return False
