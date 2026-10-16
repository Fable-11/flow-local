"""Settings: shortcuts, microphone, language, display and sound, models, memory, cleanup,
privacy, startup. Each section is one panel of rows: a label (and description) on the left, the
control on the right."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from flow.config import (
    BAR_SCREENS,
    BINDING_LABELS,
    LANGUAGES,
    MEMORY_MODES,
    SOUND_STYLES,
    STT_MODELS,
    binding_conflicts,
)
from flow.hotkeys.bindings import DEFAULT_BINDINGS, format_chord, parse_chord
from flow.ui.hub.context import HubContext
from flow.ui.hub.widgets import (
    Panel,
    Toggle,
    button,
    caption,
    hbox,
    page_header,
    section_title,
    set_role,
)

log = logging.getLogger(__name__)
DEFAULT_MIC = "System default"


class SettingsPage(QWidget):
    def __init__(self, ctx: HubContext) -> None:
        super().__init__()
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)
        outer.addWidget(page_header("Settings", "Changes apply immediately."))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll = scroll
        body = QWidget()
        body.setObjectName("Page")
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 0, 12, 0)
        self.body.setSpacing(10)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self._build_shortcuts()
        self._build_microphone()
        self._build_language()
        self._build_display_and_sound()
        self._build_models()
        self._build_memory()
        self._build_cleanup()
        self._build_privacy()
        self._build_startup()
        self._build_experimental()
        self.body.addStretch(1)
        ctx.chordCaptured.connect(self._chord_captured)

    # -- layout helpers -------------------------------------------------------------------------
    def _section(self, title: str) -> Panel:
        self.body.addSpacing(10)
        self.body.addWidget(section_title(title))
        panel = Panel()
        self.body.addWidget(panel)
        return panel

    def _check(self, panel: Panel, title: str, key: str, description: str = "") -> Toggle:
        toggle = Toggle()
        toggle.setChecked(getattr(self.ctx.settings, key))
        toggle.toggled.connect(lambda v, k=key: self.ctx.update(**{k: v}))
        toggle.setAccessibleName(title)
        panel.add_row(title, description, toggle)
        return toggle

    @staticmethod
    def _combo_width(combo: QComboBox, width: int = 240) -> QComboBox:
        combo.setMinimumWidth(width)
        return combo

    def _warn(self, text: str) -> None:
        self.shortcut_warning.setText(text)
        self.shortcut_warning.setVisible(bool(text))

    # -- shortcuts ------------------------------------------------------------------------------
    def _build_shortcuts(self) -> None:
        panel = self._section("Shortcuts")
        self.chord_edits: dict[str, QLineEdit] = {}
        self.record_buttons: dict[str, QWidget] = {}
        for name, label in BINDING_LABELS.items():
            edit = QLineEdit(self.ctx.settings.bindings[name])
            edit.setPlaceholderText("e.g. ctrl+win+space")
            edit.setFixedWidth(200)
            edit.setAccessibleName(label)
            edit.editingFinished.connect(lambda n=name: self.set_binding(n, self.chord_edits[n].text()))
            rec = button("Record")
            rec.setToolTip("Press the new shortcut, then let go of all keys")
            rec.clicked.connect(lambda _=False, n=name: self._start_record(n))
            self.chord_edits[name], self.record_buttons[name] = edit, rec
            panel.add_row(label, control=hbox(edit, rec))
        self.double_tap = Toggle()
        self.double_tap.setChecked(self.ctx.settings.double_tap)
        self.double_tap.toggled.connect(lambda v: self.ctx.update(double_tap=v))
        panel.add_row(
            "Double-tap starts hands-free",
            "Tap the push-to-talk shortcut twice quickly. Esc always cancels. Mouse buttons also "
            "work: mouse_x1, mouse_x2, mouse_middle.",
            self.double_tap,
        )
        self.shortcut_warning = set_role(QLabel(""), "error")
        self.shortcut_warning.setWordWrap(True)
        self.shortcut_warning.setVisible(False)
        self.body.addWidget(self.shortcut_warning)  # outside the panel: no empty row when hidden
        self.reset_btn = button("Reset")
        self.reset_btn.clicked.connect(self.reset_bindings)
        panel.add_row("Defaults", "Restore the original shortcuts.", self.reset_btn)

    def set_binding(self, name: str, text: str) -> bool:
        """Validate and save one shortcut. Returns False (and warns) if it is rejected."""
        try:
            chord = format_chord(parse_chord(text))
        except ValueError:
            self._warn("A shortcut needs at least one key.")
            self.chord_edits[name].setText(self.ctx.settings.bindings[name])
            return False
        trial = {**self.ctx.settings.bindings, name: chord}
        clashes = [pair for pair in binding_conflicts(trial) if name in pair]
        if clashes:
            other = next(x for x in clashes[0] if x != name)
            what = "Esc (cancel)" if other == "cancel" else BINDING_LABELS.get(other, other)
            self._warn(f"{chord} is already used by {what}. Pick another.")
            self.chord_edits[name].setText(self.ctx.settings.bindings[name])
            return False
        self._warn("")
        self.chord_edits[name].setText(chord)
        if chord != self.ctx.settings.bindings[name]:
            self.ctx.update(bindings=trial)
        return True

    def reset_bindings(self) -> None:
        for name, chord in DEFAULT_BINDINGS.items():
            self.chord_edits[name].setText(chord)
        self._warn("")
        self.ctx.update(bindings=dict(DEFAULT_BINDINGS))

    def _start_record(self, name: str) -> None:
        self.record_buttons[name].setText("Press keys...")
        self.ctx.captureRequested.emit(name)

    def _chord_captured(self, name: str, chord: str) -> None:
        self.record_buttons[name].setText("Record")
        self.set_binding(name, chord)

    # -- microphone / language ------------------------------------------------------------------
    def _build_microphone(self) -> None:
        panel = self._section("Microphone")
        self.mic = self._combo_width(QComboBox())
        self.mic.addItem(DEFAULT_MIC)
        for name in self._mic_names():
            self.mic.addItem(name)
        current = self.ctx.settings.mic_device
        if current and self.mic.findText(current) < 0:
            self.mic.addItem(current)
        self.mic.setCurrentText(current or DEFAULT_MIC)
        self.mic.currentTextChanged.connect(
            lambda t: self.ctx.update(mic_device=None if t == DEFAULT_MIC else t)
        )
        panel.add_row("Input device", control=self.mic)
        self.auto_gain = self._check(
            panel,
            "Automatic volume boost",
            "auto_gain",
            "Lifts quiet speech, for example when you sit far from the microphone.",
        )
        self.whisper_mode = self._check(
            panel, "Whisper mode", "whisper_mode", "Boosts quiet speech so you can dictate softly."
        )

    @staticmethod
    def _mic_names() -> list[str]:
        try:
            from flow.audio.capture import list_input_devices

            seen: list[str] = []
            for _idx, name in list_input_devices():
                if name not in seen and "Sound Mapper" not in name and "Primary" not in name:
                    seen.append(name)
            return seen
        except Exception:  # noqa: BLE001 - no audio stack / no devices
            log.warning("could not list microphones", exc_info=True)
            return []

    def _build_language(self) -> None:
        panel = self._section("Language")
        self.language = self._combo_width(QComboBox())
        for code, label in LANGUAGES.items():
            self.language.addItem(label, code)
        self.language.setCurrentIndex(max(0, self.language.findData(self.ctx.settings.language)))
        self.language.currentIndexChanged.connect(
            lambda _i: self.ctx.update(language=self.language.currentData())
        )
        panel.add_row(
            "Spoken language",
            "Auto-detect handles Arabic, English and mixed sentences for each dictation.",
            self.language,
        )

    # -- display and sound ------------------------------------------------------------------------
    def _build_display_and_sound(self) -> None:
        panel = self._section("Display and sound")
        self.bar_screens = self._combo_width(QComboBox())
        for key, label in BAR_SCREENS.items():
            self.bar_screens.addItem(label, key)
        self.bar_screens.setCurrentIndex(
            max(0, self.bar_screens.findData(self.ctx.settings.bar_screens))
        )
        self.bar_screens.currentIndexChanged.connect(
            lambda _i: self.ctx.update(bar_screens=self.bar_screens.currentData())
        )
        panel.add_row("Show the Flow Bar on", "The small bar that shows when you are recording.", self.bar_screens)
        self.idle_bar = self._check(
            panel, "Show the idle bar", "show_idle_bar", "A thin line at the bottom of the screen when idle."
        )
        self.sound = self._check(
            panel, "Play sounds", "sound_effects", "A soft cue when dictation starts and stops."
        )
        self.sound_style = self._combo_width(QComboBox())
        for key, label in SOUND_STYLES.items():
            self.sound_style.addItem(label, key)
        self.sound_style.setCurrentIndex(
            max(0, self.sound_style.findData(self.ctx.settings.sound_style))
        )
        self.sound_style.currentIndexChanged.connect(self._sound_style_changed)
        panel.add_row("Sound style", "Changing it plays a preview.", self.sound_style)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(self.ctx.settings.sound_volume)
        self.volume.setFixedWidth(150)
        self.volume.setAccessibleName("Sound volume")
        self.volume.valueChanged.connect(lambda v: self.ctx.update(sound_volume=v))
        self.test_sound_btn = button("Test")
        self.test_sound_btn.clicked.connect(self.play_test_sound)
        panel.add_row("Volume", control=hbox(self.volume, self.test_sound_btn))

    def _sound_style_changed(self, _index: int) -> None:
        self.ctx.update(sound_style=self.sound_style.currentData())
        self.play_test_sound()  # hear the new style straight away

    def play_test_sound(self) -> bool:
        from flow import sounds

        s = self.ctx.settings
        sounds.configure(s.sound_effects, s.sound_volume, s.sound_style)
        return sounds.play("start", force=True)

    # -- models ---------------------------------------------------------------------------------
    def _build_models(self) -> None:
        panel = self._section("Models")
        self.stt_model = self._combo_width(QComboBox(), 180)
        self.stt_model.addItems(STT_MODELS)
        self.stt_model.setCurrentText(self.ctx.settings.stt_model)
        self.stt_model.currentTextChanged.connect(self._stt_changed)
        self.stt_status = caption("")
        stt_row = panel.add_row("Speech model", control=self.stt_model)
        stt_row.title.setBuddy(self.stt_model)
        panel.add(self.stt_status)
        self.download_btn = button("Download now (one-time, uses the internet)", "primary")
        self.download_btn.clicked.connect(self.ctx.modelDownloadRequested.emit)
        panel.add(self.download_btn)
        self.llm_model = self._combo_width(QComboBox(), 220)
        self.llm_model.setEditable(True)
        self.llm_model.setCurrentText(self.ctx.settings.llm_model)
        self.llm_model.currentTextChanged.connect(lambda t: t and self.ctx.update(llm_model=t))
        refresh = button("Refresh", "ghost")
        refresh.clicked.connect(self.refresh_models)
        panel.add_row(
            "Cleanup model (Ollama)",
            "Used for punctuation, corrections and Command Mode.",
            hbox(self.llm_model, refresh),
        )
        self.llm_status = caption("")
        panel.add(self.llm_status)
        self.refresh_models()

    def _stt_changed(self, name: str) -> None:
        self.ctx.update(stt_model=name)
        self._refresh_stt_status()

    def _refresh_stt_status(self) -> None:
        from flow.stt.engine import choose_model
        from flow.stt.models import is_model_cached

        name = self.ctx.settings.stt_model
        if name == "auto":
            name = choose_model().name
        cached = is_model_cached(name)
        self.stt_status.setText(
            f"{name}: " + ("downloaded and ready." if cached else "not downloaded yet.")
        )
        self.download_btn.setVisible(not cached)

    def refresh_models(self) -> None:
        self._refresh_stt_status()
        from flow.cleanup.llm import OllamaClient

        client = OllamaClient()
        if not client.available():
            self.llm_status.setText(
                "Ollama is not running. Cleanup falls back to built-in rules until it starts."
            )
            return
        installed = client.installed_models()
        current = self.llm_model.currentText()
        self.llm_model.blockSignals(True)
        self.llm_model.clear()
        self.llm_model.addItems(installed)
        self.llm_model.setCurrentText(current)
        self.llm_model.blockSignals(False)
        ok = current in installed
        self.llm_status.setText(
            f"Ollama is running. {current} is "
            + ("installed." if ok else "not installed. Run: ollama pull " + current)
        )

    # -- memory ---------------------------------------------------------------------------------
    def _build_memory(self) -> None:
        panel = self._section("Memory")
        self.memory_mode = self._combo_width(QComboBox(), 300)
        for key, (label, _stt, _llm) in MEMORY_MODES.items():
            self.memory_mode.addItem(label, key)
        self.memory_mode.setCurrentIndex(
            max(0, self.memory_mode.findData(self.ctx.settings.memory_mode))
        )
        self.memory_mode.currentIndexChanged.connect(
            lambda _i: self.ctx.update(memory_mode=self.memory_mode.currentData())
        )
        panel.add_row(
            "Memory use",
            "Models unload after a quiet period and reload the moment you press the shortcut, "
            "while you are still speaking.",
            self.memory_mode,
        )

    # -- cleanup --------------------------------------------------------------------------------
    def _build_cleanup(self) -> None:
        panel = self._section("Cleanup")
        self.cleanup = self._check(
            panel, "Clean up dictation", "cleanup_enabled", "Punctuation, fillers and self-corrections."
        )
        self.llm = self._check(
            panel, "Use the local AI model", "llm_enabled", "Smarter cleanup. Falls back to rules if it is off."
        )
        self.commands = self._check(
            panel, "Spoken commands", "spoken_commands", 'Say "new line" or "new paragraph" to format.'
        )

    # -- privacy --------------------------------------------------------------------------------
    def _build_privacy(self) -> None:
        panel = self._section("Privacy")
        panel.add(
            caption(
                "Everything runs on this computer. Audio is never saved. The only network use is "
                "the optional one-time model download."
            )
        )
        self.history = self._check(
            panel, "Save dictation history", "history_enabled", "Stored only on this computer."
        )
        self.days = QSpinBox()
        self.days.setRange(0, 3650)
        self.days.setSpecialValueText("Never")
        self.days.setSuffix(" days")
        self.days.setValue(self.ctx.settings.history_days)
        self.days.setFixedWidth(120)
        self.days.setAccessibleName("Auto-delete history after")
        self.days.valueChanged.connect(lambda v: self.ctx.update(history_days=v))
        panel.add_row("Auto-delete history after", control=self.days)
        self.clear_btn = button("Delete all history", "danger")
        self.clear_btn.clicked.connect(lambda: self.clear_history(confirm=True))
        panel.add_row("Delete history now", "This cannot be undone.", self.clear_btn)

    def clear_history(self, confirm: bool = True) -> None:
        if confirm:
            from PySide6.QtWidgets import QMessageBox

            reply = QMessageBox.question(
                self, "Delete history", "Delete all saved dictations? This cannot be undone."
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.ctx.history.clear()
        self.ctx.historyChanged.emit()

    # -- startup --------------------------------------------------------------------------------
    def _build_startup(self) -> None:
        panel = self._section("Startup")
        self.startup = Toggle()
        self.startup.setChecked(self.ctx.settings.launch_at_startup)
        self.startup.toggled.connect(self._startup_toggled)
        panel.add_row("Launch when I sign in", "Starts quietly in the tray.", self.startup)
        self.shortcut_btn = button("Create shortcuts")
        self.shortcut_btn.clicked.connect(self.create_desktop_shortcuts)
        panel.add_row(
            "Desktop shortcuts", "One to open Flow Local, one to stop it, and a Start menu entry.", self.shortcut_btn
        )

    def _startup_toggled(self, on: bool) -> None:
        if sys.platform == "win32":
            from flow.ui import autostart

            try:
                autostart.set_enabled(on)
            except OSError:
                log.exception("could not change autostart")
                self.startup.blockSignals(True)
                self.startup.setChecked(not on)
                self.startup.blockSignals(False)
                return
        self.ctx.update(launch_at_startup=on)

    def create_desktop_shortcuts(self) -> list:
        from PySide6.QtWidgets import QMessageBox

        from flow.ui.shortcuts import install_shortcuts

        try:
            made = install_shortcuts()
        except OSError as e:
            QMessageBox.warning(self, "Desktop shortcuts", f"Could not create the shortcuts: {e}")
            return []
        names = "\n".join(p.name for p in made)
        QMessageBox.information(self, "Desktop shortcuts", f"Created:\n{names}")
        return made

    # -- experimental ---------------------------------------------------------------------------
    def _build_experimental(self) -> None:
        panel = self._section("Experimental")
        self.press_enter = self._check(
            panel, 'Say "press enter"', "press_enter", "Presses the Enter key at the end of a dictation."
        )
