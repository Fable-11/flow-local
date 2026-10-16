import pytest

pytest.importorskip("PySide6")

from flow.store.db import Database  # noqa: E402
from flow.store.dictionary import DictionaryStore  # noqa: E402
from flow.store.settings_repo import SettingsRepo  # noqa: E402
from flow.store.snippets import SnippetStore  # noqa: E402
from flow.ui.hub.context import HubContext  # noqa: E402
from flow.ui.hub.dictionary_page import DictionaryPage  # noqa: E402
from flow.ui.hub.settings_page import SettingsPage  # noqa: E402
from flow.ui.hub.snippets_page import SnippetsPage  # noqa: E402
from flow.ui.hub.style_page import StylePage  # noqa: E402
from flow.ui.hub.window import PAGES, HubWindow  # noqa: E402


@pytest.fixture
def ctx():
    db = Database()
    return HubContext(DictionaryStore(db), SnippetStore(db), SettingsRepo(db))


def test_context_persists_and_announces(ctx, qtbot):
    with qtbot.waitSignal(ctx.settingsChanged) as sig:
        ctx.update(language="ar")
    assert sig.args[0].language == "ar"
    db_ctx = HubContext(ctx.dictionary, ctx.snippets, ctx.repo)  # reload from the same DB
    assert db_ctx.settings.language == "ar"


def test_hub_has_all_pages_and_hides_on_close(ctx, qtbot):
    hub = HubWindow(ctx)
    qtbot.addWidget(hub)
    assert [hub.nav.item(i).text() for i in range(hub.nav.count())] == PAGES
    hub.show_page("Dictionary")
    assert hub.stack.currentIndex() == PAGES.index("Dictionary")
    hub.close()
    assert not hub.isVisible()  # window hides, the app keeps running in the tray


def test_dictionary_page_add_search_star_delete(ctx, qtbot):
    page = DictionaryPage(ctx)
    qtbot.addWidget(page)
    page.add_entry("Kubernetes", "cuber nettys", True)
    page.add_entry("NASA")
    assert page.words() == ["Kubernetes", "NASA"]  # starred first
    page.search.setText("nas")
    assert page.words() == ["NASA"]
    page.search.setText("")
    page.toggle_star(1)  # star NASA
    assert ctx.dictionary.get("NASA").starred
    page.table.selectRow(0)
    page.delete_selected()
    assert page.words() == ["NASA"]  # Kubernetes (sorted first among the starred) was deleted


def test_snippets_page_add_and_delete(ctx, qtbot):
    page = SnippetsPage(ctx)
    qtbot.addWidget(page)
    page.add_snippet("my email", "me@example.com\nsecond line")
    assert page.triggers() == ["my email"]
    assert "↵" in page.table.item(0, 1).text()  # multi-line content previewed on one line
    page.table.selectRow(0)
    page.delete_selected()
    assert page.triggers() == []


def test_style_page_saves_choice_and_instructions(ctx, qtbot):
    page = StylePage(ctx)
    qtbot.addWidget(page)
    page.radios["formal"].setChecked(True)
    assert ctx.settings.style == "formal"
    page.custom.setPlainText("  Use British spelling.  ")
    page.save_instructions()
    assert ctx.settings.custom_instructions == "Use British spelling."


def test_settings_page_toggles_save(ctx, qtbot):
    page = SettingsPage(ctx)
    qtbot.addWidget(page)
    page.whisper_mode.setChecked(True)
    page.cleanup.setChecked(False)
    page.press_enter.setChecked(True)
    page.days.setValue(14)
    page.language.setCurrentIndex(page.language.findData("ar"))
    s = ctx.settings
    assert (s.whisper_mode, s.cleanup_enabled, s.press_enter) == (True, False, True)
    assert (s.history_days, s.language) == (14, "ar")


def test_settings_rejects_duplicate_shortcut(ctx, qtbot):
    page = SettingsPage(ctx)
    qtbot.addWidget(page)
    original = dict(ctx.settings.bindings)
    # hands-free tries to take push-to-talk's chord
    assert page.set_binding("hands_free", "Win+Ctrl") is False
    assert "already used" in page.shortcut_warning.text()
    assert ctx.settings.bindings == original
    assert page.chord_edits["hands_free"].text() == original["hands_free"]
    # Esc is reserved for cancel
    assert page.set_binding("fix_last", "esc") is False
    # a free chord is accepted and normalised
    assert page.set_binding("fix_last", "Control+Windows+G") is True
    assert ctx.settings.bindings["fix_last"] == "ctrl+win+g"
    assert page.shortcut_warning.text() == ""


def test_settings_reset_and_record_flow(ctx, qtbot):
    page = SettingsPage(ctx)
    qtbot.addWidget(page)
    with qtbot.waitSignal(ctx.captureRequested) as sig:
        page.record_buttons["command"].click()
    assert sig.args == ["command"]
    ctx.chordCaptured.emit("command", "ctrl+alt+k")
    assert ctx.settings.bindings["command"] == "ctrl+alt+k"
    page.reset_bindings()
    assert ctx.settings.bindings["command"] == "ctrl+win+alt"


def test_empty_shortcut_rejected(ctx, qtbot):
    page = SettingsPage(ctx)
    qtbot.addWidget(page)
    assert page.set_binding("fix_last", "  ") is False


def test_settings_page_needs_no_horizontal_scroll(ctx, qtbot):
    hub = HubWindow(ctx)
    qtbot.addWidget(hub)
    hub.show_page("Settings")
    qtbot.wait(100)
    page = hub.pages["Settings"]
    assert page.scroll.horizontalScrollBar().maximum() == 0


# -- phase 8 pages ----------------------------------------------------------------------------
from datetime import datetime  # noqa: E402

from flow.ui.hub.home_page import HomePage, format_time  # noqa: E402
from flow.ui.hub.insights_page import InsightsPage, format_duration  # noqa: E402
from flow.ui.hub.notes_page import NotesPage  # noqa: E402


def test_format_helpers():
    today = datetime(2026, 10, 15, 9, 5)
    assert format_time(today, today.date()) == "09:05"
    assert format_time(datetime(2026, 10, 14, 23, 59), today.date()) == "Oct 14, 23:59"
    assert [format_duration(x) for x in (45, 125, 3900)] == ["45s", "2m 05s", "1h 05m"]


def test_home_lists_history_and_actions(ctx, qtbot, monkeypatch):
    from PySide6.QtWidgets import QApplication

    page = HomePage(ctx)
    qtbot.addWidget(page)
    assert page.empty_note.isVisibleTo(page) and not page.copy_btn.isEnabled()
    first = ctx.history.add("um hello world", "Hello world.", "chrome.exe", audio_s=2)
    ctx.history.add("raw two", "مرحبا بك", "code.exe", "command")
    ctx.historyChanged.emit()
    assert page.table.rowCount() == 2
    assert page.table.item(0, 2).text().startswith("Command: ")  # newest first, kind labelled
    page.table.selectRow(1)
    assert page.selected_id() == first
    page.copy_selected()
    assert QApplication.clipboard().text() == "Hello world."
    ctx.rerun_cleanup = lambda raw: f"CLEANED: {raw}"
    assert page.rerun_selected() == "CLEANED: um hello world"
    assert ctx.history.get(first).final == "CLEANED: um hello world"
    page.search.setText("chrome")
    assert page.table.rowCount() == 1
    page.search.setText("")
    page.table.selectRow(0)
    page.delete_selected()
    assert page.table.rowCount() == 1


def test_home_rerun_falls_back_to_rules(ctx, qtbot):
    page = HomePage(ctx)
    qtbot.addWidget(page)
    item = ctx.history.add("um so we should meet tomorrow", "old")
    ctx.historyChanged.emit()
    page.table.selectRow(0)
    assert page.rerun_selected() == "So we should meet tomorrow."
    assert ctx.history.get(item).final == "So we should meet tomorrow."


def test_insights_page_numbers(ctx, qtbot):
    ctx.history.add("r", " ".join(["w"] * 120), audio_s=60)
    page = InsightsPage(ctx)
    qtbot.addWidget(page)
    assert page.cards["words"].value.text() == "120"
    assert page.cards["wpm"].value.text() == "120"
    assert page.cards["streak"].value.text() == "1"
    page.show()
    qtbot.wait(50)
    assert not page.chart.grab().isNull()


def test_notes_page_autosave_switch_delete(ctx, qtbot):
    page = NotesPage(ctx)
    qtbot.addWidget(page)
    assert not page.editor.isEnabled()  # nothing yet
    page.new_note()
    page.editor.setPlainText("Shopping list\nmilk")
    page.flush()
    assert ctx.notes.list()[0].title == "Shopping list"
    assert page.listing.item(0).text() == "Shopping list"
    page.new_note()
    page.editor.setPlainText("Second note")
    saved = lambda: any(n.body == "Second note" for n in ctx.notes.list())  # noqa: E731
    qtbot.waitUntil(saved, timeout=2000)  # autosave fires after a short delay
    page.listing.setCurrentRow(1)
    assert page.editor.toPlainText() in ("Shopping list\nmilk", "Second note")
    count = len(ctx.notes.list())
    page.delete_note()
    assert len(ctx.notes.list()) == count - 1


def test_style_page_app_rules(ctx, qtbot):
    page = StylePage(ctx)
    qtbot.addWidget(page)
    assert page.add_app_rule("Code", "casual")
    assert ctx.settings.app_styles == {"code.exe": "casual"}
    assert page.rules.rowCount() == 1
    assert not page.add_app_rule("   ", "casual") and not page.add_app_rule("x", "bogus")
    page.rules.selectRow(0)
    page.remove_selected_rule()
    assert ctx.settings.app_styles == {}


def test_settings_clear_history(ctx, qtbot):
    page = SettingsPage(ctx)
    qtbot.addWidget(page)
    ctx.history.add("r", "text")
    with qtbot.waitSignal(ctx.historyChanged):
        page.clear_history(confirm=False)
    assert ctx.history.count() == 0


def test_dictionary_suggestions(ctx, qtbot):
    for text in ("I met Kubernetes staff.", "Then Kubernetes called.", "Also Kubernetes again."):
        ctx.history.add("r", text)
    page = DictionaryPage(ctx)
    qtbot.addWidget(page)
    assert page.suggestions.count() == 1 and "Kubernetes" in page.suggestions.item(0).text()
    page.suggestions.setCurrentRow(0)
    page.add_selected_suggestion()
    assert ctx.dictionary.get("Kubernetes") is not None
    assert page.suggestions.count() == 0  # no longer suggested once known


def test_auto_gain_setting_defaults_on_and_saves(ctx, qtbot):
    page = SettingsPage(ctx)
    qtbot.addWidget(page)
    assert ctx.settings.auto_gain is True and page.auto_gain.isChecked()
    page.auto_gain.setChecked(False)
    assert ctx.settings.auto_gain is False
