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
# so READERS x SECRET_PATHS cannot catch them.
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
# Two subtleties, both found by the test suite rather than by inspection:
#   - `.envs?\b` (not `.env\b`) is required to catch a repository's real secrets
#     file, service/.envs/.django -- `.env\b` fails on ".envs" because
#     "v"->"s" is not a word boundary.
#   - The bare-word patterns need trailing \b or they match inside ordinary
#     identifiers: "token" hits "tokenize", "secret" hits "secretary".
SECRET_PATHS = (
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
    r"\bcredentials?\b|\bsecrets?\b|\bpasswd\b|\bshadow\b|"
    r"\.pem\b|\.p12\b|\.pfx\b|\.jks\b|\.keystore\b|"
    r"\btokens?\b|\bapi[_-]?keys?\b"
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
    rf"(?:\b({READERS})\b|(?<![^\s])\.(?=\s))[^;&|]*?({SECRET_PATHS})",
    re.IGNORECASE,
)

# A redirect out of a secret file, e.g. `< .env` or `while read < .env`.
REDIRECT_FROM_SECRET = re.compile(rf"<\s*[^\s;&|]*({SECRET_PATHS})", re.IGNORECASE)

# A heredoc opener: `<<` or `<<-`, optional quoting around the terminator word.
HEREDOC_OPEN = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")

# Commands that will actually execute a heredoc body handed to them, as
# opposed to just writing it out or filing it away unread.
HEREDOC_EXECUTOR = re.compile(
    r"\b(bash|sh|zsh|dash|ksh|fish|python3?|node|perl|ruby|php|eval|exec|ssh|sudo|env|xargs|source)\b",
    re.IGNORECASE,
)


def strip_heredoc_bodies(command: str) -> str:
    """Drop heredoc body lines that are inert data instead of executed code.

    Scans line by line: a line matching `<<-?(['"]?)(\\w+)\\1` opens a heredoc
    whose body runs to the first line equal to the terminator (leading tabs
    allowed when the opener is `<<-`). If the header line (the whole line,
    every pipeline stage) names an interpreter or shell -- bash, python3,
    eval, ssh, source, and the like -- the body is kept for scanning;
    otherwise the body is dropped and only the header line remains. Several
    heredocs in one command are handled in order, and an unterminated heredoc
    drops to end of text under the same keep/drop rule.
    """
    lines = command.split("\n")
    out: list[str] = []
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
        executed = bool(HEREDOC_EXECUTOR.search(header))
        j = i + 1
        while j < n:
            candidate = lines[j].lstrip("\t") if strip_tabs else lines[j]
            if candidate == terminator:
                break
            j += 1
        if executed:
            out.extend(lines[i + 1 : j + 1] if j < n else lines[i + 1 : n])
        i = j + 1
    return "\n".join(out)


# Heredoc bodies are data unless an interpreter on the header line will
# execute them; strip_heredoc_bodies() applies that split before segments
# are checked below.
def verdict(command: str) -> str | None:
    """Return a human-readable reason to block, or None to allow."""
    command = strip_heredoc_bodies(command)
    # Evaluate each pipeline/list segment separately so one safe segment in a
    # compound command cannot mask an unsafe one.
    segments = re.split(r"&&|\|\||;|\||\n", command)
    for segment in segments:
        if not segment.strip():
            continue
        # Blank out only the allowlisted paths, never the whole segment:
        # `diff .env .env.example` reads the real file and must still block.
        segment = ALLOWLIST.sub(" ", segment)
        segment = AUTHORIZED_PATHS.sub(" ", segment)
        if not segment.strip():
            continue
        if SECRET_COMMANDS.search(segment):
            return "prints a stored credential"
        if READER_NEAR_SECRET.search(segment):
            return "reads a credential-bearing path"
        if REDIRECT_FROM_SECRET.search(segment):
            return "redirects input from a credential-bearing path"
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


def secret_var_verdict(command: str) -> str | None:
    """Return a reason to block a command that would print a secret
    variable's value, or None to allow.

    Checked against the whole command rather than split into pipeline
    units: a `python3 -c "import os; print(...)"` argument routinely
    contains its own `;`, which would otherwise get cut apart by a
    unit split and hide the very thing being checked for.
    """
    if ENV_DUMP_BARE.search(command) or _ENV_DUMP_NONFILTER.search(command):
        return "would dump the full environment"
    if _ENV_DUMP_GREP_SECRET.search(command):
        return "would print a secret-bearing variable"
    if JQ_ENV_DUMP.search(command):
        return "would dump the full environment"
    if PRINTENV_SECRET.search(command) or DECLARE_P_SECRET.search(command):
        return "would print a secret-bearing variable"
    scrubbed = CURL_AUTH_SAFE.sub(" ", command)
    if DUMP_TRANSFORM_COMMANDS.search(scrubbed) and SECRET_VAR_EXPANSION.search(scrubbed):
        return "would print a secret-bearing variable"
    if PYNODE_INVOCATION.search(command):
        stripped = PYNODE_LEN_STRIP.sub(" ", command)
        if PYNODE_SECRET_REF.search(stripped) or PYNODE_WHOLESALE.search(stripped):
            return "would print a secret-bearing variable"
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
    if re.search(SECRET_PATHS, file_path, re.IGNORECASE):
        return "reads a credential-bearing path"
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
        if secret_var_verdict(target):
            print(
                "Blocked by block_secret_reads hook: this command would print "
                "a secret-bearing variable. Pass secrets to programs via their "
                "own flags/env, never through od/xxd/echo/printf or an "
                "unfiltered env dump; if you must inspect a value's shape, "
                "report only its length.",
                file=sys.stderr,
            )
            return 2
        reason, noun = verdict(target), "command"
    elif tool_name in PATH_FIELDS:
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


if __name__ == "__main__":
    sys.exit(main())
