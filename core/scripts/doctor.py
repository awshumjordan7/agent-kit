#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import tomllib

try:
    import yaml
except ImportError:
    yaml = None

HEADER = """# Code standards

Injected into every forge implementer, reviewer, and fixer prompt. Codex and
sub-agents never read ~/.claude/CLAUDE.md, so these rules travel with the prompt.
Generated verbatim from CLAUDE.md sections "Don't", "Comments", "Tests" —
do not edit here; edit CLAUDE.md and run `doctor.py --fix`.

"""
CODEX_HEADER = (
    "<!-- Generated from ~/.claude/CLAUDE.md by `doctor.py --fix`; edit CLAUDE.md, not this file. -->\n\n"
)
# Codex reads its global AGENTS.md only from $CODEX_HOME, and install always writes it here.
CODEX_AGENTS_MD = "~/.codex/AGENTS.md"
DEFAULT_CONFIG: dict[str, Any] = {
    "models": {"codex_version": "5.6", "claude_tiers": ["haiku", "sonnet", "opus", "fable"]},
    "ignore": {"globs": ["skills/synced/**"]},
    "thresholds": {"agent_max_lines": 60},
    "repos": {"roots": ["~/Projects/work/unity"]},
    # Codex reads its global AGENTS.md on every run, so it mirrors CLAUDE.md minus the
    # sections that only mean something inside Claude Code.
    "codex": {
        "exclude_sections": ["Model Routing (Sub-Agents)"],
        "exclude_bullets": ["Use `planner` for feature planning", "memory & auto-memory"],
    },
}
PATH_REF_RE = re.compile(
    r"(?:~|\$HOME)/\.claude/[^\s`\"']+|"
    r"(?<![\w./-])(?:references|scripts|lenses)/[^\s`\"']+"
)
HOOK_PATH_RE = re.compile(
    r"(?:(?:\$HOME|~)/\.claude/|(?:/[^\s\"'`]+)?/\.claude/)"
    r"[^\s\"'`;|&]+"
)
GPT_RE = re.compile(r"(?i)gpt[- ]?5\.(\d+)")
CLAUDE_MODEL_RE = re.compile(r"(?i)\bmodels?\b[^\n]{0,40}\b(haiku|sonnet|opus|fable)\b")
# Built-in Agent types inherit the session model; skills and agents must name scout/worker instead.
BUILTIN_AGENT_RE = re.compile(
    r"\b(?:Explore|general-purpose)\b[^\n]{0,40}\b(?:sub-?)?agents?\b|"
    r"\b(?:sub-?)?agents?\b[^\n]{0,40}\b(?:Explore|general-purpose)\b"
)
BUILTIN_AGENT_NEGATIONS = ("instead of", "never", "not ", "rather than")
HISTORY_RE = re.compile(r"(?i)retired|was |previously|old ")
SKILL_PATH_RE = re.compile(r"\bskills/[A-Za-z0-9_.-]+")
MEMORY_LINK_RE = re.compile(r"\]\(([^)]+\.md)\)")
SCRATCH_GLOBS = ("*.bak*", "*.orig", "*.tmp", "*.swp", "*~")

@dataclass(frozen=True)
class Finding:
    level: str
    check: str
    path: str
    line: int | None
    message: str

@dataclass
class Context:
    root: Path
    config: dict[str, Any]
    fix: bool = False

    def __post_init__(self) -> None:
        self._reads: dict[Path, str] = {}
        self._settings_loaded = False
        self._settings: dict[str, Any] | None = None
        self._settings_error: tuple[int | None, str] | None = None

    def read(self, path: Path) -> str:
        if path not in self._reads:
            self._reads[path] = path.read_text(encoding="utf-8")
        return self._reads[path]

    def display(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def ignored(self, path: Path) -> bool:
        relative = self.display(path)
        patterns = self.config.get("ignore", {}).get("globs", [])
        return any(fnmatch.fnmatch(relative, pattern) for pattern in patterns)

    def home_path(self, configured: str) -> Path:
        if configured == "~":
            return self.root.parent
        if configured.startswith("~/"):
            return self.root.parent / configured[2:]
        return Path(configured).expanduser()

    def settings(self) -> dict[str, Any] | None:
        if self._settings_loaded:
            return self._settings
        self._settings_loaded = True
        path = self.root / "settings.json"
        try:
            parsed = json.loads(self.read(path))
        except FileNotFoundError:
            self._settings_error = (None, "settings.json is missing")
            return None
        except json.JSONDecodeError as error:
            self._settings_error = (error.lineno, f"invalid JSON: {error.msg}")
            return None
        if not isinstance(parsed, dict):
            self._settings_error = (1, "settings.json must contain a JSON object")
            return None
        self._settings = parsed
        return self._settings

Check = Callable[[Context], list[Finding]]

def finding(level: str, check: str, ctx: Context, path: Path | str, message: str,
            line: int | None = None) -> Finding:
    return Finding(level, check, ctx.display(path) if isinstance(path, Path) else path, line, message)

def source_markdown(ctx: Context) -> list[Path]:
    claude = ctx.root / "CLAUDE.md"
    files = [claude] if claude.is_file() else []
    files.extend(sorted((ctx.root / "agents").glob("*.md")))
    files.extend(sorted((ctx.root / "skills").glob("**/*.md")))
    return [path for path in files if path.is_file() and not ctx.ignored(path)]

def skill_directory(ctx: Context, source: Path) -> Path | None:
    skills = ctx.root / "skills"
    try:
        relative = source.relative_to(skills)
    except ValueError:
        return None
    return skills / relative.parts[0] if relative.parts else None

def check_paths_exist(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    skip_markers = ("<", ">", "{", "}", "*", "$RUN", "<run>")
    for source in source_markdown(ctx):
        for line_number, line in enumerate(ctx.read(source).splitlines(), 1):
            for match in PATH_REF_RE.finditer(line):
                token = match.group(0).rstrip("`.,;:!?)]}\"'")
                if any(marker in token for marker in skip_markers) or "://" in token:
                    continue
                if token.startswith("~/.claude/"):
                    target = ctx.root / token.removeprefix("~/.claude/")
                elif token.startswith("$HOME/.claude/"):
                    target = ctx.root / token.removeprefix("$HOME/.claude/")
                else:
                    base = skill_directory(ctx, source)
                    if base is None:
                        continue
                    target = base / token
                if not target.exists():
                    message = f"referenced path does not exist: {token}"
                    findings.append(finding("FAIL", "paths-exist", ctx, source, message, line_number))
    return findings

def check_no_scratch(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for base_name in ("skills", "agents"):
        base = ctx.root / base_name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if ctx.ignored(path):
                continue
            scratch_dir = path.is_dir() and fnmatch.fnmatch(path.name, ".run-*")
            scratch_file = path.is_file() and any(
                fnmatch.fnmatch(path.name, pattern) for pattern in SCRATCH_GLOBS
            )
            if scratch_dir or scratch_file:
                findings.append(finding("FAIL", "no-scratch", ctx, path, "scratch artifact found"))
    return findings

def hook_token_path(ctx: Context, token: str) -> Path:
    cleaned = token.rstrip(".,:!?)]}")
    for prefix in ("$HOME/.claude/", "~/.claude/"):
        if cleaned.startswith(prefix):
            return ctx.root / cleaned.removeprefix(prefix)
    return Path(cleaned)

def check_hooks_resolve(ctx: Context) -> list[Finding]:
    settings = ctx.settings()
    if settings is None:
        line, message = ctx._settings_error or (None, "could not read settings.json")
        return [finding("FAIL", "hooks-resolve", ctx, "settings.json", message, line)]
    findings: list[Finding] = []
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return [finding("FAIL", "hooks-resolve", ctx, "settings.json", "hooks must be an object")]
    for event_groups in hooks.values():
        if not isinstance(event_groups, list):
            continue
        for group in event_groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                continue
            for hook in group["hooks"]:
                if not isinstance(hook, dict) or hook.get("type") != "command":
                    continue
                command = hook.get("command")
                if not isinstance(command, str):
                    continue
                match = HOOK_PATH_RE.search(command)
                if match is None:
                    continue
                target = hook_token_path(ctx, match.group(0))
                if not target.is_file() or not os.access(target, os.R_OK):
                    message = f"hook script is missing or unreadable: {match.group(0)}"
                    findings.append(finding("FAIL", "hooks-resolve", ctx, "settings.json", message))
    return findings

def model_sources(ctx: Context) -> list[Path]:
    files = source_markdown(ctx)
    skills = ctx.root / "skills"
    for suffix in ("*.js", "*.sh"):
        files.extend(sorted(skills.glob(f"**/{suffix}")))
    return [path for path in files if path.is_file() and not ctx.ignored(path)]

def check_model_names(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    models = ctx.config.get("models", {})
    canonical = str(models.get("codex_version", "5.6"))
    claude_tiers = {str(tier).lower() for tier in models.get("claude_tiers", [])}
    for source in model_sources(ctx):
        for line_number, line in enumerate(ctx.read(source).splitlines(), 1):
            if HISTORY_RE.search(line):
                continue
            for match in GPT_RE.finditer(line):
                version = f"5.{match.group(1)}"
                if version != canonical:
                    message = f"GPT-{version} does not match canonical GPT-{canonical}"
                    findings.append(finding("FAIL", "model-names", ctx, source, message, line_number))
            for match in CLAUDE_MODEL_RE.finditer(line):
                tier = match.group(1).lower()
                if tier not in claude_tiers:
                    message = f"Claude model tier is not canonical: {tier}"
                    findings.append(finding("FAIL", "model-names", ctx, source, message, line_number))
    return findings

_BRACKET_CLOSERS = {"(": ")", "[": "]", "{": "}"}

def scan_bracket(text: str, opening: int) -> tuple[int | None, list[int]]:
    """Scan text[opening] (one of ``( [ {``) to its matching closer.

    Skips string and template-literal contents (honoring backslash escapes),
    and treats ``${ ... }`` inside a template literal as re-entering code so
    brackets within it are tracked. Returns (close_index, comma_indices) where
    comma_indices are the commas found directly at the opening bracket's own
    depth (i.e. top-level argument/property separators). close_index is None
    if the bracket is never closed.
    """
    stack = [text[opening]]
    commas: list[int] = []
    escaped = False
    index = opening + 1
    length = len(text)
    while index < length:
        char = text[index]
        top = stack[-1]
        if top in ("'", '"', "`"):
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == top:
                stack.pop()
            elif top == "`" and char == "$" and index + 1 < length and text[index + 1] == "{":
                stack.append("${")
                index += 1
            index += 1
            continue
        if char in ("'", '"', "`") or char in "([{":
            stack.append(char)
        elif char in ")]}":
            if top == "${" and char == "}" or top in _BRACKET_CLOSERS and char == _BRACKET_CLOSERS[top]:
                stack.pop()
            if not stack:
                return index, commas
        elif char == "," and len(stack) == 1:
            commas.append(index)
        index += 1
    return None, commas

def has_explicit_model(text: str, opening: int) -> bool:
    close, commas = scan_bracket(text, opening)
    if close is None:
        return False
    bounds = [opening] + commas + [close]
    last_start, last_end = bounds[-2] + 1, bounds[-1]
    argument = text[last_start:last_end].strip()
    if not (argument.startswith("{") and argument.endswith("}")):
        return False
    obj_open = text.index("{", last_start, last_end + 1)
    obj_close, obj_commas = scan_bracket(text, obj_open)
    if obj_close is None:
        return False
    seg_bounds = [obj_open] + obj_commas + [obj_close]
    for start, end in pairwise(seg_bounds):
        segment = text[start + 1 : end].strip()
        if re.match(r"^model\s*:", segment) or segment == "model":
            return True
    return False

def check_explicit_model(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for source in sorted((ctx.root / "skills").glob("**/*.js")):
        if not source.is_file() or ctx.ignored(source):
            continue
        text = ctx.read(source)
        for match in re.finditer(r"(?<![\w])agent\s*\(", text):
            opening = text.find("(", match.start())
            if not has_explicit_model(text, opening):
                line = text.count("\n", 0, match.start()) + 1
                message = "agent() call has no explicit model option"
                findings.append(finding("FAIL", "explicit-model", ctx, source, message, line))
    return findings

def check_builtin_agents(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for source in source_markdown(ctx):
        if source.name == "CLAUDE.md":
            continue
        for number, line in enumerate(ctx.read(source).splitlines(), start=1):
            if not BUILTIN_AGENT_RE.search(line):
                continue
            if any(word in line.lower() for word in BUILTIN_AGENT_NEGATIONS):
                continue
            message = "names a built-in agent type (Explore/general-purpose); use scout or worker so the model is pinned"
            findings.append(finding("FAIL", "builtin-agents", ctx, source, message, number))
    return findings

def frontmatter_parts(text: str) -> tuple[str | None, str, int]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return None, text, 1
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None, text, 1
    return "\n".join(lines[1:end]), "\n".join(lines[end + 1 :]), end + 2

def check_agent_defers(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    maximum = int(ctx.config.get("thresholds", {}).get("agent_max_lines", 60))
    for source in sorted((ctx.root / "agents").glob("*.md")):
        text = ctx.read(source)
        _, body, body_line = frontmatter_parts(text)
        if len(body.splitlines()) <= maximum:
            continue
        match = SKILL_PATH_RE.search(body)
        if match is not None:
            line = body_line + body.count("\n", 0, match.start())
            findings.append(finding(
                "WARN", "agent-defers", ctx, source, "restates skill rules; should defer", line
            ))
    return findings

def expected_code_standards(ctx: Context) -> tuple[str | None, str | None]:
    source = ctx.root / "CLAUDE.md"
    try:
        lines = ctx.read(source).splitlines()
    except FileNotFoundError:
        return None, "CLAUDE.md is missing"
    sections: list[str] = []
    for name in ("Don't", "Comments", "Tests"):
        heading = f"### {name}"
        try:
            start = lines.index(heading)
        except ValueError:
            return None, f'CLAUDE.md lacks the "{name}" section'
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if lines[index].startswith(("### ", "## ")):
                end = index
                break
        sections.append("\n".join(lines[start:end]).rstrip())
    return HEADER + "\n\n".join(sections) + "\n", None

def check_code_standards_sync(ctx: Context) -> list[Finding]:
    expected, error = expected_code_standards(ctx)
    target = ctx.root / "skills/forge/references/code-standards.md"
    if error is not None or expected is None:
        message = error or "cannot generate"
        return [finding("FAIL", "code-standards-sync", ctx, "CLAUDE.md", message)]
    try:
        actual = ctx.read(target)
    except FileNotFoundError:
        actual = None
    if actual == expected:
        return []
    if ctx.fix:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(expected, encoding="utf-8")
        ctx._reads[target] = expected
        return [finding("FIXED", "code-standards-sync", ctx, target, "regenerated from CLAUDE.md")]
    message = "generated code standards are missing" if actual is None else "generated code standards differ"
    return [finding("FAIL", "code-standards-sync", ctx, target, message)]

def strip_claude_only(lines: list[str], sections: list[str], bullets: list[str]) -> list[str]:
    kept: list[str] = []
    skipping_section = False
    skipping_bullet = False
    for line in lines:
        if re.match(r"#{1,2} ", line):
            skipping_section = line[3:].strip() in sections if line.startswith("## ") else False
            skipping_bullet = False
        elif skipping_bullet and (not line.strip() or not line.startswith(" ")):
            skipping_bullet = False
        if skipping_section or skipping_bullet:
            continue
        if line.lstrip().startswith("- ") and any(text in line for text in bullets):
            skipping_bullet = True
            continue
        if not line.strip() and kept and not kept[-1].strip():
            continue
        kept.append(line)
    return kept

def expected_codex_agents(ctx: Context) -> tuple[str | None, str | None]:
    source = ctx.root / "CLAUDE.md"
    try:
        lines = ctx.read(source).splitlines()
    except FileNotFoundError:
        return None, "CLAUDE.md is missing"
    codex = ctx.config.get("codex", {})
    kept = strip_claude_only(
        lines,
        [str(name) for name in codex.get("exclude_sections", [])],
        [str(text) for text in codex.get("exclude_bullets", [])],
    )
    return CODEX_HEADER + "\n".join(kept).strip() + "\n", None

def check_codex_agents_sync(ctx: Context) -> list[Finding]:
    target = ctx.home_path(CODEX_AGENTS_MD)
    expected, error = expected_codex_agents(ctx)
    if error is not None or expected is None:
        return [finding("FAIL", "codex-agents-sync", ctx, "CLAUDE.md", error or "cannot generate")]
    findings: list[Finding] = []
    override = target.with_name("AGENTS.override.md")
    if override.is_file():
        findings.append(finding("WARN", "codex-agents-sync", ctx, override, "shadows the generated AGENTS.md"))
    try:
        actual = ctx.read(target)
    except FileNotFoundError:
        actual = None
    if actual == expected:
        return findings
    if ctx.fix:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(expected, encoding="utf-8")
        ctx._reads[target] = expected
        findings.append(finding("FIXED", "codex-agents-sync", ctx, target, "regenerated from CLAUDE.md"))
        return findings
    message = "generated Codex AGENTS.md is missing" if actual is None else "generated Codex AGENTS.md differs"
    findings.append(finding("FAIL", "codex-agents-sync", ctx, target, message))
    return findings

def check_overrides_exist(ctx: Context) -> list[Finding]:
    settings = ctx.settings()
    if settings is None:
        return []
    overrides = settings.get("skillOverrides", {})
    if not isinstance(overrides, dict):
        return []
    findings: list[Finding] = []
    for name in overrides:
        if not (ctx.root / "skills" / str(name)).is_dir():
            message = f"skill override has no matching skill directory: {name}"
            findings.append(finding("WARN", "overrides-exist", ctx, "settings.json", message))
    return findings

def origin_key(url: str) -> str | None:
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url.strip())
    if match is None:
        return None
    return f"{match.group(1)}/{match.group(2)}"

def check_base_branches(ctx: Context) -> list[Finding]:
    reference = ctx.root / "skills/ship-pr/references/base-branches.json"
    if not reference.exists():
        return []
    try:
        branches = json.loads(ctx.read(reference))
    except json.JSONDecodeError as error:
        message = f"invalid JSON: {error.msg}"
        return [finding("WARN", "base-branches", ctx, reference, message, error.lineno)]
    if not isinstance(branches, dict):
        branches = {}
    findings: list[Finding] = []
    roots = ctx.config.get("repos", {}).get("roots", [])
    for configured in roots:
        repo_root = ctx.home_path(str(configured))
        if not repo_root.is_dir():
            continue
        for repo in sorted(repo_root.iterdir()):
            if not repo.is_dir() or not (repo / ".git").exists():
                continue
            try:
                result = subprocess.run(
                    ["git", "-C", str(repo), "remote", "get-url", "origin"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
            key = origin_key(result.stdout)
            if key is not None and key not in branches:
                message = f"base branch mapping is missing for {key}"
                findings.append(finding("WARN", "base-branches", ctx, str(repo), message))
    return findings

def check_memory_index(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for memory in sorted((ctx.root / "projects").glob("*/memory")):
        if not memory.is_dir():
            continue
        index = memory / "MEMORY.md"
        try:
            index_text = ctx.read(index)
        except FileNotFoundError:
            index_text = ""
        targets = set(MEMORY_LINK_RE.findall(index_text))
        for note in sorted(memory.glob("*.md")):
            if note.name != "MEMORY.md" and note.name not in targets:
                message = "memory file is not linked from MEMORY.md"
                findings.append(finding("WARN", "memory-index", ctx, note, message))
        for target in sorted(targets):
            if not (memory / target).is_file():
                message = f"memory index target does not exist: {target}"
                findings.append(finding("WARN", "memory-index", ctx, index, message))
    return findings

def minimal_frontmatter(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if match is not None:
            parsed[match.group(1)] = match.group(2).strip()
    return parsed

def check_frontmatter(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    sources = [
        (path, ("name", "description", "model"))
        for path in sorted((ctx.root / "agents").glob("*.md"))
    ]
    sources.extend(
        (path, ("name", "description"))
        for path in sorted((ctx.root / "skills").glob("*/SKILL.md"))
    )
    for source, required in sources:
        frontmatter, _, _ = frontmatter_parts(ctx.read(source))
        if frontmatter is None:
            findings.append(finding("FAIL", "frontmatter", ctx, source, "missing YAML frontmatter", 1))
            continue
        if yaml is None:
            parsed = minimal_frontmatter(frontmatter)
        else:
            try:
                parsed = yaml.safe_load(frontmatter)
            except yaml.YAMLError as error:
                findings.append(finding("FAIL", "frontmatter", ctx, source, f"invalid YAML: {error}", 1))
                continue
        if not isinstance(parsed, dict):
            parsed = {}
        missing = [key for key in required if not parsed.get(key)]
        if missing:
            message = f"frontmatter missing required keys: {', '.join(missing)}"
            findings.append(finding("FAIL", "frontmatter", ctx, source, message, 1))
    return findings

CHECKS: list[tuple[str, Check]] = [
    ("paths-exist", check_paths_exist),
    ("no-scratch", check_no_scratch),
    ("hooks-resolve", check_hooks_resolve),
    ("model-names", check_model_names),
    ("explicit-model", check_explicit_model),
    ("builtin-agents", check_builtin_agents),
    ("agent-defers", check_agent_defers),
    ("code-standards-sync", check_code_standards_sync),
    ("codex-agents-sync", check_codex_agents_sync),
    ("overrides-exist", check_overrides_exist),
    ("base-branches", check_base_branches),
    ("memory-index", check_memory_index),
    ("frontmatter", check_frontmatter),
]

def load_config() -> dict[str, Any]:
    config = {
        section: values.copy() if isinstance(values, dict) else values
        for section, values in DEFAULT_CONFIG.items()
    }
    path = Path(__file__).with_name("doctor.toml")
    try:
        with path.open("rb") as file:
            loaded = tomllib.load(file)
    except FileNotFoundError:
        return config
    for section, values in loaded.items():
        if isinstance(values, dict) and isinstance(config.get(section), dict):
            config[section].update(values)
        else:
            config[section] = values
    return config

def run_checks(root: Path, *, fix: bool = False) -> list[Finding]:
    ctx = Context(root=root.expanduser().resolve(), config=load_config(), fix=fix)
    findings: list[Finding] = []
    for name, check in CHECKS:
        result = check(ctx)
        findings.extend(result or [Finding("PASS", name, ".", None, "ok")])
    return findings

def summary(findings: list[Finding]) -> dict[str, int]:
    return {
        "pass": sum(finding.level in {"PASS", "FIXED"} for finding in findings),
        "warn": sum(finding.level == "WARN" for finding in findings),
        "fail": sum(finding.level == "FAIL" for finding in findings),
    }

def print_human(findings: list[Finding], *, quiet: bool) -> None:
    for finding in findings:
        if quiet and finding.level not in {"WARN", "FAIL"}:
            continue
        location = finding.path + (f":{finding.line}" if finding.line is not None else "")
        print(f"{finding.level:<6}  {finding.check:<21}  {location}  {finding.message}")
    counts = summary(findings)
    print(f"SUMMARY  pass={counts['pass']} warn={counts['warn']} fail={counts['fail']}")

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check the health of ~/.claude")
    parser.add_argument("--quiet", action="store_true", help="print only WARN and FAIL findings")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--fix", action="store_true", help="regenerate fixable derived files")
    parser.add_argument("--root", type=Path, default=Path("~/.claude"), help="root directory to check")
    return parser.parse_args(argv)

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        findings = run_checks(args.root, fix=args.fix)
    except (OSError, UnicodeError, TypeError, ValueError, tomllib.TOMLDecodeError) as error:
        print(f"doctor: internal error: {error}", file=sys.stderr)
        return 2
    counts = summary(findings)
    if args.json:
        print(json.dumps({"summary": counts, "findings": [asdict(item) for item in findings]}))
    else:
        print_human(findings, quiet=args.quiet)
    return 1 if counts["fail"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
