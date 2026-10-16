from flow.fixlast import suggest_fix


def test_multiword_spoken_form_to_name():
    s = suggest_fix("I joined the cuber nettys bootcamp last year.", "Kubernetes")
    assert (s.heard, s.correct) == ("cuber nettys", "Kubernetes")
    assert s.spoken == "cuber nettys"


def test_single_word_misrecognition():
    s = suggest_fix("We use pie game for the demo.", "Pygame")
    assert s is not None and s.correct == "Pygame"
    assert s.heard in ("pie game", "pie", "game")


def test_case_only_fix_has_no_spoken_form():
    s = suggest_fix("we use pygame for the demo", "Pygame")
    assert s.heard == "pygame" and s.spoken is None


def test_already_correct_returns_none():
    assert suggest_fix("I joined Kubernetes last year.", "Kubernetes") is None


def test_unrelated_or_too_long_returns_none():
    assert suggest_fix("hello there", "Zzzzzzzz") is None
    assert suggest_fix("hello there", "a b c d e") is None
    assert suggest_fix("hello there", "   ") is None
    assert suggest_fix("", "word") is None


def test_arabic_correction():
    s = suggest_fix("انا رايح لجامعة الملك سعود بكرة", "جامعة")
    assert s is not None and s.correct == "جامعة"


def test_punctuation_is_ignored():
    s = suggest_fix("Meet me at the cuber nettys, please.", "Kubernetes.")
    assert s.correct == "Kubernetes" and s.heard == "cuber nettys"
