"""Tiny local IPC so launching Flow Local again just opens the window of the running copy."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtNetwork import QLocalServer, QLocalSocket

IPC_NAME = "FlowLocalIPC"
SHOW = b"show"
ACK = b"ok"


def notify_running_instance(timeout_ms: int = 1500, name: str = IPC_NAME) -> bool:
    """Ask the already-running copy to show its window. False if none answers."""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(SHOW)
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    acknowledged = sock.waitForReadyRead(timeout_ms) and bytes(sock.readAll()) == ACK
    sock.disconnectFromServer()
    return acknowledged


def start_ipc_server(on_show: Callable[[], None], name: str = IPC_NAME) -> QLocalServer | None:
    """Listen for "show" requests from later launches. Keep the returned server referenced."""
    QLocalServer.removeServer(name)  # clear a stale pipe left by a crashed run
    server = QLocalServer()
    if not server.listen(name):
        return None

    def on_connection() -> None:
        while server.hasPendingConnections():
            sock = server.nextPendingConnection()

            def handle(s: QLocalSocket = sock) -> None:
                if bytes(s.readAll()).strip() == SHOW:
                    on_show()
                    s.write(ACK)  # the sender waits for this before it exits
                    s.flush()

            sock.readyRead.connect(handle)
            sock.disconnected.connect(sock.deleteLater)
            if sock.bytesAvailable():
                handle()

    server.newConnection.connect(on_connection)
    return server
