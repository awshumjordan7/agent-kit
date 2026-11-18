"""Windows client for the workflow-maxxing app's named pipe.

The app sets WORKFLOW_MAXXING_SOCKET to the pipe name and WORKFLOW_MAXXING_APP_PID to its
main process id, which serves the pipe. The client writes only to a pipe whose server
process is that pid, so the token never reaches a pipe another process created first.

Only for short-lived processes: after a time-out the worker thread stays blocked on the pipe
until the process exits, which closes the handle.
"""

from __future__ import annotations

import ctypes
import msvcrt
import os
import threading
import time
from ctypes import wintypes

SOCKET_VAR = "WORKFLOW_MAXXING_SOCKET"
APP_PID_VAR = "WORKFLOW_MAXXING_APP_PID"


class AppSocketRefused(OSError):
    """The client did not send: the variables are missing or the pipe is not the app's."""


def _app_pid() -> int:
    raw = os.environ.get(APP_PID_VAR, "")
    if not (raw.isascii() and raw.isdigit()) or int(raw) <= 0:
        raise AppSocketRefused(f"{APP_PID_VAR} is not a positive integer: {raw!r}")
    return int(raw)


def _server_pid_function():
    try:
        function = ctypes.WinDLL("kernel32", use_last_error=True).GetNamedPipeServerProcessId
    except AttributeError as error:
        raise AppSocketRefused("GetNamedPipeServerProcessId is not available") from error
    function.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    function.restype = wintypes.BOOL
    return function


def _exchange(name: str, app_pid: int, line: bytes, server_pid_of) -> bytes:
    with open(name, "r+b", buffering=0) as pipe:
        server_pid = wintypes.ULONG()
        if not server_pid_of(msvcrt.get_osfhandle(pipe.fileno()), ctypes.byref(server_pid)):
            raise AppSocketRefused(
                f"cannot read the pipe's server process id: {ctypes.WinError(ctypes.get_last_error())}"
            )
        if server_pid.value != app_pid:
            raise AppSocketRefused(
                f"the pipe is served by process {server_pid.value}, not the app ({app_pid})"
            )
        view = memoryview(line)
        while view:
            view = view[pipe.write(view):]
        reply = b""
        while b"\n" not in reply:
            chunk = pipe.read(4096)
            if not chunk:
                break
            reply += chunk
        return reply


def exchange_windows(line: bytes, deadline: float) -> bytes:
    """Send one request line to the app's pipe and return its reply; deadline is time.monotonic()."""
    name = os.environ.get(SOCKET_VAR, "")
    if not name:
        raise AppSocketRefused(f"{SOCKET_VAR} is not set")
    app_pid = _app_pid()
    server_pid_of = _server_pid_function()
    if deadline <= time.monotonic():
        raise TimeoutError("workflow-maxxing pipe deadline passed")
    outcome: dict[str, object] = {}

    def work() -> None:
        try:
            outcome["reply"] = _exchange(name, app_pid, line, server_pid_of)
        except OSError as error:
            outcome["error"] = error

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive():
        raise TimeoutError("no reply from the workflow-maxxing app before the deadline")
    error = outcome.get("error")
    if isinstance(error, OSError):
        raise error
    reply = outcome.get("reply")
    if not isinstance(reply, bytes):
        raise OSError("the workflow-maxxing pipe exchange failed")
    return reply
