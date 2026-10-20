#!/usr/bin/env python3
"""Serve one folder on 127.0.0.1 so Playwright MCP can open local files.

Usage: serve_dir.py start <dir> | stop <port>

`start` prints the URL and returns. The server stops on `stop <port>` or after 30 minutes.
"""

from __future__ import annotations

import os
import secrets
import signal
import stat
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BufferedReader
from pathlib import Path
from urllib.parse import unquote, urlsplit

SANDBOX_STOP = (
    "serve_dir.py must run outside the Bash sandbox, and this call ran inside it. "
    "Run it again as one bare Bash call spelled exactly python3 ~/.claude/scripts/serve_dir.py "
    "<args>: no cd prefix, pipe, redirect, 2>&1, ';' or '&&'."
)
STATE_DIR = Path.home() / ".cache" / "agent-kit" / "serve-dir"
LIFETIME_SECONDS = 1800
# This server runs without the sandbox's read denies, so it refuses the same private names itself.
PRIVATE_DIRS = {".aws", ".config", ".gnupg", ".ssh"}


def private_root(root: Path) -> bool:
    # A private name can hide behind a symlink, and macOS file names ignore case.
    names = {part.lower() for part in (*root.absolute().parts, *root.resolve().parts)}
    return any(
        name in PRIVATE_DIRS or name.startswith(".env") or "credential" in name for name in names
    )


def _open_at(dir_fd: int, name: str) -> int:
    try:
        return os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    finally:
        os.close(dir_fd)


def open_file(root: Path, request_path: str) -> tuple[BufferedReader, str] | None:
    """Open the requested regular file under root without following a symlink; None when refused."""
    try:
        path = urlsplit(request_path).path
    except ValueError:
        return None
    if not path.startswith("/"):
        return None
    names = [name for name in unquote(path).split("/") if name]
    if any(name.startswith(".") or "credential" in name.lower() for name in names):
        return None
    if path.endswith("/"):
        names.append("index.html")
    try:
        fd = os.open(root, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
        for name in names:
            fd = _open_at(fd, name)
    except (OSError, ValueError):
        return None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        return None
    return os.fdopen(fd, "rb"), names[-1]


class Handler(SimpleHTTPRequestHandler):
    def send_head(self):
        opened = open_file(Path(self.directory), self.path)
        if opened is None:
            self.send_error(404)
            return None
        file, name = opened
        self.send_response(200)
        self.send_header("Content-type", self.guess_type(name))
        self.send_header("Content-Length", str(os.fstat(file.fileno()).st_size))
        self.end_headers()
        return file

    def log_message(self, format, *args):
        pass


def build_server(root: Path) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root.resolve())))


def serve(root: Path, token: str) -> int:
    server = build_server(root)
    port = server.server_address[1]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    pid_file = STATE_DIR / f"{port}.pid"
    pid_file.write_text(f"{os.getpid()} {token}")
    print(port, flush=True)
    sys.stdout.close()
    threading.Timer(LIFETIME_SECONDS, server.shutdown).start()
    try:
        server.serve_forever()
    finally:
        pid_file.unlink(missing_ok=True)
    return 0


def start(root: Path) -> int:
    if not root.is_dir():
        sys.stderr.write(f"serve_dir.py: not a folder: {root}\n")
        return 2
    child = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "serve", str(root), secrets.token_hex(8)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    port = child.stdout.readline().strip()
    if not port.isdigit():
        sys.stderr.write("serve_dir.py: the server did not start\n")
        return 1
    print(
        f"SERVE_URL http://127.0.0.1:{port}/"
        f" (stop: python3 ~/.claude/scripts/serve_dir.py stop {port};"
        " it stops by itself after 30 minutes)"
    )
    return 0


def stop(port: str) -> int:
    pid_file = STATE_DIR / f"{port}.pid"
    try:
        pid_text, token = pid_file.read_text().split()
        pid = int(pid_text)
    except (OSError, ValueError):
        sys.stderr.write(f"serve_dir.py: no server recorded for port {port}\n")
        return 1
    # Each server carries its own token in its command line, so a stale pid file stops nothing else.
    command = subprocess.run(
        ["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True
    ).stdout
    if "serve_dir.py serve " in command and command.rstrip().endswith(f" {token}"):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    pid_file.unlink(missing_ok=True)
    print(f"stopped port {port}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Claude Code sets SANDBOX_RUNTIME only in sandboxed Bash calls; any value counts.
    if "SANDBOX_RUNTIME" in os.environ:
        sys.stderr.write(SANDBOX_STOP + "\n")
        return 86
    args = sys.argv[1:] if argv is None else argv
    serving = len(args) in (2, 3) and args[0] in ("start", "serve")
    if serving and private_root(Path(args[1]).expanduser()):
        sys.stderr.write(f"serve_dir.py: refusing a private folder: {args[1]}\n")
        return 2
    if len(args) == 2 and args[0] == "start":
        return start(Path(args[1]).expanduser())
    if len(args) == 3 and args[0] == "serve":
        return serve(Path(args[1]), args[2])
    if len(args) == 2 and args[0] == "stop" and args[1].isdigit():
        return stop(args[1])
    sys.stderr.write("usage: serve_dir.py start <dir> | stop <port>\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
