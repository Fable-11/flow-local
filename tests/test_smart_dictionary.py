from __future__ import annotations

import pytest

from flow.cleanup.pipeline import CleanupPipeline
from flow.processing import TextProcessor
from flow.smartterms import fix_terms
from flow.store.db import Database
from flow.store.dictionary import DictionaryStore
from flow.store.snippets import SnippetStore
from flow.store.terms import candidate_terms


@pytest.fixture
def db():
    d = Database()
    yield d
    d.close()


# -- smart terms ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("I asked cloud to review the function", "I asked Claude to review the function"),
        ("open cloud code and run it", "open Claude code and run it"),
        ("I use cloud sonnet for this", "I use Claude sonnet for this"),
        ("put it in cloud dot md", "put it in CLAUDE.md"),
        (
            "anthropic made cloud and chat gpt is from open ai",
            "Anthropic made Claude and ChatGPT is from OpenAI",
        ),
        ("push it to git hub", "push it to GitHub"),
        ("open it in v s code", "open it in VS Code"),
    ],
)
def test_ai_names_are_fixed_from_context(heard, expected):
    assert fix_terms(heard) == expected


@pytest.mark.parametrize(
    "text",
    [
        "we moved the servers to the cloud",
        "cloud storage is cheap",
        "ask cloud storage providers for a quote",
        "the cat clawed the sofa",
        "our cloud bill went up",
        "anthropic is in the cloud",
    ],
)
def test_real_cloud_sentences_are_untouched(text):
    assert fix_terms(text).replace("Anthropic", "anthropic") == text


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("I can see it with my I", "I can see it with my eye"),
        ("my I hurts", "my eye hurts"),
        ("close your Is and rest", "close your eyes and rest"),
        ("put the I drops in", "put the eye drops in"),
        ("add it to the Q", "add it to the queue"),
        ("a message Q holds jobs", "a message queue holds jobs"),
        ("explain stack and Q", "explain stack and queue"),
        ("Q and stack are data structures", "Queue and stack are data structures"),
        ("push it to the job Qs", "push it to the job queues"),
        ("he is waiting in the cue", "he is waiting in the queue"),
        ("a stack and cue", "a stack and queue"),
    ],
)
def test_lookalike_words_are_fixed_from_context(heard, expected):
    assert fix_terms(heard) == expected


@pytest.mark.parametrize(
    "text",
    [
        "I can see it",
        "I think I know",
        "between you and I",
        "press the Q key",
        "the letter Q is next",
        "Q and A with the team",
        "take your cue from me",
        "the cue ball is white",
        "Q3 results look good",
        "the I in team",
    ],
)
def test_lookalike_rules_leave_real_sentences_alone(text):
    assert fix_terms(text) == text


# -- term extraction ----------------------------------------------------------------------------
def test_candidate_terms_counts_once_per_text_and_skips_sentence_starts():
    text = "Today I used Kubernetes. Kubernetes is great, and so is faster-whisper on Monday"
    assert candidate_terms(text) == ["Kubernetes", "faster-whisper"]


# -- self-learning dictionary -----------------------------------------------------------------
def test_word_is_learned_after_three_separate_dictations(db):
    d = DictionaryStore(db)
    assert d.learn("we deploy with Kubernetes today") == []
    assert d.learn("then Kubernetes restarts the pod") == []
    assert d.learn("and Kubernetes scales it") == ["Kubernetes"]
    entry = d.get("kubernetes")
    assert entry is not None and entry.auto and entry.written == "Kubernetes"
    assert d.words_for_prompt() == []  # a learned word must be used twice before it steers Whisper
    d.record_use(["Kubernetes"])
    d.record_use(["Kubernetes"])
    assert d.words_for_prompt() == ["Kubernetes"]


def test_repeats_inside_one_dictation_do_not_count_extra(db):
    d = DictionaryStore(db)
    for _ in range(2):
        assert d.learn("Kubernetes and Kubernetes and Kubernetes") == []


def test_deleted_auto_word_is_not_learned_again_until_added_by_hand(db):
    d = DictionaryStore(db)
    for _ in range(3):
        d.learn("we deploy with Kubernetes")
    assert d.delete("Kubernetes")
    for _ in range(5):
        assert d.learn("we deploy with Kubernetes") == []
    assert d.get("Kubernetes") is None
    d.add("Kubernetes")  # typed in by hand: allowed again and no longer "auto"
    assert d.get("Kubernetes").auto is False


def test_deleting_a_manual_word_does_not_block_learning(db):
    d = DictionaryStore(db)
    d.add("Kubernetes")
    d.delete("Kubernetes")
    for _ in range(3):
        d.learn("we deploy with Kubernetes")
    assert d.get("Kubernetes").auto


def test_learned_word_fixes_casing_afterwards(db):
    d = DictionaryStore(db)
    for _ in range(3):
        d.learn("we deploy with Kubernetes")
    assert d.apply_replacements("i love kubernetes")[0] == "i love Kubernetes"


def test_recently_used_words_rank_first_and_stale_auto_words_are_pruned(db):
    d = DictionaryStore(db)
    for w in ("Alpha", "Beta"):
        d.add(w, auto=True)
    d.record_use(["Alpha", "Beta"])
    d.record_use(["Alpha", "Beta"])
    d.record_use(["Beta"])
    assert d.words_for_prompt() == ["Beta", "Alpha"]
    db.execute("UPDATE dictionary SET created_at = '2000-01-01 00:00:00'")
    db.execute("UPDATE dictionary SET last_used = NULL WHERE written = 'Alpha'")
    db.execute("UPDATE dictionary SET last_used = '2000-01-01 00:00:00' WHERE written = 'Beta'")
    assert d.prune_stale() == 2
    assert d.list() == []


def test_prune_keeps_manual_words(db):
    d = DictionaryStore(db)
    d.add("Manual")
    db.execute("UPDATE dictionary SET created_at = '2000-01-01 00:00:00'")
    assert d.prune_stale() == 0 and d.get("Manual") is not None


# -- processor ----------------------------------------------------------------------------------
def make_processor(db):
    pipeline = CleanupPipeline(None, use_llm=False)
    return TextProcessor(pipeline, DictionaryStore(db), SnippetStore(db))


def test_processor_fixes_claude_and_learns_it(db):
    p = make_processor(db)
    for _ in range(5):  # learned on the 3rd, then used twice before it steers Whisper
        r = p.process("i asked cloud to review it with anthropic tools")
    assert "Claude" in r.text and "cloud" not in r.text
    assert p.dictionary.get("Claude") is not None  # now it also biases Whisper
    assert "Claude" in (p.whisper_prompt() or "")


def test_processor_switches_off(db):
    p = make_processor(db)
    p.smart_terms = False
    p.learn_mode = "off"
    for _ in range(4):
        r = p.process("i asked cloud to deploy Kubernetes")
    assert "cloud" in r.text and p.dictionary.list() == []


# -- not annoying: modes and the suggestion gate ------------------------------------------------
from flow.store.settings_repo import SettingsRepo  # noqa: E402
from flow.store.suggestgate import BASE_COOLDOWN_S, MAX_PER_DAY, SuggestionGate  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def test_gate_spaces_prompts_and_limits_them_per_day(db):
    clock = Clock()
    gate = SuggestionGate(SettingsRepo(db), clock)
    assert gate.allow()
    gate.shown()
    assert not gate.allow()  # too soon
    clock.now += BASE_COOLDOWN_S + 1
    assert gate.allow()
    shown = 1
    while gate.allow() and shown < 10:
        gate.shown()
        gate.answered(True)
        clock.now += BASE_COOLDOWN_S + 1
        shown += 1
    assert shown == MAX_PER_DAY
    clock.now += 24 * 3600  # a new day starts fresh
    assert gate.allow()


def test_gate_backs_off_when_prompts_are_ignored_and_recovers_on_yes(db):
    clock = Clock()
    gate = SuggestionGate(SettingsRepo(db), clock)
    gate.shown()
    gate.answered(False)
    clock.now += BASE_COOLDOWN_S + 1
    assert not gate.allow()  # one ignored prompt doubles the pause
    clock.now += BASE_COOLDOWN_S
    assert gate.allow()
    gate.shown()
    gate.answered(True)
    clock.now += BASE_COOLDOWN_S + 1
    assert gate.allow()


def _ask_processor(db):
    p = make_processor(db)
    p.learn_mode = "ask"
    p.gate = SuggestionGate(SettingsRepo(db), Clock())
    return p


def test_ask_mode_offers_one_word_then_stays_quiet(db):
    p = _ask_processor(db)
    offered = [p.process("we deploy with Kubernetes and Terraform").suggestion for _ in range(4)]
    assert offered[:2] == [None, None]
    assert offered[2] == "Kubernetes"  # only one word at a time, nothing added without a yes
    assert offered[3] is None  # the pause between prompts is respected
    assert p.dictionary.list() == []


def test_ask_mode_keeps_counting_while_paused(db):
    p = _ask_processor(db)
    p.gate.shown()  # a prompt was just shown, so the next ones must wait
    for _ in range(3):
        assert p.process("we deploy with Kubernetes").suggestion is None
    assert p.dictionary.list() == []
    assert p.dictionary._is_rejected("Kubernetes") is False


def test_dismissed_word_is_not_offered_again(db):
    p = _ask_processor(db)
    p.dictionary.reject("Kubernetes")
    for _ in range(5):
        assert p.process("we deploy with Kubernetes").suggestion is None


@pytest.mark.parametrize("mode", ["suggest", "off"])
def test_suggest_only_and_off_modes_never_learn_or_prompt(db, mode):
    p = make_processor(db)
    p.learn_mode = mode
    for _ in range(5):
        assert p.process("we deploy with Kubernetes").suggestion is None
    assert p.dictionary.list() == []
