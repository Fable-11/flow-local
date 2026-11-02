"""Flow Bar: the small always-on-top pill that shows recording / processing state."""

from __future__ import annotations

import collections
import ctypes
import sys
import time

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from flow.ui.kit import level_from_rms, paint_trace
from flow.ui.screens import PREFIX, find_screen
from flow.ui.theme import DARK

STATES = (
    "idle", "loading", "recording", "handsfree", "command", "processing", "done", "error",
    "suggest",
)
SUGGEST_SECONDS = 10

# (width, height) of the pill per state; error/loading widen to fit their text.
_SIZES = {
    "idle": (44, 6),
    "loading": (110, 34),
    "recording": (160, 36),
    "handsfree": (160, 36),
    "command": (160, 36),
    "processing": (96, 34),
    "done": (64, 34),
    "error": (64, 34),
    "suggest": (280, 38),
}
_TOOLTIPS = {
    "recording": "Recording. Release the shortcut to insert, Esc to cancel, or click to stop.",
    "handsfree": "Hands-free. Click, or press Ctrl+Win+Space, to stop. Esc cancels.",
    "command": "Command Mode: say what to do with the selected text. Release to apply, Esc cancels.",
}
_RETURN_TO_IDLE_MS = {"done": 900, "error": 2200, "suggest": SUGGEST_SECONDS * 1000}

# The bar is always dark, so it takes the dark theme's colours.
BG = QColor(DARK.surface)
BG.setAlpha(244)
IDLE_BG = QColor(DARK.border_strong)
IDLE_BG.setAlpha(220)
BORDER = QColor(255, 255, 255, 40)  # a hairline: visible over dark windows, quiet over light ones
# The voice trace is ember while you speak; command mode (an instruction, not dictation) is off-white.
ACCENT = {
    "recording": QColor(DARK.accent),
    "handsfree": QColor(DARK.accent),
    "command": QColor(DARK.text),
}
GREEN = QColor(DARK.success)
RED = QColor(DARK.danger)
WHITE = QColor(255, 255, 255, 235)
N_BARS = 18
_CLICKABLE = ("recording", "handsfree", "command", "suggest")


class FlowBar(QWidget):
    clicked = Signal()  # user clicked the pill while it was recording
    accepted = Signal()  # user pressed Add on a dictionary suggestion
    dismissed = Signal()  # user pressed the cross on a suggestion
    expired = Signal()  # a suggestion timed out unanswered

    W, H = 400, 60

    def __init__(self, screen=None) -> None:  # noqa: ANN001 - QScreen or a stand-in
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self.W, self.H)
        self._screen = screen  # None = the primary screen
        self._state = "idle"
        self._text = ""
        self.idle_visible = True  # settings: show the small idle line
        self._levels: collections.deque[float] = collections.deque([0.0] * N_BARS, maxlen=N_BARS)
        self._w, self._h = map(float, _SIZES["idle"])
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._timed_out)
        self._suggest_t0 = 0.0
        self._add_rect = QRectF()
        self._close_rect = QRectF()
        self.reposition()

    # -- public API (Qt thread, or via queued signals) -----------------------------------
    @Slot(str, str)
    def set_state(self, state: str, text: str = "") -> None:
        if state not in STATES:
            raise ValueError(state)
        self._idle_timer.stop()
        self._state, self._text = state, text
        if state in ("recording", "handsfree", "command"):
            self._levels.extend([0.0] * N_BARS)
        self.setToolTip(_TOOLTIPS.get(state, ""))
        self._apply_click_through(state not in _CLICKABLE)
        if state == "suggest":
            self._suggest_t0 = time.monotonic()
        if state in _RETURN_TO_IDLE_MS:
            self._idle_timer.start(_RETURN_TO_IDLE_MS[state])
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    @Slot(float)
    def push_level(self, rms: float) -> None:
        # rises at once, falls gently: the trace follows the voice without flickering
        last = self._levels[-1] if self._levels else 0.0
        self._levels.append(max(level_from_rms(rms), last * 0.55))

    @property
    def state(self) -> str:
        return self._state

    def reposition(self) -> None:
        screen = self._screen or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.center().x() - self.W // 2, geo.bottom() - self.H + 1)

    # -- Windows click-through / no-activate ---------------------------------------------
    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        self._apply_click_through(self._state not in _CLICKABLE)

    def _apply_click_through(self, through: bool) -> None:
        if sys.platform != "win32" or not self.isVisible():
            return
        user32 = ctypes.WinDLL("user32")
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        hwnd = int(self.winId())
        style = user32.GetWindowLongPtrW(hwnd, -20)  # GWL_EXSTYLE
        style |= 0x08000000 | 0x00000080  # WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        style = style | 0x20 if through else style & ~0x20  # WS_EX_TRANSPARENT
        user32.SetWindowLongPtrW(hwnd, -20, style)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._state == "suggest":
            pos = event.position()
            if self._add_rect.contains(pos):
                self.accepted.emit()
            elif self._close_rect.contains(pos):
                self.dismissed.emit()
            return
        if self._state in ("recording", "handsfree", "command"):
            self.clicked.emit()

    def _timed_out(self) -> None:
        if self._state == "suggest":
            self.expired.emit()
        self.set_state("idle")

    # -- animation -----------------------------------------------------------------------
    def _target_size(self) -> tuple[float, float]:
        w, h = _SIZES[self._state]
        if self._text and self._state in ("error", "loading"):
            fm = QFontMetrics(self._font())
            w = max(w, fm.horizontalAdvance(self._text) + 56)
        if self._state == "suggest":
            fm = QFontMetrics(self._font())
            w = fm.horizontalAdvance(self._text) + 18 + 14 + 54 + 8 + 24 + 12
        return float(min(w, self.W - 8)), float(h)

    @staticmethod
    def _font() -> QFont:
        f = QFont("Segoe UI")
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.Medium)
        return f

    def _tick(self) -> None:
        tw, th = self._target_size()
        self._w += (tw - self._w) * 0.28
        self._h += (th - self._h) * 0.28
        settled = abs(tw - self._w) < 0.3 and abs(th - self._h) < 0.3
        if settled:
            self._w, self._h = tw, th
        if self._state == "idle" and settled:
            self._timer.stop()  # nothing animates while idle: no CPU use
        self.update()

    # -- painting ------------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._state == "idle" and not self.idle_visible and self._h <= 7:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self._w, self._h
        rect = QRectF((self.W - w) / 2, self.H - h - 8, w, h)
        p.setPen(QPen(BORDER, 1))
        p.setBrush(BG if self._state != "idle" else IDLE_BG)
        p.drawRoundedRect(rect, h / 2, h / 2)
        t = time.monotonic() - self._t0
        if self._state in ("recording", "handsfree", "command"):
            self._paint_wave(p, rect, t)
        elif self._state in ("processing", "loading"):
            self._paint_spinner(p, rect, t)
        elif self._state == "done":
            self._paint_check(p, rect)
        elif self._state == "error":
            self._paint_cross(p, rect)
        elif self._state == "suggest":
            self._paint_suggestion(p, rect)
        p.end()

    def _paint_wave(self, p: QPainter, rect: QRectF, t: float) -> None:
        """Each live state has its own mark: a solid dot (hold to talk), a ring (hands-free) or a
        chevron (command), then the voice trace. Nothing pulses; the trace itself shows it is live."""
        color = ACCENT[self._state]
        cy = rect.center().y()
        mark = QPointF(rect.left() + 18, cy)
        if self._state == "recording":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(mark, 4.5, 4.5)
        elif self._state == "handsfree":
            p.setPen(QPen(color, 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(mark, 4.0, 4.0)
        else:
            pen = QPen(color, 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            path = QPainterPath(QPointF(mark.x() - 3, cy - 4.5))
            path.lineTo(mark.x() + 2, cy)
            path.lineTo(mark.x() - 3, cy + 4.5)
            p.drawPath(path)
        area = QRectF(rect.left() + 34, rect.top() + 6, rect.width() - 34 - 14, rect.height() - 12)
        paint_trace(p, area, self._levels, color, 3.0, 3.0)

    def _paint_spinner(self, p: QPainter, rect: QRectF, t: float) -> None:
        pen = QPen(WHITE, 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        c = rect.center()
        text_w = 0.0
        if self._text:
            text_w = QFontMetrics(self._font()).horizontalAdvance(self._text) + 8
            c = QPointF(rect.left() + 24, c.y())
        r = 8.0
        start = int(-(t * 420) % 360 * 16)
        p.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), start, 270 * 16)
        if self._text:
            self._paint_text(p, rect, c.x() + 16, text_w)

    def _paint_check(self, p: QPainter, rect: QRectF) -> None:
        pen = QPen(GREEN, 3.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        c = rect.center()
        path = QPainterPath(QPointF(c.x() - 7, c.y()))
        path.lineTo(c.x() - 2, c.y() + 5)
        path.lineTo(c.x() + 8, c.y() - 6)
        p.drawPath(path)

    def _paint_cross(self, p: QPainter, rect: QRectF) -> None:
        pen = QPen(RED, 2.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        c = QPointF(rect.center().x(), rect.center().y())
        if self._text:
            c = QPointF(rect.left() + 22, c.y())
        d = 5.5
        p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
        p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))
        if self._text:
            self._paint_text(p, rect, c.x() + 16, rect.right() - c.x() - 22)

    def _paint_suggestion(self, p: QPainter, rect: QRectF) -> None:
        """Text, an Add button, a close cross and a thin line that runs out after 10 seconds."""
        font = self._font()
        p.setFont(font)
        p.setPen(WHITE)
        cy = rect.center().y()
        close = QRectF(rect.right() - 12 - 24, cy - 12, 24, 24)
        add = QRectF(close.left() - 8 - 54, cy - 12, 54, 24)
        self._close_rect, self._add_rect = close, add
        text_rect = QRectF(rect.left() + 18, rect.top(), add.left() - rect.left() - 32, rect.height())
        p.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            QFontMetrics(font).elidedText(self._text, Qt.TextElideMode.ElideRight, int(text_rect.width())),
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(DARK.accent))  # the one primary action
        p.drawRoundedRect(add, 12, 12)
        p.setPen(QColor(DARK.on_accent))
        p.drawText(add, Qt.AlignmentFlag.AlignCenter, "Add")
        pen = QPen(WHITE, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        c, d = close.center(), 4.0
        p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
        p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))
        left = max(0.0, 1.0 - (time.monotonic() - self._suggest_t0) / SUGGEST_SECONDS)
        bar = QRectF(rect.left() + 18, rect.bottom() - 4, (rect.width() - 36) * left, 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 90))
        p.drawRoundedRect(bar, 1, 1)

    def _paint_text(self, p: QPainter, rect: QRectF, x: float, width: float) -> None:
        p.setPen(WHITE)
        p.setFont(self._font())
        p.drawText(
            QRectF(x, rect.top(), max(width, 10), rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._text,
        )


def screen_under_cursor():  # noqa: ANN201
    """The screen where the mouse pointer is: a good proxy for 'where I am working'."""
    from PySide6.QtGui import QCursor

    return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()


def main_screen():  # noqa: ANN201
    """The monitor Windows treats as the main display."""
    return QGuiApplication.primaryScreen()


class FlowBarGroup(QObject):
    """One Flow Bar per monitor. Mode "all" mirrors it everywhere, "primary" shows it only on the
    main display, "screen:<name>" only on that monitor, and "active" only on the screen where the pointer is when a dictation starts."""

    clicked = Signal()
    suggestionAccepted = Signal()
    suggestionDismissed = Signal()
    suggestionExpired = Signal()

    def __init__(self, mode: str = "all", screens_provider=None) -> None:  # noqa: ANN001
        super().__init__()
        self.mode = mode
        self.idle_visible = True
        self._screens = screens_provider or QGuiApplication.screens
        self._bars: list[tuple[object, FlowBar]] = []
        self._state, self._text = "idle", ""
        self._active = None
        app = QGuiApplication.instance()
        if app is not None and screens_provider is None:
            app.screenAdded.connect(lambda _s: self.sync())
            app.screenRemoved.connect(lambda _s: self.sync())
        self.sync()

    @property
    def bars(self) -> list[FlowBar]:
        return [b for _s, b in self._bars]

    def sync(self) -> None:
        """Create/remove bars so there is one per current screen, then place and show them."""
        current = list(self._screens())
        for screen, bar in list(self._bars):
            if screen not in current:
                bar.hide()
                bar.deleteLater()
                self._bars.remove((screen, bar))
        known = [s for s, _b in self._bars]
        for screen in current:
            if screen not in known:
                bar = FlowBar(screen)
                bar.idle_visible = self.idle_visible
                bar.clicked.connect(self.clicked)
                bar.accepted.connect(lambda: self._answered(self.suggestionAccepted))
                bar.dismissed.connect(lambda: self._answered(self.suggestionDismissed))
                bar.expired.connect(self._expired)
                self._bars.append((screen, bar))
        self._apply()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._apply()

    def set_idle_visible(self, visible: bool) -> None:
        self.idle_visible = visible
        for bar in self.bars:
            bar.idle_visible = visible
            bar.update()

    def _target_screen(self):  # noqa: ANN202
        if self.mode == "all":
            return None
        if self.mode == "primary":
            return main_screen()
        if self.mode.startswith(PREFIX):  # one named monitor; the main one if it is unplugged
            return find_screen(list(self._screens()), self.mode) or main_screen()
        if self._state == "idle" or self._active is None:
            self._active = screen_under_cursor()
        return self._active

    def _apply(self) -> None:
        target = self._target_screen()
        for screen, bar in self._bars:
            bar.reposition()
            if target is None or screen == target:
                bar.set_state(self._state, self._text)
                if not bar.isVisible():
                    bar.show()
            else:
                bar.hide()

    def set_state(self, state: str, text: str = "") -> None:
        if state in ("recording", "handsfree", "command", "loading") and self._state in (
            "idle",
            "suggest",
        ):
            self._active = None  # re-pick the screen when a dictation starts
        self._state, self._text = state, text
        self._apply()
        if state in _RETURN_TO_IDLE_MS:  # bars return to idle themselves; keep the group in step
            QTimer.singleShot(
                _RETURN_TO_IDLE_MS[state] + 50,
                lambda s=state: setattr(self, "_state", "idle") if self._state == s else None,
            )

    def suggest(self, text: str) -> bool:
        """Show a dictionary suggestion for 10 seconds. Only when nothing else is going on."""
        if self._state != "idle":
            return False
        self.set_state("suggest", text)
        return True

    def _answered(self, signal) -> None:  # noqa: ANN001
        if self._state == "suggest":
            self.set_state("idle")
            signal.emit()

    def _expired(self) -> None:
        if self._state == "suggest":
            self._state = "idle"
            self.suggestionExpired.emit()

    def push_level(self, rms: float) -> None:
        for bar in self.bars:
            if bar.isVisible():
                bar.push_level(rms)
