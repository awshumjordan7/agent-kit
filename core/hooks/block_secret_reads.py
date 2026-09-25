#!/usr/bin/env python3
"""PreToolUse guard: block tool calls that would read secret files.

Covers Bash (command text) and the path-bearing tools: Read, Grep, Edit,
Write, NotebookEdit, Artifact. Any tool that can put file contents into the
transcript -- or, for Artifact, onto a hosted page -- needs a check here.

The settings.json Read(...) deny rules are enforced in every permission mode,
including bypassPermissions, and block both the Read and Write tools. A deny
rule cannot carve out exceptions (deny beats allow), so the deny list must not
match the ALLOWLIST templates such as .env.example. Bash is covered only by
this hook.

Fail-open by design. Any unexpected input, parse error, or unmatched command
exits 0 (allow). A bug here must never be able to brick the shell -- the cost
is that this is an accident guardrail, not a security boundary. A determined
path around it always exists (see KNOWN GAPS below).

KNOWN GAPS, deliberately not covered:
  - `docker inspect` / `docker exec ... env` can surface container env vars.
    Blocking those would have prevented legitimate diagnostic work.
  - Arbitrary interpreters (`python -c`, `node -e`) with obfuscated paths.
  - In a python or node heredoc body that neither shells out nor evaluates
    code, a path with a space inside a string literal
    (`open('/home/u/My Files/.env')`) reads as prose.
  - Grep patterns and sed/awk scripts are search text, so a non-recursive
    grep, sed or awk of named files outside dot-directories may print lines
    that mention a secret word -- the same text `cat` of those files prints.
  - Reading a secret indirectly: copy to a neutral name first, then read.
Tighten only if the threat model changes; today's goal is preventing careless
credential exposure, not defeating circumvention.

Raw dumps of Playwright traces, HAR files, and auth storage-state files are
blocked separately; scripts/trace-read.py in the forge skill prints a redacted
view of them instead.

Exit codes: 2 = block (stderr is shown to Claude), 0 = allow.
"""

import io
import json
import re
import shlex
import sys
import tokenize
from typing import NamedTuple

# Commands that surface file contents, copy them somewhere readable, or load
# them into the environment.
READERS = (
    r"cat|bat|head|tail|less|more|view|nl|tac|rev|fold|"
    r"strings|xxd|od|hexdump|base64|"
    r"grep|egrep|fgrep|rg|ag|ack|"
    r"awk|sed|cut|sort|uniq|paste|join|comm|"
    r"diff|cmp|jq|yq|"
    r"md5|md5sum|shasum|sha1sum|sha256sum|"
    r"cp|mv|scp|rsync|tar|zip|gzip|tee|"
    r"source|export|eval|"
    r"open|dd"
)

# Commands that print a credential without naming a credential-shaped path,
# so the reader-near-secret checks cannot catch them.
SECRET_COMMANDS = re.compile(
    r"\bsecurity\s+find-(generic|internet)-password|"
    r"\bgh\s+auth\s+token\b|"
    r"\baws\s+configure\s+get\b|"
    r"\bop\s+(item\s+get|read)\b|"
    r"\bvault\s+(read|kv\s+get)\b|"
    r"\bdoppler\s+secrets\b|"
    r"\bheroku\s+config\b",
    re.IGNORECASE,
)

# Path shapes that indicate credential material.
#
# Two subtleties prevent false negatives and false positives:
#   - `.envs?\b` (not `.env\b`) is required to catch a repository's real secrets
#     file, service/.envs/.django -- `.env\b` fails on ".envs" because
#     "v"->"s" is not a word boundary.
#   - The bare-word patterns need trailing \b or they match inside ordinary
#     identifiers: "token" hits "tokenize", "secret" hits "secretary".
SECRET_PATH_SHAPES = (
    r"\.envs?\b|\.env\.|/\.envs?\b|"
    r"\.ssh/|\bid_rsa\b|\bid_ed25519\b|\bid_ecdsa\b|authorized_keys|known_hosts|"
    r"\.aws/|\.gnupg/|\.kube/config|"
    # \bpasswd\b does not catch .pgpass -- these DB client stores need naming.
    r"\.pgpass\b|\.my\.cnf\b|\.mylogin\.cnf\b|\.netrc\b|\.pg_service\.conf\b|"
    # Package/registry auth: the token lives inside, but the path never says so.
    r"\.npmrc\b|\.pypirc\b|\.docker/config\.json|\.git-credentials\b|"
    r"\.tfstate\b|"
    # Shell history routinely contains pasted secrets.
    r"\.bash_history\b|\.zsh_history\b|\.psql_history\b|\.mysql_history\b|"
    r"\.pem\b|\.p12\b|\.pfx\b|\.jks\b|\.keystore\b"
)

# Bare words that name credential material in prose as easily as in a path,
# so they are skipped where the text is likely prose (interpreter heredocs).
SECRET_BARE_WORDS = (
    r"\bcredentials?\b|\bsecrets?\b|\bpasswd\b|\bshadow\b|"
    r"\btokens?\b|\bapi[_-]?keys?\b"
)

# A bare word that is also a file name with a data extension (tokens.txt,
# credentials.json). Checked for reader commands only, never in interpreter
# heredoc bodies, where prose such as "writes credentials.json" is common.
SECRET_FILE_SHAPES = (
    r"(?:\b|_)(?:credentials?|secrets?|tokens?|api[_-]?keys?)[\w-]*"
    r"\.(?:json|ya?ml|txt|ini|toml|cfg|conf|key)\b"
)

# Explicitly fine: sample/template files that carry no real values.
ALLOWLIST = re.compile(
    r"\.env\.example|\.env\.sample|\.env\.template|\.env\.dist|"
    r"secrets?\.md|credentials?\.md|token[_-]?claim|(?<![\w-])token[_-]?info",
    re.IGNORECASE,
)

# Paths the machine's owner has explicitly opted out of the guard for, so that
# read-only prod investigation can use them. Deliberately enumerated rather
# than folded into ALLOWLIST: the broad `secrets?` and `.pgpass` patterns above
# must keep guarding everything they currently guard. Remove this block (and
# the two call sites below) to restore the original behaviour.
AUTHORIZED_PATHS = re.compile(
    r"/\.secrets/|(^|[^\w.])~?/?\.pgpass\b",
    re.IGNORECASE,
)

# The shell "source" shorthand is a dot standing alone between whitespace; a dot inside a file
# name (report_issue.py) is not a reader.
READER_NEAR_SECRET = re.compile(
    rf"(?:\b({READERS})\b|(?<![^\s])\.(?=\s))[^\n]*?({SECRET_PATH_SHAPES})",
    re.IGNORECASE,
)

# Secret-named data files after a reader. Matched against pattern_scan(segment),
# so a quoted grep pattern searched in .md files does not trigger it.
READER_NEAR_SECRET_FILE = re.compile(
    rf"(?:\b({READERS})\b|(?<![^\s])\.(?=\s))[^\n]*?({SECRET_FILE_SHAPES})",
    re.IGNORECASE,
)

# Bare secret words after a reader. Matched against word_scan(segment), not the
# raw segment, so .md file names and quoted prose do not trigger it.
READER_NEAR_SECRET_WORD = re.compile(
    rf"(?:\b({READERS})\b|(?<![^\s])\.(?=\s))[^\n]*?({SECRET_BARE_WORDS})",
    re.IGNORECASE,
)

# Quoted text with a space in it is prose (a report message, a sed script),
# not a path. A quoted single word may still be a path: cat "secrets.yaml".
QUOTED_PROSE = re.compile(r"'[^']*\s[^']*'|\"[^\"]*\s[^\"]*\"")
QUOTED_ANY = re.compile(r"'[^']*'|\"[^\"]*\"")
# A .md name only as a whole path token, so `cat {tokens.txt,x.md}` and
# `cat tokens.txt>x.md` keep their secret-named part.
MD_TOKEN = re.compile(r"(?<![^\s=])[\w./~@+-]*\.md(?=$|[\s;&|)])")
# A grep/sed/awk segment left with only flags and quoted arguments once .md
# names are removed: every target was a .md file, so its quoted pattern is
# search text, not a path.
PATTERN_ONLY = re.compile(
    r"^\s*(?:grep|egrep|fgrep|rg|ag|ack|sed|awk)\b"
    r"(?:\s+(?:-\S+|'[^']*'|\"[^\"]*\"))*\s*(?:>{1,2}\s*)?$"
)

# A double-quoted `$` expansion ("$XDG_CONFIG_HOME/gh/hosts.yml") may be the
# file operand, so a segment holding one is never pattern-only.
QUOTED_EXPANSION = re.compile(r"\"[^\"]*\$[\w{(][^\"]*\"")


def word_scan(segment: str) -> str:
    """Return the segment with prose and .md names blanked for the word check."""
    scan = MD_TOKEN.sub(" ", QUOTED_PROSE.sub(" ", segment))
    pattern_only = PATTERN_ONLY.match(scan) and not QUOTED_EXPANSION.search(scan)
    return QUOTED_ANY.sub(" ", scan) if pattern_only else scan


def pattern_scan(segment: str) -> str:
    """Return the segment with quoted patterns blanked when every target is a .md file.

    Unlike word_scan, quoted prose stays: a quoted path with a space in it is
    still a path for the file-name check.
    """
    scan = MD_TOKEN.sub(" ", segment)
    pattern_only = PATTERN_ONLY.match(scan) and not QUOTED_EXPANSION.search(scan)
    return QUOTED_ANY.sub(" ", scan) if pattern_only else segment


# A redirect out of a secret file, e.g. `< .env` or `while read < .env`.
REDIRECT_FROM_SECRET = re.compile(rf"<\s*[^\s;&|]*({SECRET_PATH_SHAPES})", re.IGNORECASE)
REDIRECT_FROM_SECRET_WORD = re.compile(
    rf"<\s*(?![^\s;&|]*\.md\b)[^\s;&|]*({SECRET_BARE_WORDS})", re.IGNORECASE
)

# Raw dumps of files that hold cookies, auth headers, and typed values: a
# Playwright trace (zipped, or the *.trace / *.network files `unzip -d` leaves),
# a HAR, or an auth storage-state file. Only commands that
# print bytes are blocked; cp, mv, grep, jq, zipinfo, `unzip -l`, and
# `npx playwright show-trace` stay allowed.
RAW_DUMP_COMMAND = re.compile(
    r"^\s*(?:sudo\s+)?(?:"
    r"(?:cat|head|tail|less|more|strings|xxd|od|hexdump|base64|zcat)\b|"
    r"unzip\s+(?:-\S+\s+)*-(?-i:\w*[cp])|"
    r"gunzip\s+(?:-\S+\s+)*-(?-i:\w*c)|"
    r"(?:bsd)?tar\b(?=[^;&|]*\s-(?-i:\w*x))(?=[^;&|]*\s-(?-i:\w*O))"
    r")",
    re.IGNORECASE,
)
# Anchored at the end of a path token so `docker.network.yml` and `strace` do not match.
UNZIPPED_TRACE = r"\.(?:trace|network)(?=$|[\s;&|)'\"])"
RAW_DUMP_TARGET = re.compile(
    rf"trace\.zip|\.har\b|/\.auth/|storage[-_]?state\w*\.json|{UNZIPPED_TRACE}", re.IGNORECASE
)
# `> file` is a write, not a dump, so redirect targets are removed before the path check.
OUTPUT_REDIRECT = re.compile(r">{1,2}\s*[^\s;&|]+")
RAW_DUMP_READ_PATH = re.compile(
    rf"\.har\b|/\.auth/|storage[-_]?state\w*\.json|{UNZIPPED_TRACE}", re.IGNORECASE
)
TRACE_READER = "python3 ~/.claude/skills/forge/scripts/trace-read.py <file>"

# A heredoc opener: `<<` or `<<-`, optional quoting around the terminator word.
# A here-string (`<<<`) and a git conflict marker (`<<<<<<<`) are not openers.
HEREDOC_OPEN = re.compile(r"(?<!<)<<-?(?!<)\s*(['\"]?)(\w+)\1")

# Commands that will actually execute a heredoc body handed to them, as
# opposed to just writing it out or filing it away unread. A shell runs the
# body as commands, so it gets the full scan; an interpreter body is code
# whose string literals are often prose (a STATE.md rewrite), so it is checked
# for path-shaped secrets only. A word counts only as a command word, so
# `/bin/bash` and `x.sh` count while `.env.example` and `--env-file` do not.
HEREDOC_SHELL = re.compile(
    r"(?<![\w-])(?:bash|sh|zsh|dash|ksh\w*|fish|eval|exec|ssh|sudo|xargs|source)\b|"
    r"(?<![\w.-])env(?![\w.-])|"
    r"\$\{?(?:SHELL|BASH)\b",
    re.IGNORECASE,
)
HEREDOC_INTERPRETER = re.compile(r"\b(python3?|node|perl|ruby|php)\b", re.IGNORECASE)
# A heredoc element that closes a group or loop, so the interpreter may sit in
# an earlier element: `{ python3 -; } <<'EOF'`.
GROUP_CLOSE = re.compile(r"\s*(?:[})]|(?:done|fi)\b)")
# Files a heredoc header writes: a `>`/`>>` target (not an fd duplication).
WRITE_TARGET = re.compile(r">{1,2}\|?\s*([^\s;&|<>]+)")
TEE_OPERANDS = re.compile(r"\btee((?:\s+[^\s;&|<>]+)*)")

INTERPRETER_BODY_SECRET = re.compile(SECRET_PATH_SHAPES, re.IGNORECASE)


class Heredocs(NamedTuple):
    """A command split by strip_heredoc_bodies."""

    # The command with interpreter and data bodies removed; shell bodies stay.
    head: str
    # Each interpreter body with the interpreter words of its header.
    interpreter_bodies: list[tuple[str, set[str]]]
    # Data bodies written to a file that the command names again later.
    rerun_bodies: list[str]
    # True when every opener on a header line quotes its terminator.
    quoted: bool


def list_element_spans(line: str) -> list[tuple[int, int]]:
    """Return the spans of a line's list elements, split at unquoted `;`, `&&`, `||` and a lone `&`.

    A pipe does not split: every stage of a pipeline is one element. The `&`
    of a redirection (`2>&1`, `<&3`, `&>file`) does not split.
    """
    spans: list[tuple[int, int]] = []
    start, quote = 0, None
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == "\\" and quote != "'":
            i += 2
            continue
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif line.startswith(("&&", "||"), i):
            spans.append((start, i))
            i += 2
            start = i
            continue
        elif c == ";" or (c == "&" and line[i - 1 : i] not in ("<", ">") and line[i + 1 : i + 2] != ">"):
            spans.append((start, i))
            i += 1
            start = i
            continue
        i += 1
    spans.append((start, n))
    return spans


def _written_files(element: str) -> list[str]:
    """Return the files a heredoc header element writes: `>` targets and `tee` operands."""
    files = [m.group(1) for m in WRITE_TARGET.finditer(element)]
    for m in TEE_OPERANDS.finditer(element):
        files += [word for word in m.group(1).split() if not word.startswith("-")]
    return [f.strip("'\"") for f in files if f.strip("'\"") not in ("", "/dev/null")]


def _named_again(files: list[str], later: str) -> bool:
    """Return True when a written file's base name, or its stem as a whole word, appears in later text."""
    for path in files:
        base = path.rstrip("/").rpartition("/")[2]
        stem = base.rpartition(".")[0] or base
        if base and (base in later or re.search(rf"(?<!\w){re.escape(stem)}(?!\w)", later)):
            return True
    return False


def strip_heredoc_bodies(command: str) -> Heredocs:
    """Drop heredoc body lines that are inert data instead of executed code.

    Scans line by line: a line matching HEREDOC_OPEN opens a heredoc whose
    body runs to the first line equal to the terminator (leading tabs allowed
    when the opener is `<<-`). If the header line (the whole line, every
    pipeline stage) names a shell -- bash, eval, ssh, sudo, source, and the
    like -- the body is kept in the head for the full scan. If an interpreter
    -- python3, node, perl, ruby, php -- appears in the header's list element
    that holds the `<<`, or in a later element, the body is removed from the
    head and returned separately, with those interpreter words, for the
    path-only check; earlier elements count only when the `<<` element closes
    a group or loop (`{ python3 -; } <<'EOF'`). Otherwise the body is dropped
    as data, and also returned when the file it is written to is named again
    later in the command. Several heredocs in one command are handled in
    order, and an unterminated heredoc runs to end of text under the same rule.
    """
    lines = command.split("\n")
    out: list[str] = []
    interpreter_bodies: list[tuple[str, set[str]]] = []
    rerun_bodies: list[str] = []
    quoted = True
    i, n = 0, len(lines)
    while i < n:
        header = lines[i]
        out.append(header)
        match = HEREDOC_OPEN.search(header)
        if not match:
            i += 1
            continue
        quoted = quoted and bool(match.group(1))
        terminator = match.group(2)
        strip_tabs = match.group(0).startswith("<<-")
        shell = bool(HEREDOC_SHELL.search(header))
        spans = list_element_spans(header)
        start, end = next(((s, e) for s, e in spans if s <= match.start() < e), spans[-1])
        own = header[start:end]
        counted = header if GROUP_CLOSE.match(own) else header[start:]
        words = set() if shell else {w.lower().rstrip("3") for w in HEREDOC_INTERPRETER.findall(counted)}
        j = i + 1
        while j < n:
            candidate = lines[j].lstrip("\t") if strip_tabs else lines[j]
            if candidate == terminator:
                break
            j += 1
        body = lines[i + 1 : j + 1] if j < n else lines[i + 1 : n]
        if shell:
            out.extend(body)
        elif words:
            interpreter_bodies.append(("\n".join(body), words))
        elif _named_again(_written_files(own), header[match.end() :] + "\n" + "\n".join(lines[j + 1 :])):
            rerun_bodies.append("\n".join(body))
        i = j + 1
    return Heredocs("\n".join(out), interpreter_bodies, rerun_bodies, quoted)


def matched(rule: str, text: str) -> str:
    """Name the rule and the command text it matched, never a file or variable value."""
    fragment = " ".join(text.split())[:80]
    return f"(rule {rule}, matched `{fragment}`)"


class Hit(NamedTuple):
    """Why a secret read is blocked: the reason, rule, matched text, and its segment or path."""

    reason: str
    rule: str
    fragment: str
    context: str


def split_segments(command: str, piped: list[bool] | None = None) -> list[str]:
    """Split a command on unquoted `&&`, `||`, `|`, `;`, a lone `&`, and newlines.

    Each segment keeps its raw text, quotes included. Quote state resets at
    every newline, so an unbalanced quote on one line (`echo it's`) cannot
    hide the next line; a backslash-newline continues the line. The `&` of a
    redirection (`2>&1`, `<&3`, `&>file`) does not split. When `piped` is
    given, it gets one entry per segment: True when a single `|` ends it.
    """
    segments: list[str] = []
    buf: list[str] = []
    quote = None
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if c == "\n":
            segments.append("".join(buf))
            if piped is not None:
                piped.append(False)
            buf, quote = [], None
            i += 1
            continue
        if c == "\\" and quote != "'" and i + 1 < n:
            # The shell deletes a backslash-newline, joining the two lines.
            if command[i + 1] != "\n":
                buf.append(command[i : i + 2])
            i += 2
            continue
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c in ";|" or (c == "&" and command[i - 1 : i] not in ("<", ">") and command[i + 1 : i + 2] != ">"):
            segments.append("".join(buf))
            if piped is not None:
                piped.append(c == "|" and command[i + 1 : i + 2] != "|")
            buf = []
            i += 2 if c in "|&" and command[i + 1 : i + 2] == c else 1
            continue
        buf.append(c)
        i += 1
    segments.append("".join(buf))
    if piped is not None:
        piped.append(False)
    return segments


def _quote_end(text: str, i: int) -> int | None:
    """Return the index just past the quote that closes the one at text[i], or None."""
    quote, j, n = text[i], i + 1, len(text)
    while j < n:
        if text[j] == "\\" and quote == '"':
            j += 2
            continue
        if text[j] == quote:
            return j + 1
        j += 1
    return None


def blank_quoted(text: str, kinds: str) -> str:
    """Blank closed quoted spans whose quote character is in kinds.

    Quote-aware: a `'` inside double quotes is literal. An unclosed quote
    leaves the rest of the text as it is.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            out.append(text[i : i + 2])
            i += 2
            continue
        if c in "'\"":
            end = _quote_end(text, i)
            if end is None:
                out.append(text[i:])
                break
            out.append(" " if c in kinds else text[i:end])
            i = end
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _word_end(text: str, i: int) -> int:
    """Return the index just past the shell word that starts at text[i]."""
    quote, n = None, len(text)
    while i < n:
        c = text[i]
        if c == "\\" and quote != "'":
            i += 2
            continue
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c.isspace() or c in "<>":
            break
        i += 1
    return min(i, n)


def strip_redirections(segment: str, output_only: bool = False) -> str:
    """Remove unquoted redirections, operator and target, from one segment.

    `N>&M`, `>&M` and `N>&-` are complete on their own; every other operator
    (`>`, `>>`, `<`, `N>`, `&>`, `&>>`, a fused `2>err`) also drops its
    target word. A quoted `'>'` or an escaped `\\>` is an argument, not a
    redirection. With output_only, input redirections, here-strings and
    process substitution (`>(...)`) stay in the text.
    """
    out: list[str] = []
    quote = None
    i, n = 0, len(segment)
    while i < n:
        c = segment[i]
        if c == "\\" and quote != "'":
            out.append(segment[i : i + 2])
            i += 2
            continue
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif output_only and c == "<":
            # `<>` opens a file for reading too, so its target stays.
            while i < n and segment[i] in "<>":
                out.append(segment[i])
                i += 1
            continue
        elif output_only and segment.startswith(">(", i):
            pass
        elif c in "<>" or (c == "&" and segment.startswith(">", i + 1)):
            j = len(out)
            while j and out[j - 1].isdigit():
                j -= 1
            if j < len(out) and (j == 0 or out[j - 1].isspace()):
                del out[j:]
            if c == "&":
                i += 1
            while i < n and segment[i] in "<>":
                i += 1
            if segment.startswith("&", i):
                i += 1
                if i < n and (segment[i].isdigit() or segment[i] == "-"):
                    while i < n and (segment[i].isdigit() or segment[i] == "-"):
                        i += 1
                    out.append(" ")
                    continue
            while i < n and segment[i] in " \t":
                i += 1
            i = _word_end(segment, i)
            out.append(" ")
            continue
        out.append(c)
        i += 1
    return "".join(out)


class OptionTable(NamedTuple):
    """Every option one reader command accepts; any other option skips the parse.

    Only options that always take a value go in the value sets: a wrong entry
    would swallow a real file operand as its value.
    """

    short_values: set[str]
    short_flags: set[str]
    long_values: set[str]
    long_flags: set[str]
    numeric_short: set[str]


# GNU grep. `--color`/`--colour` take a value only as `--color=WHEN`.
_GREP_OPTS = OptionTable(
    set("efmABCdD"),
    set("EFGPiyvwxcLloqsbHhnTZzaIrRUuV0123456789"),
    {
        "regexp", "file", "max-count", "after-context", "before-context", "context", "directories", "devices",
        "include", "exclude", "exclude-from", "exclude-dir", "label", "binary-files", "group-separator",
    },
    {
        "extended-regexp", "fixed-strings", "basic-regexp", "perl-regexp", "ignore-case", "no-ignore-case",
        "word-regexp", "line-regexp", "null-data", "no-messages", "invert-match", "version", "help",
        "byte-offset", "line-number", "line-buffered", "with-filename", "no-filename", "only-matching",
        "quiet", "silent", "text", "recursive", "dereference-recursive", "files-without-match",
        "files-with-matches", "count", "initial-tab", "null", "no-group-separator", "color", "colour",
        "binary", "unix-byte-offsets",
    },
    set("ABCm"),
)
# git grep, without -O/--open-files-in-pager, which runs a program on each match.
_GIT_GREP_NEGATABLE = {
    "cached", "untracked", "exclude-standard", "recurse-submodules", "invert-match", "ignore-case",
    "word-regexp", "text", "textconv", "recursive", "extended-regexp", "basic-regexp", "fixed-strings",
    "perl-regexp", "line-number", "column", "full-name", "files-with-matches", "name-only",
    "files-without-match", "null", "only-matching", "count", "color", "break", "heading", "show-function",
    "function-context", "quiet", "all-match", "ext-grep", "index",
}
_GIT_GREP_OPTS = OptionTable(
    set("ABCefm"),
    set("viwaIrEGFPnhHlLzocpWq0123456789"),
    {"max-depth", "context", "before-context", "after-context", "threads", "max-count"},
    _GIT_GREP_NEGATABLE | {f"no-{name}" for name in _GIT_GREP_NEGATABLE} | {"and", "or", "not"},
    set("ABCm"),
)
READER_OPTS = {
    "grep": _GREP_OPTS,
    "egrep": _GREP_OPTS,
    "fgrep": _GREP_OPTS,
    "git grep": _GIT_GREP_OPTS,
    # GNU sed; -i is parsed separately for its fused or empty suffix.
    "sed": OptionTable(
        set("efl"),
        set("nErsuz"),
        {"expression", "file", "line-length"},
        {
            "quiet", "silent", "debug", "follow-symlinks", "in-place", "posix", "regexp-extended",
            "separate", "sandbox", "unbuffered", "null-data", "help", "version",
        },
        set(),
    ),
    # POSIX awk.
    "awk": OptionTable(set("Fvf"), set(), set(), set(), set()),
}
# A numeric option consumes the next token only when it is all digits.
NUMERIC_LONG_OPTS = {"max-count", "after-context", "before-context", "context", "threads", "max-depth"}
ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
# The xargs options that can precede `grep`; any other, `-a`/`--arg-file`
# included, skips the parse.
XARGS_OPTS = OptionTable(
    set("nLPsdIE"),
    set("0rtpx"),
    {"max-args", "max-lines", "max-procs", "max-chars", "delimiter", "replace", "eof"},
    {"null", "no-run-if-empty", "verbose", "interactive", "exit"},
    set(),
)
GREP_COMMANDS = ("grep", "egrep", "fgrep")
# Output limited to file names or counts prints no matched line.
NAMES_ONLY_OPTS = {
    "grep": {"-l", "-L", "-c", "-q", "--files-with-matches", "--files-without-match", "--count", "--quiet", "--silent"},
    "git grep": {
        "-l", "-L", "-c", "-q", "--files-with-matches", "--files-without-match", "--name-only", "--count", "--quiet",
    },
}
# An --include glob for one of these extensions reaches source and docs, not
# env or credential files.
CODE_EXTENSION = re.compile(
    r"md|py|js|mjs|cjs|ts|tsx|jsx|go|rs|rb|java|kt|swift|c|h|cc|cpp|hpp|cs|php|html|css|scss|vue|svelte",
    re.IGNORECASE,
)
GLOB_CHARS = re.compile(r"[*?\[]")


class ReaderArgs(NamedTuple):
    """A grep/git grep/sed/awk call split into options, patterns (or scripts), and file operands."""

    family: str
    options: list[tuple[str, str]]
    patterns: list[str]
    files: list[str]
    # True for `xargs grep`, whose file list comes from stdin.
    stdin_files: bool = False


def _skip_xargs_options(tokens: list[str]) -> list[str] | None:
    """Return the tokens after xargs's options, or None when an option is not in XARGS_OPTS."""
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--":
            return tokens[i + 1 :]
        if not token.startswith("-") or token == "-":
            return tokens[i:]
        i += 1
        if token.startswith("--"):
            name, eq, _ = token[2:].partition("=")
            if name in XARGS_OPTS.long_values:
                i += 0 if eq else 1
            elif name not in XARGS_OPTS.long_flags:
                return None
            continue
        for j, flag in enumerate(token[1:], start=2):
            if flag in XARGS_OPTS.short_values:
                i += 1 if j == len(token) else 0
                break
            if flag not in XARGS_OPTS.short_flags:
                return None
    return []


def parse_reader(raw: str) -> ReaderArgs | None:
    """Parse a grep, egrep, fgrep, git grep, sed, awk, or `xargs grep` segment into its arguments.

    Returns None when the segment is another command, when it holds command
    or process substitution, when its quotes do not balance, or when it uses
    an option missing from the command's table (an abbreviated long option
    included); the caller then applies the text checks instead. Leading
    `NAME=value` assignments are skipped before grep and xargs only.
    """
    if any(s in raw for s in ("$(", "`", "<(", ">(")):
        return None
    try:
        tokens = shlex.split(strip_redirections(raw))
    except ValueError:
        return None
    k = 0
    while k < len(tokens) and ASSIGNMENT.match(tokens[k]):
        k += 1
    if k and (k == len(tokens) or tokens[k] not in GREP_COMMANDS + ("xargs",)):
        return None
    tokens = tokens[k:]
    stdin_files = tokens[:1] == ["xargs"]
    if stdin_files:
        tokens = _skip_xargs_options(tokens[1:])
        if not tokens or tokens[0] not in GREP_COMMANDS:
            return None
    if tokens[:2] == ["git", "grep"]:
        tokens = ["git grep"] + tokens[2:]
    if not tokens or tokens[0] not in READER_OPTS:
        return None
    command = tokens[0]
    table = READER_OPTS[command]
    options: list[tuple[str, str]] = []
    positionals: list[str] = []
    i = 1
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if token == "--":
            positionals.extend(tokens[i:])
            break
        if token.startswith("--"):
            name, eq, value = token.partition("=")
            if name[2:] in table.long_values:
                numeric = name[2:] in NUMERIC_LONG_OPTS
                if not eq and i < len(tokens) and (not numeric or tokens[i].isdigit()):
                    value = tokens[i]
                    i += 1
            elif name[2:] not in table.long_flags:
                return None
            options.append((name, value))
            continue
        if not token.startswith("-") or token == "-":
            positionals.append(token)
            continue
        j = 1
        while j < len(token):
            flag = token[j]
            j += 1
            if command == "sed" and flag == "i":
                # GNU `-i.bak` fuses the suffix; BSD `-i ''` passes an empty one.
                if j == len(token) and i < len(tokens) and tokens[i] == "":
                    i += 1
                options.append(("-i", token[j:]))
                break
            if flag in table.short_values:
                value = token[j:]
                if not value and i < len(tokens) and (flag not in table.numeric_short or tokens[i].isdigit()):
                    value = tokens[i]
                    i += 1
                options.append((f"-{flag}", value))
                break
            if flag not in table.short_flags:
                return None
            options.append((f"-{flag}", ""))
    names = {name for name, _ in options}
    if names & {"-e", "--regexp", "--expression", "-f", "--file"}:
        patterns = [value for name, value in options if name in ("-e", "--regexp", "--expression")]
        files = positionals
    else:
        patterns, files = positionals[:1], positionals[1:]
    if command == "awk":
        # An assignment's value can name the file a getline reads: `f=.env`.
        files = [ASSIGNMENT.sub("", f) for f in files]
    family = "grep" if command in ("egrep", "fgrep") else command
    return ReaderArgs(family, options, patterns, files, stdin_files)


def _narrow_glob(glob: str) -> bool:
    """Return True when an include glob names one source or docs extension, such as `*.py`."""
    extension = glob.rpartition(".")[2] if "." in glob else ""
    return bool(CODE_EXTENSION.fullmatch(extension))


def _code_file(path: str) -> bool:
    """Return True when a path's last part ends in a literal source or docs extension.

    For example `$R/app.py`.
    """
    name = path.rpartition("/")[2]
    return "." in name and bool(CODE_EXTENSION.fullmatch(name.rpartition(".")[2]))


def has_dot_part(path: str) -> bool:
    """Return True when a path has a part that starts with `.`, other than `.` or `..`."""
    return any(part.startswith(".") and part not in (".", "..") for part in path.strip("'\"").split("/"))


def _secret_word_hit(patterns: list[str], raw: str) -> Hit | None:
    """Return a hit for the first pattern or script that names a secret word."""
    for pattern in patterns:
        if re.search(SECRET_BARE_WORDS, pattern, re.IGNORECASE) or UPPER_SECRET_VAR.search(pattern):
            return Hit(
                "searches every file, secret files included, for a secret word",
                "recursive-grep-secret-word",
                pattern,
                raw,
            )
    return None


def reader_verdict(args: ReaderArgs, raw: str) -> Hit | None:
    """Check the file operands and scripts of a parsed grep/git grep/sed/awk call.

    A grep pattern is search text and is never checked as a path. A broad
    search (recursive, every git grep, `xargs grep`, or a shell glob) for a secret word
    still blocks, since it prints matching lines from every secret file it
    reaches. A pattern with whitespace still counts: `"token: "` matches
    `oauth_token: <value>` lines.
    """
    family, options = args.family, args.options
    includes = [value for name, value in options if family == "grep" and name == "--include"]
    read_paths = args.files + [value for name, value in options if name in ("-f", "--file")] + includes
    read_paths += [value.partition("=")[2] for name, value in options if family == "awk" and name == "-v"]
    for path in read_paths:
        # SECRET_BARE_WORDS misses `service_credentials.json`: `_` defeats its \b.
        file_shape = re.search(SECRET_FILE_SHAPES, ALLOWLIST.sub(" ", path), re.IGNORECASE)
        if secret_path_hit(path) or (file_shape and not AUTHORIZED_PATHS.search(path)):
            return Hit("reads a credential-bearing path", "reader-operand", path, raw)
    glob = any(GLOB_CHARS.search(f) for f in args.files)
    all_md = not args.stdin_files and bool(args.files) and all(f.lower().endswith(".md") for f in args.files)
    if family in ("sed", "awk"):
        # `sed 'r FILE'`, GNU `sed e`, and awk `getline < FILE` read files.
        for script in args.patterns:
            if m := re.search(SECRET_PATH_SHAPES, ALLOWLIST.sub(" ", script), re.IGNORECASE):
                return Hit("runs a script that reads a credential-bearing path", "reader-script", m.group(0), raw)
        return _secret_word_hit(args.patterns, raw) if glob and not all_md else None
    names = {name for name, _ in options}
    shorts = "".join(name[1] for name, _ in options if len(name) == 2)
    # git grep recurses, and --no-index or --untracked reach ignored files.
    broad = (
        family == "git grep"
        or args.stdin_files
        or bool(set("rR") & set(shorts))
        or bool(names & {"--recursive", "--dereference-recursive"})
        # GNU grep accepts any unambiguous prefix: `-d rec`.
        or any(name in ("-d", "--directories") and value and "recurse".startswith(value) for name, value in options)
        or glob
    )
    if not broad or names & NAMES_ONLY_OPTS[family] or all_md:
        return None
    if includes and all(_narrow_glob(include) for include in includes):
        return None
    return _secret_word_hit(args.patterns, raw)


# Commands whose quoted arguments are text to print or store (a report
# message, a commit message), not code to run. Other git and gh forms can run
# their text as shell code (`git submodule foreach`, `gh alias set --shell`).
MESSENGER_COMMANDS = {"echo", "printf"}
TEXT_ONLY_GIT = re.compile(r"(?:git\s+(?:commit|tag|notes)|gh\s+(?:pr|issue|release)\s+(?:create|comment|edit))\b")
SCRIPT_INTERPRETERS = {"python", "python3", "node", "ruby", "perl"}
SCRIPT_FILE = re.compile(r"\.(?:py|js|mjs|cjs|rb|pl)$")


def is_messenger(raw: str) -> bool:
    """Return True when a segment's quoted prose is a message, not a command.

    Command substitution runs even inside double quotes, so a segment with
    `$(`, a backtick, `<(`, or `>(` is never a messenger.
    """
    if any(s in raw for s in ("$(", "`", "<(", ">(")):
        return False
    words = raw.split()
    if not words:
        return False
    if words[0] in MESSENGER_COMMANDS or words[0].endswith(".py") or TEXT_ONLY_GIT.match(raw.lstrip()):
        return True
    return words[0] in SCRIPT_INTERPRETERS and len(words) > 1 and bool(SCRIPT_FILE.search(words[1]))


# Commands that never run their input or arguments as code, so a message
# piped into them or printed beside them stays text.
QUIET_COMMANDS = {
    "head", "tail", "grep", "egrep", "fgrep", "wc", "cut", "uniq", "tr", "jq", "cat", "column",
    "nl", "echo", "printf", "true", "cd",
}
# An output redirection and its target; `&` marks an fd duplication (`2>&1`).
OUTPUT_REDIRECT_ANY = re.compile(r">{1,2}\|?(&)?\s*([^\s;&|<>()]*)")


def is_quiet(command: str) -> bool:
    """Return True when nothing in a command can run a messenger's text as code.

    A quiet command has no substitution anywhere, quoted or not; no output
    redirection other than an fd duplication or `/dev/null`, since a written
    file can be run later; and at most one segment that is not a
    QUIET_COMMANDS command, which must be a messenger.
    """
    if any(s in command for s in ("$(", "`", "<(", ">(")):
        return False
    for m in OUTPUT_REDIRECT_ANY.finditer(blank_quoted(command, "'\"")):
        fd_dup = m.group(1) and re.fullmatch(r"\d+|-", m.group(2))
        if not fd_dup and m.group(2) != "/dev/null":
            return False
    others = [s for s in split_segments(command) if s.split() and s.split()[0] not in QUIET_COMMANDS]
    return len(others) <= 1 and all(is_messenger(s) for s in others)


# Code in an interpreter heredoc body that hands text to a shell or evaluates
# it, so its string literals are commands, not prose. No leading \b, so
# `posix_spawnp(` and `create_subprocess_shell` count. Case-sensitive: an
# IGNORECASE `Function(` would match every JavaScript `function (`.
SHELL_OUT = re.compile(
    r"os\.system|os\.popen|subprocess|child_process|"
    r"(?:spawn\w*|popen\w*|execSync|execFile\w*|system|exec\w*|eval|shell_exec|passthru|proc_open)\s*\(|"
    r"\bFunction\s*\(|\bvm\.run\w*"
)
PYTHON_SHELL_OUT = re.compile(r"\bfrom\s+(?:os|posix|pty|subprocess)\s+import\b|\bgetattr\s*\(")
# Two-argument `open(F, "< .env")` and backticks make any literal in these
# languages a possible command.
ALWAYS_SHELL_OUT = {"perl", "ruby", "php"}


def shells_out(body: str, words: set[str]) -> bool:
    """Return True when an interpreter body may run its string literals as code."""
    if words & ALWAYS_SHELL_OUT:
        return True
    return bool(SHELL_OUT.search(body) or ("python" in words and PYTHON_SHELL_OUT.search(body)))


_PY_MIDDLE = {getattr(tokenize, t) for t in ("FSTRING_MIDDLE", "TSTRING_MIDDLE") if hasattr(tokenize, t)}
_PY_NOT_CODE = {tokenize.COMMENT} | {
    getattr(tokenize, t) for t in ("FSTRING_START", "FSTRING_END", "TSTRING_START", "TSTRING_END") if hasattr(tokenize, t)
}


def _format_fields(inner: str) -> tuple[str, list[str]]:
    """Split f-string text into its literal text and the code of its `{...}` fields."""
    rest: list[str] = []
    fields: list[str] = []
    i, n = 0, len(inner)
    while i < n:
        if inner.startswith(("{{", "}}"), i):
            rest.append(inner[i])
            i += 2
            continue
        if inner[i] == "{":
            depth, j = 1, i + 1
            while j < n and depth:
                depth += {"{": 1, "}": -1}.get(inner[j], 0)
                j += 1
            fields.append(inner[i + 1 : j - 1] if depth == 0 else inner[i + 1 :])
            i = j
            continue
        rest.append(inner[i])
        i += 1
    return "".join(rest), fields


def _python_parts(body: str) -> tuple[str, list[str]] | None:
    """Split a Python body into code (comments dropped) and string literal texts.

    Returns None when the body does not tokenize. Adjacent code tokens are
    joined without a space, so `process.env.X`-style text keeps its shape.
    """
    code: list[str] = []
    literals: list[str] = []
    prev_end = None
    try:
        for tok in tokenize.generate_tokens(io.StringIO(body).readline):
            text = None
            if tok.type == tokenize.STRING:
                prefix = re.match(r"[A-Za-z]*", tok.string).group(0)
                quote = 3 if tok.string[len(prefix) : len(prefix) + 3] in ('"""', "'''") else 1
                inner = tok.string[len(prefix) + quote : len(tok.string) - quote]
                if re.search(r"[fFtT]", prefix):
                    # Before Python 3.12 an f-string is one STRING token.
                    inner, fields = _format_fields(inner)
                    code.extend(f" {field} " for field in fields)
                literals.append(inner)
            elif tok.type in _PY_MIDDLE:
                literals.append(tok.string)
            elif tok.type not in _PY_NOT_CODE:
                text = tok.string
            if text is None:
                code.append(" ")
            else:
                code.append(text if tok.start == prev_end else " " + text)
            prev_end = tok.end
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return None
    return "".join(code), literals


def _node_parts(body: str) -> tuple[str, list[str]]:
    """Split a node body into code (comments dropped) and string literal texts.

    `'...'` and `"..."` end at a newline, so an apostrophe in text cannot
    hide later lines; a backtick template may span lines. The code of a
    template's `${...}` fields stays in the code. An unclosed literal stays code.
    A `//` or `/*` after code on its line may sit in a regex literal
    (`/[//]/`, `/[/*]/`), so the rest of that line stays code rather than
    being dropped as a comment.
    """
    code: list[str] = []
    literals: list[str] = []
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if body.startswith(("//", "/*"), i) and body[body.rfind("\n", 0, i) + 1 : i].strip():
            j = body.find("\n", i)
            j = n if j < 0 else j
            code.append(body[i:j])
            i = j
            continue
        if body.startswith("//", i):
            j = body.find("\n", i)
            i = n if j < 0 else j
            code.append(" ")
            continue
        if body.startswith("/*", i):
            j = body.find("*/", i + 2)
            i = n if j < 0 else j + 2
            code.append(" ")
            continue
        if c in "'\"":
            j = i + 1
            while j < n and body[j] not in (c, "\n"):
                j += 2 if body[j] == "\\" else 1
            if j < n and body[j] == c:
                literals.append(body[i + 1 : j])
                code.append(" ")
                i = j + 1
            else:
                code.append(body[i:j])
                i = j
            continue
        if c == "`":
            j = i + 1
            text: list[str] = []
            while j < n and body[j] != "`":
                if body[j] == "\\":
                    text.append(body[j : j + 2])
                    j += 2
                elif body.startswith("${", j):
                    k, depth = j + 2, 1
                    while k < n and depth:
                        depth += {"{": 1, "}": -1}.get(body[k], 0)
                        k += 1
                    code.append(f" {body[j + 2 : k - 1 if depth == 0 else k]} ")
                    j = k
                else:
                    text.append(body[j])
                    j += 1
            if j >= n:
                code.append(body[i:])
                break
            literals.append("".join(text))
            code.append(" ")
            i = j + 1
            continue
        code.append(c)
        i += 1
    return "".join(code), literals


def interpreter_body_scans(body: str, words: set[str]) -> list[str]:
    """Return the texts of an interpreter body to search for secret path shapes.

    A body that shells out, mixes languages, or does not tokenize is searched
    whole. Otherwise its code is searched, and each string literal without
    whitespace, which may be a path; a literal with whitespace is prose.
    """
    parts = None
    if not shells_out(body, words):
        if words == {"python"}:
            parts = _python_parts(body)
        elif words == {"node"}:
            parts = _node_parts(body)
    if parts is None:
        return [body]
    code, literals = parts
    return [code] + [literal for literal in literals if not re.search(r"\s", literal)]


def secret_path_hit(path: str) -> tuple[str, str] | None:
    """Return (rule, matched text) when a path names credential material, else None.

    ALLOWLIST names are blanked, not exempted, so a token-info file under
    ~/.aws/ still blocks. AUTHORIZED_PATHS exempts the whole path: its
    `/.secrets/` directory form covers every file below it.
    """
    if AUTHORIZED_PATHS.search(path):
        return None
    scan = ALLOWLIST.sub(" ", path)
    if m := re.search(SECRET_PATH_SHAPES, scan, re.IGNORECASE):
        return "secret-path", m.group(0)
    if not path.lower().endswith(".md") and (m := re.search(SECRET_BARE_WORDS, scan, re.IGNORECASE)):
        return "secret-word", m.group(0)
    return None


CD_TARGET = re.compile(r"[\s({]*(?:cd|pushd)\s+(.*)")
# `--exclude`, `--exclude-from` and `--exclude-dir` with their value, as
# `=value` or the next word. `--exclude-vcs` takes no value and stays.
_OPTION_VALUE = r"""(?:'[^']*'|"[^"]*"|\\.|[^\s'"\\])+"""
EXCLUDE_OPTION = re.compile(rf"(?<!\S)--exclude(?:-from|-dir)?(?:=|\s+){_OPTION_VALUE}")


# Heredoc bodies are data unless a shell or interpreter on the header line
# will execute them; strip_heredoc_bodies() applies that split before
# segments are checked below.
def verdict(command: str) -> Hit | None:
    """Return why to block a command, or None to allow."""
    heredocs = strip_heredoc_bodies(command)
    command = heredocs.head
    for body, words in heredocs.interpreter_bodies:
        for scan in interpreter_body_scans(body, words):
            scan = AUTHORIZED_PATHS.sub(" ", ALLOWLIST.sub(" ", scan))
            if m := INTERPRETER_BODY_SECRET.search(scan):
                return Hit(
                    "runs code that names a credential-bearing path", "interpreter-body-secret", m.group(0), body
                )
    piped: list[bool] = []
    segments = split_segments(command, piped)
    # Any other command may run a messenger's text: `echo "..." | bash`.
    messengers = is_quiet(command)
    # A search after `cd ~/.config/gh` reads a dot-directory like a search
    # that names it.
    dot_cd = False
    # Evaluate each pipeline/list segment separately so one safe segment in a
    # compound command cannot mask an unsafe one.
    for raw, feeds_pipe in zip(segments, piped):
        if cd := CD_TARGET.match(raw):
            dot_cd = dot_cd or any(has_dot_part(word) for word in cd.group(1).split())
        # Blank out only the allowlisted paths, never the whole segment:
        # `diff .env .env.example` reads the real file and must still block.
        segment = AUTHORIZED_PATHS.sub(" ", ALLOWLIST.sub(" ", raw))
        if not segment.strip():
            continue
        if m := SECRET_COMMANDS.search(segment):
            return Hit("prints a stored credential", "secret-command", m.group(0), raw)
        # Tokenized from the raw segment: allowlist blanking must not shift
        # which token is the pattern.
        if (reader := parse_reader(raw)) is not None:
            if hit := reader_verdict(reader, raw):
                return hit
            # A dot-directory (~/.config/gh/hosts.yml) or a variable operand
            # may hold credentials, so a secret word in the pattern still blocks.
            # A variable operand with a literal source extension ($R/app.py) is
            # a source file. Names-only output (-l, -c) prints no line unless a
            # pipe hands the names on: `grep -l token ~/.config/gh/* | xargs cat`.
            dotted = dot_cd or any(
                has_dot_part(f) or ("$" in f and not _code_file(f)) for f in reader.files
            )
            names_only = {name for name, _ in reader.options} & NAMES_ONLY_OPTS.get(
                reader.family, set()
            )
            word = READER_NEAR_SECRET_WORD.search(word_scan(segment))
            if dotted and (feeds_pipe or not names_only) and (m := word):
                return Hit("reads a credential-bearing path", "reader-near-secret-word", m.group(0), raw)
        else:
            # A file the command writes or excludes is not read.
            reader_text = EXCLUDE_OPTION.sub(" ", strip_redirections(segment, output_only=True))
            scan = QUOTED_PROSE.sub(" ", reader_text) if messengers and is_messenger(raw) else reader_text
            if m := READER_NEAR_SECRET.search(scan):
                return Hit("reads a credential-bearing path", "reader-near-secret", m.group(0), raw)
            if m := READER_NEAR_SECRET_FILE.search(pattern_scan(scan)):
                return Hit("reads a credential-bearing path", "reader-near-secret-file", m.group(0), raw)
            if m := READER_NEAR_SECRET_WORD.search(word_scan(reader_text)):
                return Hit("reads a credential-bearing path", "reader-near-secret-word", m.group(0), raw)
        if m := REDIRECT_FROM_SECRET.search(segment):
            return Hit("redirects input from a credential-bearing path", "redirect-from-secret", m.group(0), raw)
        if m := REDIRECT_FROM_SECRET_WORD.search(segment):
            return Hit("redirects input from a credential-bearing path", "redirect-from-secret-word", m.group(0), raw)
    return None


def raw_dump_verdict(command: str) -> str | None:
    """Return a reason to block a raw dump of a trace, HAR, or storage-state file."""
    for segment in split_segments(strip_heredoc_bodies(command).head):
        if RAW_DUMP_COMMAND.match(segment) and RAW_DUMP_TARGET.search(OUTPUT_REDIRECT.sub(" ", segment)):
            return f"dumps a trace, HAR, or auth-state file raw {matched('raw-dump', segment)}"
    return None


# --- Secret-bearing shell variables (values, not paths) -------------------
#
# A variable name shaped like a credential: $API_KEY, ${TOKEN}, "$DB_PASSWORD".
# Token-count settings (OPENAI_MAX_TOKENS, HANDOFF_CONTEXT_TOKENS) are not
# credentials; the exemption needs the plural at the end of the name, so
# INPUT_TOKEN and MAX_TOKENS_SECRET still count.
SECRET_VAR_NAME_ANY = r"\w*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)\w*"
SECRET_VAR_NAME = (
    r"(?!(?:\w*_)?(?:CONTEXT|MAX|MIN|NUM|COUNT|LIMIT|INPUT|OUTPUT|PROMPT|COMPLETION|TOTAL)_TOKENS\b)"
    + SECRET_VAR_NAME_ANY
)
SECRET_VAR_EXPANSION = re.compile(rf"\$\{{?({SECRET_VAR_NAME})\b", re.IGNORECASE)
# An upper-case variable name in a search pattern, such as OPENAI_API_KEY,
# which SECRET_BARE_WORDS misses because `_` defeats its \b. Case-sensitive,
# so `keyboard` does not count.
UPPER_SECRET_VAR = re.compile(rf"(?<!\w){SECRET_VAR_NAME}")

# Commands that would put a variable's expanded value into the transcript.
DUMP_TRANSFORM_COMMANDS = re.compile(
    r"\b(od|xxd|hexdump|echo|printf|base64|rev|cut|fold|sed|awk|tr|"
    r"less|more|head|tail|tee|sort|uniq|pbcopy)\b|"
    r"cat\s*<<|\|\s*cat\b|"
    r"\bpython3\s+-c\b|\bnode\s+-e\b|\bperl\s+-e\b|\bcurl\b",
    re.IGNORECASE,
)

# The legitimate pattern: passing a secret to curl's own auth flags. Blanked
# out before the dump check runs so `-H "Authorization: Bearer $TOKEN"` and
# `-u user:$TOKEN` stay allowed.
CURL_AUTH_SAFE = re.compile(
    rf"(-H|--header)\s+(['\"])[^'\"]*\$\{{?{SECRET_VAR_NAME}\}}?[^'\"]*\2|"
    rf"-u\s+\S*\$\{{?{SECRET_VAR_NAME}\}}?\S*",
    re.IGNORECASE,
)

# A presence check (`test -n "$KEY"`, `[ -z "$KEY" ]`, `[[ -n ${KEY:-} ]]`) prints
# nothing. It is blanked only as the first word of an unquoted command (after
# any `if`, `while` or `!`); an argument like `echo test -n "$KEY"` still prints.
# A default word (`${KEY:-x}`, `${KEY:+x}`) may not hold `$` or a backtick,
# which could run a command.
SECRET_TEST_SAFE = re.compile(
    rf"(?:test|\[\[?)\s+-[nz]\s+(['\"]?)"
    rf"\$(?:\{{{SECRET_VAR_NAME}(?::?[-+=][^}}$`]*)?\}}|\{{?{SECRET_VAR_NAME}\}}?)"
    r"\1(?=\s|$|[;&|\]])",
    re.IGNORECASE,
)
_CHECK_PREFIX = re.compile(r"\s*(?:(?:if|while|!)\s+)*")

# Bare environment dumps with no filtering argument. Bounded by command
# separators (start/end of string, `;`, `&`, `&&`, newline) on both sides;
# a single `|` on the far side means something downstream still gets a
# chance to filter it (`env | grep ...`), so that side is deliberately left
# out of the closing boundary and the command is allowed.
_ENV_DUMP_CMD = r"(?:env(?:\s+-0)?|printenv|set|export(?:\s+-p)?|declare\s+-x|compgen\s+-v)"
_BOUNDARY_BEFORE = r"(?:^|[;&\n]|\|\|)"
_BOUNDARY_AFTER = r"(?:$|[;&\n]|\|\|)"
ENV_DUMP_BARE = re.compile(
    rf"{_BOUNDARY_BEFORE}\s*{_ENV_DUMP_CMD}\s*{_BOUNDARY_AFTER}",
    re.IGNORECASE,
)

# A dump command followed by a pass-through, not a filter: piped into `cat`
# or `tee`, or redirected to a file. These don't reduce what's exposed, so
# unlike `env | grep ...` they stay blocked even though a `|`/`>` follows.
# The dump word must be command-positioned (boundary before it, per
# ENV_DUMP_BARE) and the pipe/redirect must follow immediately -- otherwise
# `env FOO=1 cmd > out` (env setting a var for another command) and
# `--env-file` false-match on the bare word `env`.
_ENV_DUMP_NONFILTER = re.compile(
    rf"{_BOUNDARY_BEFORE}\s*{_ENV_DUMP_CMD}\s*"
    r"(?:\|\s*(?:cat|tee)\b|>{1,2}\s*\S)",
    re.IGNORECASE,
)

# `env|set|printenv` piped straight into `grep NAME` where NAME looks like a
# secret: grep only narrows to matching lines, the value is still printed.
# These checks test only the first name, so they skip the token-count
# exemption: an exempt first name would hide the next (`printenv MAX_TOKENS API_KEY`).
_ENV_DUMP_GREP_SECRET = re.compile(
    rf"{_BOUNDARY_BEFORE}\s*(?:env(?:\s+-0)?|printenv|set)\s*\|\s*grep\b"
    rf"(?:\s+-\S+)*\s+({SECRET_VAR_NAME_ANY})\b",
    re.IGNORECASE,
)

JQ_ENV_DUMP = re.compile(r"\bjq\s+(?:-n|--null-input)\b[^|;&\n]*\benv\b", re.IGNORECASE)

PRINTENV_SECRET = re.compile(rf"\bprintenv\s+({SECRET_VAR_NAME_ANY})\b", re.IGNORECASE)
DECLARE_P_SECRET = re.compile(rf"\bdeclare\s+-p\s+({SECRET_VAR_NAME_ANY})\b", re.IGNORECASE)

PYNODE_INVOCATION = re.compile(
    r"\bpython3?\s+-c\b|"
    r"\bpython3?\s+-(?=\s|$|<<)|"
    r"\bnode\s+-[ep]\b|"
    r"\bperl\s+-[eE]\b|"
    r"\bruby\s+-e\b|"
    r"\bawk\b",
    re.IGNORECASE,
)

PYNODE_SECRET_REF = re.compile(
    rf"os\.environ(?:\.get)?\s*[\[\(]\s*['\"]({SECRET_VAR_NAME})['\"]|"
    rf"os\.getenv\s*\(\s*['\"]({SECRET_VAR_NAME})['\"]|"
    rf"process\.env(?:\.|\[)['\"]?({SECRET_VAR_NAME})|"
    rf"\$ENV\{{({SECRET_VAR_NAME})\}}|"
    rf"\bENV\[\s*['\"]?({SECRET_VAR_NAME})['\"]?\s*\]|"
    rf"\.environ\s*\[\s*['\"]({SECRET_VAR_NAME})['\"]|"
    rf"\bENVIRON\[\s*['\"]?({SECRET_VAR_NAME})['\"]?\s*\]",
    re.IGNORECASE,
)

# A bare `os.environ` / `process.env` not indexed or attribute-accessed:
# printed wholesale, every variable included.
PYNODE_WHOLESALE = re.compile(
    r"os\.environ\b(?!\s*[\[.])|process\.env\b(?!\s*[\[.])",
    re.IGNORECASE,
)

# `len(<env ref>)` reports a length, not a value. Stripped as a whole span,
# per reference, before the secret-ref check runs -- a command can carry a
# safe `len(...)` alongside an unguarded reference to the same variable.
_ENV_REF_ANY = (
    r"os\.environ(?:\.get)?\s*\[[^\]]*\]|"
    r"os\.environ(?:\.get)?\s*\([^)]*\)|"
    r"os\.getenv\([^)]*\)|"
    r"process\.env(?:\.\w+|\[[^\]]*\])"
)
PYNODE_LEN_STRIP = re.compile(rf"len\(\s*(?:{_ENV_REF_ANY})\s*\)", re.IGNORECASE)


def _scrub_presence_checks(head: str) -> str:
    """Blank SECRET_TEST_SAFE checks that start an unquoted command.

    Command starts are position 0 and the text after an unquoted `;`, `&`,
    `|`, `(` or newline. Quoted text and a here-string word are never a
    command start, so `echo "x|[ -n $KEY ]"` keeps its expansion.
    """
    starts = [0]
    quote = None
    in_here = here_word = False
    i, n = 0, len(head)
    while i < n:
        c = head[i]
        if c == "\\" and quote != "'":
            here_word = here_word or in_here
            i += 2
            continue
        if quote:
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
            here_word = here_word or in_here
        elif head.startswith("<<<", i):
            in_here, here_word = True, False
            i += 3
            continue
        elif in_here and c.isspace() and c != "\n":
            in_here = not here_word
        elif in_here and c not in ";&|\n":
            here_word = True
        elif c in ";&|(\n":
            in_here = False
            starts.append(i + 1)
        i += 1
    out, last = [], 0
    for start in starts:
        if start < last:
            continue
        pos = _CHECK_PREFIX.match(head, start).end()
        if m := SECRET_TEST_SAFE.match(head, pos):
            out.append(head[last : m.start()])
            out.append(" ")
            last = m.end()
    out.append(head[last:])
    return "".join(out)


# A `$` after an odd number of backslashes is printed, not expanded.
ESCAPED_DOLLAR = re.compile(r"(?<!\\)(?:\\\\)*\\\$")


def _unescape_messengers(head: str) -> str:
    """Blank escaped `\\$` in the messenger segments of a quiet command.

    Anywhere else the next shell may expand the text again (`bash -c`,
    `eval`, `ssh host`, `| bash`), so an escaped `$` still counts there.
    Segments are rejoined with newlines, so only search the result for
    expansions, not for the commands around them.
    """
    if "\\" not in head or not is_quiet(head):
        return head
    return "\n".join(ESCAPED_DOLLAR.sub(" ", s) if is_messenger(s) else s for s in split_segments(head))


# Lower-case loop variables that name a list item, not a credential: `for key
# in a b` over literal words, or `while read key ...; done < file` with no pipe
# feeding it. Any other binding of the name, such as `key=$(pass show x)`,
# `for key in $(env)` or `env | while read key`, drops the exemption.
FOR_KEY = re.compile(r"\bfor\s+(keys?)\s+in\s+([^;\n]*)")
READ_KEY = re.compile(r"\bread\b[^;\n|&<>]*?\s(keys?)(?=[\s;]|$)", re.MULTILINE)
KEY_ASSIGN = re.compile(r"(?<![\w-])(keys?)\+?=")
DONE_FROM_FILE = re.compile(r"\bdone\s*<")


def _loop_bound_names(command: str) -> set[str]:
    """Return the lower-case `key`/`keys` names the command binds only to non-secret words."""
    names = {m.group(1) for m in FOR_KEY.finditer(command) if not re.search(r"[$`]", m.group(2))}
    read_names = {m.group(1) for m in READ_KEY.finditer(command)}
    safe_read = (
        bool(DONE_FROM_FILE.search(command)) and "<(" not in command and "|" not in blank_quoted(command, "'\"")
    )
    names = names | read_names if safe_read else names - read_names
    return names - {m.group(1) for m in KEY_ASSIGN.finditer(command)}


def secret_var_verdict(command: str) -> str | None:
    """Return a reason to block a command that would print a secret
    variable's value, or None to allow.

    Checked against the whole command rather than split into pipeline
    units: a `python3 -c "import os; print(...)"` argument routinely
    contains its own `;`, which would otherwise get cut apart by a
    unit split and hide the very thing being checked for.

    When every heredoc terminator is quoted (`<<'EOF'`), the shell does not
    expand the bodies, so they are left out of the dump checks unless they
    shell out. An unquoted body is expanded and stays checked.

    Interpreter env references are searched in the head, the interpreter
    bodies, and any data body written to a file the command names again.
    """
    heredocs = strip_heredoc_bodies(command)
    head, bodies = (heredocs.head, heredocs.interpreter_bodies) if heredocs.quoted else (command, [])
    for body, words in bodies:
        if shells_out(body, words) and (m := SECRET_VAR_EXPANSION.search(body)):
            return f"would print a secret-bearing variable {matched('heredoc-shell-out', m.group(0))}"
    if m := ENV_DUMP_BARE.search(head) or _ENV_DUMP_NONFILTER.search(head):
        return f"would dump the full environment {matched('env-dump', m.group(0))}"
    if m := _ENV_DUMP_GREP_SECRET.search(head):
        return f"would print a secret-bearing variable {matched('env-grep-secret', m.group(0))}"
    if m := JQ_ENV_DUMP.search(head):
        return f"would dump the full environment {matched('jq-env-dump', m.group(0))}"
    if m := PRINTENV_SECRET.search(head) or DECLARE_P_SECRET.search(head):
        return f"would print a secret-bearing variable {matched('printenv-secret', m.group(0))}"
    scrubbed = _scrub_presence_checks(CURL_AUTH_SAFE.sub(" ", head))
    if DUMP_TRANSFORM_COMMANDS.search(scrubbed):
        exempt = _loop_bound_names(head)
        expansions = _scrub_presence_checks(CURL_AUTH_SAFE.sub(" ", _unescape_messengers(head)))
        for m in SECRET_VAR_EXPANSION.finditer(expansions):
            if m.group(1) not in exempt:
                return f"would print a secret-bearing variable {matched('dump-secret-var', m.group(0))}"
    if PYNODE_INVOCATION.search(command):
        executed = [
            head, *(body for body, _ in heredocs.interpreter_bodies), *heredocs.rerun_bodies
        ]
        stripped = PYNODE_LEN_STRIP.sub(" ", "\n".join(executed))
        if m := PYNODE_SECRET_REF.search(stripped) or PYNODE_WHOLESALE.search(stripped):
            return f"would print a secret-bearing variable {matched('interpreter-env-ref', m.group(0))}"
    return None


# Tools that name a file, and the input fields carrying the path. Grep needs
# both: `glob` can target secrets while `path` stays an innocuous directory.
PATH_FIELDS = {
    "Read": ("file_path",),
    "Grep": ("path", "glob"),
    "Edit": ("file_path",),
    "Write": ("file_path",),
    "NotebookEdit": ("notebook_path",),
    "Artifact": ("file_path",),
}


def path_verdict(file_path: str) -> Hit | None:
    """Return why to block a direct file read, or None to allow."""
    if found := secret_path_hit(file_path):
        rule, fragment = found
        return Hit("reads a credential-bearing path", rule, fragment, file_path)
    return None


def raw_dump_path_verdict(file_path: str) -> str | None:
    """Return a reason to block a Read of a trace, HAR, or auth storage-state file."""
    if RAW_DUMP_READ_PATH.search(file_path):
        return f"reads a trace, HAR, or auth-state file raw {matched('raw-dump-read', file_path)}"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError, UnicodeError):
        return 0

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}

    if tool_name == "Bash":
        target = tool_input.get("command") or ""
        if not isinstance(target, str):
            return 0
        if reason := secret_var_verdict(target):
            print(
                f"Blocked by block_secret_reads hook: this command {reason}. "
                "Pass secrets to programs via their "
                "own flags/env, never through od/xxd/echo/printf or an "
                "unfiltered env dump; if you must inspect a value's shape, "
                "report only its length.",
                file=sys.stderr,
            )
            return 2
        if reason := raw_dump_verdict(target):
            return block_raw_dump("command", reason)
        hit, noun = verdict(target), "command"
    elif tool_name in PATH_FIELDS:
        if tool_name == "Read" and isinstance(tool_input.get("file_path"), str):
            if reason := raw_dump_path_verdict(tool_input["file_path"]):
                return block_raw_dump("tool call", reason)
        hit, noun = None, "tool call"
        for field in PATH_FIELDS[tool_name]:
            value = tool_input.get(field) or ""
            if isinstance(value, str):
                hit = hit or path_verdict(value)
    else:
        return 0

    if hit is None:
        return 0
    return block_secret_read(noun, hit)


def block_secret_read(noun: str, hit: Hit) -> int:
    # The rule sits in parentheses on the first line so a parser can read it.
    if noun == "command":
        context = f"Segment: `{' '.join(hit.context.split())[:120]}`"
    else:
        context = f"Path: `{hit.context}`"
    print(
        f"Blocked by block_secret_reads hook (rule {hit.rule}): this {noun} {hit.reason}.\n"
        f"{context}\n"
        f"Matched: `{' '.join(hit.fragment.split())[:80]}`\n"
        "If this reads a credential file, ask the user for the value instead of printing it.\n"
        "If the matched text is a search pattern or prose, not a file: search with the Grep "
        "tool, or put the text in a file and pass the file name.\n"
        "Files tracked in git already exist in every git worktree; do not copy them.",
        file=sys.stderr,
    )
    return 2


def block_raw_dump(noun: str, reason: str) -> int:
    print(
        f"Blocked by block_secret_reads hook: this {noun} {reason}.\n"
        "Traces, HAR files, and auth storage-state files hold cookies, auth "
        "headers, and typed values. For a redacted view of actions and "
        f"requests, run `{TRACE_READER}` (on the trace.zip, not the files "
        "`unzip -d` extracts from it). Copying, listing (`unzip -l`, "
        "`zipinfo`), and `npx playwright show-trace` stay allowed.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
