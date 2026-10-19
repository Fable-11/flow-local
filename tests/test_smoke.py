import pytest

from flow import __version__
from flow.__main__ import build_parser, main


def test_version_string():
    assert __version__.count(".") == 2


def test_parser_knows_run_and_defaults_to_it():
    parser = build_parser()
    assert parser.parse_args([]).cmd is None
    assert parser.parse_args(["run"]).cmd == "run"
    assert parser.parse_args(["demo"]).cmd == "demo"


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_version_is_the_same_everywhere():
    """pyproject.toml, the package and the top CHANGELOG entry must agree."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    pyproject = re.search(r'^version = "(.+)"', (root / "pyproject.toml").read_text("utf-8"), re.M)
    changelog = re.search(r"^## (\d+\.\d+\.\d+)", (root / "CHANGELOG.md").read_text("utf-8"), re.M)
    assert pyproject and changelog
    assert pyproject.group(1) == __version__ == changelog.group(1)
