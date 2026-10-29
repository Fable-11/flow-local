"""The Home page tells the truth about the AI cleanup, and starts Ollama only when asked."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from flow import aistatus
from flow.aistatus import ai_status, ollama_exe, start_ollama

MODEL = "qwen2.5:7b-instruct"


def status(**kw):
    args = dict(
        enabled=True, reachable=True, model=MODEL, wanted=MODEL, loaded=True, installed=True
    )
    args.update(kw)
    return ai_status(**args)


def test_every_state_has_a_plain_message():
    assert status().code == "ready"
    assert status(loaded=False).code == "cold"
    assert status(enabled=False).code == "off_setting"
    assert status(model=None).code == "no_model"
    assert f"ollama pull {MODEL}" in status(model=None).text
    off = status(reachable=False)
    assert off.code == "no_server" and off.can_start  # installed: offer to start it
    assert "built-in cleanup" in off.text


def test_without_ollama_installed_there_is_no_start_button_but_a_pointer():
    s = status(reachable=False, installed=False)
    assert s.code == "no_server" and not s.can_start and "ollama.com" in s.text


def test_a_switched_off_setting_wins_over_everything_else():
    assert status(enabled=False, reachable=False).code == "off_setting"


# -- finding and starting Ollama ---------------------------------------------------------------
def test_ollama_is_only_looked_for_in_the_usual_places(monkeypatch, tmp_path):
    monkeypatch.setattr(aistatus.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert ollama_exe() is None
    exe = tmp_path / "Programs" / "Ollama" / "ollama.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert ollama_exe() == exe
    monkeypatch.setattr(aistatus.shutil, "which", lambda name: str(tmp_path / "on_path.exe"))
    assert ollama_exe() == tmp_path / "on_path.exe"  # PATH first


def test_starting_ollama_runs_only_serve_hidden_and_detached(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(aistatus.subprocess, "Popen", lambda cmd, **kw: calls.append((cmd, kw)))
    assert start_ollama(tmp_path / "ollama.exe") is True
    cmd, kw = calls[0]
    assert cmd == [str(tmp_path / "ollama.exe"), "serve"]
    assert kw["creationflags"] & aistatus.subprocess.CREATE_NO_WINDOW


def test_starting_fails_quietly_when_there_is_no_ollama_or_it_will_not_start(monkeypatch, tmp_path):
    monkeypatch.setattr(aistatus, "ollama_exe", lambda: None)
    assert start_ollama() is False

    def boom(*a, **k):
        raise OSError("blocked")

    monkeypatch.setattr(aistatus.subprocess, "Popen", boom)
    assert start_ollama(tmp_path / "ollama.exe") is False


# -- the worker's check and the Home page -------------------------------------------------------
def worker(monkeypatch, **llm):
    pytest.importorskip("PySide6")
    import queue

    import flow.app as app_mod
    from flow.config import Settings

    emitted = []
    bridge = SimpleNamespace(
        state=SimpleNamespace(emit=lambda *a: None),
        aiStatus=SimpleNamespace(emit=lambda *a: emitted.append(a)),
    )
    w = app_mod.Worker(bridge, queue.Queue(), lambda: Settings(), None, None, None)
    w.llm = SimpleNamespace(
        available=lambda: llm.get("up", True),
        resolve_model=lambda: llm.get("model", MODEL),
        is_loaded=lambda: llm.get("loaded", True),
    )
    monkeypatch.setattr(app_mod, "ollama_exe", lambda: "ollama.exe")
    return w, emitted


def test_the_worker_reports_a_change_once_not_every_time(monkeypatch):
    w, emitted = worker(monkeypatch)
    w.check_ai()
    w.check_ai()
    assert [e[0] for e in emitted] == ["ready"]


def test_the_worker_notices_when_ollama_goes_away(monkeypatch):
    w, emitted = worker(monkeypatch, up=False)
    w.check_ai()
    assert emitted[0][0] == "no_server" and emitted[0][2] is True  # button offered


def test_home_page_shows_the_line_and_only_offers_the_button_when_useful(qtbot):
    from flow.config import Settings  # noqa: F401
    from flow.store.db import Database
    from flow.store.dictionary import DictionaryStore
    from flow.store.settings_repo import SettingsRepo
    from flow.store.snippets import SnippetStore
    from flow.ui.hub.context import HubContext
    from flow.ui.hub.home_page import HomePage

    db = Database()
    ctx = HubContext(DictionaryStore(db), SnippetStore(db), SettingsRepo(db))
    page = HomePage(ctx)
    qtbot.addWidget(page)
    page.show()
    ctx.aiStatusChanged.emit("no_server", "AI cleanup: off because Ollama is not running.", True)
    assert page.ai_label.isVisible() and page.ai_button.isVisible()
    asked = []
    ctx.startOllamaRequested.connect(lambda: asked.append(1))
    page.ai_button.click()
    assert asked == [1] and not page.ai_button.isEnabled()  # one press, no double start
    ctx.aiStatusChanged.emit("ready", "AI cleanup: ready.", False)
    assert not page.ai_button.isVisible() and page.ai_label.text() == "AI cleanup: ready."
    # a window opened later shows the current state straight away
    late = HomePage(ctx)
    qtbot.addWidget(late)
    assert late.ai_label.text() == "AI cleanup: ready."


def test_a_failing_status_check_can_never_stop_the_worker(monkeypatch):
    w, emitted = worker(monkeypatch)
    w.recording = False
    w.paused = False
    w._reload_thread = None
    w.last_activity = 0.0
    w.engine = SimpleNamespace(loaded=False)

    def boom():
        raise RuntimeError("anything at all")

    monkeypatch.setattr(w, "check_ai", boom)
    w._idle_tick()  # must not raise
