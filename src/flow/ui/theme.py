"""Design tokens and the application stylesheet, for light and dark (following Windows).

Strategy: Restrained. Cool-tinted neutrals plus ONE accent (the blue of the app icon), used only
for primary actions, the selected item, toggles that are on, and the focus ring. The sidebar is a
second neutral layer. One font family (Segoe UI), a tight type scale, 8 px radius controls and
12 px radius panels. Every text colour here is checked against its background by the tests.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

FONT_FAMILY = "Segoe UI Variable Text" if sys.platform == "win32" else "Segoe UI"
FONT_FALLBACK = "Segoe UI"

# type scale (px), ratio about 1.15
SIZE_CAPTION = 12
SIZE_BODY = 13
SIZE_SECTION = 15
SIZE_TITLE = 22

RADIUS_CONTROL = 8
RADIUS_PANEL = 12


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str  # content surface
    sidebar: str  # second neutral layer
    surface: str  # panels, inputs
    surface_hover: str
    border: str
    border_strong: str
    text: str
    muted: str  # secondary text: must stay >= 4.5:1 on bg and surface
    accent: str
    accent_hover: str
    accent_pressed: str
    on_accent: str  # text on a filled accent
    accent_tint: str  # selected row / nav item background (rgba)
    danger: str
    success: str
    knob: str


LIGHT = Palette(
    name="light",
    bg="#f7f8fa", sidebar="#eef0f4", surface="#ffffff", surface_hover="#f1f3f7",
    border="#e1e5ec", border_strong="#c9cfda",
    text="#14171f", muted="#566074",
    accent="#2457d6", accent_hover="#1d49b8", accent_pressed="#173b96", on_accent="#ffffff",
    accent_tint="rgba(36, 87, 214, 0.11)",
    danger="#b42318", success="#0e7a45", knob="#ffffff",
)  # fmt: skip
DARK = Palette(
    name="dark",
    bg="#12141a", sidebar="#0d0f14", surface="#1a1d25", surface_hover="#222631",
    border="#2a2f3b", border_strong="#3a4151",
    text="#e9ebf1", muted="#a1a9ba",
    accent="#6c9bff", accent_hover="#8bb0ff", accent_pressed="#5588f0", on_accent="#0b1020",
    accent_tint="rgba(108, 155, 255, 0.16)",
    danger="#ff8f85", success="#5fd69f", knob="#ffffff",
)  # fmt: skip


def is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    return hints is not None and hints.colorScheme() == Qt.ColorScheme.Dark


_forced: Palette | None = None


def force_palette(p: Palette | None) -> None:
    """Override the system light/dark choice (tests and screenshots)."""
    global _forced
    _forced = p


def current_palette() -> Palette:
    return _forced or (DARK if is_dark() else LIGHT)


# -- contrast ---------------------------------------------------------------------------------------
def _channel(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    c = QColor(hex_color)
    return 0.2126 * _channel(c.red()) + 0.7152 * _channel(c.green()) + 0.0722 * _channel(c.blue())


def contrast(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two opaque colours (1..21)."""
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# -- notifier: custom-painted widgets repaint when the theme flips -----------------------------------
class ThemeNotifier(QObject):
    changed = Signal()


notifier = ThemeNotifier()


# -- assets referenced from the stylesheet (arrows) ---------------------------------------------------
def _asset_dir() -> Path:
    from flow.store.db import default_db_path

    d = default_db_path().parent / "ui"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_assets(p: Palette) -> dict[str, str]:
    """Small SVGs the stylesheet needs (QSS cannot draw a combo-box chevron itself)."""
    d = _asset_dir()
    stroke = p.muted
    chevron = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
        f'<path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="{stroke}" stroke-width="1.6" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )
    up = chevron.replace("M2.5 4.5 6 8l3.5-3.5", "M2.5 7.5 6 4l3.5 3.5")
    def svg(inner: str, size: int = 16) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}">{inner}</svg>'
        )

    radio_off = svg(f'<circle cx="8" cy="8" r="6.5" fill="none" stroke="{p.muted}" stroke-width="1.5"/>')
    radio_on = svg(
        f'<circle cx="8" cy="8" r="6.5" fill="none" stroke="{p.accent}" stroke-width="1.5"/>'
        f'<circle cx="8" cy="8" r="3.4" fill="{p.accent}"/>'
    )
    check_off = svg(
        f'<rect x="1.75" y="1.75" width="12.5" height="12.5" rx="3.5" fill="none" '
        f'stroke="{p.muted}" stroke-width="1.5"/>'
    )
    check_on = svg(
        f'<rect x="1" y="1" width="14" height="14" rx="4" fill="{p.accent}"/>'
        f'<path d="M4.6 8.4 7 10.8l4.4-5" fill="none" stroke="{p.on_accent}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )
    files = {
        "chevron": chevron, "chevron_up": up, "radio_off": radio_off, "radio_on": radio_on,
        "check_off": check_off, "check_on": check_on,
    }  # fmt: skip
    out = {}
    for name, svg in files.items():
        path = d / f"{name}-{p.name}.svg"
        path.write_text(svg, encoding="utf-8")
        out[name] = path.as_posix()
    return out


def stylesheet(p: Palette, assets: dict[str, str] | None = None) -> str:
    a = assets or {
        k: "" for k in ("chevron", "chevron_up", "radio_off", "radio_on", "check_off", "check_on")
    }
    f = f'"{FONT_FAMILY}", "{FONT_FALLBACK}", sans-serif'
    return f"""
* {{ font-family: {f}; font-size: {SIZE_BODY}px; }}
QWidget {{ color: {p.text}; }}
QToolTip {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border_strong};
           border-radius: 6px; padding: 5px 8px; }}

QWidget#Content, QStackedWidget#Pages, QWidget#Page {{ background: {p.bg}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QWidget#Sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.border}; }}

/* ---- type roles ---- */
QLabel[role="title"] {{ font-size: {SIZE_TITLE}px; font-weight: 600; }}
QLabel[role="section"] {{ font-size: {SIZE_SECTION}px; font-weight: 600; }}
QLabel[role="strong"] {{ font-weight: 600; }}
QLabel[role="muted"] {{ color: {p.muted}; }}
QLabel[role="caption"] {{ color: {p.muted}; font-size: {SIZE_CAPTION}px; }}
QLabel[role="error"] {{ color: {p.danger}; }}
QLabel[role="stat"] {{ font-size: 26px; font-weight: 600; }}

/* ---- sidebar navigation ---- */
QListWidget#Nav {{ background: transparent; border: none; outline: 0; }}
QListWidget#Nav::item {{ color: {p.text}; padding: 9px 12px; margin: 1px 0; border-radius: {RADIUS_CONTROL}px; }}
QListWidget#Nav::item:hover {{ background: {p.surface_hover}; }}
QListWidget#Nav::item:selected {{ background: {p.accent_tint}; color: {p.accent}; font-weight: 600; }}

/* ---- panels ---- */
QFrame#Panel {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: {RADIUS_PANEL}px; }}
QFrame#Divider {{ background: {p.border}; border: none; min-height: 1px; max-height: 1px; }}
QFrame#VDivider {{ background: {p.border}; border: none; min-width: 1px; max-width: 1px; }}
QPlainTextEdit#NoteEditor {{ border: none; background: transparent; padding: 14px; border-radius: 0; }}
QFrame#KeyCap {{ background: {p.bg}; border: 1px solid {p.border_strong}; border-bottom-width: 2px;
                 border-radius: 6px; }}
QFrame#KeyCap QLabel {{ font-size: {SIZE_CAPTION}px; font-weight: 600; background: transparent; }}

/* ---- buttons: secondary by default, primary / ghost / danger via the "variant" property ---- */
QPushButton {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border_strong};
              border-radius: {RADIUS_CONTROL}px; padding: 7px 14px; min-height: 18px; }}
QPushButton:hover {{ background: {p.surface_hover}; }}
QPushButton:pressed {{ background: {p.border}; }}
QPushButton:focus {{ border: 2px solid {p.accent}; padding: 6px 13px; }}
QPushButton:disabled {{ color: {p.muted}; background: {p.bg}; border-color: {p.border}; }}
QPushButton[variant="primary"] {{ background: {p.accent}; color: {p.on_accent}; border: 1px solid {p.accent};
                                  font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {p.accent_pressed}; border-color: {p.accent_pressed}; }}
QPushButton[variant="primary"]:disabled {{ background: {p.border}; color: {p.muted}; border-color: {p.border}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[variant="ghost"]:hover {{ background: {p.surface_hover}; }}
QPushButton[variant="danger"] {{ color: {p.danger}; }}

/* ---- inputs ---- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
    background: {p.surface}; color: {p.text}; border: 1px solid {p.border_strong};
    border-radius: {RADIUS_CONTROL}px; padding: 7px 10px; selection-background-color: {p.accent};
    selection-color: {p.on_accent}; }}
QLineEdit {{ min-height: 18px; }}
QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {p.muted}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 2px solid {p.accent}; padding: 6px 9px; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {p.muted}; background: {p.bg}; }}
QComboBox {{ padding-right: 28px; min-height: 18px; }}
QComboBox::drop-down {{ border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url({a["chevron"]}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border_strong};
    border-radius: 8px; padding: 4px; outline: 0; selection-background-color: {p.accent_tint};
    selection-color: {p.text}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

/* ---- radio buttons and check boxes: visible in both themes (the default ones vanish in dark) ---- */
QRadioButton, QCheckBox {{ spacing: 8px; }}
QRadioButton::indicator, QCheckBox::indicator {{ width: 16px; height: 16px; }}
QRadioButton::indicator:unchecked {{ image: url({a["radio_off"]}); }}
QRadioButton::indicator:checked {{ image: url({a["radio_on"]}); }}
QCheckBox::indicator:unchecked {{ image: url({a["check_off"]}); }}
QCheckBox::indicator:checked {{ image: url({a["check_on"]}); }}

/* ---- tables ---- */
QTableWidget {{ background: transparent; border: none; gridline-color: transparent; outline: 0;
               selection-background-color: {p.accent_tint}; selection-color: {p.text}; }}
QTableWidget::item {{ padding: 4px 12px; border-bottom: 1px solid {p.border}; }}
QTableWidget::item:hover {{ background: {p.surface_hover}; }}
QTableWidget::item:selected {{ background: {p.accent_tint}; color: {p.text}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {p.muted}; border: none;
    border-bottom: 1px solid {p.border}; padding: 8px 12px; font-weight: 600; font-size: {SIZE_CAPTION}px; }}
QTableCornerButton::section {{ background: transparent; border: none; }}

/* ---- lists (notes, suggestions) ---- */
QListWidget {{ background: transparent; border: none; outline: 0; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 6px; }}
QListWidget::item:hover {{ background: {p.surface_hover}; }}
QListWidget::item:selected {{ background: {p.accent_tint}; color: {p.text}; }}

/* ---- scrollbars: thin, unobtrusive ---- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border_strong}; border-radius: 3px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {p.muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.border_strong}; border-radius: 3px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0; height: 0; }}

/* ---- slider ---- */
QSlider::groove:horizontal {{ background: {p.border_strong}; height: 4px; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {p.knob}; border: 2px solid {p.accent}; width: 14px; height: 14px;
    margin: -8px 0; border-radius: 9px; }}

/* ---- menus (tray) and dialogs ---- */
QMenu {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border_strong}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 5px; }}
QMenu::item:selected {{ background: {p.accent_tint}; }}
QMenu::item:disabled {{ color: {p.muted}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 6px; }}
QDialog, QMessageBox {{ background: {p.bg}; }}
"""


def _qpalette(p: Palette) -> QPalette:
    """A matching native palette so dialogs and anything the stylesheet misses still fit."""
    pal = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, p.bg), (QPalette.ColorRole.WindowText, p.text),
        (QPalette.ColorRole.Base, p.surface), (QPalette.ColorRole.AlternateBase, p.surface_hover),
        (QPalette.ColorRole.Text, p.text), (QPalette.ColorRole.Button, p.surface),
        (QPalette.ColorRole.ButtonText, p.text), (QPalette.ColorRole.ToolTipBase, p.surface),
        (QPalette.ColorRole.ToolTipText, p.text), (QPalette.ColorRole.Highlight, p.accent),
        (QPalette.ColorRole.HighlightedText, p.on_accent), (QPalette.ColorRole.Link, p.accent),
        (QPalette.ColorRole.PlaceholderText, p.muted),
    ):  # fmt: skip
        pal.setColor(role, QColor(color))
    return pal


def apply_theme(app: QApplication | None = None, palette: Palette | None = None) -> Palette:
    """Style the whole application for the current (or given) palette and remember to follow the
    system's light/dark switch."""
    app = app or QApplication.instance()
    p = palette or current_palette()
    app.setStyle("Fusion")  # one predictable base on every Windows version
    font = QFont(FONT_FAMILY)
    font.setPixelSize(SIZE_BODY)
    app.setFont(font)
    app.setPalette(_qpalette(p))
    try:
        assets = _write_assets(p)
    except OSError:
        assets = None
    app.setStyleSheet(stylesheet(p, assets))
    notifier.changed.emit()
    return p


def follow_system_theme(app: QApplication) -> None:
    hints = QGuiApplication.styleHints()
    if hints is not None:
        hints.colorSchemeChanged.connect(lambda _scheme: apply_theme(app) if _forced is None else None)
