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
    for _ in range(3):
        r = p.process("i asked cloud to review it with anthropic tools")
    assert "Claude" in r.text and "cloud" not in r.text
    assert p.dictionary.get("Claude") is not None  # now it also biases Whisper
    assert "Claude" in (p.whisper_prompt() or "")


def test_processor_switches_off(db):
    p = make_processor(db)
    p.smart_terms = False
    p.auto_learn = False
    for _ in range(4):
        r = p.process("i asked cloud to deploy Kubernetes")
    assert "cloud" in r.text and p.dictionary.list() == []
