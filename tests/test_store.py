import json
import sqlite3

import pytest

from flow.cleanup.pipeline import CleanupPipeline
from flow.processing import TextProcessor
from flow.store.db import MIGRATIONS, Database
from flow.store.dictionary import DictionaryStore
from flow.store.settings_repo import SettingsRepo
from flow.store.snippets import SnippetStore, normalize
from flow.stt.engine import build_initial_prompt


@pytest.fixture
def db():
    d = Database()
    yield d
    d.close()


def test_migrations_set_version_and_persist(tmp_path):
    path = tmp_path / "t.db"
    d = Database(path)
    assert d.version == len(MIGRATIONS)
    DictionaryStore(d).add("Kubernetes")
    d.close()
    d2 = Database(path)  # reopening must not re-run migrations or lose data
    assert d2.version == len(MIGRATIONS)
    assert DictionaryStore(d2).get("kubernetes").written == "Kubernetes"
    d2.close()


def test_settings_roundtrip(db):
    s = SettingsRepo(db)
    assert s.get("x", 5) == 5
    s.set("x", {"a": [1, "ب"]})
    s.set("y", True)
    assert s.get("x") == {"a": [1, "ب"]}
    assert s.all() == {"x": {"a": [1, "ب"]}, "y": True}


# -- dictionary ---------------------------------------------------------------------------
def test_dictionary_add_update_delete(db):
    d = DictionaryStore(db)
    d.add("Pygame")
    d.add("pygame", spoken="pie game", starred=True)  # same word, case-insensitive upsert
    entries = d.list()
    assert len(entries) == 1
    assert entries[0].written == "pygame" and entries[0].spoken == "pie game" and entries[0].starred
    assert d.delete("PYGAME")
    assert not d.delete("pygame")
    with pytest.raises(ValueError):
        d.add("   ")


def test_dictionary_search_and_order(db):
    d = DictionaryStore(db)
    d.add("Zeta")
    d.add("Alpha")
    d.add("Mango", starred=True)
    assert [e.written for e in d.list()] == ["Mango", "Alpha", "Zeta"]
    assert [e.written for e in d.list("alp")] == ["Alpha"]


def test_prompt_words_starred_first_then_uses(db):
    d = DictionaryStore(db)
    d.add("Common")
    d.add("Rare")
    d.add("Star", starred=True)
    d.record_use(["Rare", "Rare"])
    assert d.words_for_prompt() == ["Star", "Rare", "Common"]
    assert build_initial_prompt(d.words_for_prompt()) == "Star, Rare, Common"
    assert len(d.words_for_prompt(limit=2)) == 2


def test_replacements_spoken_case_hyphen_and_arabic(db):
    d = DictionaryStore(db)
    d.add("Kubernetes", spoken="cuber nettys")
    d.add("faster-whisper")
    d.add("NASA")
    d.add("أحمد", spoken="احمد")
    spoken = "I study at nasa, the cuber nettys academy uses faster whisper"
    text, hits = d.apply_replacements(spoken)
    assert text == "I study at NASA, the Kubernetes academy uses faster-whisper"
    assert set(hits) == {"NASA", "Kubernetes", "faster-whisper"}
    assert d.apply_replacements("كلمت احمد اليوم")[0] == "كلمت أحمد اليوم"
    assert d.apply_replacements("nasaper")[0] == "nasaper"  # whole words only


def test_replacements_refresh_after_changes(db):
    d = DictionaryStore(db)
    assert d.apply_replacements("hello en ay es ay")[0] == "hello en ay es ay"
    d.add("NASA", spoken="en ay es ay")
    assert d.apply_replacements("hello en ay es ay")[0] == "hello NASA"
    d.delete("NASA")
    assert d.apply_replacements("hello en ay es ay")[0] == "hello en ay es ay"


def test_longest_spoken_form_wins(db):
    d = DictionaryStore(db)
    d.add("Open AI", spoken="open a i")
    d.add("OpenAI Codex", spoken="open a i codex")
    assert d.apply_replacements("use open a i codex now")[0] == "use OpenAI Codex now"


def test_export_import_json_and_csv_roundtrip(db):
    d = DictionaryStore(db)
    d.add("Kubernetes", spoken="cuber nettys", starred=True)
    d.add("أحمد")
    js, csv_text = d.export_json(), d.export_csv()
    assert json.loads(js)[0]["written"] == "Kubernetes"
    for text in (js, csv_text, "﻿" + csv_text):
        other = DictionaryStore(Database())
        assert other.import_text(text) == (2, 0)
        got = {e.written: (e.spoken, e.starred) for e in other.list()}
        assert got == {"Kubernetes": ("cuber nettys", True), "أحمد": (None, False)}


def test_import_skips_bad_rows_and_accepts_alt_headers(db):
    d = DictionaryStore(db)
    assert d.import_text("word,replacement,starred\nGitHub,git hub,yes\n,,\nNASA,,0\n") == (2, 1)
    assert d.get("GitHub").spoken == "git hub" and d.get("GitHub").starred


# -- snippets -----------------------------------------------------------------------------
def test_snippet_crud_and_search(db):
    s = SnippetStore(db)
    s.add("my email", "me@example.com")
    s.add("My GitHub", "https://github.com/me")
    s.add("my email", "other@example.com")  # upsert
    assert [x.trigger for x in s.list()] == ["my email", "My GitHub"]
    assert s.get("MY EMAIL").content == "other@example.com"
    assert [x.trigger for x in s.list("github")] == ["My GitHub"]
    assert s.delete("my email") and not s.delete("my email")
    with pytest.raises(ValueError):
        s.add("...", "x")
    with pytest.raises(ValueError):
        s.add("trigger", "")


def test_snippet_exact_match_ignores_case_and_punctuation(db):
    s = SnippetStore(db)
    s.add("my email", "me@example.com")
    s.add("عنواني", "الرياض، السعودية")
    assert s.match_exact("My email.").content == "me@example.com"
    assert s.match_exact("  my   EMAIL! ").content == "me@example.com"
    assert s.match_exact("عنواني؟").content == "الرياض، السعودية"
    assert s.match_exact("send my email to him") is None
    assert s.match_exact("") is None
    assert normalize("Hello, World!") == "hello world"


def test_snippet_multiline_content_kept_verbatim(db):
    s = SnippetStore(db)
    body = "Best regards,\nAlex Example\nExample Co"
    s.add("sign off", body)
    assert s.match_exact("sign off").content == body


def test_snippet_embedded_only_when_enabled(db):
    s = SnippetStore(db)
    s.add("my email", "me@example.com")
    s.add("my github", "github.com/me", anywhere=True)
    text, used = s.expand_embedded("my email and my github, thanks")
    assert text == "my email and github.com/me thanks"
    assert used == ["my github"]


# -- processor ----------------------------------------------------------------------------
def make_processor(db, **kw):
    pipeline = CleanupPipeline(None, use_llm=False)
    return TextProcessor(pipeline, DictionaryStore(db), SnippetStore(db), **kw)


def test_processor_snippet_bypasses_cleanup(db):
    p = make_processor(db)
    p.snippets.add("my email", "me@example.com")
    r = p.process("um my email.")
    assert r.kind == "text"  # "um" breaks the exact match; filler removed, then no embedded expand
    r = p.process("My email.")
    assert (r.kind, r.text) == ("snippet", "me@example.com")


def test_processor_applies_dictionary_and_cleanup(db):
    p = make_processor(db)
    p.dictionary.add("Kubernetes", spoken="cuber nettys")
    p.dictionary.add("NASA")
    r = p.process("um i joined the cuber nettys bootcamp at nasa")
    assert r.text == "I joined the Kubernetes bootcamp at NASA."
    assert p.dictionary.get("Kubernetes").uses >= 1


def test_processor_empty(db):
    r = make_processor(db).process("um uh")
    assert r.kind == "empty" and r.text == ""


def test_processor_whisper_prompt(db):
    p = make_processor(db)
    assert p.whisper_prompt() is None
    p.dictionary.add("Pygame", starred=True)
    p.dictionary.add("NASA")
    assert p.whisper_prompt() == "Pygame, NASA"


def test_db_is_thread_safe(db):
    import threading

    d = DictionaryStore(db)
    errors = []

    def work(i):
        try:
            for j in range(20):
                d.add(f"w{i}-{j}")
        except sqlite3.Error as e:  # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors and len(d.list()) == 80
