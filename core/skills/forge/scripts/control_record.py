"""Check the control records the workflow-maxxing app writes before it sends a plain `go`.

Every subcommand prints one JSON line on stdout. Exit 0 means accepted or written, 1 refused,
2 a usage error. Callers act on the JSON line; a run with no JSON line is a refusal.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import stat
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

RECORD_NAME = re.compile(r"^[0-9]{8}T[0-9]{9}Z-(approve-plan|rulings)\.json$")
FORGE_RESULT_NAME = re.compile(r"^forge-result-([1-9][0-9]*)\.json$")
AUTO_RULINGS_NAME = re.compile(r"^rulings-auto-([1-9][0-9]*)\.json$")
UTC_TIME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$")
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

KB = 1024
MB = 1024 * KB
RECORD_CAP = 256 * KB
PLAN_CAP = 2 * MB
TRANSCRIPT_CAP = 256 * MB
FORGE_RESULT_CAP = 5 * MB
TASK_OUTPUT_CAP = 20 * MB

# The file clock can stamp a ctime a few milliseconds before the real write, so a file must be
# this much older than the `go` to count as written before it.
SEP_NS = 25_000_000
MAX_RECORD_AGE_MS = 60_000
CLOCK_REALTIME_COARSE = 5
MAX_CLOCK_RES_S = 0.010
TAIL_RETRIES = 5
TAIL_WAIT_S = 0.05
MAX_RULINGS = 200
MAX_INSTRUCTION = 2000
AUTO_LIMIT = 2

RECORD_KEYS = {"v", "action", "by", "at", "sessionId", "turnUuid", "runDir", "planPath", "planSha256", "payload"}
LAUNCH_RECORD_KEYS = {"v", "record", "recordSha256", "turnUuid", "planSha256", "auto", "review"}
DECISIONS = {"drop", "apply", "rescope"}
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class Refused(Exception):
    def __init__(self, reason: str, chat_fallback: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.chat_fallback = chat_fallback


def _emit(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Windows CPython has no O_NOFOLLOW or O_CLOEXEC, and opens in text mode without O_BINARY.
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_BINARY = getattr(os, "O_BINARY", 0)


def _open_regular(path: str) -> tuple[int, os.stat_result]:
    linked = None
    if not O_NOFOLLOW:
        # Without O_NOFOLLOW: refuse a link before the open, then check the opened file is the one lstat saw.
        linked = os.lstat(path)
        if not stat.S_ISREG(linked.st_mode):
            raise Refused(f"not a regular file with one link: {path}")
    fd = os.open(path, os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_BINARY)
    st = os.fstat(fd)
    if linked is not None and (st.st_dev, st.st_ino) != (linked.st_dev, linked.st_ino):
        os.close(fd)
        raise Refused(f"file replaced while opening: {path}")
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        os.close(fd)
        raise Refused(f"not a regular file with one link: {path}")
    return fd, st


def _same_file(a: os.stat_result, b: os.stat_result) -> bool:
    return (a.st_ino, a.st_size, a.st_mtime_ns, a.st_ctime_ns) == (b.st_ino, b.st_size, b.st_mtime_ns, b.st_ctime_ns)


def _read_file(path: str, cap: int) -> tuple[bytes, os.stat_result]:
    fd, before = _open_regular(path)
    try:
        chunks = []
        remaining = cap + 1
        while remaining > 0:
            chunk = os.read(fd, min(remaining, MB))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > cap:
            raise Refused(f"file too large: {path}")
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if not _same_file(before, after):
        raise Refused(f"file changed while reading: {path}")
    return data, after


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _no_constant(name: str) -> object:
    raise ValueError(f"constant {name} is not allowed")


def _strict_json(data: bytes) -> object:
    if data.startswith(b"\xef\xbb\xbf"):
        raise ValueError("byte order mark")
    return json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)


def _utc_ms(value: object) -> int:
    if type(value) is not str or not UTC_TIME.match(value):
        raise Refused(f"not a UTC time: {value!r}")
    moment = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    return (moment - EPOCH) // timedelta(milliseconds=1)


def _stamp(at: str) -> str:
    return f"{at[0:4]}{at[5:7]}{at[8:10]}T{at[11:13]}{at[14:16]}{at[17:19]}{at[20:23]}Z"


def _real_dir(path: str) -> str:
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise Refused(f"run folder is not a directory: {path}")
    return os.path.realpath(path)


def _highest(folder: str, pattern: re.Pattern[str]) -> int:
    numbers = [int(match.group(1)) for name in os.listdir(folder) if (match := pattern.match(name))]
    return max(numbers, default=0)


def _ext4_device(run_dir: str) -> int:
    st_dev = os.lstat(run_dir).st_dev
    device = f"{os.major(st_dev)}:{os.minor(st_dev)}"
    types = []
    with open("/proc/self/mountinfo", encoding="utf-8") as handle:
        for line in handle:
            fields = line.split(" ")
            if len(fields) < 3 or fields[2] != device or " - " not in line:
                continue
            types.append(line.split(" - ", 1)[1].split(" ", 1)[0])
    if not types or any(kind != "ext4" for kind in types):
        raise Refused("control records are checked only on ext4")
    return st_dev


class Transcript:
    """The session transcript, read once up to its size at open and then followed by tail passes."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.fd, st = _open_regular(path)
        if st.st_size > TRANSCRIPT_CAP:
            os.close(self.fd)
            raise Refused("transcript too large")
        self.ino = st.st_ino
        self.size0 = st.st_size
        self.pos = 0

    def close(self) -> None:
        os.close(self.fd)

    def lines(self):
        buffer = b""
        offset = 0
        while offset < self.size0:
            chunk = os.pread(self.fd, min(MB, self.size0 - offset), offset)
            if not chunk:
                break
            offset += len(chunk)
            buffer += chunk
            *complete, buffer = buffer.split(b"\n")
            for line in complete:
                self.pos += len(line) + 1
                yield line

    def tail_pass(self) -> None:
        handle_st = os.fstat(self.fd)
        try:
            path_st = os.stat(self.path)
        except FileNotFoundError as error:
            raise Refused("transcript replaced") from error
        if handle_st.st_ino != self.ino or path_st.st_ino != self.ino or handle_st.st_size < self.pos:
            raise Refused("transcript replaced")
        added = b""
        for attempt in range(TAIL_RETRIES + 1):
            size = os.fstat(self.fd).st_size
            added = os.pread(self.fd, size - self.pos, self.pos) if size > self.pos else b""
            if not added or added.endswith(b"\n"):
                break
            if attempt == TAIL_RETRIES:
                raise Refused("torn transcript line after go")
            time.sleep(TAIL_WAIT_S)
        for line in added.split(b"\n")[:-1]:
            if _arrived_message(line):
                raise Refused("a message arrived during the check")
        self.pos += len(added)


def _parse_line(line: bytes) -> dict | None:
    try:
        record = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def _is_queued_command(record: dict) -> bool:
    attachment = record.get("attachment")
    return record.get("type") == "attachment" and isinstance(attachment, dict) and attachment.get("type") == "queued_command"


def _arrived_message(line: bytes) -> bool:
    record = _parse_line(line)
    if record is None:
        return True
    kind = record.get("type")
    if kind == "queue-operation":
        return True
    if kind == "user" and "promptSource" in record:
        return True
    return _is_queued_command(record)


def _is_human(record: dict) -> bool:
    if record.get("type") == "user":
        return (
            record.get("isSidechain") is not True
            and record.get("isMeta") is not True
            and "promptSource" in record
            and record["promptSource"] != "system"
        )
    if _is_queued_command(record):
        return record["attachment"].get("commandMode") != "task-notification"
    return False


def _latest_go(transcript: Transcript) -> dict:
    latest: dict | None = None
    latest_index = -1
    last_unparsed = -1
    waiting: deque[object] = deque()
    delivering = 0
    for index, line in enumerate(transcript.lines()):
        record = _parse_line(line)
        if record is None:
            last_unparsed = index
            continue
        if _is_human(record):
            latest, latest_index = record, index
        kind = record.get("type")
        if kind == "queue-operation":
            operation = record.get("operation")
            if operation == "enqueue":
                waiting.append(record.get("content"))
            elif operation == "dequeue":
                if waiting:
                    waiting.popleft()
                delivering += 1
            elif operation == "remove":
                content = record.get("content")
                if content in waiting:
                    waiting.remove(content)
                elif waiting:
                    waiting.popleft()
                if record.get("reason") == "absorbed_mid_turn":
                    delivering += 1
        elif kind == "assistant":
            delivering = 0
        elif delivering and (
            (kind == "user" and "promptSource" in record and record.get("isSidechain") is not True)
            or _is_queued_command(record)
        ):
            delivering -= 1
    content = latest.get("message", {}).get("content") if latest and isinstance(latest.get("message"), dict) else None
    if (
        latest is None
        or latest.get("type") != "user"
        or type(content) is not str
        or content.strip() != "go"
        or type(latest.get("uuid")) is not str
        or type(latest.get("timestamp")) is not str
        or not UTC_TIME.match(latest["timestamp"])
    ):
        raise Refused("the latest message is not go")
    if last_unparsed > latest_index:
        raise Refused("torn transcript line after go")
    if waiting:
        raise Refused("a message is waiting behind go")
    if delivering:
        raise Refused("a message is being delivered behind go")
    return latest


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise Refused(reason)


def _load_forge_result(path: str, sha256: str, run_dir: str, device: int | None) -> tuple[dict, os.stat_result]:
    reason = "forge result is not the one saved for this stop"
    if os.path.realpath(os.path.dirname(os.path.abspath(path))) != run_dir:
        raise Refused(reason)
    match = FORGE_RESULT_NAME.match(os.path.basename(path))
    if not match or int(match.group(1)) != _highest(run_dir, FORGE_RESULT_NAME):
        raise Refused(reason)
    data, st = _read_file(path, FORGE_RESULT_CAP)
    if _sha256(data) != sha256:
        raise Refused(reason)
    result = _strict_json(data)
    if (
        not isinstance(result, dict)
        or result.get("status") != "needsJudge"
        or type(result.get("runDir")) is not str
        or os.path.realpath(result["runDir"]) != run_dir
    ):
        raise Refused(reason)
    if device is not None and st.st_dev != device:
        raise Refused("control records are checked only on ext4")
    return result, st


def _disputes(result: dict) -> dict[str, list[object]]:
    disputes = result.get("disputes")
    _require(isinstance(disputes, list), "forge result has no dispute list")
    by_id: dict[str, list[object]] = {}
    for dispute in disputes:
        _require(isinstance(dispute, dict) and type(dispute.get("id")) is str, "forge result has a malformed dispute")
        by_id.setdefault(dispute["id"], []).append(dispute.get("finding"))
    return by_id


def _check_rulings(rulings: object, disputes: dict[str, list[object]]) -> list[dict]:
    _require(isinstance(rulings, list) and len(rulings) <= MAX_RULINGS, "rulings must be a list of at most 200")
    seen: set[str] = set()
    for ruling in rulings:
        _require(isinstance(ruling, dict), "a ruling is not an object")
        _require({"id", "decision"} <= set(ruling) <= {"id", "decision", "instruction"}, "a ruling has wrong keys")
        ruling_id = ruling["id"]
        _require(type(ruling_id) is str, "a ruling id is not a string")
        _require(ruling_id in disputes, f"unknown dispute id {ruling_id}")
        _require(ruling_id not in seen, f"dispute ruled twice {ruling_id}")
        seen.add(ruling_id)
        _require(type(ruling["decision"]) is str and ruling["decision"] in DECISIONS, "a ruling has an unknown decision")
        instruction = ruling.get("instruction")
        if "instruction" in ruling:
            _require(type(instruction) is str and len(instruction) <= MAX_INSTRUCTION, "a ruling instruction is invalid")
        if ruling["decision"] == "rescope":
            _require(type(instruction) is str and instruction.strip() != "", f"rescope needs an instruction {ruling_id}")
    _require(seen == set(disputes), "the rulings do not name every dispute")
    return rulings


class Check:
    def __init__(self, args: argparse.Namespace, action: str) -> None:
        self.args = args
        self.action = action
        self.run_dir = _real_dir(args.run_dir)
        self.transcript: Transcript | None = None

    def close(self) -> None:
        if self.transcript is not None:
            self.transcript.close()

    def run(self) -> dict:
        args = self.args
        session = args.session_id or ""
        _require(bool(UUID.match(session)), "session id is not a UUID")
        matches = glob.glob(os.path.join(os.path.expanduser(args.projects_dir), "*", f"{session}.jsonl"))
        _require(len(matches) == 1, "no single transcript for this session")
        self.transcript = Transcript(matches[0])
        go = _latest_go(self.transcript)
        name, record, data, record_st = self._record_for(go)
        self._check_record(go, name, record, record_st)
        payload = record["payload"]
        self._check_payload(go, name, record, data, payload)
        return {
            "ok": True,
            "action": self.action,
            "record": os.path.join(self.run_dir, "controls", name),
            "recordSha256": _sha256(data),
            "turnUuid": go["uuid"],
            "at": record["at"],
            "payload": payload,
            "planSha256": record["planSha256"],
        }

    def _record_for(self, go: dict) -> tuple[str, dict, bytes, os.stat_result]:
        controls = os.path.join(self.run_dir, "controls")
        found = []
        try:
            controls_st = os.lstat(controls)
        except FileNotFoundError:
            controls_st = None
        if controls_st is not None:
            _require(
                stat.S_ISDIR(controls_st.st_mode) and not stat.S_ISLNK(controls_st.st_mode),
                "controls is not a directory",
            )
            for name in sorted(os.listdir(controls)):
                if not RECORD_NAME.match(name):
                    continue
                try:
                    data, st = _read_file(os.path.join(controls, name), RECORD_CAP)
                    record = _strict_json(data)
                except (Refused, OSError, ValueError) as error:
                    raise Refused(f"unreadable record {name}") from error
                _require(isinstance(record, dict), f"unreadable record {name}")
                if record.get("turnUuid") == go["uuid"]:
                    found.append((name, record, data, st))
        if not found:
            self.transcript.tail_pass()
            raise Refused("no record for this go", chat_fallback=True)
        _require(len(found) == 1, "more than one record for this go")
        name, record, _, _ = found[0]
        expected = "approve-plan" if self.action == "auto" else self.action
        _require(record.get("action") == expected, f"record action is not {expected}")
        _require(go.get("promptSource") == "sdk", "go was not sent by the app")
        return found[0]

    def _check_record(self, go: dict, name: str, record: dict, record_st: os.stat_result) -> None:
        _require(sys.platform == "linux", "control records are checked only on Linux")
        self.device = _ext4_device(self.run_dir)
        _require(record_st.st_dev == self.device, "control records are checked only on ext4")
        _require(time.clock_getres(CLOCK_REALTIME_COARSE) <= MAX_CLOCK_RES_S, "file clock too coarse")
        _require(set(record) == RECORD_KEYS, "record has wrong keys")
        _require(type(record["v"]) is int and record["v"] == 1, "record version is not 1")
        _require(record["action"] == RECORD_NAME.match(name).group(1), "record action does not match its name")
        _require(record["by"] == "workflow-maxxing", "record is not by workflow-maxxing")
        _require(type(record["sessionId"]) is str and record["sessionId"] == self.args.session_id, "record is for another session")
        for key in ("turnUuid", "runDir", "planPath"):
            _require(type(record[key]) is str, f"record {key} is not a string")
        _require(type(record["planSha256"]) is str and bool(SHA256.match(record["planSha256"])), "record planSha256 is invalid")
        _require(isinstance(record["payload"], dict), "record payload is not an object")
        at_ms = _utc_ms(record["at"])
        _require(_stamp(record["at"]) == name.split("-", 1)[0], "record name does not match at")
        go_ms = _utc_ms(go["timestamp"])
        _require(at_ms <= go_ms, "record is later than go")
        _require(go_ms - at_ms <= MAX_RECORD_AGE_MS, "record is more than 60 s older than go")
        _require(record_st.st_ctime_ns + SEP_NS <= go_ms * 1_000_000, "record not written before go")
        _require(os.path.realpath(record["runDir"]) == self.run_dir, "record is for another run folder")
        _require(os.path.realpath(record["planPath"]) == os.path.realpath(self.args.plan), "record is for another plan")
        plan_bytes, _ = _read_file(self.args.plan, PLAN_CAP)
        _require(_sha256(plan_bytes) == record["planSha256"], "plan sha256 does not match the record")

    def _check_payload(self, go: dict, name: str, record: dict, data: bytes, payload: dict) -> None:
        if record["action"] == "approve-plan":
            _require(set(payload) <= {"review", "auto"}, "approve-plan payload has wrong keys")
            if "review" in payload:
                _require(type(payload["review"]) is str and payload["review"] in ("codex", "claude"), "review is not codex or claude")
            if "auto" in payload:
                _require(payload["auto"] is True, "auto is not true")
            if self.action == "approve-plan" and payload.get("review") == "codex":
                self._require_codex_review()
        if self.action == "auto":
            self._check_auto(go, name, data, payload)
        elif self.action == "rulings":
            self._check_rulings_payload(go, payload)

    def _require_codex_review(self) -> None:
        config_bytes, _ = _read_file(os.path.expanduser(self.args.forge_config), PLAN_CAP)
        config = _strict_json(config_bytes)
        codex = config.get("codex") if isinstance(config, dict) else None
        roles = codex.get("roles") if isinstance(codex, dict) else None
        review = roles.get("review") if isinstance(roles, dict) else None
        _require(isinstance(review, dict), "forge.config.json has no codex.roles.review")

    def _check_auto(self, go: dict, name: str, data: bytes, payload: dict) -> None:
        launch_path = os.path.join(self.run_dir, "launch-record.json")
        try:
            launch_bytes, _ = _read_file(launch_path, RECORD_CAP)
        except FileNotFoundError as error:
            raise Refused("no launch record") from error
        launch = _strict_json(launch_bytes)
        _require(isinstance(launch, dict) and set(launch) == LAUNCH_RECORD_KEYS, "launch record has wrong keys")
        _require(launch["turnUuid"] == go["uuid"], "auto belongs to the launch go")
        _require(launch["record"] == os.path.join(self.run_dir, "controls", name), "launch record names another record")
        _require(launch["recordSha256"] == _sha256(data), "launch record changed since launch")
        _require(payload.get("auto") is True, "the launch record has no auto")
        auto_files = [entry for entry in os.listdir(self.run_dir) if AUTO_RULINGS_NAME.match(entry)]
        _require(len(auto_files) < AUTO_LIMIT, "auto limit reached")
        self.forge_result, _ = _load_forge_result(
            self.args.forge_result, self.args.forge_result_sha256, self.run_dir, self.device
        )

    def _check_rulings_payload(self, go: dict, payload: dict) -> None:
        result, result_st = _load_forge_result(
            self.args.forge_result, self.args.forge_result_sha256, self.run_dir, self.device
        )
        _require(set(payload) == {"forgeResult", "forgeResultSha256", "rulings"}, "rulings payload has wrong keys")
        _require(payload["forgeResult"] == os.path.basename(self.args.forge_result), "record names another forge result")
        _require(payload["forgeResultSha256"] == self.args.forge_result_sha256, "record names another forge result hash")
        go_ms = _utc_ms(go["timestamp"])
        _require(result_st.st_ctime_ns + SEP_NS <= go_ms * 1_000_000, "forge result not written before go")
        _check_rulings(payload["rulings"], _disputes(result))


def _create_exclusive(path: str, data: bytes) -> os.stat_result:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_CLOEXEC | O_BINARY, 0o644)
    try:
        os.write(fd, data)
        return os.fstat(fd)
    finally:
        os.close(fd)


def _claim(transcript: Transcript, path: str, data: bytes) -> None:
    transcript.tail_pass()
    created = _create_exclusive(path, data)
    try:
        transcript.tail_pass()
    except Refused:
        try:
            if os.lstat(path).st_ino == created.st_ino:
                os.unlink(path)
        except FileNotFoundError:
            pass
        raise


def cmd_check(args: argparse.Namespace) -> dict:
    check = Check(args, args.action)
    try:
        result = check.run()
        check.transcript.tail_pass()
        return result
    finally:
        check.close()


def cmd_claim_launch(args: argparse.Namespace) -> dict:
    check = Check(args, "approve-plan")
    try:
        result = check.run()
        launch_path = os.path.join(check.run_dir, "launch-record.json")
        payload = result["payload"]
        body = {
            "v": 1,
            "record": result["record"],
            "recordSha256": result["recordSha256"],
            "turnUuid": result["turnUuid"],
            "planSha256": result["planSha256"],
            "auto": payload.get("auto") is True,
            "review": payload.get("review"),
        }
        try:
            _claim(check.transcript, launch_path, json.dumps(body, sort_keys=True).encode("utf-8"))
        except FileExistsError as error:
            raise Refused("this run folder was already launched by a record") from error
        return {**result, "launchRecord": launch_path}
    finally:
        check.close()


def cmd_claim_auto(args: argparse.Namespace) -> dict:
    args.forge_config = None
    check = Check(args, "auto")
    try:
        result = check.run()
        draft_bytes, _ = _read_file(args.rulings, RECORD_CAP)
        draft = _strict_json(draft_bytes)
        _require(isinstance(draft, dict) and set(draft) == {"rulings"}, "draft rulings file has wrong keys")
        disputes = _disputes(check.forge_result)
        rulings = _check_rulings(draft["rulings"], disputes)
        for ruling in rulings:
            if ruling["decision"] == "drop" and not all(
                isinstance(finding, dict)
                and finding.get("severity") in ("LOW", "MEDIUM")
                and type(finding.get("reviewer")) is str
                and finding["reviewer"] != "security"
                for finding in disputes[ruling["id"]]
            ):
                raise Refused(f"auto may not drop {ruling['id']}")
        check.transcript.tail_pass()
        n = _highest(check.run_dir, AUTO_RULINGS_NAME) + 1
        _require(n <= AUTO_LIMIT, "auto limit reached")
        path = os.path.join(check.run_dir, f"rulings-auto-{n}.json")
        body = {
            "v": 1,
            "n": n,
            "launchRecord": os.path.join(check.run_dir, "launch-record.json"),
            "turnUuid": result["turnUuid"],
            "forgeResult": os.path.basename(args.forge_result),
            "forgeResultSha256": args.forge_result_sha256,
            "rulings": rulings,
        }
        try:
            _claim(check.transcript, path, json.dumps(body, sort_keys=True).encode("utf-8"))
        except FileExistsError as error:
            raise Refused("auto limit reached") from error
        return {"ok": True, "path": path, "n": n, "rulings": rulings}
    finally:
        check.close()


def cmd_save_result(args: argparse.Namespace) -> dict:
    run_dir = _real_dir(args.run_dir)
    data, _ = _read_file(args.output_file, TASK_OUTPUT_CAP)
    output = _strict_json(data)
    result = output.get("result") if isinstance(output, dict) else None
    _require(isinstance(result, dict) and type(result.get("status")) is str, "no result object")
    _require(
        type(result.get("runDir")) is str and os.path.realpath(result["runDir"]) == run_dir,
        "result is for another run folder",
    )
    body = json.dumps(result, sort_keys=True).encode("utf-8")
    _require(len(body) <= FORGE_RESULT_CAP, "result too large")
    n = _highest(run_dir, FORGE_RESULT_NAME) + 1
    path = os.path.join(run_dir, f"forge-result-{n}.json")
    _create_exclusive(path, body)
    return {"ok": True, "path": path, "sha256": _sha256(body), "status": result["status"]}


def _add_session_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--session-id", default=os.environ.get("CLAUDE_CODE_SESSION_ID"))
    parser.add_argument("--projects-dir", default=str(Path("~/.claude/projects")))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    default_config = str(Path("~/.claude/skills/forge/forge.config.json"))

    check = commands.add_parser("check")
    _add_session_options(check)
    check.add_argument("--action", required=True, choices=["approve-plan", "rulings", "auto"])
    check.add_argument("--forge-result")
    check.add_argument("--forge-result-sha256")
    check.add_argument("--forge-config", default=default_config)

    launch = commands.add_parser("claim-launch")
    _add_session_options(launch)
    launch.add_argument("--forge-config", default=default_config)

    auto = commands.add_parser("claim-auto")
    _add_session_options(auto)
    auto.add_argument("--rulings", required=True)
    auto.add_argument("--forge-result", required=True)
    auto.add_argument("--forge-result-sha256", required=True)

    save = commands.add_parser("save-result")
    save.add_argument("--run-dir", required=True)
    save.add_argument("--output-file", required=True)
    return parser


COMMANDS = {
    "check": cmd_check,
    "claim-launch": cmd_claim_launch,
    "claim-auto": cmd_claim_auto,
    "save-result": cmd_save_result,
}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        has_result = args.forge_result is not None or args.forge_result_sha256 is not None
        if args.action == "approve-plan" and has_result:
            parser.error("--forge-result and --forge-result-sha256 are not used with approve-plan")
        if args.action != "approve-plan" and (args.forge_result is None or args.forge_result_sha256 is None):
            parser.error(f"--action {args.action} needs --forge-result and --forge-result-sha256")
    try:
        _emit(COMMANDS[args.command](args))
    except Refused as refusal:
        _emit({"ok": False, "chatFallback": refusal.chat_fallback, "reason": refusal.reason})
        return 1
    except (OSError, ValueError) as error:
        _emit({"ok": False, "chatFallback": False, "reason": f"{type(error).__name__}: {error}"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
