from flow.insert.spacing import SpacingTracker


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_space_between_consecutive_dictations():
    clock = Clock()
    s = SpacingTracker(now=clock)
    assert s.prefix_for(1, "Hello") == ""  # first insertion
    s.record(1, "Hello")
    assert s.prefix_for(1, "world") == " "


def test_no_space_in_new_window_or_after_timeout():
    clock = Clock()
    s = SpacingTracker(window_s=60, now=clock)
    s.record(1, "Hello")
    assert s.prefix_for(2, "world") == ""
    clock.t = 61
    assert s.prefix_for(1, "world") == ""


def test_no_space_before_punctuation_or_after_newline():
    s = SpacingTracker(now=Clock())
    s.record(1, "Hello")
    assert s.prefix_for(1, ", and more") == ""
    assert s.prefix_for(1, "؟") == ""
    s.record(1, "line one\n")
    assert s.prefix_for(1, "line two") == ""


def test_arabic_and_forget():
    s = SpacingTracker(now=Clock())
    s.record(1, "مرحبا")
    assert s.prefix_for(1, "بكم") == " "
    s.forget()
    assert s.prefix_for(1, "بكم") == ""
