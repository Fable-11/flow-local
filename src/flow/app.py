"""The running app: Qt UI on the main thread, dictation pipeline on a worker thread."""

from __future__ import annotations

import ctypes
import logging
import queue
import signal
import sys
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from flow import memory, sounds
from flow.audio import enhance
from flow.audio.capture import Recorder
from flow.cleanup.llm import OllamaClient
from flow.cleanup.pipeline import CleanupPipeline
from flow.cleanup.rules import RuleOptions
from flow.command import CommandError, run_command
from flow.config import MEMORY_MODES, Settings
from flow.fixlast import suggest_fix
from flow.hardware import detect as detect_hardware
from flow.hardware import recommend
from flow.hotkeys.bindings import (
    ABORT,
    CANCEL,
    COMMAND_START,
    COMMAND_STOP,
    FIX_LAST,
    HANDSFREE_TOGGLE,
    PTT_START,
    PTT_STOP,
    HotkeyMachine,
)
from flow.hotkeys.winhook import HotkeyListener
from flow.insert import clipboard, winapi
from flow.insert.context import get_active_app
from flow.insert.paste import method_for, paste_text
from flow.insert.selection import SelectionError, capture_selection
from flow.insert.spacing import SpacingTracker
from flow.ipc import notify_running_instance, start_ipc_server
from flow.logging_setup import setup_logging
from flow.processing import TextProcessor
from flow.store.db import Database, default_db_path
from flow.store.dictionary import DictionaryStore
from flow.store.history import HistoryStore
from flow.store.settings_repo import SettingsRepo
from flow.store.snippets import SnippetStore
from flow.stt.engine import ModelNotDownloaded, SttEngine, choose_model
from flow.stt.models import is_model_cached
from flow.ui.flowbar import FlowBarGroup
from flow.ui.hub.context import HubContext
from flow.ui.hub.window import HubWindow
from flow.ui.theme import apply_theme, follow_system_theme
from flow.ui.tray import Tray

log = logging.getLogger(__name__)

TAIL_S = 0.3  # keep recording briefly after release so the last word is not clipped
WHISPER_GAIN = 3.0
BAR_CLICK, QUIT, SETTINGS, PAUSE, RESUME, DOWNLOAD, PURGE = (
    "bar_click",
    "quit",
    "settings",
    "pause",
    "resume",
    "download_model",
    "purge_history",
)
CAPTURE_PREFIX = "capture:"
STATUS_TEXT = {
    "idle": "Ready",
    "recording": "Listening...",
    "handsfree": "Listening (hands-free)...",
    "processing": "Working...",
    "done": "Inserted",
}


class Bridge(QObject):
    """Signals the worker thread uses to talk to the UI (delivered on the Qt thread)."""

    state = Signal(str, str)
    level = Signal(float)
    captured = Signal(str, str)
    historyChanged = Signal()
    fixSuggested = Signal(str, str)


class Worker:
    def __init__(
        self,
        bridge: Bridge,
        events: queue.Queue[str],
        settings_getter,  # noqa: ANN001 - Callable[[], Settings]
        dictionary: DictionaryStore,
        snippets: SnippetStore,
        history: HistoryStore,
    ) -> None:
        self.bridge = bridge
        self.events = events
        self.get_settings = settings_getter
        self.dictionary = dictionary
        self.snippets = snippets
        self.history = history
        self.last_dictation = ""  # final text of the last insertion, for "Fix last word"
        self.recording = False
        self.handsfree = False
        self.command_mode = False
        self.last_command: tuple[int, str, str] | None = None  # (hwnd, original, result)
        self.paused = False
        self.notice = ""  # persistent status shown on Home (e.g. model missing)
        self.listener: HotkeyListener | None = None
        self.recorder: Recorder | None = None
        self.last_activity = time.monotonic()  # drives idle unloading
        self.unloaded_for_idle = False
        self._reload_thread: threading.Thread | None = None
        self._trimmed = False

    # -- lifecycle ----------------------------------------------------------------------
    def run(self) -> None:
        for attempt in range(1, 4):
            try:
                self._run()
                return
            except Exception:  # noqa: BLE001
                log.exception("worker crashed (attempt %d of 3)", attempt)
                self._cleanup()
                self.bridge.state.emit("error", "Something broke, restarting")
                time.sleep(2)
        self.notice = "Flow Local stopped after repeated errors. Check the log and restart it."
        self.bridge.state.emit("error", "Flow Local stopped, see log")

    def _cleanup(self) -> None:
        if self.listener:
            self.listener.stop()
            self.listener = None
        if self.recorder:
            self.recorder.close()
        self.recording = False

    def _run(self) -> None:
        emit = self.bridge.state.emit
        s = self.get_settings()
        emit("loading", "Loading model")
        if clipboard.recover_journal():
            log.info("recovered clipboard from an interrupted paste")
        self.engine = SttEngine(choose_model(s.stt_model))
        self._load_model(allow_download=False)
        self.llm = OllamaClient(model=s.llm_model)
        self.pipeline = CleanupPipeline(self.llm)
        self.processor = TextProcessor(self.pipeline, self.dictionary, self.snippets)
        self.dictionary.prune_stale()
        self.recorder = Recorder(device=s.mic_device, keep_open=True, on_level=self.bridge.level.emit)
        self._open_mic()
        self.machine = HotkeyMachine(s.bindings, double_tap=s.double_tap)
        self.listener = HotkeyListener(self.machine, self.events.put)
        try:
            self.listener.start()
        except OSError:
            log.exception("could not install the keyboard hook")
            self.notice = "Keyboard shortcuts are unavailable (could not install the hook)."
            emit("error", "Shortcuts unavailable")
        self.spacing = SpacingTracker()
        self._apply(s)
        self._purge()
        threading.Thread(target=self.llm.warm_up, daemon=True).start()
        if self.engine.loaded:
            emit("idle", "")
        log.info("ready")
        memory.trim_working_set()
        try:
            while True:
                try:
                    action = self.events.get(timeout=30)
                except queue.Empty:
                    self._idle_tick()
                    continue
                if action == QUIT:
                    break
                try:
                    self._dispatch(action)
                except Exception:  # noqa: BLE001
                    log.exception("handler failed for %r", action)
                    emit("error", "Something went wrong")
        finally:
            self.listener.stop()
            self.recorder.close()

    def _load_model(self, allow_download: bool) -> bool:
        """Load the speech model. Only downloads it when the user asked (allow_download)."""
        emit = self.bridge.state.emit
        emit("loading", "Downloading model" if allow_download else "Loading model")
        try:
            self.engine.load(allow_download)
        except ModelNotDownloaded as e:
            log.warning("speech model %s is not downloaded; waiting for the user to download it", e.model_name)
            self.notice = (
                f"The speech model '{e.model_name}' is not downloaded yet. Open Settings > Models "
                "and press Download (one-time, uses the internet). Nothing else needs the internet."
            )
            emit("error", "Speech model not downloaded")
            return False
        except Exception:  # noqa: BLE001
            log.exception("could not load the speech model")
            self.notice = "Could not load the speech model. Check the log, or try a smaller model."
            emit("error", "Could not load speech model")
            return False
        self.notice = ""
        emit("idle", "")
        return True

    # -- memory: unload when idle, reload when the hotkey goes down ------------------------
    def _touch(self) -> None:
        self.last_activity = time.monotonic()
        self._trimmed = False

    def _idle_tick(self) -> None:
        if self.recording or self.paused or self._reload_thread is not None:
            return
        idle = time.monotonic() - self.last_activity
        unload_min = MEMORY_MODES[self.get_settings().memory_mode][1]
        if unload_min and self.engine.loaded and idle > unload_min * 60 and not self.notice:
            log.info("idle for %.0f min: unloading the speech model to free memory", idle / 60)
            self.engine.unload()
            self.unloaded_for_idle = True
            memory.trim_working_set()
            self._trimmed = True
        elif idle > 60 and not self._trimmed:
            memory.trim_working_set()
            self._trimmed = True

    def _reload_in_background(self) -> None:
        """Start loading the speech model now, while the user is still speaking."""
        if self.engine.loaded or not self.unloaded_for_idle or self._reload_thread is not None:
            return

        def work() -> None:
            try:
                self.engine.load(allow_download=False)
                self.unloaded_for_idle = False
            except Exception:  # noqa: BLE001
                log.exception("could not reload the speech model")
            finally:
                self._reload_thread = None

        self._reload_thread = threading.Thread(target=work, name="flow-reload", daemon=True)
        self._reload_thread.start()

    def _wait_for_model(self) -> bool:
        thread = self._reload_thread
        if thread is not None:
            thread.join(90)
        return self.engine.loaded

    def _prewarm_llm(self) -> None:
        """Wake the AI model while the user speaks, if Ollama has unloaded it meanwhile."""
        if self.pipeline.use_llm and time.monotonic() - self.llm.last_used > 45:
            threading.Thread(target=self.llm.warm_up, daemon=True).start()

    def _open_mic(self) -> bool:
        try:
            self.recorder.open()
            return True
        except Exception:  # noqa: BLE001
            log.exception("microphone unavailable")
            self.bridge.state.emit("error", "No microphone found")
            return False

    # -- settings -----------------------------------------------------------------------
    def _apply(self, s: Settings) -> None:
        self.machine = HotkeyMachine(s.bindings, double_tap=s.double_tap)
        if self.listener:
            self.listener.machine = self.machine
        self.processor.style = s.style
        self.processor.custom_instructions = s.custom_instructions
        self.processor.cleanup_enabled = s.cleanup_enabled
        self.processor.smart_terms = s.smart_terms
        self.processor.auto_learn = s.auto_dictionary
        self.processor.app_styles = s.app_styles
        self.pipeline.use_llm = s.llm_enabled
        self.pipeline.rules = RuleOptions(spoken_commands=s.spoken_commands, press_enter=s.press_enter)
        self.llm.model = s.llm_model
        self.llm.keep_alive = f"{MEMORY_MODES[s.memory_mode][2]}m"
        self.llm._active_model = None  # re-resolve against installed models
        self.recorder.gain = WHISPER_GAIN if s.whisper_mode else 1.0
        if s.mic_device != self.recorder.device:
            self.recorder.close()
            self.recorder.device = s.mic_device
            self._open_mic()
        wanted = choose_model(s.stt_model)
        if wanted != self.engine.choice:
            if is_model_cached(wanted.name):
                self.engine.choice = wanted
                self._load_model(allow_download=False)
            elif self.engine.loaded:  # keep the working model until the new one is downloaded
                self.notice = (
                    f"Speech model '{wanted.name}' is not downloaded. "
                    "Open Settings > Models to download it (one-time, uses the internet)."
                )
                self.bridge.state.emit("idle", "")

    # -- events -------------------------------------------------------------------------
    def _dispatch(self, action: str) -> None:
        if action == SETTINGS:
            self._apply(self.get_settings())
        elif action == PAUSE:
            self.paused = True
            if self.recording:
                self._handle(CANCEL)
            self.machine.end_handsfree()
        elif action == RESUME:
            self.paused = False
        elif action == PURGE:
            self._purge()
        elif action == FIX_LAST:
            self._fix_last()
        elif action == DOWNLOAD:
            self.engine.choice = choose_model(self.get_settings().stt_model)
            self._load_model(allow_download=True)
        elif action.startswith(CAPTURE_PREFIX):
            name = action[len(CAPTURE_PREFIX) :]
            self.listener.begin_capture(lambda chord, n=name: self.bridge.captured.emit(n, chord))
        else:
            self._handle(action)

    def rerun_cleanup(self, raw: str) -> str:
        """Re-run cleanup on a saved transcript (called from the Hub, on the UI thread)."""
        try:
            return self.processor.process(raw).text
        except Exception:  # noqa: BLE001
            log.exception("re-run cleanup failed")
            return ""

    # -- history / learning ---------------------------------------------------------------
    def _record(self, raw: str, final: str, app: str, kind: str, lang: str, audio_s: float) -> None:
        if not self.get_settings().history_enabled or not final:
            return
        self.history.add(raw, final, app, kind, lang, audio_s)
        self.bridge.historyChanged.emit()

    def _purge(self) -> None:
        days = self.get_settings().history_days
        if days > 0 and self.history.purge_older_than(days):
            self.bridge.historyChanged.emit()

    def _fix_last(self) -> None:
        """Learn from a correction: the user fixed a word, selected it, and pressed the hotkey."""
        emit = self.bridge.state.emit
        if not self.last_dictation:
            emit("error", "Nothing to fix yet")
            return
        app = get_active_app()
        try:
            selected = capture_selection(app.process)
        except SelectionError:
            emit("error", "Select the corrected word first")
            return
        suggestion = suggest_fix(self.last_dictation, selected)
        if suggestion is None:
            emit("error", "Nothing new to learn from that")
            return
        self.bridge.fixSuggested.emit(suggestion.heard, suggestion.correct)

    def _handle(self, action: str) -> None:
        emit = self.bridge.state.emit
        if self.paused and action not in (CANCEL, ABORT):
            return
        starting = action in (PTT_START, COMMAND_START) or (
            action == HANDSFREE_TOGGLE and not self.recording
        )
        stopping = (
            action in (PTT_STOP, COMMAND_STOP, HANDSFREE_TOGGLE, BAR_CLICK) and self.recording
        )
        if starting and not self.recording:
            self._reload_in_background()
            if not self.engine.loaded and not self.unloaded_for_idle:
                emit("error", "Download the speech model in Settings")
                self.machine.end_handsfree()
                return
            self._touch()
            self._prewarm_llm()
            try:
                mute = sounds.cue_duration("start") + 0.05 if sounds.enabled else 0.0
                self.recorder.start(mute_s=mute)
            except Exception:  # noqa: BLE001
                log.exception("could not start recording")
                emit("error", "No microphone found")
                self.machine.end_handsfree()
                return
            sounds.play("start")
            self.recording = True
            self.handsfree = action == HANDSFREE_TOGGLE
            self.command_mode = action == COMMAND_START
            emit("command" if self.command_mode else "handsfree" if self.handsfree else "recording", "")
        elif stopping:
            time.sleep(TAIL_S)
            audio = self.recorder.stop()
            sounds.play("stop")
            self.recording = False
            self.machine.end_handsfree()
            self._touch()
            emit("processing", "")
            if self.command_mode:
                self._finish_command(audio)
            else:
                self._finish(audio)
        elif action in (CANCEL, ABORT) and self.recording:
            self.recorder.stop()
            if action == CANCEL:  # Esc: audible. A silent abort is just a shortcut changing form.
                sounds.play("stop")
            self.recording = False
            # Do not reset the machine's hands-free flag here: an ABORT is often followed by
            # the hands-free toggle, and the machine already clears it itself on Esc.
            emit("idle", "")

    def _finish_command(self, audio) -> None:  # noqa: ANN001
        """Command Mode: apply the spoken instruction to the selected text and replace it.

        The replacement is one paste over the selection, so Ctrl+Z in the app undoes it.
        """
        emit = self.bridge.state.emit
        s = self.get_settings()
        try:
            app = get_active_app()
            try:
                selected = capture_selection(app.process)  # fail fast, before any speech work
            except SelectionError as e:
                emit("error", str(e))
                return
            prepared = enhance.prepare(audio, s.auto_gain)
            if prepared.silent:
                emit("error", enhance.quiet_hint(prepared.stats))
                return
            audio = prepared.audio
            if not self._wait_for_model():
                emit("error", "Speech model not available")
                return
            text, _lang, _ = self.engine.transcribe(
                audio, language=s.language_code(), initial_prompt=self.processor.whisper_prompt()
            )
            try:
                result = run_command(selected, text, self.llm)
            except CommandError as e:
                emit("error", str(e))
                return
            if get_active_app().hwnd != app.hwnd:  # never paste into a window the user left
                emit("error", "The window changed, nothing was replaced")
                return
            paste_text(result.text, method_for(app.process))
            self.last_command = (app.hwnd, selected, result.text)
            self._record(result.instruction, result.text, app.process, "command", _lang, len(audio) / 16000)
            log.info("command %r on %d chars -> %d chars", result.instruction, len(selected), len(result.text))
            emit("done", "")
        except Exception:  # noqa: BLE001
            log.exception("command failed")
            emit("error", "Something went wrong")

    def _finish(self, audio) -> None:  # noqa: ANN001
        emit = self.bridge.state.emit
        s = self.get_settings()
        try:
            prepared = enhance.prepare(audio, s.auto_gain)
            if prepared.silent:
                emit("error", enhance.quiet_hint(prepared.stats))
                return
            if prepared.gain_db > 0:
                log.info(
                    "quiet recording: boosted +%.0f dB (peak %.4f, snr %.0f dB, denoised=%s)",
                    prepared.gain_db, prepared.stats.peak, prepared.stats.snr_db, prepared.denoised,
                )
            raw_audio, audio = audio, prepared.audio
            if not self._wait_for_model():
                emit("error", "Speech model not available")
                return
            t0 = time.perf_counter()
            text, lang, _ = self.engine.transcribe(
                audio,
                language=s.language_code(),
                initial_prompt=self.processor.whisper_prompt(),
                quiet=s.whisper_mode,
            )
            if not text:
                emit("error", enhance.quiet_hint(enhance.analyze(raw_audio)))
                return
            app = get_active_app()
            result = self.processor.process(text, app.process, app.title)
            if not result.text and not result.press_enter:
                emit("idle", "")
                return
            out = self.spacing.prefix_for(app.hwnd, result.text) + result.text
            if out:
                paste_text(out, method_for(app.process))
                self.spacing.record(app.hwnd, out)
            if result.press_enter:
                winapi.chord([winapi.VK_RETURN])
            if result.text:
                self.last_dictation = result.text
                self._record(text, result.text, app.process, result.kind, lang, len(audio) / 16000)
            log.info(
                "[%s] raw=%r -> %r (%s, %.2fs, %s)",
                lang, text, result.text, result.kind, time.perf_counter() - t0, app.process,
            )
            emit("done", "")
            self._touch()
            memory.trim_working_set()
        except Exception:  # noqa: BLE001
            log.exception("dictation failed")
            emit("error", "Something went wrong")


# -- single instance ------------------------------------------------------------------------
_mutex_handle = None


def acquire_single_instance() -> bool:
    """True if this is the only running copy (two copies would both react to the hotkeys)."""
    global _mutex_handle
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    _mutex_handle = kernel32.CreateMutexW(None, False, "Local\\FlowLocalSingleInstance")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


class LazyHub:
    """Builds the Hub window on first use and frees it when closed (saves memory in the tray)."""

    def __init__(self, ctx: HubContext) -> None:
        self.ctx = ctx
        self._hub: HubWindow | None = None

    def show_page(self, name: str = "Home") -> None:
        if self._hub is None:
            self._hub = HubWindow(self.ctx, delete_on_close=True)
            self._hub.closed.connect(self._forget)
        self._hub.show_page(name)

    def _forget(self) -> None:
        self._hub = None
        memory.trim_working_set()


def offer_dictionary_word(ctx: HubContext, heard: str, correct: str) -> None:
    """Ask whether to add a correction to the dictionary (runs on the UI thread)."""
    spoken = None if heard.casefold() == correct.casefold() else heard
    text = f"Add “{correct}” to your dictionary?"
    if spoken:
        text += f"\n\nWhen it hears “{spoken}” it will write “{correct}”."
    box = QMessageBox(QMessageBox.Icon.Question, "Flow Local", text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    if box.exec() == QMessageBox.StandardButton.Yes:
        ctx.dictionary.add(correct, spoken)
        ctx.historyChanged.emit()  # refreshes pages that show dictionary-derived data


def run_app(background: bool = False) -> int:
    setup_logging()
    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)
    qt_app.setApplicationName("Flow Local")
    apply_theme(qt_app)  # modern look, light or dark like Windows
    follow_system_theme(qt_app)
    if not acquire_single_instance():
        if not notify_running_instance():  # normally: the running copy opens its window
            QMessageBox.information(
                None, "Flow Local", "Flow Local is already running. Look for its icon in the tray."
            )
        return 0

    db = Database(default_db_path())
    dictionary, snippets, repo = DictionaryStore(db), SnippetStore(db), SettingsRepo(db)
    ctx = HubContext(dictionary, snippets, repo)
    hub = LazyHub(ctx)
    bridge = Bridge()
    bar = FlowBarGroup(ctx.settings.bar_screens)
    bar.set_idle_visible(ctx.settings.show_idle_bar)
    sounds.configure(ctx.settings.sound_effects, ctx.settings.sound_volume, ctx.settings.sound_style)
    events: queue.Queue[str] = queue.Queue()

    bridge.state.connect(bar.set_state)
    bridge.level.connect(bar.push_level)
    bridge.captured.connect(ctx.chordCaptured)
    bridge.historyChanged.connect(ctx.historyChanged)
    bridge.fixSuggested.connect(lambda heard, correct: offer_dictionary_word(ctx, heard, correct))
    holder: dict[str, Worker] = {}

    def show_status(st: str, text: str) -> None:
        notice = holder["worker"].notice if "worker" in holder else ""
        normal = text if st in ("error", "loading") else STATUS_TEXT.get(st, "")
        ctx.statusChanged.emit(notice if notice and st not in ("recording", "handsfree", "command") else normal)

    bridge.state.connect(show_status)
    bridge.state.connect(
        lambda st, text: sounds.play("error") if st == "error" and text != "No speech heard" else None
    )
    bar.clicked.connect(lambda: events.put(BAR_CLICK))

    def on_settings(s: Settings) -> None:
        bar.set_idle_visible(s.show_idle_bar)
        bar.set_mode(s.bar_screens)
        sounds.configure(s.sound_effects, s.sound_volume, s.sound_style)
        events.put(SETTINGS)

    ctx.settingsChanged.connect(on_settings)
    ctx.captureRequested.connect(lambda name: events.put(CAPTURE_PREFIX + name))
    ctx.modelDownloadRequested.connect(lambda: events.put(DOWNLOAD))

    tray = Tray(qt_app.quit, hub.show_page)
    ipc_server = start_ipc_server(lambda: hub.show_page("Home"))  # noqa: F841 - keep referenced
    tray.pause_toggled.connect(lambda paused: events.put(PAUSE if paused else RESUME))

    bar.set_state("loading", "Loading model")
    if not background or not ctx.settings.first_run_done:
        hub.show_page("Home")
    if not ctx.settings.first_run_done:
        rec = recommend(detect_hardware())  # laptops without a GPU get the lighter models
        ctx.update(first_run_done=True, **rec.as_settings())
        for note in rec.notes:
            log.info(note)

    worker = Worker(bridge, events, lambda: ctx.settings, dictionary, snippets, ctx.history)
    holder["worker"] = worker
    ctx.rerun_cleanup = lambda raw: worker.rerun_cleanup(raw)
    thread = threading.Thread(target=worker.run, name="flow-worker", daemon=True)
    thread.start()

    purge_timer = QTimer()  # apply the history auto-delete setting every few hours
    purge_timer.start(6 * 3600 * 1000)
    purge_timer.timeout.connect(lambda: events.put(PURGE))
    ctx.settingsChanged.connect(lambda _s: events.put(PURGE))

    signal.signal(signal.SIGINT, lambda *_: qt_app.quit())
    pump = QTimer()  # lets Python run signal handlers (Ctrl+C) while Qt owns the loop
    pump.start(250)
    pump.timeout.connect(lambda: None)

    code = qt_app.exec()
    events.put(QUIT)
    thread.join(3)
    return code
