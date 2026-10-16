import sys

import pytest

from flow.config import Settings, load_settings, save_settings, settings_from_dict
from flow.store.db import Database
from flow.store.settings_repo import SettingsRepo


def test_defaults_roundtrip():
    repo = SettingsRepo(Database())
    assert load_settings(repo) == Settings()
    s = Settings(language="ar", whisper_mode=True, history_days=30)
    s.bindings["push_to_talk"] = "ctrl+alt+space"
    save_settings(repo, s)
    assert load_settings(repo) == s


def test_garbage_values_fall_back_to_defaults():
    s = settings_from_dict(
        {
            "language": "klingon",
            "style": 5,
            "history_days": -3,
            "cleanup_enabled": "yes",
            "bindings": {"push_to_talk": "", "hands_free": "ctrl+shift+h", "bogus": "x"},
            "mic_device": 7,
            "unknown_key": 1,
        }
    )
    d = Settings()
    assert s.language == "auto" and s.style == "default"
    assert s.history_days == 0 and s.cleanup_enabled is d.cleanup_enabled
    assert s.bindings["push_to_talk"] == d.bindings["push_to_talk"]
    assert s.bindings["hands_free"] == "ctrl+shift+h"
    assert "bogus" not in s.bindings
    assert s.mic_device is None


def test_language_code():
    assert Settings().language_code() is None
    assert Settings(language="ar").language_code() == "ar"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_autostart_registry_roundtrip():
    import winreg

    from flow.ui import autostart

    key_path = r"Software\FlowLocalTest\Run"
    try:
        assert not autostart.is_enabled(key_path)
        autostart.set_enabled(True, key_path, command='"C:\\x\\pythonw.exe" -m flow')
        assert autostart.is_enabled(key_path)
        autostart.set_enabled(False, key_path)
        assert not autostart.is_enabled(key_path)
        autostart.set_enabled(False, key_path)  # disabling twice is harmless
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\FlowLocalTest")
        except FileNotFoundError:
            pass


def test_launch_command_mentions_module():
    from flow.ui import autostart

    cmd = autostart.launch_command()
    assert "-m flow" in cmd and "--background" in cmd


def test_app_styles_sanitised():
    raw = {"WhatsApp.exe": "casual", "x.exe": "nonsense", "y.exe": 3}
    s = settings_from_dict({"app_styles": raw})
    assert s.app_styles == {"whatsapp.exe": "casual"}
