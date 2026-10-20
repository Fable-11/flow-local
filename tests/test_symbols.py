from __future__ import annotations

import pytest

from flow.cleanup.pipeline import CleanupPipeline
from flow.processing import TextProcessor
from flow.store.db import Database
from flow.store.dictionary import DictionaryStore
from flow.store.snippets import SnippetStore
from flow.symbols import speak_symbols


@pytest.mark.parametrize(
    ("spoken", "typed"),
    [
        ("john underscore smith at sign gmail dot com", "john_smith@gmail dot com"),
        ("john underscore smith add sign gmail dot com", "john_smith@gmail dot com"),
        ("john at the rate gmail dot com", "john@gmail dot com"),
        ("sara at gmail dot com", "sara@gmail dot com"),
        ("the file name is index dot js", "the file name is index.js"),
        ("open main dot PY now", "open main.py now"),
        ("version three dot five is out", "version 3.5 is out"),
        ("pi is 3 dot 14", "pi is 3.14"),
        ("tag it hashtag flow", "tag it #flow"),
        ("set user underscore name equals sign admin", "set user_name = admin"),
        ("yes slash no", "yes/no"),
        ("it costs dollar sign fifty", "it costs $fifty"),
        ("fifty percent sign off", "fifty% off"),
        ("tom ampersand jerry", "tom & jerry"),
        ("open parenthesis see note close parenthesis", "(see note)"),
        ("type back slash n", r"type \n"),
    ],
)
def test_spoken_symbols_become_symbols(spoken, typed):
    assert speak_symbols(spoken) == typed


@pytest.mark.parametrize(
    "text",
    [
        "she put a dot on the map",
        "the at sign is on my keyboard",
        "use the underscore key",
        "a hashtag is useful",
        "email me at gmail dot com",
        "meet me at noon",
        "the dash of salt",
        "he will slash prices today",
        "a good point about three things",
    ],
)
def test_ordinary_sentences_keep_their_words(text):
    assert speak_symbols(text) == text


def make_processor():
    db = Database()
    p = TextProcessor(CleanupPipeline(None, use_llm=False), DictionaryStore(db), SnippetStore(db))
    p.learn_mode = "off"
    return p


@pytest.mark.parametrize(
    ("spoken", "final"),
    [
        (
            "send it to john underscore smith at sign gmail dot com",
            "Send it to john_smith@gmail.com",
        ),
        (
            "send it to john underscore smith add sign gmail dot com",
            "Send it to john_smith@gmail.com",
        ),
        ("my email is sara at gmail dot com", "My email is sara@gmail.com"),
        ("the file name is index dot js", "The file name is index.js"),
        ("tag it hashtag flow", "Tag it #flow"),
        ("set user underscore name equals sign admin", "Set user_name = admin."),
        ("version three dot five is out", "Version 3.5 is out."),
        ("what is your name question mark", "What is your name?"),
    ],
)
def test_through_the_whole_pipeline(spoken, final):
    assert make_processor().process(spoken).text == final


def test_switched_off_with_spoken_commands():
    p = make_processor()
    p.spoken_symbols = False
    assert "underscore" in p.process("john underscore smith").text
