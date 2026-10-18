"""Typed user settings, persisted as one JSON blob in the settings table."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

from flow.cleanup.llm import DEFAULT_MODEL
from flow.hotkeys.bindings import DEFAULT_BINDINGS, find_conflicts, parse_chord
from flow.store.settings_repo import SettingsRepo

LANGUAGES = {"auto": "Auto-detect", "en": "English", "ar": "Arabic"}
STT_MODELS = ["auto", "tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]
SOUND_STYLES = {
    "soft": "Soft bloop (default)",
    "pop": "Short pop",
    "windows": "Windows speech chime (softened)",
}
BAR_SCREENS = {"all": "All screens", "active": "Only the screen I am working on"}
# name -> (label, minutes before the speech model unloads (0 = never), AI model keep-alive minutes)
MEMORY_MODES = {
    "fast": ("Fastest (keep models loaded)", 0, 30),
    "balanced": ("Balanced (unload after 10 idle minutes)", 10, 5),
    "low": ("Lowest memory (unload after 2 idle minutes)", 2, 2),
}
STYLE_NAMES = {
    "default": "Default",
    "formal": "Formal",
    "casual": "Casual",
    "excited": "Excited",
    "very_casual": "Very casual",
}
BINDING_LABELS = {
    "push_to_talk": "Push-to-talk (hold)",
    "hands_free": "Hands-free (toggle)",
    "command": "Command Mode (hold)",
    "fix_last": "Fix last word",
}
SETTINGS_KEY = "settings"


@dataclass
class Settings:
    language: str = "auto"
    stt_model: str = "auto"
    cleanup_enabled: bool = True
    llm_enabled: bool = True
    llm_model: str = DEFAULT_MODEL
    style: str = "default"
    custom_instructions: str = ""
    spoken_commands: bool = True
    smart_terms: bool = True  # fix product names such as Claude, ChatGPT, GitHub by context
    auto_dictionary: bool = True  # learn recurring names and terms into the dictionary
    press_enter: bool = False  # experimental
    whisper_mode: bool = False
    auto_gain: bool = True  # boost quiet recordings (speaking far from the microphone)
    mic_device: str | None = None  # device name; None = system default
    bindings: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BINDINGS))
    double_tap: bool = True
    history_enabled: bool = True
    history_days: int = 0  # 0 = keep forever
    launch_at_startup: bool = False
    show_idle_bar: bool = True
    app_styles: dict[str, str] = field(default_factory=dict)  # process name -> style
    sound_effects: bool = True
    sound_volume: int = 40  # percent
    sound_style: str = "soft"  # key of SOUND_STYLES
    bar_screens: str = "all"  # "all" monitors or only the "active" one (where the pointer is)
    memory_mode: str = "balanced"  # see MEMORY_MODES
    first_run_done: bool = False

    def language_code(self) -> str | None:
        return None if self.language == "auto" else self.language


def _coerce(default, value):  # noqa: ANN001, ANN202
    """Keep ``value`` only if it has the same type as the default; otherwise use the default."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, int):
        return value if isinstance(value, int) and not isinstance(value, bool) else default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    if isinstance(default, dict):
        return value if isinstance(value, dict) else default
    return value


def settings_from_dict(data: dict) -> Settings:
    base = Settings()
    kwargs = {}
    for f in fields(Settings):
        default = getattr(base, f.name)
        if f.name in data:
            kwargs[f.name] = _coerce(default, data[f.name]) if default is not None else data[f.name]
    s = Settings(**kwargs)
    if s.language not in LANGUAGES:
        s.language = "auto"
    if s.style not in STYLE_NAMES:
        s.style = "default"
    s.history_days = max(0, s.history_days)
    s.sound_volume = max(0, min(100, s.sound_volume))
    if s.sound_style not in SOUND_STYLES:
        s.sound_style = "soft"
    if s.bar_screens not in BAR_SCREENS:
        s.bar_screens = "all"
    if s.memory_mode not in MEMORY_MODES:
        s.memory_mode = "balanced"
    # keep only known, parseable bindings; fill gaps with defaults
    clean = dict(DEFAULT_BINDINGS)
    for name, chord in s.bindings.items():
        if name in DEFAULT_BINDINGS and isinstance(chord, str):
            try:
                parse_chord(chord)
                clean[name] = chord
            except ValueError:
                pass
    s.bindings = clean
    s.app_styles = {
        str(k).lower(): v
        for k, v in s.app_styles.items()
        if isinstance(v, str) and v in STYLE_NAMES
    }
    if s.mic_device is not None and not isinstance(s.mic_device, str):
        s.mic_device = None
    return s


def load_settings(repo: SettingsRepo) -> Settings:
    data = repo.get(SETTINGS_KEY, {})
    return settings_from_dict(data if isinstance(data, dict) else {})


def save_settings(repo: SettingsRepo, settings: Settings) -> None:
    repo.set(SETTINGS_KEY, asdict(settings))


def binding_conflicts(bindings: dict[str, str]) -> list[tuple[str, str]]:
    return find_conflicts(bindings)
