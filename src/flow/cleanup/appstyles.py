"""Per-app tone: built-in defaults by app category, overridable per process."""

from __future__ import annotations

from flow.cleanup.prompts import _CHAT_APPS, _MAIL_APPS


def builtin_style(process: str) -> str | None:
    p = process.lower().removesuffix(".exe")
    if any(a in p for a in _CHAT_APPS):
        return "casual"
    if any(a in p for a in _MAIL_APPS):
        return "formal"
    return None


def resolve_style(process: str, global_style: str, overrides: dict[str, str]) -> str:
    """Explicit per-app rule > the user's chosen global style > built-in app default."""
    p = process.lower()
    if p in overrides:
        return overrides[p]
    if global_style != "default":
        return global_style
    return builtin_style(p) or "default"
