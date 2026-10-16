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
