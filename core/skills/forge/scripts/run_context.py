from __future__ import annotations

import argparse
import ast
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


# The plan patterns below follow JavaScript regex rules for whitespace, line ends and ASCII-only
# case folding, so a plan parses the same as in earlier forge versions. Python's \s, ".", "$",
# \b and re.IGNORECASE all differ from those rules, so the sets are spelled out.
_JS_WS = " \t\n\x0b\x0c\r\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_JS_STRIP = (
    " \t\n\x0b\x0c\r\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009"
    "\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_S = f"[{_JS_WS}]"
_NOT_S = f"[^{_JS_WS}]"
_LINE_END = "\n\r\u2028\u2029"
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


_CONTEXT_DEFAULTS: dict = {
    "files": [],
    "preexisting": [],
    "droppedPaths": [],
    "commandSucceeded": False,
    "diffPath": "",
    "diffBytes": 0,
    "diffLines": 0,
    "diffValid": False,
    "testPaths": [],
    "error": "",
    "briefPath": "",
    "hasContract": False,
}
_CHECKPOINT_DEFAULTS: dict = {
    "recommendation": "",
    "command": "",
    "decidedBy": "",
    "implementFilesChanged": [],
    "planSha256": "",
}


def _known(source: object, defaults: dict) -> dict:
    # Keeps only the keys of defaults; a missing or wrongly typed value becomes the empty default.
    # type() and not isinstance(): a bool is an int in Python and must not pass for one.
    values = source if isinstance(source, dict) else {}
    kept: dict = {}
    for key, default in defaults.items():
        value = values.get(key)
        if type(value) is not type(default):
            value = default
        kept[key] = [str(item) for item in value] if isinstance(value, list) else value
    return kept


def _shell_quote(value: str) -> str:
    # Always quotes, as shellQuote in forge-core.js does; shlex.quote leaves safe strings bare.
    return "'" + value.replace("'", "'\\''") + "'"


def _read_json(path: Path) -> tuple[dict, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return {}, f"could not read {path}: {exc.strerror or exc}"
    except ValueError as exc:
        return {}, f"could not parse {path}: {exc}"
    if not isinstance(document, dict):
        return {}, f"{path} does not hold a JSON object"
    return document, ""


def _smoke_script_problem(script_path: Path, context_path: Path) -> str:
    try:
        source = script_path.read_text(encoding="utf-8")
        stale = script_path.stat().st_mtime_ns < context_path.stat().st_mtime_ns
    except (OSError, UnicodeDecodeError) as exc:
        return f"could not read {script_path}: {getattr(exc, 'strerror', None) or exc}"
    if stale:
        return f"{script_path} is older than {context_path}; this run's reviewer did not write it"
    try:
        ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return f"{script_path} is not valid Python: {exc}"
    return ""


def checkpoint_save(
    run_dir: Path,
    recommendation: str,
    decided_by: str,
    files: list[str],
    script: bool = False,
    command: str = "",
    branch: str | None = None,
    plan_sha256: str = "",
) -> dict:
    path = run_dir / "checkpoint.json"
    context_path = run_dir / "context-gate.json"
    context_document, error = _read_json(context_path)
    phases: list = []
    # phases.json is read only on request, so a file left by an earlier run cannot turn a
    # single-pass run into a phased one.
    if not error and branch is not None:
        phases_document, error = _read_json(run_dir / "phases.json")
        phases = phases_document.get("phases") or []
    if not error and script:
        script_path = run_dir / "smoke.py"
        error = _smoke_script_problem(script_path, context_path)
        command = f"python3 {_shell_quote(str(script_path))}"
    facts = {
        "written": False,
        "path": str(path),
        "sha256": "",
        "hasScript": script,
        "command": command,
        "files": len(files),
        "error": error,
    }
    if error:
        return _checked(facts)
    document = {
        "recommendation": recommendation,
        "command": command,
        "decidedBy": decided_by,
        "implementFilesChanged": files,
        "branch": branch or "",
        "phases": phases,
        "planSha256": plan_sha256,
        "context": _known(context_document, _CONTEXT_DEFAULTS),
    }
    try:
        _write_atomic(path, json.dumps(document, indent=2) + "\n")
    except OSError as exc:
        return _checked({**facts, "error": f"could not write {path}: {exc.strerror or exc}"})
    return _checked({**facts, "written": True, "sha256": _sha256(path) or ""})


def checkpoint_facts(run_dir: Path, plan_file: Path) -> dict:
    document, error = _read_json(run_dir / "checkpoint.json")
    facts = _known(document, _CHECKPOINT_DEFAULTS)
    facts["context"] = _known(document.get("context"), _CONTEXT_DEFAULTS)
    saved_plan = facts["planSha256"]
    facts["planChanged"] = bool(saved_plan) and saved_plan != (_sha256(plan_file) or "")
    facts["error"] = error
    # Empty branch and phases are left out: forge-core.js drops them before it recomputes the
    # digest, because an echoing agent drops or invents empty optional fields.
    branch = document.get("branch")
    if isinstance(branch, str) and branch:
        facts["branch"] = branch
    rows = document.get("phases")
    if isinstance(rows, list) and rows:
        # Facts hold no null, so a phase without a sha or a gate carries an empty string.
        facts["phases"] = [
            {key: str(values.get(key) or "") for key in ("id", "title", "sha", "gate")}
            for values in rows
            if isinstance(values, dict)
        ]
    return _checked(facts)


def _colon_fields(value: str, count: int) -> list[str | None]:
    fields = value.split(":")
    if len(fields) != count:
        raise ValueError(f"expected {count} fields separated by colons: {value}")
    return [field or None for field in fields]


def phases_save(
    run_dir: Path,
    plan_file: Path,
    branch: str,
    phases: list[str],
    pending: list[str],
    head_sha: str | None = None,
    last: str | None = None,
) -> dict:
    path = run_dir / "phases.json"
    _raw, plan, error = _read_plan(plan_file)
    planned: list[dict] = []
    if not error:
        planned, error = _plan_phases(plan)
    titles = {item["id"]: item["title"] for item in planned}
    rows: list[dict] = []
    pending_gates: list[dict] = []
    try:
        for value in phases:
            phase_id, sha, gate = _colon_fields(value, 3)
            if not error and phase_id not in titles:
                error = f"phase {phase_id} is not under ## Phases in {plan_file}"
            title = titles.get(phase_id, "")
            rows.append({"id": phase_id, "title": title, "sha": sha, "gate": gate})
        for value in pending:
            phase_id, sha, label = _colon_fields(value, 3)
            pending_gates.append({"id": phase_id, "sha": sha, "label": label})
    except ValueError as exc:
        error = error or str(exc)
    if error:
        return _checked({"written": False, "phases": 0, "error": error})
    document = {
        "branch": branch,
        "phases": rows,
        "lastCommittedPhase": last or None,
        "headSha": head_sha or None,
        "pendingGates": pending_gates,
    }
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        _write_atomic(path, json.dumps(document, indent=2) + "\n")
    except OSError as exc:
        return _checked(
            {"written": False, "phases": 0, "error": f"could not write {path}: {exc.strerror or exc}"}
        )
    return _checked({"written": True, "phases": len(rows), "error": ""})


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
    checkpoint_save_parser = subparsers.add_parser("checkpoint-save")
    checkpoint_save_parser.add_argument("--run-dir", type=Path, required=True)
    checkpoint_save_parser.add_argument(
        "--recommendation", choices=["ship", "smoke", "qa"], required=True
    )
    checkpoint_save_parser.add_argument("--decided-by", choices=["auto", "pending"], required=True)
    checkpoint_save_parser.add_argument("--script", action="store_true")
    checkpoint_save_parser.add_argument("--command", dest="save_command", default="")
    checkpoint_save_parser.add_argument("--branch")
    checkpoint_save_parser.add_argument("--plan-sha256", default="")
    checkpoint_save_parser.add_argument("--files", nargs="*", default=[])
    checkpoint_facts_parser = subparsers.add_parser("checkpoint-facts")
    checkpoint_facts_parser.add_argument("--run-dir", type=Path, required=True)
    checkpoint_facts_parser.add_argument("--plan-file", type=Path, required=True)
    phases_save_parser = subparsers.add_parser("phases-save")
    phases_save_parser.add_argument("--run-dir", type=Path, required=True)
    phases_save_parser.add_argument("--plan-file", type=Path, required=True)
    phases_save_parser.add_argument("--branch", required=True)
    phases_save_parser.add_argument("--head-sha")
    phases_save_parser.add_argument("--last")
    phases_save_parser.add_argument("--phase", nargs="*", default=[])
    phases_save_parser.add_argument("--pending", nargs="*", default=[])
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
    elif args.command == "checkpoint-save":
        result = checkpoint_save(
            args.run_dir,
            args.recommendation,
            args.decided_by,
            args.files,
            args.script,
            args.save_command,
            args.branch,
            args.plan_sha256,
        )
    elif args.command == "checkpoint-facts":
        result = checkpoint_facts(args.run_dir, args.plan_file)
    elif args.command == "phases-save":
        result = phases_save(
            args.run_dir,
            args.plan_file,
            args.branch,
            args.phase,
            args.pending,
            args.head_sha,
            args.last,
        )
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
