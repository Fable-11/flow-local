import faulthandler
import logging
import sys
import threading

import pytest

from flow import logging_setup


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = logging.getLogger()
    saved = (list(root.handlers), root.level, sys.excepthook, threading.excepthook)
    monkeypatch.setattr(logging_setup, "_configured", False)
    yield tmp_path
    for h in list(root.handlers):
        if h not in saved[0]:
            h.close()
            root.removeHandler(h)
    root.setLevel(saved[1])
    sys.excepthook, threading.excepthook = saved[2], saved[3]
    faulthandler.disable()


def test_log_file_written_and_rotating(isolated):
    path = logging_setup.setup_logging(to_console=False)
    assert path == isolated / "FlowLocal" / "logs" / "flow.log"
    logging.getLogger("flow.test").warning("hello log %s", "ünï")
    for h in logging.getLogger().handlers:
        h.flush()
    text = path.read_text("utf-8")
    assert "hello log ünï" in text and "WARNING" in text
    assert any(
        isinstance(h, logging.handlers.RotatingFileHandler) for h in logging.getLogger().handlers
    )


def test_setup_is_idempotent(isolated):
    logging_setup.setup_logging(to_console=False)
    n = len(logging.getLogger().handlers)
    logging_setup.setup_logging(to_console=False)
    assert len(logging.getLogger().handlers) == n


def test_uncaught_exceptions_are_logged(isolated):
    path = logging_setup.setup_logging(to_console=False)

    def boom():
        raise ValueError("thread exploded")

    t = threading.Thread(target=boom, name="boom-thread")
    t.start()
    t.join()
    for h in logging.getLogger().handlers:
        h.flush()
    text = path.read_text("utf-8")
    assert "uncaught exception in thread boom-thread" in text and "thread exploded" in text
