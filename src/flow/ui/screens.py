"""Naming monitors, so the Flow Bar can be pinned to one of them (for example "Acme ...")."""

from __future__ import annotations

PREFIX = "screen:"


def screen_key(screen) -> str:  # noqa: ANN001 - QScreen or a stand-in
    """A stable name for a monitor: its model, falling back to the Windows display name.

    Qt's "manufacturer" field is unreliable on Windows (it can hold a cut-off fragment), but the
    model already reads like "Acme AB2412C", so only the model is used.
    """
    model = (getattr(screen, "model", lambda: "")() or "").strip()
    return model or (getattr(screen, "name", lambda: "")() or "Screen")


def screen_label(screen, primary=None) -> str:  # noqa: ANN001
    """What the Settings list shows, for example "Acme X27C4 (1920 x 1080, main)"."""
    geo = screen.geometry() if hasattr(screen, "geometry") else screen.availableGeometry()
    extra = f"{geo.width()} x {geo.height()}"
    if primary is not None and screen is primary:
        extra += ", main"
    return f"{screen_key(screen)} ({extra})"


def find_screen(screens, key: str):  # noqa: ANN001, ANN201
    """The connected monitor whose name is ``key`` (a "screen:..." setting value), or None."""
    wanted = key[len(PREFIX) :] if key.startswith(PREFIX) else key
    for s in screens:
        if screen_key(s) == wanted:
            return s
    return None
