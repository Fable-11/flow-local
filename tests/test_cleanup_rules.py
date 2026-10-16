import json
from pathlib import Path

import pytest

from flow.cleanup.rules import ENTER, NL, RuleOptions, apply_post, apply_pre, clean_rules

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "cleanup" / "rule_cases.json").read_text("utf-8")
)


def test_fixture_set_is_big_enough_and_multilingual():
    assert len(CASES) >= 30
    assert {c["lang"] for c in CASES} == {"en", "ar", "mixed"}
    assert len({c["id"] for c in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_rule_cleanup(case):
    assert clean_rules(case["input"]) == case["expected"]


def test_press_enter_experimental_toggle():
    opts = RuleOptions(press_enter=True)
    pre = apply_pre("send message press enter", opts)
    assert ENTER in pre
    assert apply_post(pre, opts) == "Send message"


def test_sentinels_roundtrip_through_pre_post():
    pre = apply_pre("one new line two")
    assert NL in pre
    assert apply_post(pre).startswith("One\nTwo")


def test_options_can_disable_rules():
    opts = RuleOptions(remove_fillers=False, self_corrections=False, final_period=False)
    assert clean_rules("um meet at 3, no wait, 4", opts) == "Um meet at 3, no wait, 4"


def test_idempotent_on_clean_text():
    text = "This is already clean, with punctuation."
    assert clean_rules(text) == text


def test_empty_and_whitespace():
    assert clean_rules("") == ""
    assert clean_rules("   ") == ""
