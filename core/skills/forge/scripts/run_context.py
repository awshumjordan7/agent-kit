from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
        if any(code in entry[:2] for code in "RC") and index + 1 < len(entries):
            index += 1
        paths.append(path)
        index += 1
    return porcelain, paths


def _safe_paths(repo: Path, paths: list[str]) -> tuple[list[str], list[str]]:
    repo_root = repo.resolve()
    kept: list[str] = []
    dropped: list[str] = []
    for path in paths:
        candidate = Path(path)
        if not path or candidate.is_absolute() or ".." in candidate.parts:
            dropped.append(path)
            continue
        try:
            (repo_root / candidate).resolve().relative_to(repo_root)
        except (OSError, RuntimeError, ValueError):
            dropped.append(path)
            continue
        kept.append(path)
    return list(dict.fromkeys(kept)), list(dict.fromkeys(dropped))


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def baseline(run_dir: Path, repo: Path, reuse: bool = False) -> dict:
    # A resumed run must keep its first baseline: phase commits move HEAD, and a fresh baseline
    # would hide the run's own committed and dirty files from the review diff.
    if reuse and (run_dir / "baseline.json").is_file():
        return {"written": False}
    porcelain, paths = _status(repo)
    document = {
        "head": str(_git(repo, "rev-parse", "HEAD")).strip(),
        "porcelain": porcelain,
        "files": {path: _sha256(repo / path) for path in paths},
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "baseline.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    return {"written": True}


def smoke_run(run_dir: Path, repo: Path, command: str, log_name: str = "smoke.log") -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / Path(log_name).name
    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            shell=True,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=900,
        )
        output = completed.stdout or ""
        exit_code = completed.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        exit_code = 124
        timed_out = True
    tail = "\n".join(output.splitlines()[-200:])
    log_path.write_text(tail + ("\n" if tail else ""), encoding="utf-8")
    return {
        "passed": exit_code == 0,
        "exitCode": exit_code,
        "timedOut": timed_out,
        "command": command,
        "logPath": str(log_path),
        "summary": "smoke command passed" if exit_code == 0 else f"smoke command failed with exit {exit_code}",
    }


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


_CRITERION = re.compile(r"^(?:[-*](?: \[[ xX]\])?|\d+[.)])\s+")


def _criteria(section: str) -> list[str]:
    items: list[str] = []
    for line in section.splitlines():
        marker = _CRITERION.match(line.lstrip())
        if marker:
            items.append(line.lstrip()[marker.end() :].strip())
        elif items and line[:1] in " \t" and line.strip():
            items[-1] += " " + line.strip()
    return items


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fnv1a(text: str) -> int:
    value = 2166136261
    for char in text:
        value = ((value ^ ord(char)) * 16777619) & 0xFFFFFFFF
    return value


def _checked(facts: dict) -> dict:
    # forge-core.js recomputes both numbers over the facts it receives, so an agent that adds,
    # drops or edits a field while echoing this line is caught. Facts must hold no null or float.
    canon = _canonical(facts)
    return {"facts": facts, "canonLength": len(canon), "fnv1a": _fnv1a(canon)}


# The plan patterns below must match the JavaScript regular expressions forge used before, so
# they spell out JavaScript's whitespace set, line terminators and ASCII-only case folding
# instead of using Python's \s, ".", "$", \b and re.IGNORECASE, which all differ.
_JS_WS = " \t\n\x0b\x0c\r   -     　﻿"
_JS_STRIP = (
    " \t\n\x0b\x0c\r            "
    "     　﻿"
)
_S = f"[{_JS_WS}]"
_NOT_S = f"[^{_JS_WS}]"
_LINE_END = "\n\r  "
_DOT = f"[^{_LINE_END}]"
_LINE_START = f"(?:\\A|(?<=[{_LINE_END}]))"
_LINE_STOP = f"(?=[{_LINE_END}]|\\Z)"
_PHASE_WORD = "[Pp][Hh][Aa][Ss][Ee]"
_PHASES_WORD = _PHASE_WORD + "[Ss]"
_ASCII_LOWER = {code: code + 32 for code in range(ord("A"), ord("Z") + 1)}

_H1 = re.compile(f"{_LINE_START}#{_S}+({_DOT}+){_LINE_STOP}")
_PHASES_LINE = re.compile(f"##{_S}+{_PHASES_WORD}{_S}*\\Z")
_FENCE_LINE = re.compile(f"{_S}*(?:```|~~~)")
_TOP_HEADING_LINE = re.compile(f"#{{1,2}}{_S}")
_SUB_HEADING_LINE = re.compile(f"###{_S}")
_PHASE_HEADING = re.compile(
    f"###{_S}+Phase{_S}+([A-Za-z]*[0-9]+):{_S}*({_NOT_S}{_DOT}*?){_S}*\\Z"
)
_PHASES_SECTION = re.compile(f"{_LINE_START}(#{{2,}}){_S}*{_PHASES_WORD}{_S}*{_LINE_STOP}")
_PLAN_PATH = re.compile(r"`([^`\n]+\.[A-Za-z0-9]+)`")
_SOURCE_EXTENSION = re.compile(
    r"\.(?:bash|c|cc|cpp|cs|css|cxx|go|h|hpp|html|java|js|jsx|kt|kts|less|mjs|php|py|rb|rs"
    r"|scala|scss|sh|sql|svelte|swift|toml|ts|tsx|vue|yaml|yml|zsh)\Z"
)
_NAME_EXTENSION = re.compile(r"\.[a-z0-9]+\Z")


def _plan_phases(plan: str) -> tuple[list[dict], str]:
    # str.splitlines() also splits on form feed and U+2028, which would move the phase headings.
    lines = re.split(r"\r?\n", plan)
    start = next((index for index, line in enumerate(lines) if _PHASES_LINE.match(line)), None)
    if start is None:
        return [], ""
    phases: list[dict] = []
    fenced = False
    for line in lines[start + 1 :]:
        if _FENCE_LINE.match(line):
            fenced = not fenced
        elif not fenced and _TOP_HEADING_LINE.match(line):
            break
        elif not fenced and _SUB_HEADING_LINE.match(line):
            match = _PHASE_HEADING.match(line)
            if not match:
                return [], (
                    'Plan heading under ## Phases must read "### Phase <id>: <title>" '
                    f"with an id such as 1 or A1: {line.strip(_JS_STRIP)}"
                )
            if any(item["id"] == match.group(1) for item in phases):
                return [], f"Plan phase id {match.group(1)} appears twice under ## Phases"
            phases.append({"id": match.group(1), "title": match.group(2)})
    return phases, ""


def _is_source_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    name = normalized.split("/")[-1]
    return (
        not normalized.startswith("tests/")
        and "/tests/" not in normalized
        and not name.startswith("test_")
        and not name.endswith(("_test.py", ".md", ".json"))
        and bool(_NAME_EXTENSION.search(name))
    )


def _planned_source_files(plan: str) -> int:
    section = _PHASES_SECTION.search(plan)
    if not section:
        return 0
    after = plan[section.end() :]
    # The section ends at the next heading of its own level or higher, except a "Phase" heading.
    next_heading = re.search(
        f"{_LINE_START}#{{2,{len(section.group(1))}}}{_S}+(?!{_PHASE_WORD}(?![A-Za-z0-9_]))",
        after,
    )
    body = after[: next_heading.start()] if next_heading else after
    paths = [
        path
        for path in _PLAN_PATH.findall(body)
        if "/" in path or "\\" in path or _SOURCE_EXTENSION.search(path.translate(_ASCII_LOWER))
    ]
    return len({path for path in paths if _is_source_path(path)})


def _read_plan(plan_file: Path) -> tuple[bytes, str, str]:
    # Bytes, not read_text: universal newlines would turn CRLF and a lone CR into LF.
    try:
        raw = plan_file.read_bytes()
    except OSError as exc:
        return b"", "", f"could not read the plan at {plan_file}: {exc.strerror or exc}"
    if not raw:
        return raw, "", f"could not read the plan at {plan_file}: the file is empty"
    try:
        return raw, raw.decode("utf-8"), ""
    except UnicodeDecodeError as exc:
        return raw, "", f"could not read the plan at {plan_file}: {exc}"


def plan_facts(plan_file: Path, criteria_only: bool = False) -> dict:
    raw, plan, error = _read_plan(plan_file)
    if criteria_only:
        return _checked({"criteria": _criteria(_section(plan, "Acceptance Criteria"))})
    phases: list[dict] = []
    if not error:
        phases, error = _plan_phases(plan)
    heading = _H1.search(plan)
    return _checked(
        {
            "h1": heading.group(1) if heading else "",
            "phases": phases,
            "plannedSourceFiles": _planned_source_files(plan),
            "hasContract": bool(_section(plan, "Public API contract")),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest() if raw else "",
            "error": error,
        }
    )


def _write_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _review_brief(plan: str, references: Path) -> str:
    # The reviewer contract stays out: this file is added whole to the Codex prompt, and that
    # contract tells its reader to read the diff from disk, which a Codex prompt must not do.
    criteria = _criteria(_section(plan, "Acceptance Criteria"))
    parts = [
        ("Plan summary", _section(plan, "Summary") or plan[:4000]),
        ("Public API contract", _section(plan, "Public API contract") or "(none declared)"),
        (
            "Acceptance criteria",
            "\n".join(f"{number}. {item}" for number, item in enumerate(criteria, 1))
            or "(none listed)",
        ),
        ("Review checklist", (references / "review-checklist.md").read_text(encoding="utf-8")),
        ("Code standards", (references / "code-standards.md").read_text(encoding="utf-8")),
    ]
    return "".join(f"## {heading}\n\n{body.strip()}\n\n" for heading, body in parts)


def _ref_exists(repo: Path, ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


def _advanced_base(repo: Path, head: str, base: str) -> str:
    # Merging a newer base into the branch mid-run brings in other PRs' files. Start the diff at
    # the merge-base only when it descends from the baseline head, so the diff never widens.
    ref = f"origin/{base}" if _ref_exists(repo, f"origin/{base}") else base
    merge_base = subprocess.run(
        ["git", "-C", str(repo), "merge-base", ref, "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    candidate = merge_base.stdout.strip()
    if merge_base.returncode or not candidate:
        return head
    is_ancestor = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", head, candidate],
        check=False,
        capture_output=True,
    )
    return candidate if is_ancestor.returncode == 0 else head


def _diff_base(
    repo: Path, document: dict, base: str | None, advance_only: bool = False
) -> str:
    head = document.get("head")
    if base and advance_only and head:
        return _advanced_base(repo, str(head).strip(), base)
    if base and not advance_only:
        return str(_git(repo, "merge-base", base, "HEAD")).strip()
    return str(head or _git(repo, "rev-parse", "HEAD")).strip()


def _changed_since_baseline(
    repo: Path,
    document: dict,
    diff_base: str,
    all_dirty: bool = False,
) -> tuple[list[str], list[str], list[str]]:
    _porcelain, dirty = _status(repo)
    committed = str(
        _git(repo, "diff", "--name-only", "--diff-filter=ACMRD", diff_base, "HEAD")
    ).splitlines()
    baseline_files = document.get("files", {})
    candidates, dropped = _safe_paths(repo, [*committed, *dirty])
    committed_set = set(committed)
    files: list[str] = []
    preexisting: list[str] = []
    for path in candidates:
        current_sha = _sha256(repo / path)
        unchanged_preexisting = path in baseline_files and current_sha == baseline_files[path]
        if not all_dirty and path not in committed_set and unchanged_preexisting:
            preexisting.append(path)
        else:
            files.append(path)
    return files, preexisting, dropped


def _build_diff(repo: Path, diff_base: str, files: list[str]) -> str:
    if not files:
        return ""
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
                    "--",
                    "/dev/null",
                    path,
                ],
                cwd=repo,
                check=False,
                capture_output=True,
                text=True,
            )
            diff += addition.stdout
    return diff


def write_diff(
    run_dir: Path,
    repo: Path,
    label: str,
    base: str | None = None,
    hints: list[str] | None = None,
    advance_only: bool = False,
) -> tuple[Path, list[str], list[str], list[str]]:
    baseline_path = run_dir / "baseline.json"
    document = (
        json.loads(baseline_path.read_text(encoding="utf-8"))
        if baseline_path.is_file()
        else {}
    )
    diff_base = _diff_base(repo, document, base, advance_only)
    files, preexisting, dropped = _changed_since_baseline(repo, document, diff_base)
    _kept_hints, dropped_hints = _safe_paths(repo, hints or [])
    dropped = list(dict.fromkeys([*dropped, *dropped_hints]))
    run_dir.mkdir(parents=True, exist_ok=True)
    diff_path = run_dir / f"gate-{label}.diff"
    diff_path.write_text(_build_diff(repo, diff_base, files), encoding="utf-8")
    return diff_path, files, preexisting, dropped


def context(
    run_dir: Path,
    repo: Path,
    plan_file: Path,
    label: str,
    all_dirty: bool = False,
    base: str | None = None,
    hints: list[str] | None = None,
    advance_only: bool = False,
) -> dict:
    baseline_path = run_dir / "baseline.json"
    document = json.loads(baseline_path.read_text(encoding="utf-8"))
    diff_base = _diff_base(repo, document, base, advance_only)
    files, preexisting, dropped = _changed_since_baseline(
        repo, document, diff_base, all_dirty=all_dirty
    )
    _kept_hints, dropped_hints = _safe_paths(repo, hints or [])
    dropped = list(dict.fromkeys([*dropped, *dropped_hints]))
    diff = _build_diff(repo, diff_base, files)
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
    brief_path = run_dir / f"review-brief-{label}.md"
    _write_atomic(brief_path, _review_brief(plan, references))
    facts = {
        "files": files,
        "preexisting": preexisting,
        "droppedPaths": dropped,
        "commandSucceeded": True,
        "diffPath": str(diff_path),
        "diffBytes": len(diff.encode("utf-8")),
        "diffLines": len(diff.splitlines()),
        "diffValid": diff_valid,
        "testPaths": list(dict.fromkeys(tests)) or ["tests/unit"],
        "error": "",
        "briefPath": str(brief_path),
        "hasContract": bool(_section(plan, "Public API contract")),
    }
    _write_atomic(run_dir / f"context-{label}.json", json.dumps(facts, indent=2) + "\n")
    return _checked(facts)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    baseline_parser = subparsers.add_parser("baseline")
    baseline_parser.add_argument("--run-dir", type=Path, required=True)
    baseline_parser.add_argument("--repo", type=Path, required=True)
    baseline_parser.add_argument("--reuse", action="store_true")
    context_parser = subparsers.add_parser("context")
    context_parser.add_argument("--run-dir", type=Path, required=True)
    context_parser.add_argument("--repo", type=Path, required=True)
    context_parser.add_argument("--plan-file", type=Path, required=True)
    context_parser.add_argument("--label", required=True)
    context_parser.add_argument("--all-dirty", action="store_true")
    context_parser.add_argument("--base")
    context_parser.add_argument("--advance-only", action="store_true")
    context_parser.add_argument("--files", nargs="*")
    diff_parser = subparsers.add_parser("diff")
    diff_parser.add_argument("--run-dir", type=Path, required=True)
    diff_parser.add_argument("--repo", type=Path, required=True)
    diff_parser.add_argument("--label", required=True)
    diff_parser.add_argument("--base")
    diff_parser.add_argument("--advance-only", action="store_true")
    diff_parser.add_argument("--files", nargs="*")
    smoke_run_parser = subparsers.add_parser("smoke-run")
    smoke_run_parser.add_argument("--run-dir", type=Path, required=True)
    smoke_run_parser.add_argument("--repo", type=Path, required=True)
    smoke_run_parser.add_argument("--command", dest="smoke_command", required=True)
    smoke_run_parser.add_argument("--log-name", default="smoke.log")
    plan_facts_parser = subparsers.add_parser("plan-facts")
    plan_facts_parser.add_argument("--plan-file", type=Path, required=True)
    plan_facts_parser.add_argument("--criteria-only", action="store_true")
    args = parser.parse_args()
    if args.command == "baseline":
        result = baseline(args.run_dir, args.repo, args.reuse)
    elif args.command == "context":
        result = context(
            args.run_dir,
            args.repo,
            args.plan_file,
            args.label,
            args.all_dirty,
            args.base,
            args.files,
            args.advance_only,
        )
    elif args.command == "diff":
        diff_path, _files, _preexisting, _dropped = write_diff(
            args.run_dir, args.repo, args.label, args.base, args.files, args.advance_only
        )
        sys.stdout.write(str(diff_path) + "\n")
        return
    elif args.command == "smoke-run":
        result = smoke_run(args.run_dir, args.repo, args.smoke_command, args.log_name)
    elif args.command == "plan-facts":
        result = plan_facts(args.plan_file, args.criteria_only)
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
