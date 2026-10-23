"""Self-corrections ("no no, I mean ..."): resolved when clear, left alone when not.

The cases come from a design debate: one agent proposed the rules, another wrote the sentences
that would break a naive version (a correction cue that is really content), and real sentences
from the user's own history.
"""

from __future__ import annotations

import pytest

from flow.cleanup.corrections import repair_corrections
from flow.cleanup.rules import clean_rules

RESOLVED = [
    # (spoken, what is left)
    ("send it to Ahmed, no no, I mean Omar", "send it to Omar"),
    ("Send it to Ahmed no no no Omar", "Send it to Omar"),
    ("The meeting is on Monday, sorry, I meant Tuesday", "The meeting is on Tuesday"),
    ("Book a flight to Paris, or rather Lyon", "Book a flight to Lyon"),
    (
        "Let's use the red one, actually no, the blue one with the long strap",
        "Let's use the blue one with the long strap",
    ),
    ("Open the settings, sorry, I meant the preferences window", "Open the preferences window"),
    ("I want the red car, no I mean the blue car", "I want the blue car"),
    # a restart: the abandoned beginning disappears
    (
        "so I think we should, no no, what I want to say is we should wait",
        "what I want to say is we should wait",
    ),
    (
        "what is it, no, no, no, no, no what is the deadline for the second report",
        "what is the deadline for the second report",
    ),
    ("how to start, how to start, I mean", "how to start"),
    # Arabic and mixed
    ("ابعته لأحمد، لا لا، قصدي عمر", "ابعته لعمر"),
    ("الاجتماع يوم الأحد، أقصد الاثنين", "الاجتماع يوم الاثنين"),
    ("Send the report to أحمد، no no قصدي عمر", "Send the report to عمر"),
]


@pytest.mark.parametrize(("spoken", "left"), RESOLVED)
def test_clear_corrections_keep_only_the_corrected_version(spoken, left):
    assert repair_corrections(spoken) == left


LEFT_ALONE = [
    "I mean business",
    "No, I mean it",
    "I told him no no no and he left",
    "Sorry for the delay",
    "Actually that works",
    "It works not only on Windows but also on Mac",
    'She said, "no, I meant Omar," and hung up',
    "The feature lets you say scratch that to delete a sentence",
    "No problem",
    "I mean, it depends",
    "What do you mean by that?",
    "I said sorry, then I left",
    "Or rather than waiting, we shipped it",
    "I'm not sorry, I meant it",
    "Wait, no, the file is not there",
    "لا لا لا تقلق",
    "قصدي في المشروع واضح",
    "يعني ما فهمت",
    "Send it, أقصد المنزل is closer",
    # the user describing the feature (a real dictation)
    "I explain a fix and say no no I mean this, it keeps both versions",
    # points back at earlier words ("it" = the file): the AI model decides, not the rules
    "send the file to Ahmed no wait send it to Omar",
    # ambiguous: keep both versions rather than guess
    "I want the red one, sorry, the blue one is nice too",
    "Send it to Ahmed, actually Omar should see it too",
    "Meet at 3, I mean 4 is also fine",
    "I want a red car, I mean blue",
    "Not like this, I mean change the last heading to summary and remove the line you added",
]


@pytest.mark.parametrize("text", LEFT_ALONE)
def test_content_that_only_looks_like_a_correction_is_not_touched(text):
    assert repair_corrections(text) == text


def test_the_correction_works_through_the_whole_cleanup_without_the_ai_model():
    assert clean_rules("send it to Ahmed, no no, I mean Omar") == "Send it to Omar."
    assert clean_rules("um so what is it, no no no what is the plan") == "What is the plan."


def test_numbers_still_use_the_number_rules():
    assert clean_rules("let's meet at 3, no wait, 4") == "Let's meet at 4."
    assert clean_rules("I need 5 dollars, I mean 10") == "I need 10 dollars."


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("call him tomorrow, scratch that. Email him today", "Email him today."),
        ("send it to Ahmed scratch that send it to Omar", "Send it to Omar."),
        ("The feature lets you say scratch that to delete a sentence", None),
    ],
)
def test_scratch_that_deletes_the_last_sentence_but_not_when_it_is_only_mentioned(
    spoken, expected
):
    out = clean_rules(spoken)
    assert out == (expected or spoken + ".")


def test_scratch_that_never_erases_a_whole_long_dictation():
    long = " ".join(f"word{i}" for i in range(30))
    out = clean_rules(long + " scratch that")
    assert out.startswith("Word0") and "word29" not in out  # only the last 12 words go


def test_a_correction_with_nothing_before_it_is_left_alone():
    assert repair_corrections("no no I mean Omar") == "no no I mean Omar"
    assert repair_corrections("") == ""
