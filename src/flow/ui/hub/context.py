"""Shared state for the Hub pages: stores, current settings, and change signals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from flow.config import Settings, load_settings, save_settings
from flow.store.dictionary import DictionaryStore
from flow.store.history import HistoryStore, NotesStore
from flow.store.settings_repo import SettingsRepo
from flow.store.snippets import SnippetStore


class HubContext(QObject):
    settingsChanged = Signal(object)  # the new Settings
    captureRequested = Signal(str)  # binding name: app should listen for the next chord
    chordCaptured = Signal(str, str)  # binding name, chord text (from the app)
    statusChanged = Signal(str)  # "Ready", "Loading model"...
    modelDownloadRequested = Signal()
    historyChanged = Signal()  # a dictation was added/removed
    fixSuggested = Signal(str, str)  # heard, correct: offer to add to the dictionary

    def __init__(
        self, dictionary: DictionaryStore, snippets: SnippetStore, repo: SettingsRepo
    ) -> None:
        super().__init__()
        self.dictionary = dictionary
        self.snippets = snippets
        self.repo = repo
        self.settings: Settings = load_settings(repo)
        self.history = HistoryStore(dictionary.db)
        self.notes = NotesStore(dictionary.db)
        # set by the app: re-run cleanup on a raw transcript (uses the AI model if available)
        self.rerun_cleanup: Callable[[str], str] | None = None
        self.status = ""  # last status text, so a window opened later shows the current state
        self.statusChanged.connect(self._remember_status)

    def _remember_status(self, text: str) -> None:
        if text:
            self.status = text

    def update(self, **changes) -> Settings:  # noqa: ANN003
        """Apply, persist and announce a settings change."""
        self.settings = replace(self.settings, **changes)
        save_settings(self.repo, self.settings)
        self.settingsChanged.emit(self.settings)
        return self.settings
