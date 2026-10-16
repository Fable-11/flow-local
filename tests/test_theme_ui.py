import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from flow.store.db import Database  # noqa: E402
from flow.store.dictionary import DictionaryStore  # noqa: E402
from flow.store.settings_repo import SettingsRepo  # noqa: E402
from flow.store.snippets import SnippetStore  # noqa: E402
from flow.ui import icons, theme  # noqa: E402
from flow.ui.hub.context import HubContext  # noqa: E402
from flow.ui.hub.widgets import KeyCaps, Toggle, key_label  # noqa: E402
from flow.ui.hub.window import NAV_ICONS, PAGES, HubWindow, status_state  # noqa: E402

PALETTES = [theme.LIGHT, theme.DARK]


@pytest.fixture
def ctx():
    db = Database()
    return HubContext(DictionaryStore(db), SnippetStore(db), SettingsRepo(db))


@pytest.fixture(autouse=True)
def reset_palette(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))  # theme assets go to a temp folder
    yield
    theme.force_palette(None)


# -- accessibility: every text colour clears WCAG AA against what it sits on ---------------------------
@pytest.mark.parametrize("p", PALETTES, ids=lambda p: p.name)
def test_text_contrast_meets_wcag_aa(p):
    pairs = {
        "text on content": (p.text, p.bg), "text on panel": (p.text, p.surface),
        "text on sidebar": (p.text, p.sidebar), "muted on content": (p.muted, p.bg),
        "muted on panel": (p.muted, p.surface), "muted on sidebar": (p.muted, p.sidebar),
        "accent text on content": (p.accent, p.bg), "accent text on sidebar": (p.accent, p.sidebar),
        "label on primary button": (p.on_accent, p.accent), "danger on panel": (p.danger, p.surface),
        "danger on content": (p.danger, p.bg), "success on panel": (p.success, p.surface),
    }  # fmt: skip
    for name, (fg, bg) in pairs.items():
        assert theme.contrast(fg, bg) >= 4.5, f"{p.name}: {name} = {theme.contrast(fg, bg):.2f}"


@pytest.mark.parametrize("p", PALETTES, ids=lambda p: p.name)
def test_non_text_elements_are_visible(p):
    assert theme.contrast(p.border_strong, p.surface) >= 1.5  # input borders can be seen
    assert theme.contrast(p.accent, p.surface) >= 3.0  # toggle track / focus ring (WCAG non-text)


def test_contrast_function_known_values():
    assert theme.contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert theme.contrast("#777777", "#777777") == pytest.approx(1.0)


# -- stylesheet ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("p", PALETTES, ids=lambda p: p.name)
def test_stylesheet_is_complete_and_resolved(p):
    qss = theme.stylesheet(p)
    assert "{{" not in qss and "}}" not in qss and "{p." not in qss  # every token substituted
    for selector in ("QPushButton[variant=\"primary\"]", "QLineEdit", "QTableWidget", "QListWidget#Nav",
                     "QFrame#Panel", "QScrollBar", "QRadioButton::indicator", "QComboBox"):  # fmt: skip
        assert selector in qss
    assert p.accent in qss and p.surface in qss


def test_apply_theme_styles_the_app_in_both_schemes(qtbot, ctx):
    app = QApplication.instance()
    for p in PALETTES:
        theme.force_palette(p)
        applied = theme.apply_theme(app, p)
        assert applied is p and app.styleSheet()
        assert app.palette().color(app.palette().ColorRole.Window).name() == p.bg  # dialogs match too
        hub = HubWindow(ctx)
        qtbot.addWidget(hub)
        hub.show()
        for name in PAGES:
            hub.show_page(name)
            qtbot.wait(10)
            assert not hub.grab().isNull()
        hub.close()


def test_theme_change_notifies_custom_painted_widgets(qtbot):
    seen = []
    theme.notifier.changed.connect(lambda: seen.append(1))
    theme.apply_theme(QApplication.instance(), theme.DARK)
    assert seen


def test_chevron_and_indicator_assets_are_written(tmp_path):
    theme.apply_theme(QApplication.instance(), theme.DARK)
    files = {f.name for f in (tmp_path / "FlowLocal" / "ui").glob("*.svg")}
    assert {"chevron-dark.svg", "radio_on-dark.svg", "check_on-dark.svg"} <= files


# -- toggle switch ------------------------------------------------------------------------------------
def test_toggle_behaves_like_a_checkbox(qtbot):
    t = Toggle()
    qtbot.addWidget(t)
    t.show()
    seen = []
    t.toggled.connect(seen.append)
    QTest.mouseClick(t, Qt.MouseButton.LeftButton)
    assert t.isChecked() and seen == [True]
    qtbot.keyClick(t, Qt.Key.Key_Space)  # keyboard operable
    assert not t.isChecked() and seen == [True, False]


def test_toggle_set_checked_does_not_animate_and_animation_settles(qtbot):
    t = Toggle()
    qtbot.addWidget(t)
    t.setChecked(True)
    assert t._pos == 1.0  # loading a saved setting jumps straight to the right position
    t.toggle()
    qtbot.waitUntil(lambda: t._pos == 0.0, timeout=1500)
    assert not t.grab().isNull()


def test_toggle_paints_in_both_themes_and_disabled(qtbot):
    t = Toggle("Label")
    qtbot.addWidget(t)
    for p in PALETTES:
        theme.force_palette(p)
        for enabled in (True, False):
            t.setEnabled(enabled)
            assert not t.grab().isNull()
    assert t.sizeHint().width() > Toggle.W


# -- small widgets --------------------------------------------------------------------------------------
def test_key_caps_split_a_chord_into_keys(qtbot):
    from PySide6.QtWidgets import QFrame, QLabel

    caps = KeyCaps("ctrl+win+space")
    qtbot.addWidget(caps)
    frames = caps.findChildren(QFrame, "KeyCap")
    assert [f.findChild(QLabel).text() for f in frames] == ["Ctrl", "Win", "Space"]
    assert key_label("mouse_x1") == "Mouse X1" and key_label("f") == "F" and key_label("f20") == "F20"


def test_status_text_maps_to_dot_state():
    assert status_state("Ready") == "ok"
    assert status_state("Listening...") == "busy"
    assert status_state("Loading model") == "busy"
    assert status_state("Speech model not downloaded") == "error"
    assert status_state("No microphone found") == "error"
    assert status_state("Inserted") == "ok"


def test_every_page_has_a_nav_icon_and_icons_render(qtbot):
    assert set(NAV_ICONS) == set(PAGES)
    for name, icon_name in NAV_ICONS.items():
        pm = icons.pixmap(icon_name, "#336699", 20)
        assert not pm.isNull() and pm.width() == 40  # 20 logical px at 2x
        image = pm.toImage()
        painted = sum(1 for x in range(image.width()) for y in range(image.height())
                      if image.pixelColor(x, y).alpha() > 0)  # fmt: skip
        assert painted > 20, f"{name} icon is blank"


def test_icon_colour_follows_the_requested_colour():
    red = icons.pixmap("check", "#ff0000", 20).toImage()
    blue = icons.pixmap("check", "#0000ff", 20).toImage()
    px = next(
        (x, y) for x in range(red.width()) for y in range(red.height()) if red.pixelColor(x, y).alpha() > 200
    )
    assert red.pixelColor(*px).red() > 200 and blue.pixelColor(*px).blue() > 200


# -- hub shell -------------------------------------------------------------------------------------------
def test_hub_sidebar_shows_current_status_even_if_opened_late(qtbot, ctx):
    ctx.statusChanged.emit("Speech model not downloaded")  # emitted before any window exists
    hub = HubWindow(ctx)
    qtbot.addWidget(hub)
    assert hub.status_text.text() == "Speech model not downloaded"
    ctx.statusChanged.emit("Ready")
    assert hub.status_text.text() == "Ready"


def test_content_column_is_capped_so_wide_monitors_stay_readable(qtbot, ctx):
    from flow.ui.hub.window import CONTENT_MAX_WIDTH

    hub = HubWindow(ctx)
    qtbot.addWidget(hub)
    hub.resize(2200, 900)
    hub.show()
    qtbot.wait(30)
    for page in hub.pages.values():
        assert page.maximumWidth() == CONTENT_MAX_WIDTH


@pytest.mark.parametrize("p", PALETTES, ids=lambda p: p.name)
def test_settings_page_fits_without_horizontal_scroll_in_both_themes(qtbot, ctx, p):
    theme.force_palette(p)
    theme.apply_theme(QApplication.instance(), p)
    hub = HubWindow(ctx)
    qtbot.addWidget(hub)
    hub.resize(900, 650)  # the minimum window size
    hub.show_page("Settings")
    qtbot.wait(50)
    assert hub.pages["Settings"].scroll.horizontalScrollBar().maximum() == 0


def test_empty_pages_teach_instead_of_showing_a_blank_table(qtbot, ctx):
    hub = HubWindow(ctx)
    qtbot.addWidget(hub)
    hub.show()
    d, s, h = hub.pages["Dictionary"], hub.pages["Snippets"], hub.pages["Home"]
    assert d.empty_state.isVisibleTo(d) and not d.table.isVisibleTo(d)
    assert s.empty_state.isVisibleTo(s) and not s.table.isVisibleTo(s)
    assert h.empty_note.isVisibleTo(h)
    ctx.dictionary.add("Kubernetes")
    d.refresh()
    assert d.table.isVisibleTo(d) and not d.empty_state.isVisibleTo(d)
    assert d.empty_add.text()  # the empty state offers the next action
