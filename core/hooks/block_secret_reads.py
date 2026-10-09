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
  - A reader name glued to a hyphen (`llvm-strings .env`) is not seen as a
    reader, so option names such as `--head` and hyphenated branch names
    do not match.
  - Reading a secret indirectly: copy to a neutral name first, then read.
  - The env-reach rule (below) checks git work trees only. A search root
    outside one, such as a grep across ~/Projects, a non-git parent of many
    repositories, is not checked.
  - The env-reach rule assumes the search honours .gitignore. `git grep
    --no-index` does not, and may read env files git does not list. `command
    grep`, an absolute grep path, and a search run through a wrapper
    (`timeout`, `nice`, `sudo`) get no env-reach check at all.
  - `xargs grep` and greps over shell globs (`git ls-files | xargs grep -n X`,
    `grep -n X **/*`) get no env-reach check.
  - Env files inside a nested git repository or a submodule's work tree are
    not in the reach listing (ls-files lists each as one entry), so grep -r,
    rg and the Grep tool can reach them; `git grep --recurse-submodules` is
    covered.
  - A nested subshell (`(cd a && (cd b && make)); grep -rn X .`) or a `$(...)`
    that closes inside an open subshell can restore the effective directory to
    the wrong level.
  - Revisions passed to `git grep` are checked against the index, not their trees.
  - The reach set over-blocks tracked files that are also ignored, which ugrep
    and rg skip.
  - For a grep root below the work-tree top, an env file inside an ignored
    directory whose own name is not env-shaped (`build/.env`) is missed.
  - A positive rg or Grep glob with a directory part is tested against
    top-level env names only.
Tighten only if the threat model changes; today's goal is preventing careless
credential exposure, not defeating circumvention.

A broad search -- every git grep (`git -C <dir> grep` included), a recursive
grep, an rg over a directory or the working directory, a Grep tool content
search -- prints lines from every env file it reaches, whatever its pattern.
Unless it prints names or counts only, the env-reach rule asks git which
env-shaped files it reaches (`git ls-files` from the payload cwd, after each
`cd` and `-C`), drops the ones the search itself excludes (git `:!` pathspecs,
grep `--exclude`/`--exclude-dir`, rg and Grep `!` globs), and blocks when any
remain. A search that reads ignored files (rg `-u`, `--unrestricted` or
`--no-ignore*`, `git grep --untracked --no-exclude-standard`) also blocks
unless its own excludes cover every env name. This rule fails closed: a
directory it cannot resolve (a variable, a command substitution, `cd -`), a
git failure other than "not a git repository", or git running past its
deadline blocks with "could not check".

Raw dumps of Playwright traces, HAR files, and auth storage-state files are
blocked separately; scripts/trace-read.py in the forge skill prints a redacted
view of them instead.

Two narrow exceptions keep forge working in repositories that implement API keys:
  - A source file (.py, .ts, ...) whose only secret word is api_key, api-key or
    apikey, under no dot-directory but .venv, is code, not a stored key.
  - A Bash command that is exactly one of forge.config.json's worktree gate
    commands may source the repository's .envs files; it never prints them.

Exit codes: 2 = block (stderr is shown to Claude), 0 = allow.
"""

import fnmatch
import io
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
import time
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
    r"\bgh\s+auth\s+status\b.*\s(?:--show-token\b|-\w*t)|"
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
# ENV_PATH_SHAPES are the env files on their own. `.envrc` and `.env_*` match
# the settings deny rules. `/app/env.sh` is the env file of a Daytona fork; an
# `env.sh` anywhere else is usually a script.
ENV_PATH_SHAPES = r"\.envs?\b|\.env\.|/\.envs?\b|\.envrc\b|\.env_|(?<![\w.~-])/app/env\.sh\b"
SECRET_PATH_SHAPES = (
    ENV_PATH_SHAPES + "|"
    r"\.ssh/|\bid_rsa\b|\bid_ed25519\b|\bid_ecdsa\b|authorized_keys|known_hosts|"
    r"\.aws/|\.gnupg/|\.kube/config|"
    # gh writes its token to hosts.yml in plain text when no credential store works.
    r"\.config/gh(?![\w-])|\bgh/hosts\.yml\b|"
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
# credentials.json). Checked for path tools and reader commands, never in
# interpreter heredoc bodies, where prose such as "writes credentials.json" is common.
SECRET_FILE_SHAPES = (
    r"(?:\b|_)(?:credentials?|secrets?|tokens?|api[_-]?keys?)[\w-]*"
    r"\.(?:json|ya?ml|txt|ini|toml|cfg|conf|key)\b"
)
# The system account files, bare or with a data extension: `/etc/shadow`,
# `passwd.txt`. A base name that only contains the word (`box-shadow.css`) is not one.
SYSTEM_SECRET_FILE = re.compile(
    r"(?:^|/)(?:passwd|shadow)(?:\.(?:json|ya?ml|txt|ini|toml|cfg|conf|key))?$", re.IGNORECASE
)
# A folder named for credentials holds them whatever its files are called
# (`/run/secrets/db_password`). `.secrets/` is left out: AUTHORIZED_PATHS opts it out.
SECRET_FOLDER = re.compile(r"(?:^|/)(?:secrets?|\.secret|credentials?)/", re.IGNORECASE)
# A forge gate output (`gate-apikey.log`, `gate-commit-phase-1.json`) is named
# after the gate's label, not after what it holds.
GATE_OUTPUT = re.compile(r"(?:^|/)gate-[\w-]+\.(?:log|json|diff)$", re.IGNORECASE)

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

# Loading a repository's local dev env files into the shell for a test run
# (`set -a; . .envs/.postgres; set +a`) prints nothing. Only a bare
# `.`/`source` statement on a relative `.envs/` path is exempt, and only as
# the first word of a simple command: at the start, after `;`, `&`, `|`, `(`
# or a newline, or opening a shell's `-c` argument. `cat . .envs/x` reads the
# file. The lead is captured and must be kept in the replacement.
SOURCED_REPO_ENV = re.compile(
    r"(?P<lead>(?:^|[;&|(\n]|\b(?:ba|z|da|k)?sh(?:\s+-[\w-]+)*\s+-\w*c\s*['\"])\s*)"
    r"(?:source|\.)\s+(?:\./)?\.envs/(?![^\s;&|)'\"`]*prod)"
    r"(?:\.[\w-]+/)?\.[\w-]+(?=$|[\s;&|)'\"`])",
    re.IGNORECASE,
)
# SOURCED_REPO_ENV applies only when the command matches none of these, since
# each can print the loaded values: `declare -p`, `typeset -p`, `env | sort`
# and any `set` but a lone `set -a`/`set +a` (which _ENV_DUMP_CMD does not fully
# catch; `set -a -x` traces the sourced assignments); a shell traced with
# `-x`/`-v` or `xtrace`/`verbose`; any `$` parameter expansion; and an
# interpreter reading its environment. Case-insensitive, because a
# case-insensitive file system can run `ENV` or `PRINTENV` as env or printenv.
ENV_DUMP_WORD = re.compile(
    r"\b(?:declare|typeset|env|printenv|export|compgen)\b"
    r"|\bset\b(?!\s+[-+]a\s*(?:$|[;&|)'\"`\n]))"
    r"|\b(?:ba|z|da|k)?sh(?:\s+-[\w-]+)*\s+-[a-z]*[xv][a-z]*(?![\w-])|\b(?:xtrace|verbose)\b"
    r"|\$[\w{@*#?!$-]|\b(?:environ|getenv)|\bprocess\.env\b|\bENV\[|%ENV\b",
    re.IGNORECASE,
)

# The shell "source" shorthand is a dot standing alone after whitespace or an opening quote
# (`sh -c '. file'`) and before whitespace; a dot inside a file name (report_issue.py) is not a reader.
READER_NEAR_SECRET = re.compile(
    rf"(?:(?<![\w-])({READERS})\b|(?<![^\s'\"])\.(?=\s))[^\n]*?({SECRET_PATH_SHAPES})",
    re.IGNORECASE,
)

# Secret-named data files after a reader. Matched against pattern_scan(segment),
# so a quoted grep pattern searched in .md files does not trigger it.
READER_NEAR_SECRET_FILE = re.compile(
    rf"(?:(?<![\w-])({READERS})\b|(?<![^\s])\.(?=\s))[^\n]*?({SECRET_FILE_SHAPES})",
    re.IGNORECASE,
)

# Bare secret words after a reader. Matched against word_scan(segment), not the
# raw segment, so .md file names and quoted prose do not trigger it.
READER_NEAR_SECRET_WORD = re.compile(
    rf"(?:(?<![\w-])({READERS})\b|(?<![^\s])\.(?=\s))[^\n]*?({SECRET_BARE_WORDS})",
    re.IGNORECASE,
)

QUOTED_ANY = re.compile(r"'[^']*'|\"[^\"]*\"")
# A .md name only as a whole path token, so `cat {tokens.txt,x.md}` and
# `cat tokens.txt>x.md` keep their secret-named part.
MD_TOKEN = re.compile(r"(?<![^\s=])[\w./~@+$-]*\.md(?=$|[\s;&|)])")
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
    """Return the segment with prose and .md names blanked for the word check.

    Quoted text with a space in it is prose (a report message, a sed script),
    not a path.
    """
    scan = MD_TOKEN.sub(" ", blank_plain_quotes(segment, prose_only=True))
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
    # Block text that replaces the shared routes, for rules that name their own.
    advice: str = ""


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


def _runs_code(span: str) -> bool:
    """Return True when double-quoted text holds `$(` or an unescaped backtick, which the shell runs."""
    i, n = 0, len(span)
    while i < n:
        if span[i] == "\\":
            i += 2
            continue
        if span[i] == "`" or span.startswith("$(", i):
            return True
        i += 1
    return False


def blank_plain_quotes(text: str, *, prose_only: bool = False) -> str:
    """Blank closed quoted spans that the shell passes on as plain text.

    Tracks escapes and quote state like blank_quoted. A double-quoted span
    holding `$(` or an unescaped backtick stays, because the shell runs it
    (`echo "value: $(cat tokens.txt)"`); so does an input redirect target
    (`< "tokens.txt"`). With prose_only, only spans holding whitespace are
    blanked: a quoted single word may still be a path (cat "secrets.yaml").
    An unclosed quote leaves the rest of the text as it is.
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
            span = text[i:end]
            before = "".join(out).rstrip()
            keep = (
                (c == '"' and _runs_code(span[1:-1]))
                or (before.endswith("<") and not before.endswith("<<"))
                or (prose_only and not re.search(r"\s", span))
            )
            out.append(span if keep else " ")
            i = end
            continue
        out.append(c)
        i += 1
    return "".join(out)


def has_substitution(text: str) -> bool:
    """Return True when text runs a substitution.

    That is `$(` or an unescaped backtick outside single quotes, or `<(` or
    `>(` outside quotes.
    """
    scan = re.sub(r"\\.", "  ", blank_plain_quotes(text), flags=re.DOTALL)
    return any(s in scan for s in ("$(", "`", "<(", ">("))


# A short option cluster ending in `c` (`sh -c`, `su -c`, `bash -lc`) may hand
# its quoted argument to a shell.
DASH_C_OPTION = re.compile(r"(?<!\S)-\w*c(?![^\s;&|)])")


def reruns_quotes(command: str) -> bool:
    """Return True when a command may hand quoted text to a shell: a HEREDOC_SHELL word or a `-c` option."""
    return bool(HEREDOC_SHELL.search(command) or DASH_C_OPTION.search(command))


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
    # ripgrep. Options that run a program or change what is searched
    # (--pre, --pre-glob, --type-add, --ignore-file, --no-config) are left out.
    "rg": OptionTable(
        set("efgtTmABCMjdEr"),
        set("iSswxvFnNHIlcqopUaLbzu.0"),
        {
            "regexp", "file", "glob", "iglob", "type", "type-not", "max-count", "after-context",
            "before-context", "context", "max-columns", "threads", "max-depth", "encoding", "replace",
            "sort", "sortr", "color", "colors", "engine", "max-filesize", "path-separator",
        },
        {
            "ignore-case", "smart-case", "case-sensitive", "word-regexp", "line-regexp", "invert-match",
            "fixed-strings", "line-number", "no-line-number", "with-filename", "no-filename", "no-heading",
            "heading", "files-with-matches", "files-without-match", "count", "count-matches", "quiet",
            "only-matching", "pretty", "multiline", "text", "follow", "byte-offset", "search-zip",
            "unrestricted", "hidden", "null", "column", "vimgrep", "json", "trim", "no-messages",
            "crlf", "pcre2", "stats", "help", "version", "no-ignore", "no-ignore-vcs", "no-ignore-parent",
            "no-ignore-dot", "no-ignore-exclude", "no-ignore-global", "no-ignore-files", "no-ignore-messages",
        },
        set("ABCmMjd"),
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
    "rg": {"-l", "-c", "-q", "--files-with-matches", "--files-without-match", "--count", "--count-matches", "--quiet"},
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
# A git pathspec that excludes: `:!x`, `:^x`, `:/!x`, or long magic whose
# comma list holds `exclude` (`:(top,exclude)x`).
_EXCLUDE_MAGIC = r":(?:/*[!^]|\((?:[^),]*,)*exclude(?:,[^)]*)?\))"
EXCLUDE_PATHSPEC = re.compile(_EXCLUDE_MAGIC)


class ReaderArgs(NamedTuple):
    """A grep/git grep/rg/sed/awk call split into options, patterns (or scripts), and file operands."""

    family: str
    options: list[tuple[str, str]]
    patterns: list[str]
    files: list[str]
    # True for `xargs grep`, whose file list comes from stdin.
    stdin_files: bool = False
    # The `-C <dir>` values of `git -C <dir> grep`, in order.
    git_dirs: tuple[str, ...] = ()
    # The index in files where the operands after `--` start; None without `--`.
    dashdash: int | None = None


def read_operands(args: ReaderArgs) -> list[str]:
    """Return the file operands a call reads; a git grep exclude pathspec reads nothing."""
    if args.family != "git grep":
        return args.files
    return [f for f in args.files if not EXCLUDE_PATHSPEC.match(f)]


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
    """Parse a grep, egrep, fgrep, git grep, rg, sed, awk, or `xargs grep` segment into its arguments.

    Returns None when the segment is another command, when it holds command
    or process substitution, when its quotes do not balance, or when it uses
    an option missing from the command's table (an abbreviated long option
    included); the caller then applies the text checks instead. Leading
    `NAME=value` assignments are skipped before grep and xargs only.
    """
    if has_substitution(raw):
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
    git_dirs: list[str] = []
    if tokens[:1] == ["git"]:
        j = 1
        while j < len(tokens) and tokens[j] in ("-C", "--no-pager"):
            if tokens[j] == "-C":
                if j + 1 == len(tokens):
                    return None
                git_dirs.append(tokens[j + 1])
            j += 2 if tokens[j] == "-C" else 1
        if tokens[j : j + 1] != ["grep"]:
            return None
        tokens = ["git grep", *tokens[j + 1 :]]
    if not tokens or tokens[0] not in READER_OPTS:
        return None
    command = tokens[0]
    table = READER_OPTS[command]
    options: list[tuple[str, str]] = []
    positionals: list[str] = []
    dashdash_at: int | None = None
    i = 1
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if token == "--":
            dashdash_at = len(positionals)
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
    offset = 0
    if names & {"-e", "--regexp", "--expression", "-f", "--file"}:
        patterns = [value for name, value in options if name in ("-e", "--regexp", "--expression")]
        files = positionals
    else:
        patterns, files = positionals[:1], positionals[1:]
        offset = 1
    if command == "awk":
        # An assignment's value can name the file a getline reads: `f=.env`.
        files = [ASSIGNMENT.sub("", f) for f in files]
    family = "grep" if command in ("egrep", "fgrep") else command
    dashdash = None if dashdash_at is None else max(dashdash_at - offset, 0)
    return ReaderArgs(family, options, patterns, files, stdin_files, tuple(git_dirs), dashdash)


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


def reader_verdict(args: ReaderArgs, raw: str, fed_by_pipe: bool = False, *, here: str | None) -> Hit | None:
    """Check the file operands and scripts of a parsed grep/git grep/rg/sed/awk call.

    A grep pattern is search text and is never checked as a path. A broad
    search (recursive, every git grep, `xargs grep`, or a shell glob) for a secret word
    still blocks, since it prints matching lines from every secret file it
    reaches. A pattern with whitespace still counts: `"token: "` matches
    `oauth_token: <value>` lines. An rg search is broad when it reaches hidden,
    ignored or symlinked files (`-u`, `--hidden`, `-L`, a positive `-g`), names
    no path and reads no pipe, or names `.`, `~`, `$HOME` or `/`.

    A search that prints lines, run from `here` (None when the directory is
    unknown), then gets the env-reach check: see env_reach().
    """
    family, options = args.family, args.options
    includes = [
        value
        for name, value in options
        if (family == "grep" and name == "--include")
        or (family == "rg" and name in ("-g", "--glob", "--iglob") and not value.startswith("!"))
    ]
    read_paths = read_operands(args) + [value for name, value in options if name in ("-f", "--file")] + includes
    read_paths += [value.partition("=")[2] for name, value in options if family == "awk" and name == "-v"]
    for path in read_paths:
        # A reader operand still blocks on a bare credential word (`config/token`); a path tool does not.
        word = (
            re.search(SECRET_BARE_WORDS, ALLOWLIST.sub(" ", path), re.IGNORECASE)
            and not path.lower().endswith(".md")
            and not AUTHORIZED_PATHS.search(path)
            and not api_key_source(path)
            and not gate_output(path)
        )
        if secret_path_hit(path) or word:
            return Hit("reads a credential-bearing path", "reader-operand", path, raw, env_read_advice(family, path))
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
    recursive = (
        bool(set("rR") & set(shorts))
        or bool(names & {"--recursive", "--dereference-recursive"})
        # GNU grep accepts any unambiguous prefix: `-d rec`.
        or any(name in ("-d", "--directories") and value and "recurse".startswith(value) for name, value in options)
    )
    # git grep recurses, and --no-index or --untracked reach ignored files.
    broad = family == "git grep" or args.stdin_files or recursive or glob
    # rg reads dot files with --hidden, `-.`, `-uu` or --unrestricted twice; one -u only drops the ignore rules.
    hidden = (
        "." in shorts
        or shorts.count("u") + [name for name, _ in options].count("--unrestricted") >= 2
        or "--hidden" in names
    )
    if family == "rg":
        reads_ignored = (
            "u" in shorts
            or "--unrestricted" in names
            # --no-ignore-messages only silences errors about ignore files.
            or any(name.startswith("--no-ignore") and name != "--no-ignore-messages" for name in names)
        )
    else:
        reads_ignored = family == "git grep" and {"--untracked", "--no-exclude-standard"} <= names
    if family == "rg":
        # Plain rg skips hidden and git-ignored files, where .env files live;
        # a positive -g glob overrides the ignore rules, and -L follows symlinks
        # out of the named dir. rg's -r is --replace, not recursive.
        broad = (
            glob
            or bool(includes)
            or bool(set("u.L") & set(shorts))
            or bool(names & {"--hidden", "--unrestricted", "--follow"})
            or reads_ignored
            # With no path rg searches the working directory, unless a pipe
            # feeds it; then it reads stdin.
            or (not args.files and not fed_by_pipe)
            or any(
                (posixpath.normpath(f).rstrip("/") or "/") in (".", "~", "$HOME", "${HOME}", "/")
                for f in args.files
            )
        )
    if names & NAMES_ONLY_OPTS[family]:
        return None
    narrow = bool(includes) and all(_narrow_glob(include) for include in includes)
    if broad and not all_md and not narrow and (hit := _secret_word_hit(args.patterns, raw)):
        return hit
    search = _reader_env_search(args, includes, here, recursive, hidden, fed_by_pipe, reads_ignored)
    return None if search is None else env_reach(search, raw)


# --- Broad searches that reach env files -----------------------------------
#
# A repo-wide git grep, recursive grep or rg prints lines from every file it
# reaches, so an env file in reach prints its values whatever the pattern.
# git lists those files: the index for git grep, and the files the search does
# not ignore for grep and rg (the session's grep is ugrep with --ignore-files).
ENV_REACH_RULE = "search-reaches-env-file"
REACH_SECONDS = 3.0
# One deadline for every git call this hook run makes.
REACH_DEADLINE = time.monotonic() + REACH_SECONDS
# A positive rg or Grep glob overrides the ignore rules, so it is tested
# against these names instead of a listing. A search that reads ignored files
# is also tested against them.
ENV_PROBES = (".env", ".env.local", ".envs/x", "x.env", ".envrc", ".env_x")
HOME_WORD = re.compile(r"^\$(?:HOME|\{HOME\})(?=/|$)")
GREP_IGNORE = "--exclude-per-directory=.gitignore"
ENV_EXCLUDES = {
    "git grep": "add `-- . ':!.env*' ':!*/.env*'`",
    "grep": "add `--exclude-dir=.envs --exclude='.env*'`",
    "rg": "add `-g '!.env*'`",
    "Grep": 'set `glob` to `"!.env*"`',
}
# Excludes that cover every ENV_PROBES name, for a search that reads ignored files.
PROBE_EXCLUDES = {"git grep": "add `-- . ':!*.env*'`", "rg": "add `-g '!.env*' -g '!*.env'`"}
NAMES_ONLY_ROUTES = {
    "git grep": "print names only with -l (`git grep -l`)",
    "grep": "print names only with -l (`grep -rl`)",
    "rg": "print names only with -l (`rg -l`)",
    "Grep": "use `output_mode` `files_with_matches`",
}


class ReachUnknown(Exception):
    """git could not list the files a search reaches."""


class GitTimeout(ReachUnknown):
    """git did not answer before REACH_DEADLINE."""


class EnvSearch(NamedTuple):
    """A broad search for the env-reach check."""

    # "git grep", "grep", "rg", or "Grep" for the Grep tool.
    tool: str
    # The directories searched; None when one cannot be resolved.
    roots: list[str] | None
    pathspecs: tuple[str, ...] = ()
    untracked: bool = False
    hidden: bool = True
    # (glob, parts): a glob without `/` is matched against one path part,
    # "base" (the file name), "dirs" (a directory) or "any".
    excludes: tuple[tuple[str, str], ...] = ()
    # grep --include globs: only the files they match are read.
    includes: tuple[str, ...] = ()
    # rg or Grep globs in command order, `!` ones included, when any is positive.
    positives: tuple[str, ...] = ()
    # The search reads files .gitignore hides.
    reads_ignored: bool = False
    submodules: bool = False


def _shell_word(word: str) -> str | None:
    """Return a word with a leading `~` or `$HOME` expanded, or None when it holds another `$` or a backtick."""
    word = posixpath.expanduser(HOME_WORD.sub("~", word))
    return None if "$" in word or "`" in word else word


def _join_dir(base: str | None, word: str) -> str | None:
    """Join a directory word onto base, or return None when the result cannot be resolved."""
    resolved = _shell_word(word)
    if resolved is None or (base is None and not resolved.startswith("/")):
        return None
    return posixpath.normpath(posixpath.join(base or "/", resolved))


def _search_roots(here: str | None, operands: list[str]) -> list[str] | None:
    """Return the directories a grep or rg call searches: its operands joined onto here, or here alone."""
    if not operands:
        return None if here is None else [here]
    roots: list[str] = []
    for operand in operands:
        if (root := _join_dir(here, operand)) is None:
            return None
        roots.append(root)
    return roots


def _git_pathspecs(args: ReaderArgs, root: str) -> list[str] | None:
    """Return a git grep call's pathspecs, or None when one holds a variable.

    Before `--`, a word after the pattern is a pathspec only when it starts
    with `:` or exists under root; any other word is a revision.
    """
    start = len(args.files) if args.dashdash is None else args.dashdash
    words = [f for f in args.files[:start] if f.startswith(":") or os.path.lexists(posixpath.join(root, f))]
    pathspecs: list[str] = []
    for word in words + args.files[start:]:
        if (pathspec := _shell_word(word)) is None:
            return None
        pathspecs.append(pathspec)
    return pathspecs


def _reader_env_search(
    args: ReaderArgs,
    includes: list[str],
    here: str | None,
    recursive: bool,
    hidden: bool,
    fed_by_pipe: bool,
    reads_ignored: bool = False,
) -> EnvSearch | None:
    """Return the env-reach search of a parsed git grep, recursive grep or rg call, or None for any other call."""
    options = args.options
    if args.family == "git grep":
        root = here
        for directory in args.git_dirs:
            root = _join_dir(root, directory)
        pathspecs = None if root is None else _git_pathspecs(args, root)
        if root is None or pathspecs is None:
            return EnvSearch("git grep", None)
        names = {name for name, _ in options}
        return EnvSearch(
            "git grep",
            [root],
            tuple(pathspecs),
            "--untracked" in names,
            reads_ignored=reads_ignored,
            submodules="--recurse-submodules" in names,
        )
    operands = [f for f in args.files if f != "-"]
    if args.files and not operands:
        return None
    if args.family == "grep" and recursive and not args.stdin_files:
        excludes = tuple(
            (value, "base" if name == "--exclude" else "dirs")
            for name, value in options
            if name in ("--exclude", "--exclude-dir")
        )
        return EnvSearch("grep", _search_roots(here, operands), excludes=excludes, includes=tuple(includes))
    if args.family == "rg" and (args.files or not fed_by_pipe):
        roots = _search_roots(here, operands)
        off_root = roots is not None and any(root != posixpath.normpath(here or "") for root in roots)
        globs = [value for name, value in options if name in ("-g", "--glob", "--iglob")]
        if off_root:
            globs = [g if g.startswith("!") else g.lstrip("/") for g in globs if not g.startswith("!/")]
        excludes = tuple((g[1:], "any") for g in globs if g.startswith("!"))
        positives = tuple(globs) if includes or reads_ignored else ()
        return EnvSearch(
            "rg",
            roots,
            hidden=hidden,
            excludes=excludes,
            positives=positives,
            reads_ignored=reads_ignored,
        )
    return None


def _glob_regex(glob: str, ignore_case: bool = False) -> re.Pattern[str] | None:
    """Translate a glob: `*` and `?` stop at `/`, `**` crosses it, `{a,b}` is a choice.

    Returns None for a glob it does not understand.
    """
    out: list[str] = []
    braces, i, n = 0, 0, len(glob)
    while i < n:
        c = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if glob.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "[":
            end = glob.find("]", i + 2)
            body = glob[i + 1 : end]
            if end < 0 or "[" in body or "\\" in body:
                return None
            out.append("[" + ("^" + body[1:] if body[0] in "!^" else body) + "]")
            i = end + 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(re.escape(glob[i + 1]))
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "{":
            braces += 1
            out.append("(?:")
        elif c == "}" and braces:
            braces -= 1
            out.append(")")
        elif c == "," and braces:
            out.append("|")
        else:
            out.append(re.escape(c))
        i += 1
    if braces:
        return None
    try:
        return re.compile("".join(out), re.IGNORECASE if ignore_case else 0)
    except re.error:
        return None


def _glob_hit(glob: str, entry: str, parts: str, ignore_case: bool = False) -> bool | None:
    """Return whether a glob matches a listed path, or None when the glob is not understood.

    A glob with `/` (a leading one included) matches the whole path or,
    unless parts is "base", a directory above it. Otherwise it matches one
    part, as parts says. An ignored directory listed as one entry ends in `/`.
    """
    # A directory-only glob is not modelled, so the path is kept.
    if glob.endswith("/") and parts != "dirs":
        return None
    pattern = glob.strip("/")
    regex = _glob_regex(pattern, ignore_case)
    if regex is None:
        return None
    is_dir = entry.endswith("/")
    names = entry.rstrip("/").split("/")
    if "/" in glob.rstrip("/"):
        prefixes = ["/".join(names[:k]) for k in range(1, len(names) + 1)]
        if parts == "base":
            candidates = [] if is_dir else prefixes[-1:]
        else:
            candidates = prefixes if parts == "any" or is_dir else prefixes[:-1]
    elif parts == "base":
        candidates = [] if is_dir else names[-1:]
    elif parts == "dirs":
        candidates = names if is_dir else names[:-1]
    else:
        candidates = names
    return any(regex.fullmatch(candidate) for candidate in candidates)


def env_path(path: str) -> bool:
    """Return True when a path names an env file, blanked as secret_path_hit() blanks it."""
    if AUTHORIZED_PATHS.search(path):
        return False
    return bool(re.search(ENV_PATH_SHAPES, ALLOWLIST.sub(" ", path), re.IGNORECASE))


def _git_output(root: str, *args: str) -> bytes | None:
    """Run git in root and return its output, or None when root is not in a git work tree."""
    remaining = REACH_DEADLINE - time.monotonic()
    if remaining <= 0:
        raise GitTimeout(f"git did not answer within {REACH_SECONDS:g} seconds")
    try:
        result = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=remaining,
            env={**os.environ, "LC_ALL": "C"},
            check=False,
        )
    except subprocess.TimeoutExpired as err:
        raise GitTimeout(f"git did not answer within {REACH_SECONDS:g} seconds") from err
    except OSError as err:
        raise ReachUnknown(f"git could not run ({err.strerror or err})") from err
    except ValueError as err:
        # An argument with a NUL byte cannot be passed to a program.
        raise ReachUnknown(f"git could not run ({err})") from err
    if result.returncode == 0:
        return result.stdout
    if b"not a git repository" in result.stderr:
        return None
    detail = os.fsdecode(result.stderr).strip().splitlines()[:1]
    raise ReachUnknown(f"git exited {result.returncode}" + (f": {detail[0][:160]}" if detail else ""))


def _nul_split(output: bytes | None) -> list[str] | None:
    """Split `git ls-files -z` output into paths."""
    return None if output is None else [os.fsdecode(path) for path in output.split(b"\0") if path]


def _reach_listing(search: EnvSearch, root: str) -> list[str] | None:
    """Return the paths under root that git says the search can read, or None outside a git work tree."""
    if search.tool == "git grep":
        args = ["ls-files", "-z", "--cached"]
        if search.untracked:
            args += ["--others", "--exclude-standard"]
        if search.submodules:
            args.append("--recurse-submodules")
        if search.pathspecs:
            args += ["--", *search.pathspecs]
        return _nul_split(_git_output(root, *args))
    if search.tool != "grep":
        return _nul_split(_git_output(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    prefix = _git_output(root, "rev-parse", "--show-prefix")
    if prefix is None:
        return None
    listed = _nul_split(_git_output(root, "ls-files", "-z", "--cached", "--others", GREP_IGNORE)) or []
    if prefix.strip():
        # ugrep reads no .gitignore above its root, so below the work-tree top
        # the files a parent .gitignore hides are read too.
        ignored = _git_output(root, "ls-files", "-z", "--others", "--ignored", GREP_IGNORE, "--directory")
        listed += _nul_split(ignored) or []
    return listed


def _walk_listing(root: str) -> list[str]:
    """List every file under root, for a search whose git listing failed.

    It lists ignored and untracked files too, so it never misses a file git
    would list. Like the git listing it does not follow directory links: a
    directory link, a directory it cannot read, or REACH_DEADLINE raises ReachUnknown.
    """

    def fail(err: OSError) -> None:
        raise ReachUnknown(f"the file walk could not read `{err.filename}` ({err.strerror or err})") from err

    listed: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=fail):
        if time.monotonic() > REACH_DEADLINE:
            raise ReachUnknown(f"the file walk did not finish within {REACH_SECONDS:g} seconds")
        dirnames[:] = [name for name in dirnames if name != ".git"]
        rel = os.path.relpath(dirpath, root)
        prefix = "" if rel == "." else f"{rel}/"
        if link := next((name for name in dirnames if os.path.islink(os.path.join(dirpath, name))), None):
            raise ReachUnknown(f"`{prefix}{link}` is a directory link, which the file walk does not follow")
        listed += [prefix + name for name in filenames]
    return listed


def _reaches(search: EnvSearch, root: str, entry: str) -> bool:
    """Return True when a listed path is an env file the search reads."""
    rel = entry.rstrip("/")
    if not env_path(posixpath.join(root, rel)):
        return False
    if not search.hidden and has_dot_part(rel):
        return False
    if any(_glob_hit(glob, entry, parts) for glob, parts in search.excludes):
        return False
    return (
        not search.includes
        or entry.endswith("/")
        or any(_glob_hit(glob, entry, "base") is not False for glob in search.includes)
    )


def _positive_reaches(search: EnvSearch, probe: str) -> bool:
    """Return True when the last glob that matches an env name is a positive one.

    In rg the last matching glob wins. For a search that reads ignored files,
    the name also counts when no glob matches it. A git grep that reads ignored
    files reaches the name unless its exclude pathspecs cover it.
    """
    if search.tool == "git grep":
        patterns = [
            spec[m.end() :]
            for spec in search.pathspecs
            if (m := EXCLUDE_PATHSPEC.match(spec))
            and not any(magic in m.group(0) for magic in ("glob", "icase", "attr"))
        ]
        return not all(any(fnmatch.fnmatchcase(path, p) for p in patterns) for path in (probe, f"x/{probe}"))
    for glob in reversed(search.positives):
        if glob.startswith("!"):
            if _glob_hit(glob[1:], probe, "any"):
                return False
        elif _glob_hit(glob, probe, "any", ignore_case=True) is not False:
            return True
    return (
        search.reads_ignored
        and (search.hidden or not has_dot_part(probe))
        and all(glob.startswith("!") for glob in search.positives)
    )


def _sq(text: str) -> str:
    """Quote text for a shell with single quotes."""
    return "'" + text.replace("'", "'\\''") + "'"


def _path_exclude(tool: str, entry: str) -> str | None:
    """Return the exclude for a reached path that the tool's exclude in ENV_EXCLUDES misses, else None."""
    rel = entry.rstrip("/")
    names = rel.split("/")
    if tool == "git grep":
        # A git pathspec `*` also matches `/`, as fnmatch's does.
        if fnmatch.fnmatchcase(rel, ".env*") or fnmatch.fnmatchcase(rel, "*/.env*"):
            return None
        return _sq(f":!{rel}")
    if tool == "grep":
        dirs, base = (names, "") if entry.endswith("/") else (names[:-1], names[-1])
        if ".envs" in dirs or fnmatch.fnmatchcase(base, ".env*"):
            return None
        # grep matches --exclude against the file name only.
        if env_path(base):
            return f"--exclude={_sq(base)}"
        directory = next((name for name in dirs if env_path(name)), None)
        return None if directory is None else f"--exclude-dir={_sq(directory)}"
    if any(fnmatch.fnmatchcase(name, ".env*") for name in names):
        return None
    return f"-g {_sq('!' + rel)}" if tool == "rg" else f"!{rel}"


def _reach_hit(
    tool: str, context: str, root: str, reached: list[str], probe: bool = False, ignored: bool = False
) -> Hit:
    """Return the block for a search that reaches env files, naming the excludes that skip them."""
    shown = ", ".join(f"`{path}`" for path in reached[:3])
    if len(reached) > 3:
        shown += f" and {len(reached) - 3} more"
    base = ENV_EXCLUDES[tool]
    if probe and ignored:
        found = f"It reads files .gitignore hides, so it can reach env files named like {shown}."
        base = PROBE_EXCLUDES[tool]
        extra: list[str] = []
    elif probe:
        found = f"Its positive glob overrides the ignore rules and can match env files such as {shown}."
        extra = []
    else:
        found = f"Env files it reaches (names only; the hook did not open them): {shown}"
        extra = list(dict.fromkeys(x for path in reached if (x := _path_exclude(tool, path))))
    route = f"To search without them, {base}"
    if extra and tool == "Grep":
        flags = " ".join(f"-g {_sq(x)}" for x in ["!.env*", *extra[:10]])
        route = (
            "The Grep `glob` field holds one exclude, so narrow `path` to a folder without env files, "
            f"or run `rg {flags}` in Bash"
        )
    elif extra:
        route += ", and also exclude " + " ".join(f"`{x}`" for x in extra[:10])
    advice = f"Root: `{root}`\n{found}\n{route}; or {NAMES_ONLY_ROUTES[tool]}."
    return Hit("prints lines from the env files it reaches", ENV_REACH_RULE, reached[0], context, advice)


def _unchecked_hit(tool: str, context: str, why: str) -> Hit:
    """Return the block for a broad search whose reach cannot be checked."""
    advice = (
        f"Why: {why}.\n"
        "Name the directory literally (`cd /abs/path && ...`, or a literal path operand) "
        f"and exclude env files ({ENV_EXCLUDES[tool]}), or {NAMES_ONLY_ROUTES[tool]}."
    )
    return Hit(
        "is a broad search, and the hook could not check which env files it reaches",
        ENV_REACH_RULE,
        why,
        context,
        advice,
    )


def env_reach(search: EnvSearch, context: str) -> Hit | None:
    """Return a hit when a broad search can print lines from an env file, or when that cannot be checked.

    Each root is listed with `git ls-files` and filtered to env-shaped names,
    then the search's own excludes and includes apply. A root that is not a
    directory, or not in a git work tree, is skipped. When git fails for
    another reason than the deadline (a broken index), a file walk lists the
    root instead. A git timeout, a walk that cannot finish, or an unresolved
    directory blocks.
    """
    if search.roots is None:
        return _unchecked_hit(search.tool, context, "a directory is a variable, a command substitution or `cd -`")
    for root in search.roots:
        if not os.path.isdir(root):
            continue
        if search.positives or search.reads_ignored:
            if probes := [probe for probe in ENV_PROBES if _positive_reaches(search, probe)]:
                return _reach_hit(search.tool, context, root, probes, probe=True, ignored=search.reads_ignored)
            if not search.reads_ignored:
                continue
        try:
            listed = _reach_listing(search, root)
        except GitTimeout as err:
            return _unchecked_hit(search.tool, context, str(err))
        except ReachUnknown as err:
            try:
                listed = _walk_listing(root)
            except ReachUnknown as walk_err:
                return _unchecked_hit(search.tool, context, f"{err}; {walk_err}")
        if reached := [entry for entry in listed or [] if _reaches(search, root, entry)]:
            return _reach_hit(search.tool, context, root, reached)
    return None


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


def secret_path_hit(path: str, new_file: bool = False) -> tuple[str, str] | None:
    """Return (rule, matched text) when a path names credential material, else None.

    ALLOWLIST names are blanked, not exempted, so a token-info file under
    ~/.aws/ still blocks. AUTHORIZED_PATHS exempts the whole path: its
    `/.secrets/` directory form covers every file below it. A bare credential
    word alone (`sidebar-tokens.css`, `hs-token/x.json`) does not count. A file
    that does not exist yet (`new_file`) holds nothing, so only
    SECRET_PATH_SHAPES apply to it.
    """
    if AUTHORIZED_PATHS.search(path):
        return None
    scan = ALLOWLIST.sub(" ", path)
    if m := re.search(SECRET_PATH_SHAPES, scan, re.IGNORECASE):
        return "secret-path", m.group(0)
    if new_file:
        return None
    if m := SECRET_FOLDER.search(scan):
        return "secret-folder", m.group(0)
    if gate_output(path):
        return None
    if m := re.search(SECRET_FILE_SHAPES, scan, re.IGNORECASE) or SYSTEM_SECRET_FILE.search(path):
        return "secret-file", m.group(0)
    return None


def gate_output(path: str) -> bool:
    """Return True when a path's base name is a forge gate output, such as `gate-apikey.log`."""
    return bool(GATE_OUTPUT.search(path.strip("'\"")))


API_KEY_WORD = re.compile(r"api[_-]?keys?", re.IGNORECASE)
API_KEY_SOURCE_EXTENSION = re.compile(r"\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs)$", re.IGNORECASE)
SHELL_WORD = re.compile(r"[^\s;&|<>()`]+")


def api_key_source(path: str) -> bool:
    """Return True when a path is source code whose only secret words are the api-key family.

    A part that starts with `.`, other than `.venv`, `.` or `..`, keeps the
    block: `~/.config/tool/api_key.py` may hold a key.
    """
    path = path.strip("'\"")
    words = [m.group(0) for m in re.finditer(SECRET_BARE_WORDS, ALLOWLIST.sub(" ", path), re.IGNORECASE)]
    return (
        bool(words)
        and all(API_KEY_WORD.fullmatch(word) for word in words)
        and bool(API_KEY_SOURCE_EXTENSION.search(path))
        and not any(part.startswith(".") and part not in (".", "..", ".venv") for part in path.split("/"))
    )


def blank_exempt_paths(text: str) -> str:
    """Blank the shell words that api_key_source() or gate_output() exempts, before a word check."""
    return SHELL_WORD.sub(
        lambda m: " " if api_key_source(m.group(0)) or gate_output(m.group(0)) else m.group(0), text
    )


FORGE_CONFIG = "~/.claude/skills/forge/forge.config.json"
GATE_ARG = r"(?!'?-)(?:'[\w./@+,:~-]+'|[\w./@+,:~-]+)"
# Forge runs a gate command bare, after `cd <dir> &&`, or under its perl alarm wrapper,
# with an optional FORGE_GATE_RUN_ID. No other assignment: `SHELLOPTS=xtrace` traces the
# values the gate loads.
GATE_PREFIX = (
    rf"(?:cd[ \t]+(?P<cd>{GATE_ARG})[ \t]*&&[ \t]*)?"
    rf"(?:FORGE_GATE_RUN_ID={GATE_ARG}[ \t]+)?"
    r"(?:perl[ \t]+-e[ \t]+'alarm shift @ARGV; exec @ARGV'[ \t]+\d+[ \t]+)?"
)
# A log path in a variable: `$L`, `${L}`, quoted or not.
GATE_VAR = r"\$(?:[A-Za-z_]\w*|\{[A-Za-z_]\w*\})"
# Output handling an agent may append to keep the result short: `> log 2>&1`, `2>&1 | tail -40`.
GATE_SUFFIX = (
    rf"(?:[ \t]*>>?[ \t]*(?P<out>{GATE_ARG}|{GATE_VAR}|\"{GATE_VAR}\"))?"
    r"(?:[ \t]*2>&1)?"
    r"(?:[ \t]*\|[ \t]*(?:tail|head)(?:[ \t]+(?:-n[ \t]*\d+|-\d+))?)?"
)
# The only command a gate segment may pipe into; anything else (`| sh`) could run its output.
GATE_PIPE_TARGET = re.compile(r"[ \t]*(?:tail|head)(?:[ \t]+(?:-n[ \t]*\d+|-\d+))?[ \t]*")


def _gate_pattern(template: str) -> re.Pattern[str]:
    """Compile a gate command template: `<paths>` takes plain path words, `<create-db>` is optional."""
    pattern = ""
    for i, part in enumerate(re.split(r"(<paths>|<create-db>)", template)):
        if i % 2 == 0:
            pattern += re.escape(part)
        elif part == "<create-db>":
            pattern += r"(?: --create-db)?"
        elif pattern.endswith(re.escape(" ")):
            pattern = pattern[: -len(re.escape(" "))] + rf"(?P<paths{i}>(?:[ \t]+{GATE_ARG})*)"
        else:
            pattern += rf"(?P<paths{i}>(?:{GATE_ARG}(?:[ \t]+{GATE_ARG})*)?)"
    return re.compile(GATE_PREFIX + pattern + GATE_SUFFIX)


def is_gate_command(command: str) -> bool:
    """Return True when one command segment is a worktree gate command from forge.config.json.

    A config that cannot be read grants nothing. Each path word, the `cd`
    target and an output redirect target must still pass secret_path_hit().
    """
    try:
        with open(posixpath.expanduser(FORGE_CONFIG), encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError, UnicodeError):
        return False
    gates = config.get("gate") if isinstance(config, dict) else None
    if not isinstance(gates, dict):
        return False
    command = command.strip()
    for entry in gates.values():
        worktree = entry.get("worktree") if isinstance(entry, dict) else None
        if not isinstance(worktree, dict):
            continue
        for template in worktree.values():
            if not isinstance(template, str) or not (m := _gate_pattern(template).fullmatch(command)):
                continue
            words = [w for name, value in m.groupdict().items() if value and name != "cd" for w in value.split()]
            words += [m.group("cd")] if m.group("cd") else []
            if not any(secret_path_hit(word.strip("'")) for word in words):
                return True
    return False


CD_TARGET = re.compile(r"[\s({]*(?:cd|pushd)\s+(.*)")
BARE_CD = re.compile(r"[\s({]*(?:cd|pushd)\s*")


def _cd_dir(here: str | None, target: str) -> str | None:
    """Return the directory a `cd`/`pushd` with this target text moves to, or None when it cannot be resolved."""
    try:
        words = [w for w in shlex.split(strip_redirections(target)) if w not in ("-L", "-P", "-e", "-@", "--")]
    except ValueError:
        return None
    if not words:
        return posixpath.expanduser("~")
    return None if words[0] == "-" else _join_dir(here, words[0])
# `--exclude`, `--exclude-from` and `--exclude-dir` with their value, as
# `=value` or the next word. `--exclude-vcs` takes no value and stays.
_OPTION_VALUE = r"""(?:'[^']*'|"[^"]*"|\\.|[^\s'"\\])+"""
EXCLUDE_OPTION = re.compile(rf"(?<!\S)--exclude(?:-from|-dir)?(?:=|\s+){_OPTION_VALUE}")
# An rg `!` glob and a git exclude pathspec, quoted or bare.
EXCLUDE_GLOB_OPTION = re.compile(r"""(?<!\S)(?:-g\s*|--i?glob(?:=|\s+))(?:'![^']*'|"![^"]*"|![^\s'"]*)""")
EXCLUDE_PATHSPEC_WORD = re.compile(
    rf"""(?<!\S)(?:'{_EXCLUDE_MAGIC}[^']*'|"{_EXCLUDE_MAGIC}[^"]*"|{_EXCLUDE_MAGIC}[^\s'"]*)"""
)


def blank_excludes(text: str) -> str:
    """Blank what a search excludes: grep `--exclude*` values, rg `!` globs and git exclude pathspecs."""
    for pattern in (EXCLUDE_OPTION, EXCLUDE_GLOB_OPTION, EXCLUDE_PATHSPEC_WORD):
        text = pattern.sub(" ", text)
    return text


# Search commands the parser could not read, found by their command word.
_LEAD = r"^[\s({]*(?:[A-Za-z_]\w*=\S*\s+)*"
GIT_GREP_COMMAND = re.compile(
    rf"{_LEAD}git(?P<opts>(?:\s+(?:-[Cc]\s+{_OPTION_VALUE}|--(?:git-dir|work-tree|namespace)\s+{_OPTION_VALUE}"
    rf"|--?[\w-]+(?:={_OPTION_VALUE})?))*)\s+grep(?![\w-])"
)
GIT_C_VALUE = re.compile(rf"(?<!\S)-C\s+({_OPTION_VALUE})")
GREP_COMMAND = re.compile(rf"{_LEAD}(?:grep|egrep|fgrep)(?![\w-])")
RECURSIVE_FLAG = re.compile(
    r"(?<!\S)(?:-[A-Za-z0-9]*[rR][A-Za-z0-9]*|--(?:dereference-)?recursive|--directories=rec\w*|-d\s*rec\w*)(?!\S)"
)
RG_COMMAND = re.compile(rf"{_LEAD}rg(?![\w-])")


def unparsed_search_verdict(raw: str, here: str | None, fed_by_pipe: bool) -> Hit | None:
    """Check a git grep, recursive grep or rg segment that parse_reader() could not read.

    It gets a whole-repo env-reach check from the effective directory, with
    no excludes, since its options are unknown. A command substitution, or a
    `-C` value that holds a variable, leaves the directory unresolved.
    """
    unquoted = blank_quoted(raw, "'\"")
    git = GIT_GREP_COMMAND.match(raw)
    if git:
        tool = "git grep"
    elif GREP_COMMAND.match(raw) and RECURSIVE_FLAG.search(unquoted):
        tool = "grep"
    elif RG_COMMAND.match(raw) and not fed_by_pipe:
        tool = "rg"
    else:
        return None
    # git's own options (`git -c k=v grep`) come before grep's; only grep's count here.
    words = (blank_quoted(raw[git.end() :], "'\"") if git else unquoted).split()
    if set(words) & NAMES_ONLY_OPTS[tool]:
        return None
    root = None if has_substitution(raw) else here
    for m in GIT_C_VALUE.finditer(git.group("opts") if git else ""):
        try:
            values = shlex.split(m.group(1))
        except ValueError:
            values = []
        root = _join_dir(root, values[0]) if root is not None and values else None
    search = EnvSearch(tool, None if root is None else [root], untracked="--untracked" in words)
    hit = env_reach(search, raw)
    if hit is None or root is None:
        return hit
    note = "The hook could not parse this command, so it applied none of its excludes; drop the options it does not know."
    return hit._replace(advice=f"{hit.advice}\n{note}")


# A grep call up to the end of its arguments, followed by redirects to
# /dev/null only and then the end of a command or of a quoted `sh -c` script.
GREP_CALL = re.compile(
    r"(?<![\w./-])[ef]?grep(?:[ \t]+(?:'[^']*'|\"[^\"]*\"|[^\s;&|<>()'\"`]+))+"
    r"(?:[ \t]*(?:[\d&]?>>?[ \t]*/dev/null|\d?>&\d))*"
    r"(?=[ \t]*(?:$|[;\n'\"]|&&|\|\||&(?![>&])))"
)
SAFE_REDIRECT = re.compile(r"[\d&]?>>?[ \t]*/dev/null|\d?>&\d")


def blank_names_only_env_greps(segment: str, feeds_pipe: bool) -> str:
    """Blank the env-file operands of each grep that prints only names, counts or nothing.

    `grep -q`, `-c`, `-l` and `-L` print no line of an env file. `-o` still
    does, and a pipe, a file redirect or a substitution can hand the names on
    to another reader (`grep -l X .env | xargs cat`), so those keep the segment whole.
    """
    if (
        feeds_pipe
        or any(s in segment for s in ("$(", "`", "<(", ">("))
        or re.search(r"(?<!\|)\|(?!\|)", segment)
        or ">" in SAFE_REDIRECT.sub(" ", segment)
    ):
        return segment

    def blank(m: re.Match[str]) -> str:
        args = parse_reader(m.group(0))
        if args is None or args.family != "grep" or args.stdin_files:
            return m.group(0)
        names = {name for name, _ in args.options}
        if not names & NAMES_ONLY_OPTS["grep"] or names & {"-o", "--only-matching"}:
            return m.group(0)
        env_files = {f for f in args.files if env_path(f)}
        return re.sub(r"[^\s'\"]+", lambda t: " " if t.group(0) in env_files else t.group(0), m.group(0))

    return GREP_CALL.sub(blank, segment)


# A jq field projection (`.a`, `.a.b`, `{a,b}`, `.a | length`) of one token-info
# file, such as a vendor's `01-vendorx-token-info.json`.
_JQ_FIELD = r"[A-Za-z_]\w*"
JQ_PROJECTION = re.compile(
    rf"(?:\.{_JQ_FIELD}(?:\.{_JQ_FIELD})*|\{{\s*{_JQ_FIELD}(?:\s*,\s*{_JQ_FIELD})*\s*\}})(?:\s*\|\s*length)?"
)
JQ_TOKEN_INFO_CALL = re.compile(
    r"^\s*jq(?:\s+--?[A-Za-z][\w-]*)*\s+(?P<filter>'[^']*'|\"[^\"]*\"|\.[\w.]+)"
    r"\s+(?P<file>[^\s'\";&|<>()`]*token[_-]info\.json)\s*$",
    re.IGNORECASE,
)


def blank_jq_projection(text: str) -> str:
    """Blank the token-info operand of a jq call that prints only named fields.

    The file holds a token, so `jq .`, a field named like a secret (`.token`,
    `.access_token`) and a file under a credential path (`~/.aws/`) keep it.
    """
    m = JQ_TOKEN_INFO_CALL.match(text)
    if not m or not JQ_PROJECTION.fullmatch(m.group("filter").strip("'\"").strip()):
        return text
    fields = set(re.findall(_JQ_FIELD, m.group("filter"))) - {"length"}
    if any(
        re.search(SECRET_BARE_WORDS, field, re.IGNORECASE) or re.fullmatch(SECRET_VAR_NAME, field, re.IGNORECASE)
        for field in fields
    ):
        return text
    path = m.group("file")
    if re.search(SECRET_PATH_SHAPES, path, re.IGNORECASE) or SECRET_FOLDER.search(path):
        return text
    return text[: m.start("file")] + " " + text[m.end("file") :]


ENV_RECIPE = "~/.claude/references/env-recipe.md"
SOURCE_ENV_ADVICE = (
    f"To load an env file for a command, follow {ENV_RECIPE}: write a runner script with the Write tool, "
    "then run `bash <runDir>/with-env.sh <command>`. A relative `set -a; . .envs/<file>; set +a` is "
    "allowed in a command with no `$` expansion and no env dump."
)
ENV_NAMES_ADVICE = (
    "To check which names an env file sets, use `grep -q '^NAME=.' <file>` or `grep -c '^NAME=' <file>`; "
    "they print no value. `cut` and `awk` print whole lines, values included."
)


def env_read_advice(command: str | None, path: str) -> str:
    """Return the route for a blocked env-file read by command (None for the `.` shorthand), or ""."""
    if not re.search(ENV_PATH_SHAPES, path, re.IGNORECASE):
        return ""
    if command is None or command.lower() == "source":
        return SOURCE_ENV_ADVICE
    if command.lower() in ("cut", "awk"):
        return ENV_NAMES_ADVICE
    return ""


# Heredoc bodies are data unless a shell or interpreter on the header line
# will execute them; strip_heredoc_bodies() applies that split before
# segments are checked below.
def verdict(command: str, cwd: str | None) -> Hit | None:
    """Return why to block a command run in cwd (None when unknown), or None to allow."""
    sources_repo_env = ENV_DUMP_WORD.search(command) is None
    heredocs = strip_heredoc_bodies(command)
    command = heredocs.head
    for body, words in heredocs.interpreter_bodies:
        for scan in interpreter_body_scans(body, words):
            scan = AUTHORIZED_PATHS.sub(" ", ALLOWLIST.sub(" ", scan))
            if sources_repo_env:
                scan = SOURCED_REPO_ENV.sub(r"\g<lead> ", scan)
            if m := INTERPRETER_BODY_SECRET.search(scan):
                return Hit(
                    "runs code that names a credential-bearing path", "interpreter-body-secret", m.group(0), body
                )
    piped: list[bool] = []
    segments = split_segments(command, piped)
    # Any other command may run a messenger's text: `echo "..." | bash`.
    messengers = is_quiet(command)
    shell_quotes = reruns_quotes(command)
    # A search after `cd ~/.config/gh` reads a dot-directory like a search
    # that names it.
    dot_cd = False
    # The directory a search runs in; None once a `cd` cannot be resolved.
    here = cwd
    # The directory to restore when a `( ... )` subshell closes.
    outer: list[str | None] = []
    # Evaluate each pipeline/list segment separately so one safe segment in a
    # compound command cannot mask an unsafe one.
    for i, (raw, feeds_pipe) in enumerate(zip(segments, piped)):
        if i and segments[i - 1].rstrip().endswith(")") and outer:
            here = outer.pop()
        if raw.lstrip().startswith("("):
            outer.append(here)
        if is_gate_command(raw) and (
            not feeds_pipe or (GATE_PIPE_TARGET.fullmatch(segments[i + 1]) and not piped[i + 1])
        ):
            continue
        if cd := CD_TARGET.match(raw):
            dot_cd = dot_cd or any(has_dot_part(word) for word in cd.group(1).split())
        if cd or BARE_CD.fullmatch(raw):
            here = _cd_dir(here, cd.group(1) if cd else "")
        read = blank_names_only_env_greps(raw, feeds_pipe)
        # Blank out only the allowlisted paths, never the whole segment:
        # `diff .env .env.example` reads the real file and must still block.
        segment = AUTHORIZED_PATHS.sub(" ", ALLOWLIST.sub(" ", read))
        if sources_repo_env:
            segment = SOURCED_REPO_ENV.sub(r"\g<lead> ", segment)
        if not segment.strip():
            continue
        if m := SECRET_COMMANDS.search(segment):
            return Hit("prints a stored credential", "secret-command", m.group(0), raw)
        # Tokenized before allowlist blanking: that must not shift which
        # token is the pattern.
        if (reader := parse_reader(read)) is not None:
            fed_by_pipe = i > 0 and piped[i - 1]
            if hit := reader_verdict(reader, raw, fed_by_pipe=fed_by_pipe, here=here):
                return hit
            # rg recurses into every directory operand, so any rg that reads
            # files rather than stdin gets the plain reader word check.
            if reader.family == "rg" and (reader.files or not fed_by_pipe):
                reader_text = blank_excludes(strip_redirections(segment, output_only=True))
                if m := READER_NEAR_SECRET_WORD.search(word_scan(blank_exempt_paths(reader_text))):
                    return Hit("reads a credential-bearing path", "reader-near-secret-word", m.group(0), raw)
            # A dot-directory (~/.config/rclone/rclone.conf) or a variable operand
            # may hold credentials, so a secret word in the pattern still blocks.
            # A variable operand with a literal source extension ($R/app.py) is
            # a source file. Names-only output (-l, -c) prints no line unless a
            # pipe hands the names on: `grep -l token ~/.config/rclone/* | xargs cat`.
            dotted = dot_cd or any(
                has_dot_part(f) or ("$" in f and not _code_file(f)) for f in read_operands(reader)
            )
            names_only = {name for name, _ in reader.options} & NAMES_ONLY_OPTS.get(
                reader.family, set()
            )
            word = READER_NEAR_SECRET_WORD.search(word_scan(blank_exempt_paths(blank_excludes(segment))))
            if dotted and (feeds_pipe or not names_only) and (m := word):
                return Hit("reads a credential-bearing path", "reader-near-secret-word", m.group(0), raw)
        else:
            # A file the command writes or excludes is not read.
            reader_text = blank_jq_projection(blank_excludes(strip_redirections(segment, output_only=True)))
            scan = reader_text
            if messengers and is_messenger(raw):
                scan = blank_plain_quotes(reader_text, prose_only=True)
            if m := READER_NEAR_SECRET.search(scan):
                return Hit(
                    "reads a credential-bearing path",
                    "reader-near-secret",
                    m.group(0),
                    raw,
                    env_read_advice(m.group(1), m.group(2)),
                )
            if m := READER_NEAR_SECRET_FILE.search(pattern_scan(blank_exempt_paths(scan))):
                return Hit("reads a credential-bearing path", "reader-near-secret-file", m.group(0), raw)
            if m := READER_NEAR_SECRET_WORD.search(word_scan(blank_exempt_paths(reader_text))):
                return Hit("reads a credential-bearing path", "reader-near-secret-word", m.group(0), raw)
            if hit := unparsed_search_verdict(raw, here, fed_by_pipe=i > 0 and piped[i - 1]):
                return hit
        # A `<` inside quotes is text (`sed 's/x/<token-redacted>/'`), unless a shell may run the quotes again.
        redirects = segment if shell_quotes else blank_plain_quotes(segment)
        if m := REDIRECT_FROM_SECRET.search(redirects):
            return Hit("redirects input from a credential-bearing path", "redirect-from-secret", m.group(0), raw)
        if m := REDIRECT_FROM_SECRET_WORD.search(redirects):
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
# An `env=` keyword argument hands the environment to a child process, which
# inherits it anyway. The assignment `env = dict(os.environ)` is not one:
# `print(env)` may follow.
PY_ENV_KWARG = re.compile(
    r"(?P<lead>[(,]\s*)env\s*=\s*"
    r"(?:os\.environ\b(?!\s*[\[.])|\{\s*\*\*\s*os\.environ\b(?!\s*[\[.])|dict\(\s*os\.environ\s*\))"
)
PYTHON_C_ARG = re.compile(r"\bpython3?\s+-c\s+(?=['\"])")

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


def _python_code(program: str) -> str:
    """Return a Python program without its string literals, or whole when it shells out or does not tokenize."""
    parts = None if shells_out(program, {"python"}) else _python_parts(program)
    return program if parts is None else parts[0]


def _python_c_code(head: str) -> str:
    """Return head with each quoted `python3 -c` program reduced to its code by _python_code().

    A double-quoted program holding `$(` or a backtick stays whole: the shell
    runs that before Python sees the text.
    """
    out: list[str] = []
    last = 0
    for m in PYTHON_C_ARG.finditer(head):
        start = m.end()
        if start < last:
            continue
        end = _quote_end(head, start)
        if end is None:
            break
        program = head[start + 1 : end - 1]
        if head[start] == '"':
            if "$(" in program or "`" in program:
                continue
            program = re.sub(r'\\([\\"$`])', r"\1", program)
        out += [head[last:start], f" {_python_code(program)} "]
        last = end
    return "".join(out) + head[last:]


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
        # Indexed references keep their literal names (`os.environ['API_KEY']`); a
        # wholesale reference counts only in Python code, outside string literals.
        code = [
            _python_c_code(head),
            *(_python_code(body) if words == {"python"} else body for body, words in heredocs.interpreter_bodies),
            *heredocs.rerun_bodies,
        ]
        wholesale = PY_ENV_KWARG.sub(r"\g<lead> ", PYNODE_LEN_STRIP.sub(" ", "\n".join(code)))
        if m := PYNODE_SECRET_REF.search(stripped) or PYNODE_WHOLESALE.search(wholesale):
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


def path_verdict(file_path: str, new_file: bool = False) -> Hit | None:
    """Return why to block a direct file read, or None to allow."""
    if found := secret_path_hit(file_path, new_file):
        rule, fragment = found
        return Hit("reads a credential-bearing path", rule, fragment, file_path)
    return None


def grep_tool_verdict(tool_input: dict, cwd: str | None) -> Hit | None:
    """Check a Grep tool call: its path and glob, then the env files a content search reaches.

    A glob that starts with `!` excludes files, so it is not a path the call
    reads. The Grep tool searches like `rg --hidden`.
    """
    hit = None
    for field in PATH_FIELDS["Grep"]:
        value = tool_input.get(field) or ""
        if isinstance(value, str) and not (field == "glob" and value.startswith("!")):
            hit = hit or path_verdict(value)
    path, glob = tool_input.get("path") or "", tool_input.get("glob") or ""
    if hit or tool_input.get("output_mode") != "content" or not isinstance(path, str) or not isinstance(glob, str):
        return hit
    path = posixpath.expanduser(path)
    if not path:
        root = cwd
    elif cwd is not None or path.startswith("/"):
        root = posixpath.normpath(posixpath.join(cwd or "/", path))
    else:
        root = None
    off_root = root is not None and root != posixpath.normpath(cwd or "")
    excludes = ((glob[1:], "any"),) if glob.startswith("!") and not (off_root and glob.startswith("!/")) else ()
    if off_root and not glob.startswith("!"):
        glob = glob.lstrip("/")
    positives = (glob,) if glob and not glob.startswith("!") else ()
    search = EnvSearch("Grep", None if root is None else [root], excludes=excludes, positives=positives)
    return env_reach(search, root or path)


def raw_dump_path_verdict(file_path: str) -> str | None:
    """Return a reason to block a Read of a trace, HAR, or auth storage-state file."""
    if RAW_DUMP_READ_PATH.search(file_path):
        return f"reads a trace, HAR, or auth-state file raw {matched('raw-dump-read', file_path)}"
    return None


NO_RESHAPE = (
    "Use only the routes this message names. Do not rewrite the command to hide what matched "
    "(split or build names, encode paths, move it into a script); if no route fits, stop and report the block."
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError, UnicodeError):
        return 0

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    cwd = start_dir(payload)

    if tool_name == "Bash":
        target = tool_input.get("command") or ""
        if not isinstance(target, str):
            return 0
        if reason := secret_var_verdict(target):
            quoted_route = (
                "If the match is quoted text, not code that reads the environment: put the text "
                "in a file, or write it with the Edit tool.\n"
                if "(rule interpreter-env-ref," in reason
                else ""
            )
            print(
                f"Blocked by block_secret_reads hook: this command {reason}. "
                "Pass secrets to programs via their "
                "own flags/env, never through od/xxd/echo/printf or an "
                "unfiltered env dump; if you must inspect a value's shape, "
                f"report only its length.\n{quoted_route}{NO_RESHAPE}",
                file=sys.stderr,
            )
            return 2
        if reason := raw_dump_verdict(target):
            return block_raw_dump("command", reason)
        hit, noun = verdict(target, cwd), "command"
    elif tool_name == "Grep":
        hit, noun = grep_tool_verdict(tool_input, cwd), "tool call"
    elif tool_name in PATH_FIELDS:
        if tool_name == "Read" and isinstance(tool_input.get("file_path"), str):
            if reason := raw_dump_path_verdict(tool_input["file_path"]):
                return block_raw_dump("tool call", reason)
        hit, noun = None, "tool call"
        for field in PATH_FIELDS[tool_name]:
            value = tool_input.get(field) or ""
            if isinstance(value, str):
                new_file = tool_name == "Write" and not os.path.lexists(
                    posixpath.join(cwd or "", posixpath.expanduser(value))
                )
                hit = hit or path_verdict(value, new_file)
    else:
        return 0

    if hit is None:
        return 0
    if hit.rule == ENV_REACH_RULE:
        return block_env_reach(noun, hit)
    return block_secret_read(noun, hit)


def start_dir(payload: dict) -> str | None:
    """Return the payload's cwd when it is a string, else the hook's own working directory."""
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        return cwd
    try:
        return os.getcwd()
    except OSError:
        return None


def _block_context(noun: str, hit: Hit) -> str:
    """Return the Segment or Path line of a block message."""
    if noun == "command":
        return f"Segment: `{' '.join(hit.context.split())[:120]}`"
    return f"Path: `{hit.context}`"


def block_env_reach(noun: str, hit: Hit) -> int:
    print(
        f"Blocked by block_secret_reads hook (rule {hit.rule}): this {noun} {hit.reason}.\n"
        f"{_block_context(noun, hit)}\n{hit.advice}\n{NO_RESHAPE}",
        file=sys.stderr,
    )
    return 2


def block_secret_read(noun: str, hit: Hit) -> int:
    # The rule sits in parentheses on the first line so a parser can read it.
    context = _block_context(noun, hit)
    routes = hit.advice or (
        "If this reads a credential file, ask the user for the value instead of printing it.\n"
        "If the matched text is a search pattern, not a file: put the pattern in a file and pass "
        "`grep -f <file>`, or search with the Grep tool. If it is prose, put the text in a file "
        "and pass the file name."
    )
    print(
        f"Blocked by block_secret_reads hook (rule {hit.rule}): this {noun} {hit.reason}.\n"
        f"{context}\n"
        f"Matched: `{' '.join(hit.fragment.split())[:80]}`\n"
        f"{routes}\n"
        f"Files tracked in git already exist in every git worktree; do not copy them.\n{NO_RESHAPE}",
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
        f"`zipinfo`), and `npx playwright show-trace` stay allowed.\n{NO_RESHAPE}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
