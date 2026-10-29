"""Quiet the other programs while you dictate (music, videos, calls), then put them back.

Windows keeps one volume control per program in its mixer. While a dictation is being recorded,
every other program is muted (or lowered), so what you say is not mixed with what they play. They
keep playing and come back the moment you stop talking.

Safety comes first, because this touches other programs:
* only programs that are not already muted are touched, and only the ones this code changed are
  restored, and only if nobody changed them in the meantime (the user may have used the mixer);
* a small record is written to disk before anything is muted, so if Flow Local ever crashes
  the next start puts everything back;
* Flow Local's own sounds (the start cue) are never muted.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

LOWERED_TO = 0.12  # "lower" mode keeps other programs at this share of their volume


class Session(Protocol):
    """One program's volume control (the real ones come from Windows, tests use fakes)."""

    pid: int
    name: str

    def muted(self) -> bool: ...
    def volume(self) -> float: ...
    def set_muted(self, value: bool) -> None: ...
    def set_volume(self, value: float) -> None: ...


@dataclass
class Touched:
    pid: int
    name: str
    mode: str  # "mute" or "lower"
    was_volume: float


class SystemSessions:
    """The real Windows mixer, through pycaw. Everything is guarded: no audio device, no pycaw or
    a COM error just means nothing is quietened."""

    class _Real:
        def __init__(self, raw) -> None:  # noqa: ANN001
            self._raw = raw
            self.pid = int(raw.ProcessId)
            try:
                self.name = raw.Process.name() if raw.Process is not None else ""
            except Exception:  # noqa: BLE001 - the program may have just exited
                self.name = ""
            self._vol = raw.SimpleAudioVolume

        def muted(self) -> bool:
            return bool(self._vol.GetMute())

        def volume(self) -> float:
            return float(self._vol.GetMasterVolume())

        def set_muted(self, value: bool) -> None:
            self._vol.SetMute(1 if value else 0, None)

        def set_volume(self, value: float) -> None:
            self._vol.SetMasterVolume(max(0.0, min(1.0, value)), None)

    def sessions(self) -> list[Session]:
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities

            comtypes.CoInitialize()  # this thread may not have used COM yet
            return [self._Real(s) for s in AudioUtilities.GetAllSessions() if s.ProcessId]
        except Exception:  # noqa: BLE001
            log.debug("could not read the Windows mixer", exc_info=True)
            return []


class AudioDucker:
    def __init__(
        self,
        mode: str = "mute",
        journal: Path | None = None,
        backend: SystemSessions | None = None,
        own_pids: set[int] | None = None,
    ) -> None:
        self.mode = mode if mode in ("mute", "lower") else "off"
        self.journal = journal
        self.backend = backend or SystemSessions()
        self.own_pids = own_pids if own_pids is not None else {os.getpid(), os.getppid()}
        self._touched: list[Touched] = []
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return bool(self._touched)

    # -- quieten -------------------------------------------------------------------------
    def start(self) -> None:
        """Quieten every other program. Safe to call twice; does nothing in mode "off"."""
        if self.mode == "off":
            return
        with self._lock:
            if self._touched:
                return
            touched: list[Touched] = []
            live: dict[int, Session] = {}
            for s in self.backend.sessions():
                if s.pid in self.own_pids:
                    continue
                try:
                    if s.muted():
                        continue  # already quiet: not ours to touch or restore
                    was = s.volume()
                    if self.mode == "lower" and was <= LOWERED_TO:
                        continue
                    touched.append(Touched(s.pid, s.name, self.mode, was))
                    live[s.pid] = s
                except Exception:  # noqa: BLE001 - a program that vanished mid-scan
                    continue
            if not touched:
                return
            self._write_journal(touched)  # before changing anything: a crash can be undone
            done: list[Touched] = []
            for t in touched:
                s = live.get(t.pid)
                if s is None:
                    continue
                try:
                    if t.mode == "mute":
                        s.set_muted(True)
                    else:
                        s.set_volume(t.was_volume * LOWERED_TO)
                    done.append(t)
                except Exception:  # noqa: BLE001
                    log.debug("could not quieten %s", t.name, exc_info=True)
            self._touched = done
            if not done:
                self._clear_journal()

    # -- restore -------------------------------------------------------------------------
    def stop(self) -> None:
        """Put back everything that was quietened. Safe to call any time, any number of times."""
        with self._lock:
            touched, self._touched = self._touched, []
            if not touched:
                return
            self._restore(touched, self.backend)
            self._clear_journal()

    @staticmethod
    def _restore(touched: list[Touched], backend) -> None:  # noqa: ANN001
        by_pid = {s.pid: s for s in backend.sessions()}
        for t in touched:
            s = by_pid.get(t.pid)
            if s is None or s.name != t.name:
                continue  # gone, or the number now belongs to another program: leave it alone
            try:
                if t.mode == "mute":
                    if s.muted():  # still as we left it; if the user unmuted it, leave it
                        s.set_muted(False)
                else:
                    # restore only while it is still near the level we set (not moved by the user)
                    if abs(s.volume() - t.was_volume * LOWERED_TO) < 0.03:
                        s.set_volume(t.was_volume)
            except Exception:  # noqa: BLE001
                log.debug("could not restore %s", t.name, exc_info=True)

    # -- crash recovery --------------------------------------------------------------------
    def _write_journal(self, touched: list[Touched]) -> None:
        if self.journal is None:
            return
        try:
            self.journal.parent.mkdir(parents=True, exist_ok=True)
            self.journal.write_text(json.dumps([asdict(t) for t in touched]), encoding="utf-8")
        except OSError:
            log.debug("could not write the ducking record", exc_info=True)

    def _clear_journal(self) -> None:
        if self.journal is not None:
            try:
                self.journal.unlink(missing_ok=True)
            except OSError:
                pass

    def recover(self) -> int:
        """After a crash: put back whatever a previous run left quietened. Returns how many."""
        if self.journal is None or not self.journal.exists():
            return 0
        try:
            entries = [Touched(**e) for e in json.loads(self.journal.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            self._clear_journal()
            return 0
        self._restore(entries, self.backend)
        self._clear_journal()
        return len(entries)


class DuckRunner:
    """Runs start and stop one after the other, on its own thread, so the recording is never
    delayed and the two can never overtake each other.

    A start is held back for a moment. A recording that is taken over right away (a tap, or the
    shortcut turning into hands-free mode, which stops and starts again within milliseconds) then
    never makes the other programs flicker: the stop cancels the waiting start.
    """

    def __init__(self, ducker: AudioDucker, delay: float = 0.15) -> None:
        self.ducker = ducker
        self.delay = delay
        self._q: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._loop, name="duck", daemon=True).start()

    def start(self) -> None:
        self._q.put("start")

    def stop(self) -> None:
        self._q.put("stop")

    def _loop(self) -> None:
        pending: str | None = None
        while True:
            op = pending or self._q.get()
            pending = None
            try:
                if op == "start":
                    try:
                        nxt = self._q.get(timeout=self.delay)
                    except queue.Empty:
                        self.ducker.start()
                    else:
                        if nxt != "stop":  # another start: still one recording
                            pending = nxt
                        # a stop cancels the start that was still waiting: nothing was muted
                else:
                    self.ducker.stop()
            except Exception:  # noqa: BLE001 - this thread must never die
                log.exception("audio ducking step failed")
