import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from flow.ui.flowbar import FlowBarGroup  # noqa: E402


class FakeScreen:
    """A monitor stand-in: only what FlowBar needs to position itself."""

    def __init__(self, x, w=1920, h=1080):
        self.rect = QRect(x, 0, w, h - 40)

    def availableGeometry(self):  # noqa: N802
        return self.rect


@pytest.fixture
def two_screens():
    return [FakeScreen(0), FakeScreen(1920)]


def make_group(screens, mode="all"):
    state = {"screens": screens}
    g = FlowBarGroup(mode, screens_provider=lambda: state["screens"])
    g._state_holder = state  # tests change the monitor list through this
    return g


def test_one_bar_per_monitor_centered_at_the_bottom(qtbot, two_screens):
    g = make_group(two_screens)
    assert len(g.bars) == 2
    for screen, bar in zip(two_screens, g.bars, strict=True):
        qtbot.addWidget(bar)
        geo = screen.availableGeometry()
        assert abs(bar.geometry().center().x() - geo.center().x()) <= 1
        assert bar.geometry().bottom() <= geo.bottom() + 1


def test_mirror_mode_shows_the_same_state_on_every_monitor(qtbot, two_screens):
    g = make_group(two_screens)
    g.set_state("recording")
    assert all(b.isVisible() and b.state == "recording" for b in g.bars)
    g.push_level(0.1)
    assert all(b._levels[-1] > 0 for b in g.bars)
    g.set_state("processing")
    assert all(b.state == "processing" for b in g.bars)
    for b in g.bars:
        qtbot.addWidget(b)


def test_active_mode_shows_only_the_screen_with_the_pointer(qtbot, two_screens, monkeypatch):
    import flow.ui.flowbar as fb

    monkeypatch.setattr(fb, "screen_under_cursor", lambda: two_screens[1])
    g = make_group(two_screens, "active")
    g.set_state("recording")
    first, second = g.bars
    assert not first.isVisible() and second.isVisible() and second.state == "recording"
    for b in g.bars:
        qtbot.addWidget(b)
    # the pointer moves to monitor 1; the next dictation follows it
    g.set_state("idle")
    monkeypatch.setattr(fb, "screen_under_cursor", lambda: two_screens[0])
    g.set_state("idle")
    g.set_state("recording")
    assert first.isVisible() and not second.isVisible()


def test_switching_modes_live(qtbot, two_screens, monkeypatch):
    import flow.ui.flowbar as fb

    monkeypatch.setattr(fb, "screen_under_cursor", lambda: two_screens[0])
    g = make_group(two_screens, "all")
    g.set_state("recording")
    assert all(b.isVisible() for b in g.bars)
    g.set_mode("active")
    assert g.bars[0].isVisible() and not g.bars[1].isVisible()
    g.set_mode("all")
    assert all(b.isVisible() for b in g.bars)
    for b in g.bars:
        qtbot.addWidget(b)


def test_plugging_and_unplugging_a_monitor(qtbot, two_screens):
    g = make_group(two_screens[:1])
    assert len(g.bars) == 1
    g.set_state("recording")
    g._state_holder["screens"] = two_screens  # monitor plugged in mid-dictation
    g.sync()
    assert len(g.bars) == 2 and g.bars[1].state == "recording" and g.bars[1].isVisible()
    g._state_holder["screens"] = two_screens[1:]  # first monitor unplugged
    g.sync()
    assert len(g.bars) == 1
    for b in g.bars:
        qtbot.addWidget(b)


def test_click_from_any_bar_is_forwarded(qtbot, two_screens):
    g = make_group(two_screens)
    g.set_state("handsfree")
    clicks = []
    g.clicked.connect(lambda: clicks.append(1))
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(g.bars[1], Qt.MouseButton.LeftButton)
    assert clicks == [1]
    for b in g.bars:
        qtbot.addWidget(b)


def test_idle_visibility_applies_to_all_bars(qtbot, two_screens):
    g = make_group(two_screens)
    g.set_idle_visible(False)
    assert all(b.idle_visible is False for b in g.bars)
    for b in g.bars:
        qtbot.addWidget(b)


def test_real_screens_work_without_a_stub(qtbot):
    g = FlowBarGroup("all")
    assert len(g.bars) == len(QGuiApplication.screens()) >= 1
    for b in g.bars:
        qtbot.addWidget(b)
