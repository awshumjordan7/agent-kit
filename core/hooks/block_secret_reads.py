#!/usr/bin/env python3
"""PreToolUse guard: block tool calls that would read secret files.

Covers Bash (command text) and the path-bearing tools: Read, Grep, Edit,
Write, NotebookEdit, Artifact. Any tool that can put file contents into the
transcript -- or, for Artifact, onto a hosted page -- needs a check here.

The settings.json Read(...) deny rules do NOT cover the Read tool here:
defaultMode is bypassPermissions, which skips permission evaluation entirely,
so every deny rule is inert. Hooks still run in that mode, which makes this
file the only enforcement point for both tools. Keep the deny rules -- they
apply if the default mode ever changes -- but do not rely on them.

Fail-open by design. Any unexpected input, parse error, or unmatched command
exits 0 (allow). A bug here must never be able to brick the shell -- the cost
is that this is an accident guardrail, not a security boundary. A determined
path around it always exists (see KNOWN GAPS below).

KNOWN GAPS, deliberately not covered:
  - `docker inspect` / `docker exec ... env` can surface container env vars.
    Blocking those would have prevented legitimate diagnostic work.
  - Arbitrary interpreters (`python -c`, `node -e`) with obfuscated paths.
  - Reading a secret indirectly: copy to a neutral name first, then read.
Tighten only if the threat model changes; today's goal is preventing careless
credential exposure, not defeating circumvention.

Raw dumps of Playwright traces, HAR files, and auth storage-state files are
blocked separately; scripts/trace-read.py in the forge skill prints a redacted
view of them instead.

Exit codes: 2 = block (stderr is shown to Claude), 0 = allow.
"""

import json
import re
import sys

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
    r"secrets?\.md|credentials?\.md|token[_-]?claim",
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
    rf"(?:\b({READERS})\b|(?<![^\s])\.(?=\s))[^;&|]*?({SECRET_PATH_SHAPES}|{SECRET_FILE_SHAPES})",
    re.IGNORECASE,
)

# Bare secret words after a reader. Matched against word_scan(segment), not the
# raw segment, so .md file names and quoted prose do not trigger it.
READER_NEAR_SECRET_WORD = re.compile(
    rf"(?:\b({READERS})\b|(?<![^\s])\.(?=\s))[^;&|]*?({SECRET_BARE_WORDS})",
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


def word_scan(segment: str) -> str:
    """Return the segment with prose and .md names blanked for the word check."""
    scan = MD_TOKEN.sub(" ", QUOTED_PROSE.sub(" ", segment))
    return QUOTED_ANY.sub(" ", scan) if PATTERN_ONLY.match(scan) else scan


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
HEREDOC_OPEN = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")

# Commands that will actually execute a heredoc body handed to them, as
# opposed to just writing it out or filing it away unread. A shell runs the
# body as commands, so it gets the full scan; an interpreter body is code
# whose string literals are often prose (a STATE.md rewrite), so it is checked
# for path-shaped secrets only.
HEREDOC_SHELL = re.compile(
    r"\b(bash|sh|zsh|dash|ksh|fish|eval|exec|ssh|sudo|env|xargs|source)\b",
    re.IGNORECASE,
)
HEREDOC_INTERPRETER = re.compile(r"\b(python3?|node|perl|ruby|php)\b", re.IGNORECASE)

INTERPRETER_BODY_SECRET = re.compile(SECRET_PATH_SHAPES, re.IGNORECASE)


def strip_heredoc_bodies(command: str) -> tuple[str, list[str]]:
    """Drop heredoc body lines that are inert data instead of executed code.

    Scans line by line: a line matching `<<-?(['"]?)(\\w+)\\1` opens a heredoc
    whose body runs to the first line equal to the terminator (leading tabs
    allowed when the opener is `<<-`). If the header line (the whole line,
    every pipeline stage) names a shell -- bash, eval, ssh, sudo, source, and
    the like -- the body is kept in the returned command for the full scan.
    If it names only an interpreter -- python3, node, perl, ruby, php -- the
    body is removed from the command and returned separately for the
    path-only check. Otherwise the body is dropped and only the header line
    remains. Several heredocs in one command are handled in order, and an
    unterminated heredoc runs to end of text under the same rule.
    """
    lines = command.split("\n")
    out: list[str] = []
    interpreter_bodies: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        header = lines[i]
        out.append(header)
        match = HEREDOC_OPEN.search(header)
        if not match:
            i += 1
            continue
        terminator = match.group(2)
        strip_tabs = match.group(0).startswith("<<-")
        shell = bool(HEREDOC_SHELL.search(header))
        interpreter = not shell and bool(HEREDOC_INTERPRETER.search(header))
        j = i + 1
        while j < n:
            candidate = lines[j].lstrip("\t") if strip_tabs else lines[j]
            if candidate == terminator:
                break
            j += 1
        body = lines[i + 1 : j + 1] if j < n else lines[i + 1 : n]
        if shell:
            out.extend(body)
        elif interpreter:
            interpreter_bodies.append("\n".join(body))
        i = j + 1
    return "\n".join(out), interpreter_bodies


def matched(rule: str, text: str) -> str:
    """Name the rule and the command text it matched, never a file or variable value."""
    fragment = " ".join(text.split())[:80]
    return f"(rule {rule}, matched `{fragment}`)"


SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")


# Heredoc bodies are data unless a shell or interpreter on the header line
# will execute them; strip_heredoc_bodies() applies that split before
# segments are checked below.
def verdict(command: str) -> str | None:
    """Return a human-readable reason to block, or None to allow."""
    command, interpreter_bodies = strip_heredoc_bodies(command)
    for body in interpreter_bodies:
        body = ALLOWLIST.sub(" ", body)
        body = AUTHORIZED_PATHS.sub(" ", body)
        if m := INTERPRETER_BODY_SECRET.search(body):
            return f"runs code that names a credential-bearing path {matched('interpreter-body-secret', m.group(0))}"
    # Evaluate each pipeline/list segment separately so one safe segment in a
    # compound command cannot mask an unsafe one.
    for segment in SEGMENT_SPLIT.split(command):
        if not segment.strip():
            continue
        # Blank out only the allowlisted paths, never the whole segment:
        # `diff .env .env.example` reads the real file and must still block.
        segment = ALLOWLIST.sub(" ", segment)
        segment = AUTHORIZED_PATHS.sub(" ", segment)
        if not segment.strip():
            continue
        if m := SECRET_COMMANDS.search(segment):
            return f"prints a stored credential {matched('secret-command', m.group(0))}"
        if m := READER_NEAR_SECRET.search(segment):
            return f"reads a credential-bearing path {matched('reader-near-secret', m.group(0))}"
        if m := READER_NEAR_SECRET_WORD.search(word_scan(segment)):
            return f"reads a credential-bearing path {matched('reader-near-secret-word', m.group(0))}"
        if m := REDIRECT_FROM_SECRET.search(segment):
            return f"redirects input from a credential-bearing path {matched('redirect-from-secret', m.group(0))}"
        if m := REDIRECT_FROM_SECRET_WORD.search(segment):
            return f"redirects input from a credential-bearing path {matched('redirect-from-secret-word', m.group(0))}"
    return None


def raw_dump_verdict(command: str) -> str | None:
    """Return a reason to block a raw dump of a trace, HAR, or storage-state file."""
    command, _ = strip_heredoc_bodies(command)
    for segment in SEGMENT_SPLIT.split(command):
        if RAW_DUMP_COMMAND.match(segment) and RAW_DUMP_TARGET.search(OUTPUT_REDIRECT.sub(" ", segment)):
            return f"dumps a trace, HAR, or auth-state file raw {matched('raw-dump', segment)}"
    return None


# --- Secret-bearing shell variables (values, not paths) -------------------
#
# A variable name shaped like a credential: $API_KEY, ${TOKEN}, "$DB_PASSWORD".
SECRET_VAR_NAME = r"\w*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)\w*"
SECRET_VAR_EXPANSION = re.compile(rf"\$\{{?({SECRET_VAR_NAME})\b", re.IGNORECASE)

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
_ENV_DUMP_GREP_SECRET = re.compile(
    rf"{_BOUNDARY_BEFORE}\s*(?:env(?:\s+-0)?|printenv|set)\s*\|\s*grep\b"
    rf"(?:\s+-\S+)*\s+({SECRET_VAR_NAME})\b",
    re.IGNORECASE,
)

JQ_ENV_DUMP = re.compile(r"\bjq\s+(?:-n|--null-input)\b[^|;&\n]*\benv\b", re.IGNORECASE)

PRINTENV_SECRET = re.compile(rf"\bprintenv\s+({SECRET_VAR_NAME})\b", re.IGNORECASE)
DECLARE_P_SECRET = re.compile(rf"\bdeclare\s+-p\s+({SECRET_VAR_NAME})\b", re.IGNORECASE)

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


# Code in a quoted heredoc body that hands text to a shell, where a $VAR in it
# would be expanded and printed.
SHELL_OUT = re.compile(r"os\.system|subprocess|popen|child_process|execSync|spawn|`", re.IGNORECASE)


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
    """
    quoted = all(m.group(1) for m in HEREDOC_OPEN.finditer(command))
    head, bodies = strip_heredoc_bodies(command) if quoted else (command, [])
    for body in bodies:
        if SHELL_OUT.search(body) and (m := SECRET_VAR_EXPANSION.search(body)):
            return f"would print a secret-bearing variable {matched('heredoc-shell-out', m.group(0))}"
    if m := ENV_DUMP_BARE.search(head) or _ENV_DUMP_NONFILTER.search(head):
        return f"would dump the full environment {matched('env-dump', m.group(0))}"
    if m := _ENV_DUMP_GREP_SECRET.search(head):
        return f"would print a secret-bearing variable {matched('env-grep-secret', m.group(0))}"
    if m := JQ_ENV_DUMP.search(head):
        return f"would dump the full environment {matched('jq-env-dump', m.group(0))}"
    if m := PRINTENV_SECRET.search(head) or DECLARE_P_SECRET.search(head):
        return f"would print a secret-bearing variable {matched('printenv-secret', m.group(0))}"
    scrubbed = CURL_AUTH_SAFE.sub(" ", head)
    if DUMP_TRANSFORM_COMMANDS.search(scrubbed) and (m := SECRET_VAR_EXPANSION.search(scrubbed)):
        return f"would print a secret-bearing variable {matched('dump-secret-var', m.group(0))}"
    if PYNODE_INVOCATION.search(command):
        stripped = PYNODE_LEN_STRIP.sub(" ", command)
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


def path_verdict(file_path: str) -> str | None:
    """Return a reason to block a direct file read, or None to allow."""
    if ALLOWLIST.search(file_path) or AUTHORIZED_PATHS.search(file_path):
        return None
    if re.search(SECRET_PATH_SHAPES, file_path, re.IGNORECASE):
        return f"reads a credential-bearing path {matched('secret-path', file_path)}"
    if not file_path.lower().endswith(".md") and re.search(SECRET_BARE_WORDS, file_path, re.IGNORECASE):
        return f"reads a credential-bearing path {matched('secret-word', file_path)}"
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
        reason, noun = verdict(target), "command"
    elif tool_name in PATH_FIELDS:
        if tool_name == "Read" and isinstance(tool_input.get("file_path"), str):
            if reason := raw_dump_path_verdict(tool_input["file_path"]):
                return block_raw_dump("tool call", reason)
        reason, noun = None, "tool call"
        for field in PATH_FIELDS[tool_name]:
            value = tool_input.get(field) or ""
            if isinstance(value, str):
                reason = reason or path_verdict(value)
    else:
        return 0

    if reason is None:
        return 0

    print(
        f"Blocked by block_secret_reads hook: this {noun} {reason}.\n"
        "Secret files are off-limits. The settings.json deny rules are inert "
        "under bypassPermissions, so this hook is the enforcement point for "
        "both Bash and Read. If you genuinely need a value from one, ask the "
        "user to provide it rather than printing the file.",
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
