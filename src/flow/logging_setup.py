"""Rotating file log plus crash hooks, so problems can be diagnosed after the fact."""

from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False
_fault_file = None


def log_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FlowLocal" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def log_path() -> Path:
    return log_dir() / "flow.log"


def setup_logging(level: int = logging.INFO, to_console: bool = True) -> Path:
    """Configure logging once. Safe to call repeatedly. Returns the log file path."""
    global _configured, _fault_file
    path = log_path()
    if _configured:
        return path
    _configured = True
    root = logging.getLogger()
    root.setLevel(level)
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
    ]
    if to_console and sys.stderr is not None:  # pythonw has no console
        handlers.append(logging.StreamHandler(sys.stderr))
    for h in handlers:
        h.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(h)
    for noisy in ("httpx", "httpcore", "huggingface_hub", "urllib3", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    def excepthook(exc_type, exc, tb):  # noqa: ANN001
        logging.getLogger("flow").critical("uncaught exception", exc_info=(exc_type, exc, tb))

    def thread_hook(args):  # noqa: ANN001
        logging.getLogger("flow").critical(
            "uncaught exception in thread %s", args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )  # fmt: skip

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    try:  # native crashes (e.g. in a driver) leave a traceback behind
        _fault_file = open(log_dir() / "crash.log", "a", encoding="utf-8")  # noqa: SIM115
        faulthandler.enable(_fault_file)
    except OSError:
        pass
    return path
