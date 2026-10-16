import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from flow.ui.flowbar import STATES, FlowBar  # noqa: E402
from flow.ui.tray import make_icon  # noqa: E402


@pytest.fixture
def bar(qtbot):
    b = FlowBar()
    qtbot.addWidget(b)
    b.show()
    return b


def test_starts_idle_and_not_animating(bar):
    assert bar.state == "idle"
    bar.set_state("idle")
    qtbot_wait_ms = 150
    QTest.qWait(qtbot_wait_ms)
    assert not bar._timer.isActive()  # no timer running while idle: no CPU use


def test_recording_state_animates_and_expands(bar):
    bar.set_state("recording")
    assert bar._timer.isActive()
    QTest.qWait(400)
    assert bar._w > 120  # pill grew from the idle dot toward the recording width
    bar.set_state("idle")
    QTest.qWait(600)
    assert bar._w < 60


def test_done_and_error_return_to_idle(qtbot, bar, monkeypatch):
    import flow.ui.flowbar as fb

    monkeypatch.setitem(fb._RETURN_TO_IDLE_MS, "done", 50)
    monkeypatch.setitem(fb._RETURN_TO_IDLE_MS, "error", 50)
    for state in ("done", "error"):
        bar.set_state(state, "No speech heard" if state == "error" else "")
        qtbot.waitUntil(lambda: bar.state == "idle", timeout=1500)


def test_levels_are_normalised(bar):
    bar.push_level(0.0)
    bar.push_level(5.0)
    bar.push_level(-1.0)
    assert all(0.0 <= v <= 1.0 for v in bar._levels)
    assert list(bar._levels)[-2] == 1.0


def test_click_only_while_recording(qtbot, bar):
    clicks = []
    bar.clicked.connect(lambda: clicks.append(1))
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton)
    assert clicks == []
    bar.set_state("handsfree")
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton)
    assert clicks == [1]


def test_invalid_state_rejected(bar):
    with pytest.raises(ValueError):
        bar.set_state("exploding")


@pytest.mark.parametrize("state", STATES)
def test_every_state_paints_something(bar, state):
    bar.set_state(state, "Loading model" if state in ("loading", "error") else "")
    QTest.qWait(450)
    img = bar.grab().toImage()
    opaque = sum(
        1 for x in range(0, img.width(), 2) for y in range(0, img.height(), 2)
        if img.pixelColor(x, y).alpha() > 0
    )
    assert opaque > 0


def test_tray_icon_is_drawn():
    assert not make_icon().isNull()


def test_bar_sits_at_bottom_center(bar):
    from PySide6.QtGui import QGuiApplication

    geo = QGuiApplication.primaryScreen().availableGeometry()
    assert abs(bar.geometry().center().x() - geo.center().x()) <= 1
    assert bar.geometry().bottom() <= geo.bottom() + 1
