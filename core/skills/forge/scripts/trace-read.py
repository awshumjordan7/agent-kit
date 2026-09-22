#!/usr/bin/env python3
"""Print a redacted view of a Playwright trace.zip or a HAR file.

Actions: time offset from the first action, action type, selector, and the
names (never the values) of any other parameters. Network: method, status,
host, path without query, has-auth, set-cookie. Nothing else from the file is
printed: typed and fill values, action titles, cookies, header values, query
strings, and bodies are never shown.

has-auth is yes when the request carries an Authorization, Proxy-Authorization,
or Cookie header, or request cookies. set-cookie is yes when the response sets
a cookie.

Exit codes: 0 = printed, 2 = unreadable or unknown file.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

AUTH_HEADERS = {"authorization", "proxy-authorization", "cookie"}
URL_SCHEMES = {"http", "https", "ws", "wss"}
NOT_NAME = re.compile(r"[^\w.:-]")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
METHOD = re.compile(r"[A-Z]{1,10}")


class TraceError(Exception):
    """The file is not a readable trace or HAR."""


def as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def name_text(value: object, limit: int = 60) -> str:
    """Reduce an identifier (action type, parameter name) to safe characters."""
    return NOT_NAME.sub("", str(value))[:limit]


def action_row(event: dict) -> tuple[float, str, str, str] | None:
    """Return (start, type, selector, param names) for an action event, else None."""
    kind = event.get("type")
    if kind == "action":
        event = as_dict(event.get("metadata")) or event
    elif kind != "before":
        return None
    start = event.get("startTime")
    if not isinstance(start, (int, float)):
        return None
    action_type = event.get("apiName")
    if not action_type:
        cls, method = event.get("class"), event.get("method")
        action_type = f"{cls}.{method}" if cls and method else method
    params = as_dict(event.get("params"))
    selector = params.get("selector")
    selector = CONTROL.sub(" ", selector)[:160] if isinstance(selector, str) else "-"
    others = sorted(name_text(key, 30) for key in params if key != "selector")
    return float(start), name_text(action_type) or "?", selector, ",".join(k for k in others if k)


def header_names(headers: object) -> set[str]:
    return {str(h.get("name", "")).lower() for h in as_list(headers) if isinstance(h, dict)}


def host_and_path(url: object) -> tuple[str, str]:
    if not isinstance(url, str):
        return "-", "-"
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "-", "<unparsed url>"
    scheme = parts.scheme.lower()
    if scheme not in URL_SCHEMES:
        return "-", f"<{name_text(scheme, 12) or 'unknown'} url>"
    host = (parts.hostname or "-") + (f":{port}" if port else "")
    return CONTROL.sub("", host)[:80], CONTROL.sub(" ", parts.path or "/")[:160]


def network_row(entry: dict) -> tuple[str, str, str, str, str, str]:
    request, response = as_dict(entry.get("request")), as_dict(entry.get("response"))
    method = request.get("method")
    method = method if isinstance(method, str) and METHOD.fullmatch(method) else "?"
    status = response.get("status")
    status = str(status) if isinstance(status, int) else "?"
    host, path = host_and_path(request.get("url"))
    has_auth = bool(header_names(request.get("headers")) & AUTH_HEADERS or as_list(request.get("cookies")))
    set_cookie = "set-cookie" in header_names(response.get("headers")) or bool(as_list(response.get("cookies")))
    return method, status, host, path, "yes" if has_auth else "no", "yes" if set_cookie else "no"


def print_actions(label: str, rows: list[tuple[float, str, str, str]]) -> None:
    print(f"== actions: {label} ({len(rows)})")
    if not rows:
        return
    base = min(row[0] for row in rows)
    print(f"{'offset':>10}  {'type':<28} selector  [other params]")
    for start, action_type, selector, others in sorted(rows, key=lambda row: row[0]):
        suffix = f"  [{others}]" if others else ""
        print(f"{(start - base) / 1000:>9.3f}s  {action_type:<28} {selector}{suffix}")


def print_network(label: str, rows: list[tuple[str, str, str, str, str, str]]) -> None:
    print(f"== network: {label} ({len(rows)})")
    if not rows:
        return
    print(f"{'method':<7} {'status':<6} {'auth':<4} {'set-ck':<6} host path")
    for method, status, host, path, has_auth, set_cookie in rows:
        print(f"{method:<7} {status:<6} {has_auth:<4} {set_cookie:<6} {host} {path}")


def read_events(lines: Iterable[str]) -> tuple[list, list, int]:
    actions, network, skipped = [], [], 0
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        event = as_dict(event)
        if event.get("type") == "resource-snapshot":
            network.append(network_row(as_dict(event.get("snapshot"))))
        elif row := action_row(event):
            actions.append(row)
    return actions, network, skipped


def print_trace(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.endswith((".trace", ".network"))]
        if not names:
            raise TraceError("zip has no .trace or .network entries")
        skipped = 0
        for name in sorted(names):
            with archive.open(name) as handle:
                text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
                actions, network, bad = read_events(text)
            skipped += bad
            label = name_text(name, 80)
            if name.endswith(".trace") or actions:
                print_actions(label, actions)
            if name.endswith(".network") or network:
                print_network(label, network)
        if skipped:
            print(f"== skipped {skipped} unparsable lines")


def print_har(path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise TraceError("not a zip and not JSON") from exc
    entries = as_dict(as_dict(data).get("log")).get("entries")
    if not isinstance(entries, list):
        raise TraceError("JSON has no log.entries list, so it is not a HAR")
    print_network(name_text(path.name, 80), [network_row(as_dict(e)) for e in entries])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a redacted view of a Playwright trace.zip or HAR file.")
    parser.add_argument("file", type=Path, help="trace.zip or .har file")
    args = parser.parse_args(argv)
    try:
        if zipfile.is_zipfile(args.file):
            print_trace(args.file)
        else:
            print_har(args.file)
    except TraceError as exc:
        print(f"trace-read: {exc}", file=sys.stderr)
        return 2
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        print(f"trace-read: cannot read file ({type(exc).__name__})", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
