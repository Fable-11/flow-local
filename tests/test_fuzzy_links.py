from __future__ import annotations

import pytest

from flow.cleanup.pipeline import CleanupPipeline, validate_llm_output
from flow.links import protect_links, restore_links, speak_to_links
from flow.processing import TextProcessor
from flow.store.db import Database
from flow.store.dictionary import DictionaryStore
from flow.store.fuzzy import skeleton
from flow.store.snippets import SnippetStore


@pytest.fixture
def d():
    store = DictionaryStore(Database())
    for word in ("Kubernetes", "Pygame", "GitHub", "faster-whisper", "Anthropic"):
        store.add(word)
    return store


# -- automatic replacement by sound ---------------------------------------------------------------
def test_skeleton_ignores_vowels_and_spelling_variants():
    assert skeleton("cubernettys") == skeleton("Kubernetes")
    assert skeleton("phone") == skeleton("fone")


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("we deploy on cuber nettys today", "we deploy on Kubernetes today"),
        ("I use pie game for it", "I use Pygame for it"),
        ("open get hub now", "open GitHub now"),
        ("use faster whisper here", "use faster-whisper here"),
        ("kubernetis is great", "Kubernetes is great"),
    ],
)
def test_words_that_sound_like_a_dictionary_word_are_replaced_without_a_spoken_form(
    d, heard, expected
):
    assert d.apply_replacements(heard)[0] == expected


@pytest.mark.parametrize(
    "text",
    [
        "the cloud is big",
        "the page about a pigeon",
        "a quad is a square",
        "this game is fun",
        "we met at the hub",
        "the cooper netted fish",
    ],
)
def test_ordinary_sentences_are_left_alone(d, text):
    assert d.apply_replacements(text)[0] == text


def test_fuzzy_can_be_switched_off_and_counts_as_a_use(d):
    d.fuzzy = False
    assert d.apply_replacements("on cuber nettys")[0] == "on cuber nettys"
    d.fuzzy = True
    text, hits = d.apply_replacements("on cuber nettys")
    assert text == "on Kubernetes" and hits == ["Kubernetes"]


def test_short_and_non_latin_words_are_matched_exactly_only(d):
    d.add("AWS")
    d.add("أحمد")
    assert d.apply_replacements("use a w s today")[0] == "use a w s today"
    assert d.apply_replacements("كلمت احمد")[0] == "كلمت احمد"


# -- spoken links and addresses -------------------------------------------------------------------
@pytest.mark.parametrize(
    ("spoken", "typed"),
    [
        ("go to github dot com slash flow dash local", "go to github.com/flow-local"),
        ("visit www dot google dot com", "visit www.google.com"),
        (
            "open https colon slash slash example dot com slash a slash b now",
            "open https://example.com/a/b now",
        ),
        ("docs dot python dot org slash 3", "docs.python.org/3"),
        ("email me at john dot smith at gmail dot com", "email me at john.smith@gmail.com"),
        ("my email is sara at outlook dot com", "my email is sara@outlook.com"),
        ("open github .com now", "open github.com now"),
    ],
)
def test_spoken_links_are_written_as_typed(spoken, typed):
    assert speak_to_links(spoken) == typed


@pytest.mark.parametrize(
    "text",
    [
        "call me at noon",
        "the dot com era",
        "it is available at amazon.com",
        "see you at the cloud",
        "look at google.com",
    ],
)
def test_ordinary_text_is_not_turned_into_a_link(text):
    assert speak_to_links(text) == text


def test_links_survive_cleanup_untouched():
    text, links = protect_links(speak_to_links("visit github dot com slash flow"))
    assert text == "visit ⟦U0⟧" and links == ["github.com/flow"]
    assert restore_links("Visit ⟦U0⟧.", links) == "Visit github.com/flow."
    assert protect_links("Visit github.com.")[0] == "Visit ⟦U0⟧."


def test_llm_output_that_changes_a_link_placeholder_is_rejected():
    assert validate_llm_output("go to ⟦U0⟧ now", "go to the site now") == "link placeholder changed"
    assert validate_llm_output("go to ⟦U0⟧ now please", "Go to ⟦U0⟧ now, please.") is None


def test_processor_keeps_links_lowercase_unpunctuated_and_complete():
    db = Database()
    p = TextProcessor(CleanupPipeline(None, use_llm=False), DictionaryStore(db), SnippetStore(db))
    r = p.process("um github dot com slash flow is where i keep it")
    assert r.text == "github.com/flow is where I keep it."
    assert p.process("send it to sara at gmail dot com").text == "Send it to sara@gmail.com"
    assert p.process("go to https colon slash slash example dot com").text == (
        "Go to https://example.com"
    )
