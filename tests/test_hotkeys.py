from flow.hotkeys.bindings import (
    ABORT,
    CANCEL,
    COMMAND_START,
    COMMAND_STOP,
    FIX_LAST,
    HANDSFREE_TOGGLE,
    PTT_START,
    PTT_STOP,
    HotkeyMachine,
    find_conflicts,
    format_chord,
    parse_chord,
)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def make(**kw):
    clock = Clock()
    return HotkeyMachine(now=clock, **kw), clock


def press(m, *keys):
    out = []
    for k in keys:
        out.append(m.feed(k, True))
    return out


def release(m, *keys):
    return [m.feed(k, False) for k in keys]


def acts(results):
    return [a for r in results for a in r.actions]


def test_parse_and_format():
    assert parse_chord("Control+Windows+Space") == frozenset({"ctrl", "win", "space"})
    assert format_chord(frozenset({"space", "win", "ctrl"})) == "ctrl+win+space"


def test_conflicts():
    assert find_conflicts({"a": "ctrl+win", "b": "win+ctrl"}) == [("a", "b")]
    assert find_conflicts({"a": "ctrl+win", "b": "ctrl+win+space"}) == []
    assert find_conflicts({"a": "esc"}) == [("a", "cancel")]


def test_push_to_talk_hold_and_release():
    m, clock = make()
    assert acts(press(m, "ctrl", "win")) == [PTT_START]
    clock.advance(1.0)
    r = release(m, "win", "ctrl")
    assert acts(r) == [PTT_STOP]
    assert r[0].inject_dummy  # Win-up must not open the Start menu
    assert not m.active


def test_short_tap_cancels():
    m, clock = make()
    press(m, "ctrl", "win")
    clock.advance(0.1)
    assert acts(release(m, "win", "ctrl")) == [ABORT]


def test_double_tap_starts_hands_free():
    m, clock = make()
    press(m, "ctrl", "win")
    clock.advance(0.1)
    release(m, "win", "ctrl")
    clock.advance(0.2)
    press(m, "ctrl", "win")
    clock.advance(0.1)
    assert acts(release(m, "win", "ctrl")) == [ABORT, HANDSFREE_TOGGLE]
    assert m.active


def test_double_tap_disabled():
    m, clock = make(double_tap=False)
    for _ in range(2):
        press(m, "ctrl", "win")
        clock.advance(0.1)
        assert acts(release(m, "win", "ctrl")) == [ABORT]
        clock.advance(0.1)


def test_hands_free_toggle_swallows_space_and_cancels_ptt():
    m, clock = make()
    press(m, "ctrl", "win")
    r = m.feed("space", True)
    assert r.actions == [ABORT, HANDSFREE_TOGGLE]
    assert r.swallow
    assert m.active
    assert m.feed("space", False).swallow
    release(m, "win", "ctrl")
    assert m.active


def test_hands_free_second_toggle_stops():
    m, clock = make()
    press(m, "ctrl", "win")
    m.feed("space", True)
    m.feed("space", False)
    release(m, "win", "ctrl")
    clock.advance(1)
    press(m, "ctrl", "win")  # ignored while hands-free owns the mic
    r = m.feed("space", True)
    assert r.actions == [HANDSFREE_TOGGLE]
    assert not m.active


def test_command_mode_upgrade_from_ptt():
    m, clock = make()
    press(m, "ctrl", "win")
    r = m.feed("alt", True)
    assert r.actions == [ABORT, COMMAND_START]
    clock.advance(2)
    assert acts(release(m, "alt")) == [COMMAND_STOP]
    # ctrl+win still held: must not re-trigger push-to-talk
    assert acts(press(m, "alt")) == []


def test_escape_cancels_only_when_active():
    m, clock = make()
    r = m.feed("esc", True)
    assert r.actions == [] and not r.swallow
    m.feed("esc", False)
    press(m, "ctrl", "win")
    r = m.feed("esc", True)
    assert r.actions == [CANCEL] and r.swallow
    assert m.feed("esc", False).swallow
    assert not m.active


def test_unrelated_key_cancels_held_chord():
    m, clock = make()
    press(m, "ctrl", "win")
    assert m.feed("left", True).actions == [ABORT]


def test_fix_last():
    m, _ = make()
    press(m, "ctrl", "win")
    r = m.feed("f", True)
    assert r.actions == [ABORT, FIX_LAST] and r.swallow


def test_mouse_button_binding_is_swallowed():
    m, clock = make(bindings={"push_to_talk": "mouse_x1"})
    r = m.feed("mouse_x1", True)
    assert r.actions == [PTT_START] and r.swallow
    clock.advance(1)
    r = m.feed("mouse_x1", False)
    assert r.actions == [PTT_STOP] and r.swallow


def test_auto_repeat_ignored():
    m, _ = make()
    press(m, "ctrl", "win")
    assert m.feed("win", True).actions == []
