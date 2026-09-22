from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=text,
    )
    return completed.stdout


def _status(repo: Path) -> tuple[list[str], list[str]]:
    raw = _git(repo, "status", "--porcelain", "--untracked-files=all", "-z", text=False)
    entries = [entry for entry in raw.split(b"\0") if entry]
    porcelain: list[str] = []
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index].decode("utf-8", "surrogateescape")
        porcelain.append(entry)
        path = entry[3:]
        if entry[:2] in {"R ", "C ", "RM", "CM"} and index + 1 < len(entries):
            index += 1
        paths.append(path)
        index += 1
    return porcelain, paths


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def baseline(run_dir: Path, repo: Path) -> dict:
    porcelain, paths = _status(repo)
    document = {
        "head": str(_git(repo, "rev-parse", "HEAD")).strip(),
        "porcelain": porcelain,
        "files": {path: _sha256(repo / path) for path in paths},
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "baseline.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return {"written": True}


def _section(text: str, heading: str) -> str:
    lines = text.splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip().lower() == f"## {heading}".lower()
        ),
        None,
    )
    if start is None:
        return ""
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start + 1 : end]).strip()


def _changed_since_baseline(repo: Path, document: dict) -> tuple[list[str], list[str]]:
    _porcelain, dirty = _status(repo)
    committed = str(
        _git(repo, "diff", "--name-only", "--diff-filter=ACMRD", document["head"], "HEAD")
    ).splitlines()
    baseline_files = document.get("files", {})
    candidates = list(dict.fromkeys([*committed, *dirty, *baseline_files]))
    files: list[str] = []
    preexisting: list[str] = []
    for path in candidates:
        current_sha = _sha256(repo / path)
        if path in baseline_files and current_sha == baseline_files[path]:
            preexisting.append(path)
        else:
            files.append(path)
    return files, preexisting


def context(
    run_dir: Path,
    repo: Path,
    plan_file: Path,
    label: str,
    all_dirty: bool = False,
    base: str | None = None,
) -> dict:
    baseline_path = run_dir / "baseline.json"
    document = json.loads(baseline_path.read_text(encoding="utf-8"))
    if all_dirty:
        _porcelain, dirty = _status(repo)
        files, preexisting = list(dict.fromkeys(dirty)), []
    else:
        files, preexisting = _changed_since_baseline(repo, document)
    diff_base = document["head"]
    if base:
        diff_base = str(_git(repo, "merge-base", base, "HEAD")).strip()
        committed = str(
            _git(repo, "diff", "--name-only", "--diff-filter=ACMRD", diff_base, "HEAD")
        ).splitlines()
        files = list(dict.fromkeys([*files, *committed]))
        preexisting = [path for path in preexisting if path not in files]
    gate_diff = run_dir / f"gate-{label}.diff"
    if gate_diff.is_file():
        diff = gate_diff.read_text(encoding="utf-8", errors="replace")
    elif files:
        diff = str(_git(repo, "diff", "--no-ext-diff", diff_base, "--", *files))
        for path in files:
            tracked = subprocess.run(
                ["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", path],
                check=False,
                capture_output=True,
            )
            if tracked.returncode and (repo / path).is_file():
                addition = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(repo),
                        "diff",
                        "--no-index",
                        "--no-ext-diff",
                        "/dev/null",
                        path,
                    ],
                    cwd=repo,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                diff += addition.stdout
    else:
        diff = ""
    run_dir.mkdir(parents=True, exist_ok=True)
    diff_path = run_dir / f"review-{label}.diff"
    diff_path.write_text(diff, encoding="utf-8")
    diff_valid = bool(diff) and diff.startswith("diff --git")
    plan = plan_file.read_text(encoding="utf-8") if plan_file.is_file() else ""
    references = Path(__file__).resolve().parent.parent / "references"
    tests = [
        token.strip("`.,:;()")
        for token in plan.split()
        if "test" in token.lower() and token.strip("`.,:;()").endswith((".py", "/tests", "/unit"))
    ]
    return {
        "files": files,
        "preexisting": preexisting,
        "commandSucceeded": True,
        "diffPath": str(diff_path),
        "diffBytes": len(diff.encode("utf-8")),
        "diffLines": len(diff.splitlines()),
        "diffValid": diff_valid,
        "planSummary": _section(plan, "Summary") or plan[:4000],
        "criteria": [
            line.removeprefix("- [ ] ").removeprefix("- ").strip()
            for line in _section(plan, "Acceptance Criteria").splitlines()
            if line.strip().startswith("-")
        ],
        "checklist": (references / "review-checklist.md").read_text(encoding="utf-8"),
        "standards": (references / "code-standards.md").read_text(encoding="utf-8"),
        "testPaths": list(dict.fromkeys(tests)) or ["tests/unit"],
        "error": "",
        "contract": _section(plan, "Public API contract"),
        "reviewerContract": (references / "claude-reviewer-contract.md").read_text(
            encoding="utf-8"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    baseline_parser = subparsers.add_parser("baseline")
    baseline_parser.add_argument("--run-dir", type=Path, required=True)
    baseline_parser.add_argument("--repo", type=Path, required=True)
    context_parser = subparsers.add_parser("context")
    context_parser.add_argument("--run-dir", type=Path, required=True)
    context_parser.add_argument("--repo", type=Path, required=True)
    context_parser.add_argument("--plan-file", type=Path, required=True)
    context_parser.add_argument("--label", required=True)
    context_parser.add_argument("--all-dirty", action="store_true")
    context_parser.add_argument("--base")
    args = parser.parse_args()
    if args.command == "baseline":
        result = baseline(args.run_dir, args.repo)
    elif args.command == "context":
        result = context(
            args.run_dir,
            args.repo,
            args.plan_file,
            args.label,
            args.all_dirty,
            args.base,
        )
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
