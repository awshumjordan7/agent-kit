#!/usr/bin/env python3
"""Record the plan answer and review verdicts for a change made outside forge, and check them at ship time.

Usage:
  ship_record.py answer --repo <repo> --run-dir <d> --plan yes|no [--plan-path <p>]
  ship_record.py snapshot --repo <repo> --run-dir <d> --label <l> --files-json <context json>
  ship_record.py verdict --repo <repo> --run-dir <d> --stage plan-review|review
                 --provider <p> --model <m> --verdict <v> [--label <l>]
  ship_record.py check --repo <repo> [--run-dir <d>] --files <path>...

The record is <run-dir>/ship-record.json. `check` prints one line and exits 0:
SHIP_RECORD_EXEMPT, SHIP_RECORD_OK, or NEEDS_SHIP_CONFIRM with what is missing.
Exit codes for the other subcommands: 0 written, 1 a file could not be hashed, 2 bad input.
"""

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

RECORD_NAME = "ship-record.json"
# Forge writes these into its run dir; forge plans and reviews its own changes.
FORGE_MARKERS = ("phases.json", "context-gate.json", "checkpoint.json")


def _run_dir(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load(run_dir: Path) -> dict:
    try:
        data = json.loads((run_dir / RECORD_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(run_dir: Path, record: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=run_dir, prefix=".ship-record.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, run_dir / RECORD_NAME)


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _normalize(repo: Path, path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(repo)
        except ValueError:
            pass
    return Path(os.path.normpath(candidate)).as_posix()


def files_sha(repo: Path, files: list[str]) -> str:
    """Hash each file as git would stage it: regular files by blob id, symlinks by target text."""
    paths = sorted({_normalize(repo, path) for path in files})
    lines: dict[str, str] = {}
    regular: list[str] = []
    for path in paths:
        try:
            info = os.lstat(repo / path)
        except FileNotFoundError:
            lines[path] = f"{path}\t0\tdeleted"
            continue
        if stat.S_ISLNK(info.st_mode):
            target = os.fsencode(os.readlink(repo / path))
            lines[path] = f"{path}\t120000\t{hashlib.sha256(target).hexdigest()}"
        elif stat.S_ISREG(info.st_mode):
            mode = "100755" if info.st_mode & stat.S_IXUSR else "100644"
            lines[path] = f"{path}\t{mode}\t"
            regular.append(path)
        else:
            lines[path] = f"{path}\t0\tother"
    if regular:
        result = subprocess.run(
            ["git", "-C", str(repo), "hash-object", "--stdin-paths"],
            input="\n".join(regular) + "\n",
            capture_output=True,
            text=True,
            check=True,
        )
        for path, blob in zip(regular, result.stdout.split(), strict=True):
            lines[path] += blob
    body = "\n".join(lines[path] for path in paths) + "\n"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def cmd_answer(args: argparse.Namespace, repo: Path) -> int:
    run_dir = _run_dir(args.run_dir)
    record = _load(run_dir)
    record["planAnswer"] = args.plan
    if args.plan_path:
        record["planPath"] = str(Path(args.plan_path).expanduser().resolve())
    else:
        record["planPath"] = str(run_dir / "plan.md") if args.plan == "yes" else None
    _save(run_dir, record)
    return 0


def cmd_snapshot(args: argparse.Namespace, repo: Path) -> int:
    run_dir = _run_dir(args.run_dir)
    try:
        context = json.loads(Path(args.files_json).read_text(encoding="utf-8"))
        files = context["files"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: cannot read files from {args.files_json}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(files, list) or not all(isinstance(path, str) for path in files):
        print(f"error: {args.files_json} has no list of file paths", file=sys.stderr)
        return 2
    try:
        sha = files_sha(repo, files)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"error: cannot hash the reviewed files: {exc}", file=sys.stderr)
        return 1
    record = _load(run_dir)
    snapshots = record.get("snapshots") if isinstance(record.get("snapshots"), dict) else {}
    snapshots[args.label] = {"files": files, "filesSha": sha}
    record["snapshots"] = snapshots
    _save(run_dir, record)
    return 0


def cmd_verdict(args: argparse.Namespace, repo: Path) -> int:
    run_dir = _run_dir(args.run_dir)
    record = _load(run_dir)
    entry = {
        "provider": _one_line(args.provider),
        "model": _one_line(args.model),
        "verdict": _one_line(args.verdict),
    }
    if args.stage == "plan-review":
        record["planReview"] = entry
    else:
        snapshots = record.get("snapshots") if isinstance(record.get("snapshots"), dict) else {}
        snapshot = snapshots.get(args.label)
        entry["label"] = args.label
        if isinstance(snapshot, dict) and isinstance(snapshot.get("filesSha"), str):
            entry.update(files=snapshot.get("files", []), filesSha=snapshot["filesSha"], stale=False)
        else:
            entry.update(files=[], filesSha=None, stale=True)
        record["review"] = entry
    _save(run_dir, record)
    return 0


def _verdict(entry: object) -> str | None:
    if isinstance(entry, dict) and isinstance(entry.get("verdict"), str) and entry["verdict"]:
        return entry["verdict"]
    return None


def cmd_check(args: argparse.Namespace, repo: Path) -> int:
    record: dict = {}
    if args.run_dir:
        run_dir = Path(args.run_dir).expanduser().resolve()
        if any((run_dir / name).is_file() for name in FORGE_MARKERS):
            print("SHIP_RECORD_EXEMPT forge run")
            return 0
        if run_dir.is_dir():
            record = _load(run_dir)
    plan_answer = record.get("planAnswer")
    plan = {"yes": "yes", "no": "declined"}.get(plan_answer, "not asked")
    plan_review = _verdict(record.get("planReview")) or "missing"
    review_entry = record.get("review")
    review = _verdict(review_entry)
    current = False
    if review is not None:
        recorded_sha = review_entry.get("filesSha")
        try:
            current = isinstance(recorded_sha, str) and recorded_sha == files_sha(repo, args.files)
        except (OSError, subprocess.CalledProcessError):
            current = False
    if current and (plan == "declined" or (plan == "yes" and plan_review != "missing")):
        print("SHIP_RECORD_OK")
        return 0
    review_text = "missing" if review is None else (review if current else "stale")
    print(f"NEEDS_SHIP_CONFIRM plan: {plan}; plan review: {plan_review}; review: {review_text}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    answer = sub.add_parser("answer")
    answer.add_argument("--plan", required=True, choices=("yes", "no"))
    answer.add_argument("--plan-path")

    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--label", required=True)
    snapshot.add_argument("--files-json", required=True)

    verdict = sub.add_parser("verdict")
    verdict.add_argument("--stage", required=True, choices=("plan-review", "review"))
    verdict.add_argument("--provider", required=True)
    verdict.add_argument("--model", required=True)
    verdict.add_argument("--verdict", required=True)
    verdict.add_argument("--label", default="change")

    check = sub.add_parser("check")
    check.add_argument("--files", required=True, nargs="+")

    for name, command in sub.choices.items():
        command.add_argument("--repo", required=True)
        command.add_argument("--run-dir", required=name != "check")

    args = parser.parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        print(f"error: repo dir not found: {args.repo}", file=sys.stderr)
        return 2
    handlers = {"answer": cmd_answer, "snapshot": cmd_snapshot, "verdict": cmd_verdict, "check": cmd_check}
    return handlers[args.command](args, repo)


if __name__ == "__main__":
    sys.exit(main())
