import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not shutil.which("powershell"), reason="needs Windows PowerShell"
)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup.ps1"


def test_setup_script_is_valid_powershell():
    cmd = (
        "$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{SCRIPT}', [ref]$null, [ref]$e); if ($e) {{ $e | ForEach-Object {{ $_.Message }}; exit 1 }}"
    )
    done = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


def test_check_mode_installs_nothing_and_reports_the_machine():
    venv = SCRIPT.parents[1] / ".venv" / "Scripts" / "python.exe"
    if not venv.exists():
        pytest.skip("no .venv to inspect")
    done = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
         "-Check", "-SkipOllama"],
        capture_output=True, text=True, timeout=180,
    )  # fmt: skip
    out = done.stdout
    assert done.returncode == 0, out + done.stderr
    assert "Flow Local" in out and "Speech model" in out and "Done." in out


def test_script_documents_all_its_switches():
    text = SCRIPT.read_text(encoding="utf-8")
    for switch in ("-NoCuda", "-SkipOllama", "-DownloadModel", "-Check"):
        assert switch in text
