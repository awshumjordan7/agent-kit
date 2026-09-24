#!/usr/bin/env bash
# codex-exec.sh — the single place forge shells the OpenAI Codex CLI.
# Centralizes model/effort/sandbox flags, thread persistence, the prompt
# contract, budget guards, stall detection, and completion verification, so the
# CLI contract lives in exactly one file (SKILL.md and forge-core.js both call this).
#
# Usage:
#   codex-exec.sh config [--role impl|review|plan-review]   # print the resolved settings and exit
#   codex-exec.sh start  --thread-file <f> --prompt-file <p> --log <events.jsonl> --out <last-msg.md> \
#                        [--sandbox read-only|workspace-write] [--role <r>] [--model <m>] [--effort <e>] [--cd <dir>] \
#                        [--writable <dir>] (repeatable) \
#                        [--fresh] [--foreground] [--max-tool-calls N] [--max-tool-output-kb N] \
#                        [--handoff-context-tokens N] [--handoff-tool-calls N] [--max-handoffs N] [--state-file PATH] \
#                        [--parallel] [--no-contract]
#   codex-exec.sh resume ...same flags; requires an existing --thread-file
#   codex-exec.sh watch  --log <events.jsonl> --out <last-msg.md> [--max-wait <secs>] [--stall <secs>]
#   codex-exec.sh stats  --log <events.jsonl>          # tool calls, output bytes, tokens, errors from an event log
#
# start:  launches a NEW Codex run detached by default and captures thread_id from the JSON event stream
#         into --thread-file. Exits 2 if the thread-file already exists (use
#         resume to continue it, or --fresh to deliberately overwrite).
# resume: launches the persisted thread detached by default (context retained). Exits 2 if the
#         thread-file is missing.
# watch:  cheap blocking wait for orchestrator agents. Blocks until --out is
#         non-empty (exit 0), --max-wait elapses while the session is still
#         making progress (exit 10 — call watch again), the session recorded a
#         terminal failure in <log>.failed (exits with that code), or the event
#         log stops changing for --stall seconds (exit 75).
#
# PROMPT CONTRACT: every start/resume prepends the role's section of
# references/codex-prompt-contract.md (inline inputs, ranged reads only, no web
# or MCP, the numeric budget) to the prompt. The composed prompt is saved next to
# the prompt file as <prompt>.sent. --no-contract skips it.
#
# BUDGET GUARD: tool calls and cumulative tool-output bytes are counted from the
# event log every poll. Past the role's cap the session is killed (exit 76,
# CODEX_BUDGET_EXCEEDED); on start the thread id is still persisted so a resume
# can ask for the verdict with what Codex has. Per-call output is also truncated
# by Codex itself via tool_output_token_limit. Web search and MCP servers are
# disabled per role.
#
# CREDITS: the "out of credits" error kills that session at once (exit 77,
# CODEX_NO_CREDITS). A later start may retry after billing is fixed.
#
# LOCK: sessions run one at a time by default (a credit failure then costs one
# session, not three). A second start waits up to lockWaitSeconds, touching the
# event log so watch stays alive, then exits 78. --parallel or
# FORGE_CODEX_PARALLEL=1 skips the lock.
#
# STALL WATCHDOG (start/resume): if the event log stops changing for
# FORGE_CODEX_STALL_TIMEOUT seconds (default 600):
#   - stall at ZERO progress (no item.completed events — the resume-wedge
#     signature): the process is killed, the log rotated to <log>.stalled, and the
#     SAME prompt retried ONCE as a fresh session. Prompts must be self-contained.
#   - stall mid-work: no auto-retry; exits 75 for the caller to triage.
#
# Every finished run appends one line to <state>/usage.log and prints usage in
# the CODEX_OK line. Codex reports usage cumulatively per thread in exec mode, so
# on a resume the token numbers cover the whole thread so far.
#
# Exit codes: 0 success (CODEX_OK line + final message); 1 codex failed or
# produced no final message; 2 thread-file state error; 10 watch max-wait
# elapsed while still running; 64 usage error or codex not on PATH; 65 config error;
# 69 not logged in (CODEX_NOT_LOGGED_IN); 75 stalled;
# 76 budget exceeded; 77 out of credits; 78 lock timeout;
# 79 context/tool-call handoff (CODEX_CONTEXT_HANDOFF).
#
# Settings come from forge.config.json per --role; --model/--effort/--max-* flags
# and FORGE_CODEX_MODEL / FORGE_CODEX_EFFORT / FORGE_CODEX_STALL_TIMEOUT override.
# Requires jq.

set -euo pipefail

ORIGINAL_ARGS=("$@")
MODE="${1:-}"
shift || true
case "$MODE" in
    start|resume|watch|config|stats) ;;
    *) echo "usage: codex-exec.sh start|resume|watch|config|stats --thread-file <f> --prompt-file <p> --log <l> --out <o> [...]" >&2; exit 64 ;;
esac

SKILL_DIR="${FORGE_CODEX_EXEC_SKILL_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
CONFIG_FILE="$SKILL_DIR/forge.config.json"
CONTRACT_FILE="$SKILL_DIR/references/codex-prompt-contract.md"
STATE_DIR="${FORGE_CODEX_STATE_DIR:-$SKILL_DIR/.state}"
LOCK_DIR="$STATE_DIR/session.lock"
USAGE_LOG="$STATE_DIR/usage.log"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"

THREAD_FILE="" PROMPT_FILE="" LOG="" OUT="" INLINE_DIFF="" STATE_FILE=""
FRESH=false
SANDBOX="read-only"
CD_DIR="$PWD"
ROLE=""
MODEL="${FORGE_CODEX_MODEL:-}"
EFFORT="${FORGE_CODEX_EFFORT:-}"
STALL_TIMEOUT="${FORGE_CODEX_STALL_TIMEOUT:-}"
MAX_TOOL_CALLS="" MAX_TOOL_OUTPUT_KB="" TOOL_OUTPUT_TOKEN_LIMIT="" WEB_SEARCH="" MCP_ENABLED="" CONTRACT=""
HANDOFF_CONTEXT_TOKENS="" HANDOFF_TOOL_CALLS="" MAX_HANDOFFS=""
PARALLEL="${FORGE_CODEX_PARALLEL:-false}"
USE_CONTRACT=true
FOREGROUND=false
MAX_WAIT=270
POLL_INTERVAL="${FORGE_CODEX_POLL_INTERVAL:-15}"
WRITABLE_DIRS=()
RESULT_WRITTEN=false

write_result() {
    local status=$1 code=$2 message=$3 stats
    [ -n "$LOG" ] || return 0
    command -v jq >/dev/null 2>&1 || return 0
    if type log_stats >/dev/null 2>&1; then
        stats="$(log_stats "$LOG")"
    else
        stats='{"calls":0,"bytes":0,"usage":{}}'
    fi
    jq -n \
        --arg status "$status" --argjson code "$code" --arg message "$message" \
        --arg thread "$([ -s "$THREAD_FILE" ] && head -1 "$THREAD_FILE" || true)" \
        --arg role "$ROLE" --arg model "$MODEL" --argjson stats "$stats" \
        --argjson max_handoffs "${MAX_HANDOFFS:-3}" \
        '{status:$status,code:$code,message:$message,thread:$thread,max_handoffs:$max_handoffs,
          tool_calls:($stats.calls // 0),tool_output_kb:(($stats.bytes // 0) / 1024 | floor),
          tokens_in:($stats.usage.input_tokens // 0),tokens_out:($stats.usage.output_tokens // 0),
          role:$role,model:$model}' >"$LOG.result.json"
    RESULT_WRITTEN=true
}

while [ $# -gt 0 ]; do
    case "$1" in
        --thread-file) THREAD_FILE="$2"; shift 2 ;;
        --prompt-file) PROMPT_FILE="$2"; shift 2 ;;
        --log)         LOG="$2"; shift 2 ;;
        --out)         OUT="$2"; shift 2 ;;
        --inline-diff) INLINE_DIFF="$2"; shift 2 ;;
        --sandbox)     SANDBOX="$2"; shift 2 ;;
        --role)        ROLE="$2"; shift 2 ;;
        --model)       MODEL="$2"; shift 2 ;;
        --effort)      EFFORT="$2"; shift 2 ;;
        --cd)          CD_DIR="$2"; shift 2 ;;
        --writable)    WRITABLE_DIRS+=("$2"); shift 2 ;;
        --fresh)       FRESH=true; shift ;;
        --max-wait)    MAX_WAIT="$2"; shift 2 ;;
        --stall)       STALL_TIMEOUT="$2"; shift 2 ;;
        --max-tool-calls)     MAX_TOOL_CALLS="$2"; shift 2 ;;
        --max-tool-output-kb) MAX_TOOL_OUTPUT_KB="$2"; shift 2 ;;
        --handoff-context-tokens) HANDOFF_CONTEXT_TOKENS="$2"; shift 2 ;;
        --handoff-tool-calls) HANDOFF_TOOL_CALLS="$2"; shift 2 ;;
        --max-handoffs) MAX_HANDOFFS="$2"; shift 2 ;;
        --state-file) STATE_FILE="$2"; shift 2 ;;
        --parallel)    PARALLEL=true; shift ;;
        --no-contract) USE_CONTRACT=false; shift ;;
        --foreground) FOREGROUND=true; shift ;;
        *) echo "error: unknown flag: $1" >&2; exit 64 ;;
    esac
done
case "$PARALLEL" in 1|true) PARALLEL=true ;; *) PARALLEL=false ;; esac

LOCK_HELD=false
terminal_cleanup() {
    local rc=$?
    if [ "$LOCK_HELD" = "true" ] && type release_lock >/dev/null 2>&1; then
        release_lock
    fi
    if [[ "$MODE" = "start" || "$MODE" = "resume" ]] && [ "$rc" -ne 0 ] && [ -n "$LOG" ] && [ ! -f "$LOG.failed" ]; then
        mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
        { echo "$rc"; echo "codex-exec.sh exited with code $rc"; } >"$LOG.failed" 2>/dev/null || true
    fi
    if [[ "$MODE" = "start" || "$MODE" = "resume" ]] && [ "$FOREGROUND" = "true" ] && [ "$RESULT_WRITTEN" != "true" ]; then
        write_result failed "$rc" "codex-exec.sh exited with code $rc" 2>/dev/null || true
    fi
}
trap terminal_cleanup EXIT

add_output_writable_dirs() {
    local resolved_cd path parent resolved_parent item resolved_item duplicate
    resolved_cd=$(cd "$CD_DIR" 2>/dev/null && pwd -P) || return
    for path in "$LOG" "$OUT"; do
        [ -n "$path" ] || continue
        case "$path" in
            */*) parent=${path%/*}; [ -n "$parent" ] || parent=/ ;;
            *) parent=. ;;
        esac
        mkdir -p "$parent" 2>/dev/null || continue
        resolved_parent=$(cd "$parent" 2>/dev/null && pwd -P) || continue
        case "$resolved_parent/" in "${resolved_cd%/}/"*) continue ;; esac
        duplicate=false
        for item in "${WRITABLE_DIRS[@]}"; do
            if resolved_item=$(cd "$item" 2>/dev/null && pwd -P) && [ "$resolved_item" = "$resolved_parent" ]; then
                duplicate=true
                break
            fi
        done
        [ "$duplicate" = true ] && continue
        WRITABLE_DIRS+=("$resolved_parent")
        echo "writable: added $resolved_parent for --out/--log" >&2
    done
}
if [ "$SANDBOX" = "workspace-write" ]; then
    add_output_writable_dirs
fi

command -v jq >/dev/null || { echo "error: jq is required" >&2; exit 64; }

# ---------- event-log parsing (shared by watch/stats/start/resume) ----------
# Each line is parsed on its own so a half-written last line is ignored.
EMPTY_STATS='{"calls":0,"bytes":0,"nocredit":0,"completed":0,"errors":"","usage":{}}'
log_stats() {
    # $1 = log path. Prints one JSON object.
    if [ ! -f "$1" ]; then echo "$EMPTY_STATS"; return; fi
    jq -Rc 'fromjson? // empty' "$1" 2>/dev/null | jq -sc '
        def tool_items: [.[] | select(.type == "item.completed") | .item
                         | select(.type == "command_execution" or .type == "mcp_tool_call" or .type == "web_search")];
        def out_bytes: ((.aggregated_output // (if .result == null then "" else (.result | tostring) end)) | utf8bytelength);
        def errs: [.[] | select(.type == "error" or .type == "turn.failed") | (.message // .error.message // "")];
        {
          calls: (tool_items | length),
          bytes: (tool_items | map(out_bytes) | add // 0),
          completed: ([.[] | select(.type == "item.completed")] | length),
          nocredit: (errs | map(select(test("out of credits"; "i"))) | length),
          errors: (errs | unique | join(" | ")),
          usage: ([.[] | select(.type == "turn.completed") | .usage] | last // {})
        }' 2>/dev/null || echo "$EMPTY_STATS"
}
stat_field() { jq -r "$2" <<<"$1"; }
usage_line() {
    # $1 = stats JSON. Prints tool_calls=… tool_output_kb=… tokens_in=… …
    jq -r '"tool_calls=\(.calls) tool_output_kb=\((.bytes / 1024) | floor) tokens_in=\(.usage.input_tokens // "n/a") tokens_cached=\(.usage.cached_input_tokens // "n/a") tokens_out=\(.usage.output_tokens // "n/a") tokens_reasoning=\(.usage.reasoning_output_tokens // "n/a")"' <<<"$1"
}
abspath() { case "$1" in /*) printf '%s\n' "$1" ;; *) printf '%s/%s\n' "$PWD" "$1" ;; esac; }
log_sig() { stat -f '%m %z' "$1" 2>/dev/null || stat -c '%Y %s' "$1" 2>/dev/null || echo 0; }
mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || echo 0; }

# ---------- stats mode ----------
if [ "$MODE" = "stats" ]; then
    [ -n "$LOG" ] || { echo "error: stats requires --log" >&2; exit 64; }
    stats="$(log_stats "$LOG")"
    echo "$stats"
    echo "CODEX_STATS log=$LOG $(usage_line "$stats") errors=$(stat_field "$stats" '.errors | if . == "" then "none" else . end')"
    exit 0
fi

# ---------- watch mode: cheap blocking wait, no codex invocation ----------
if [ "$MODE" = "watch" ]; then
    if [ -z "$LOG" ] || [ -z "$OUT" ]; then
        echo "error: watch requires --log and --out" >&2
        exit 64
    fi
    STALL_TIMEOUT="${STALL_TIMEOUT:-600}"
    start_ts=$(date +%s)
    last_sig=$(log_sig "$LOG")
    stalled_for=0
    while :; do
        if [ -s "$OUT" ] && [ -s "$LOG.result.json" ]; then
            echo "WATCH_DONE out=$OUT"
            echo "WATCH_RESULT $LOG.result.json"
            [ ! -f "$LOG.status" ] || cat "$LOG.status"
            exit 0
        fi
        if [ -f "$LOG.failed" ]; then
            code=$(head -1 "$LOG.failed" | tr -dc '0-9')
            echo "WATCH_FAILED $(tail -n +2 "$LOG.failed")" >&2
            exit "${code:-1}"
        fi
        elapsed=$(( $(date +%s) - start_ts ))
        if [ "$elapsed" -ge "$MAX_WAIT" ]; then
            echo "WATCH_WAITING elapsed=${elapsed}s — session still active; call watch again"
            exit 10
        fi
        sleep "$POLL_INTERVAL"
        sig=$(log_sig "$LOG")
        if [ "$sig" != "$last_sig" ]; then
            last_sig=$sig
            stalled_for=0
        else
            stalled_for=$(( stalled_for + POLL_INTERVAL ))
            if [ "$stalled_for" -ge "$STALL_TIMEOUT" ]; then
                echo "WATCH_STALLED no event-log change for ${STALL_TIMEOUT}s (log=$LOG)" >&2
                exit 75
            fi
        fi
    done
fi

# ---------- config resolution ----------
resolve_config() {
    # $1 = jq path; prints the value or nothing.
    [ -f "$CONFIG_FILE" ] || return 0
    jq -r "$1 // empty" "$CONFIG_FILE" 2>/dev/null
}
if [ -z "$ROLE" ]; then
    ROLE="$(resolve_config '.codex.defaultRole')"
    ROLE="${ROLE:-review}"
fi
role_cfg() { resolve_config ".codex.roles[\"$ROLE\"].$1"; }
role_runtime_cfg() { resolve_config ".roles[\"$ROLE\"].$1 // .codex.roles[\"$ROLE\"].$1"; }
[ -n "$MODEL" ]  || MODEL="$(role_runtime_cfg model)"
[ -n "$EFFORT" ] || EFFORT="$(role_runtime_cfg effort)"
[ -n "$MAX_TOOL_CALLS" ] || MAX_TOOL_CALLS="$(role_cfg maxToolCalls)"
[ -n "$MAX_TOOL_OUTPUT_KB" ] || MAX_TOOL_OUTPUT_KB="$(role_cfg maxToolOutputKB)"
[ -n "$HANDOFF_CONTEXT_TOKENS" ] || HANDOFF_CONTEXT_TOKENS="$(role_cfg handoffContextTokens)"
[ -n "$HANDOFF_TOOL_CALLS" ] || HANDOFF_TOOL_CALLS="$(role_cfg handoffToolCalls)"
[ -n "$MAX_HANDOFFS" ] || MAX_HANDOFFS="$(role_cfg maxHandoffs)"
TOOL_OUTPUT_TOKEN_LIMIT="$(role_cfg toolOutputTokenLimit)"
WEB_SEARCH="$(role_cfg webSearch)"
MCP_ENABLED="$(role_cfg mcp)"
CONTRACT="$(role_cfg contract)"
[ -n "$STALL_TIMEOUT" ] || STALL_TIMEOUT="$(resolve_config '.codex.stallTimeoutSeconds')"
STALL_TIMEOUT="${STALL_TIMEOUT:-600}"
LOCK_WAIT="$(resolve_config '.codex.lockWaitSeconds')"; LOCK_WAIT="${LOCK_WAIT:-1800}"
MAX_TOOL_CALLS="${MAX_TOOL_CALLS:-40}"
MAX_TOOL_OUTPUT_KB="${MAX_TOOL_OUTPUT_KB:-300}"
HANDOFF_CONTEXT_TOKENS="${HANDOFF_CONTEXT_TOKENS:-120000}"
if [ -z "$HANDOFF_TOOL_CALLS" ]; then
    if [ "$CONTRACT" = "impl" ]; then HANDOFF_TOOL_CALLS=60; else HANDOFF_TOOL_CALLS=30; fi
fi
MAX_HANDOFFS="${MAX_HANDOFFS:-3}"
if [ "$HANDOFF_TOOL_CALLS" -gt 0 ] && [ "$HANDOFF_TOOL_CALLS" -gt "$MAX_TOOL_CALLS" ]; then
    HANDOFF_TOOL_CALLS=$(( MAX_TOOL_CALLS - 1 ))
    echo "warn: handoff tool-call cap must be below hard budget; clamped to $HANDOFF_TOOL_CALLS (budget $MAX_TOOL_CALLS)" >&2
fi
MCP_ENABLED="${MCP_ENABLED:-false}"
CONTRACT="${CONTRACT:-review}"
build_writable_roots() {
    local existing="" resolved escaped item
    local roots=()
    if [ -f "$CODEX_HOME_DIR/config.toml" ]; then
        existing=$(sed -n -E 's/^[[:space:]]*writable_roots[[:space:]]*=[[:space:]]*\[(.*)\][[:space:]]*(#.*)?$/\1/p' "$CODEX_HOME_DIR/config.toml" | head -n 1)
    fi
    for item in "${WRITABLE_DIRS[@]}"; do
        if resolved=$(cd "$item" 2>/dev/null && pwd -P); then
            escaped=${resolved//\\/\\\\}
            escaped=${escaped//\"/\\\"}
            roots+=("\"$escaped\"")
        else
            echo "warn: writable directory does not exist; skipping: $item" >&2
        fi
    done
    WRITABLE_ROOTS_VALUE="[${existing}]"
    for item in "${roots[@]}"; do
        if [ "$WRITABLE_ROOTS_VALUE" = "[]" ]; then
            WRITABLE_ROOTS_VALUE="[$item]"
        else
            WRITABLE_ROOTS_VALUE="${WRITABLE_ROOTS_VALUE%]}, $item]"
        fi
    done
}
if [ -z "$MODEL" ] || [ -z "$EFFORT" ]; then
    echo "error: no model/effort for role '$ROLE' — set them in $CONFIG_FILE or pass --model/--effort" >&2
    exit 65
fi
if [ "$MODE" = "config" ]; then
    echo "role=$ROLE model=$MODEL effort=$EFFORT max_tool_calls=$MAX_TOOL_CALLS max_tool_output_kb=$MAX_TOOL_OUTPUT_KB handoff_context_tokens=$HANDOFF_CONTEXT_TOKENS handoff_tool_calls=$HANDOFF_TOOL_CALLS max_handoffs=$MAX_HANDOFFS tool_output_token_limit=${TOOL_OUTPUT_TOKEN_LIMIT:-default} web_search=${WEB_SEARCH:-default} mcp=$MCP_ENABLED contract=$CONTRACT stall=$STALL_TIMEOUT lock_wait=$LOCK_WAIT config=$CONFIG_FILE"
    if [ "$SANDBOX" = "workspace-write" ] && [ "${#WRITABLE_DIRS[@]}" -gt 0 ]; then
        build_writable_roots
        echo "writable_roots=$WRITABLE_ROOTS_VALUE"
    fi
    exit 0
fi

# ---------- start / resume ----------
if [ -z "$THREAD_FILE" ] || [ -z "$PROMPT_FILE" ] || [ -z "$LOG" ] || [ -z "$OUT" ]; then
    echo "error: --thread-file, --prompt-file, --log, and --out are all required" >&2
    exit 64
fi
# Resolve file args before the cd below: a relative path would re-resolve against
# --cd, and `$(cat …)` on the then-missing prompt hands codex an empty string it
# happily answers ("What would you like to work on?") while this script reports OK.
THREAD_FILE=$(abspath "$THREAD_FILE"); PROMPT_FILE=$(abspath "$PROMPT_FILE")
LOG=$(abspath "$LOG"); OUT=$(abspath "$OUT")
[ -n "$STATE_FILE" ] || STATE_FILE="$(dirname "$THREAD_FILE")/codex-state.md"
STATE_FILE=$(abspath "$STATE_FILE")
[ -z "$INLINE_DIFF" ] || INLINE_DIFF=$(abspath "$INLINE_DIFF")
mkdir -p "$(dirname "$LOG")"
rm -f "$LOG.failed"
if [ ! -f "$PROMPT_FILE" ]; then
    echo "error: prompt file not found: $PROMPT_FILE" >&2
    exit 64
fi
if [ -z "$(tr -d '[:space:]' <"$PROMPT_FILE")" ]; then
    echo "error: prompt file is empty: $PROMPT_FILE" >&2
    exit 64
fi

# Terminal failures are recorded next to the log so a concurrent `watch` exits at
# once with the same code instead of waiting out its stall timeout.
fail() {
    local code=$1; shift
    { echo "$code"; echo "$*"; } >"$LOG.failed"
    write_result failed "$code" "$*"
    echo "$*" >&2
    exit "$code"
}
mkdir -p "$STATE_DIR"

if [ -n "$INLINE_DIFF" ] && [ ! -f "$INLINE_DIFF" ]; then
    fail 65 "CODEX_DIFF_INVALID: diff file not found: $INLINE_DIFF"
fi
if [ -n "$INLINE_DIFF" ] && [ ! -s "$INLINE_DIFF" ]; then
    fail 65 "CODEX_DIFF_INVALID: diff must be non-empty: $INLINE_DIFF"
elif [ -n "$INLINE_DIFF" ] && [ "$(head -c 10 "$INLINE_DIFF")" != "diff --git" ]; then
    fail 65 "CODEX_DIFF_INVALID: non-empty diff must begin with diff --git: $INLINE_DIFF"
fi

# Checked before the session lock is taken, so a logged-out run holds no lock.
command -v codex >/dev/null 2>&1 || fail 64 "error: codex is not on PATH"
if ! login_err=$(codex login status 2>&1 >/dev/null); then
    fail 69 "CODEX_NOT_LOGGED_IN: 'codex login status' failed for CODEX_HOME=$CODEX_HOME_DIR ($(printf '%s\n' "$login_err" | tail -n 1)). Run 'codex login' and retry."
fi

if [ "$MODE" = "start" ]; then
    if [ -f "$THREAD_FILE" ] && [ "$FRESH" != "true" ]; then
        echo "error: thread already exists for this target ($(cat "$THREAD_FILE"))" >&2
        echo "       use 'resume' to continue it, or pass --fresh for a deliberate new session" >&2
        exit 2
    fi
    rm -f "$THREAD_FILE"
else
    if [ ! -f "$THREAD_FILE" ]; then
        echo "error: no thread file at $THREAD_FILE — run 'start' first" >&2
        exit 2
    fi
    if [ -z "$(tr -d '[:space:]' <"$THREAD_FILE")" ]; then
        echo "error: thread file is empty: $THREAD_FILE — run 'start' first" >&2
        exit 2
    fi
fi

# ---------- prompt contract ----------
compose_prompt() {
    if [ "$USE_CONTRACT" = "true" ] && [ "$CONTRACT" != "none" ] && [ -f "$CONTRACT_FILE" ]; then
        awk -v want="## $CONTRACT" '
            /^## (review|impl)$/ { on = ($0 == want); next }
            on { print }
        ' "$CONTRACT_FILE" \
        | sed -e "s/{{MAX_TOOL_CALLS}}/$MAX_TOOL_CALLS/g" \
              -e "s/{{MAX_TOOL_OUTPUT_KB}}/$MAX_TOOL_OUTPUT_KB/g" \
              -e "s/{{HANDOFF_CONTEXT_TOKENS}}/$HANDOFF_CONTEXT_TOKENS/g" \
              -e "s/{{HANDOFF_TOOL_CALLS}}/$HANDOFF_TOOL_CALLS/g" \
              -e "s|{{STATE_FILE}}|$STATE_FILE|g" \
              -e "s/{{ROLE}}/$ROLE/g"
        echo
    fi
    cat "$PROMPT_FILE"
    if [ -n "$INLINE_DIFF" ]; then
        python3 - "$INLINE_DIFF" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
diff = path.read_text(encoding="utf-8", errors="replace")
line_count = len(diff.splitlines())
print(f"\n## DIFF ({path}, {line_count} lines)")
print(diff[:160000], end="" if diff.endswith("\n") or len(diff) >= 160000 else "\n")
if len(diff) > 160000:
    print(f"\n[cut at 160000 of {len(diff)} characters]")
PY
    fi
}
SENT_PROMPT="$PROMPT_FILE.sent"
compose_prompt >"$SENT_PROMPT"
rm -f "$OUT" "$LOG.status"

if [ "$FOREGROUND" != "true" ]; then
    SELF_PATH="$SKILL_DIR/scripts/codex-exec.sh"
    # Run a copy: a fix round may edit this script while a session is still running.
    LAUNCH_COPY="$LOG.launcher.sh"
    cp "$SELF_PATH" "$LAUNCH_COPY"
    FORGE_CODEX_EXEC_SKILL_DIR="$SKILL_DIR" nohup bash "$LAUNCH_COPY" "${ORIGINAL_ARGS[@]}" --foreground </dev/null >"$LOG.launcher" 2>&1 &
    echo "CODEX_STARTED mode=$MODE role=$ROLE log=$LOG out=$OUT watch=\"bash $SELF_PATH watch --log $LOG --out $OUT --max-wait 2400\""
    exit 0
fi

# ---------- session lock ----------
release_lock() { rm -rf "$LOCK_DIR" 2>/dev/null || true; }
# A stale lock that cannot be removed would otherwise send acquire_lock into a tight loop.
lock_gone_or_fail() {
    [ -e "$LOCK_DIR" ] || return 0
    fail 78 "CODEX_LOCK_STUCK: could not remove stale lock $LOCK_DIR; remove it by hand"
}
acquire_lock() {
    [ "$PARALLEL" = "true" ] && return 0
    local waited=0 announced=false owner
    while ! mkdir "$LOCK_DIR" 2>/dev/null; do
        owner=$(cat "$LOCK_DIR/pid" 2>/dev/null || echo "")
        if [ -n "$owner" ] && ! kill -0 "$owner" 2>/dev/null; then
            echo "warn: removing stale codex lock held by dead pid $owner" >&2
            release_lock; lock_gone_or_fail; continue
        fi
        if [ -z "$owner" ] && [ $(( $(date +%s) - $(mtime "$LOCK_DIR") )) -gt 60 ]; then
            echo "warn: removing stale codex lock with no owner" >&2
            release_lock; lock_gone_or_fail; continue
        fi
        if [ "$waited" -ge "$LOCK_WAIT" ]; then
            fail 78 "CODEX_LOCK_TIMEOUT: another codex session (pid $owner) held $LOCK_DIR for ${LOCK_WAIT}s. Sessions run one at a time by default; pass --parallel only when the user asked for it."
        fi
        if [ "$announced" != "true" ]; then
            echo "CODEX_WAITING_LOCK held by pid ${owner:-?}; sessions run one at a time (max wait ${LOCK_WAIT}s)" >&2
            announced=true
        fi
        touch "$LOG"
        sleep "$POLL_INTERVAL"; waited=$(( waited + POLL_INTERVAL ))
    done
    echo $$ >"$LOCK_DIR/pid"
    LOCK_HELD=true
}
acquire_lock

# `codex exec resume` accepts only a subset of `codex exec`'s flags (no --sandbox,
# --cd, or --color) — so: cwd is set by cd'ing here, sandbox goes through the -c
# config key on resume, and --color is omitted (--json output is JSONL either way).
cd "$CD_DIR"
ARGS=(
    --json
    --skip-git-repo-check
    --output-last-message "$OUT"
    -c model="$MODEL"
    -c model_reasoning_effort="$EFFORT"
)
[ -n "$TOOL_OUTPUT_TOKEN_LIMIT" ] && ARGS+=( -c tool_output_token_limit="$TOOL_OUTPUT_TOKEN_LIMIT" )
[ -n "$WEB_SEARCH" ] && ARGS+=( -c web_search="$WEB_SEARCH" )
if [ "$SANDBOX" = "workspace-write" ] && [ "${#WRITABLE_DIRS[@]}" -gt 0 ]; then
    build_writable_roots
    ARGS+=( -c "sandbox_workspace_write.writable_roots=$WRITABLE_ROOTS_VALUE" )
fi
if [ "$MCP_ENABLED" != "true" ] && [ -f "$CODEX_HOME_DIR/config.toml" ]; then
    # Disable every configured MCP server for this session; the ids are the
    # [mcp_servers.<id>] tables (nested [mcp_servers.<id>.tools.*] tables are skipped).
    while IFS= read -r server; do
        [ -n "$server" ] && ARGS+=( -c "mcp_servers.$server.enabled=false" )
    done < <(grep -oE '^\[mcp_servers\.[^].]+\]' "$CODEX_HOME_DIR/config.toml" | sed -e 's/^\[mcp_servers\.//' -e 's/\]$//' | sort -u)
fi

# Runs codex ($1 = start|resume) in the background and babysits it every
# POLL_INTERVAL seconds: handoff (79), budget (76), credits (77), stall (75). Returns codex's
# own exit code otherwise.
kill_codex() {
    kill "$1" 2>/dev/null || true
    sleep 2
    kill -9 "$1" 2>/dev/null || true
    wait "$1" 2>/dev/null || true
}
run_codex() {
    # semgrep's OCaml TLS client cannot read the macOS keychain inside the Codex sandbox and aborts with
    # "ca-certs: empty trust anchors" unless a PEM bundle path is exported.
    if [[ -z "${SSL_CERT_FILE:-}" && -r /etc/ssl/cert.pem ]]; then
        export SSL_CERT_FILE=/etc/ssl/cert.pem
    fi
    if [ "$1" = "start" ]; then
        codex exec --sandbox "$SANDBOX" "${ARGS[@]}" <"$SENT_PROMPT" \
            >"$LOG" 2>"$LOG.stderr" &
    else
        codex exec resume "$(cat "$THREAD_FILE")" -c sandbox_mode="$SANDBOX" "${ARGS[@]}" <"$SENT_PROMPT" \
            >"$LOG" 2>"$LOG.stderr" &
    fi
    local pid=$!
    local last_size=0 stalled_for=0 size stats calls bytes thread_id context=0
    local rollout_file="" rollout_warned=false candidate reason
    local max_bytes=$(( MAX_TOOL_OUTPUT_KB * 1024 ))
    while kill -0 "$pid" 2>/dev/null; do
        sleep "$POLL_INTERVAL"
        if [ "$1" = "start" ] && [ ! -s "$THREAD_FILE" ]; then
            thread_id="$(thread_id_from_log)"
            if [ -n "$thread_id" ] && [ "$thread_id" != "null" ]; then
                printf '%s\n' "$thread_id" >"$THREAD_FILE"
            fi
        fi
        stats="$(log_stats "$LOG")"
        if [ "$(stat_field "$stats" .nocredit)" != "0" ]; then
            kill_codex "$pid"
            return 77
        fi
        calls=$(stat_field "$stats" .calls); bytes=$(stat_field "$stats" .bytes)
        thread_id="$(thread_id_from_log)"
        # The rollout file can appear a poll or two after thread.started; keep looking until it does.
        if [ -n "$thread_id" ] && [ "$thread_id" != "null" ] && [ -z "$rollout_file" ]; then
            for candidate in "$CODEX_HOME_DIR"/sessions/*/*/*/rollout-*-"$thread_id".jsonl; do
                if [ -f "$candidate" ]; then rollout_file="$candidate"; break; fi
            done
            if [ -z "$rollout_file" ] && [ "$rollout_warned" = "false" ]; then
                rollout_warned=true
                echo "warn: rollout file not found yet for thread $thread_id; context handoff check unavailable until it appears" >&2
            fi
        fi
        if [ -n "$rollout_file" ]; then
            context=$(tail -n 300 "$rollout_file" | jq -r 'select(.type=="event_msg" and .payload.type=="token_count") | .payload.info.last_token_usage.input_tokens' 2>/dev/null | tail -1)
            case "$context" in ''|null) context=0 ;; esac
        fi
        reason=""
        if [ "$HANDOFF_CONTEXT_TOKENS" -gt 0 ] && [ "$context" -ge "$HANDOFF_CONTEXT_TOKENS" ]; then
            reason="context=$context/$HANDOFF_CONTEXT_TOKENS"
        fi
        if [ "$HANDOFF_TOOL_CALLS" -gt 0 ] && [ "$calls" -ge "$HANDOFF_TOOL_CALLS" ]; then
            if [ -n "$reason" ]; then reason="$reason calls=$calls/$HANDOFF_TOOL_CALLS"; else reason="calls=$calls/$HANDOFF_TOOL_CALLS"; fi
        fi
        if [ -n "$reason" ]; then
            echo "warn: context handoff ($reason) — killing codex (pid $pid)" >&2
            kill_codex "$pid"
            if [ -n "$thread_id" ] && [ "$thread_id" != "null" ]; then printf '%s\n' "$thread_id" >"$THREAD_FILE"; fi
            if [ -n "$rollout_file" ]; then
                tail -n 300 "$rollout_file" | jq -s -r '[.[] | select(.type=="event_msg" and .payload.type=="agent_message") | .payload.message] | last // ""' 2>/dev/null >"$LOG.last-message.txt"
            else
                : >"$LOG.last-message.txt"
            fi
            {
                echo "## Reason"; echo; echo "$reason thread_id=${thread_id:-unknown}"
                echo; echo "## State file"; echo
                if [ -f "$STATE_FILE" ]; then cat "$STATE_FILE"; else echo "absent"; fi
                echo; echo "## Last message"; echo
                head -c 4000 "$LOG.last-message.txt"; echo
                echo; echo "## git diff --stat"; echo
                { git -C "$CD_DIR" diff --stat; git -C "$CD_DIR" status --short | grep '^??' || true; } | sed -n '1,200p'
            } >"$LOG.handoff.md"
            HANDOFF_CONTEXT="$context"
            HANDOFF_CALLS="$calls"
            HANDOFF_THREAD_ID="${thread_id:-}"
            return 79
        fi
        if [ "$calls" -gt "$MAX_TOOL_CALLS" ] || [ "$bytes" -gt "$max_bytes" ]; then
            echo "warn: budget exceeded (tool_calls=$calls/$MAX_TOOL_CALLS tool_output_kb=$(( bytes / 1024 ))/$MAX_TOOL_OUTPUT_KB) — killing codex (pid $pid)" >&2
            kill_codex "$pid"
            return 76
        fi
        size=$(wc -c <"$LOG" 2>/dev/null || echo 0)
        if [ "$size" != "$last_size" ]; then
            last_size=$size
            stalled_for=0
        else
            stalled_for=$(( stalled_for + POLL_INTERVAL ))
            if [ "$stalled_for" -ge "$STALL_TIMEOUT" ]; then
                echo "warn: no event-log change for ${STALL_TIMEOUT}s — killing stalled codex (pid $pid)" >&2
                kill_codex "$pid"
                return 75
            fi
        fi
    done
    local rc=0
    wait "$pid" || rc=$?
    return "$rc"
}

thread_id_from_log() { jq -r 'select(.type == "thread.started") | .thread_id' "$LOG" 2>/dev/null | head -1; }
record_usage() {
    # $1 = outcome label. One line per run so cost is visible across sessions.
    local stats; stats="$(log_stats "$LOG")"
    echo "$(date '+%Y-%m-%dT%H:%M:%S') outcome=$1 role=$ROLE model=$MODEL effort=$EFFORT mode=$MODE $(usage_line "$stats") log=$LOG" >>"$USAGE_LOG"
    echo "$stats"
}

rc=0
run_codex "$MODE" || rc=$?

if [ "$rc" -eq 75 ] && [ "$(stat_field "$(log_stats "$LOG")" .completed)" -eq 0 ]; then
    # Zero-progress stall: the classic wedge (most often a resume of a thread whose
    # previous turn died abnormally). Nothing was done, so a fresh retry is safe.
    echo "warn: stall at ZERO progress (the known codex wedge signature) — retrying ONCE as a fresh session" >&2
    echo "warn: thread context is lost on the retry; forge prompts are self-contained by design" >&2
    mv -f "$LOG" "$LOG.stalled" 2>/dev/null || true
    mv -f "$LOG.stderr" "$LOG.stderr.stalled" 2>/dev/null || true
    rm -f "$THREAD_FILE"
    MODE="start"
    rc=0
    run_codex start || rc=$?
fi

# A thread id is persisted on success and on a budget kill (so the caller can
# resume and ask for the verdict); not after a credit failure or a wedge.
if [ "$MODE" = "start" ] && { [ "$rc" -eq 0 ] || [ "$rc" -eq 76 ] || [ "$rc" -eq 79 ]; }; then
    THREAD_ID="$(thread_id_from_log)"
    if [ -n "$THREAD_ID" ] && [ "$THREAD_ID" != "null" ]; then
        printf '%s\n' "$THREAD_ID" >"$THREAD_FILE"
    fi
fi

# Any final message Codex already wrote before a kill is worth surfacing (a
# review that stopped itself at the budget still has a verdict in --out).
final_message_after_kill() {
    if [ -s "$OUT" ]; then
        echo "--- final message (written before the session was killed) ---" >&2
        cat "$OUT" >&2
    fi
}

case "$rc" in
    79)
        stats="$(record_usage handoff)"
        handoff_line="CODEX_CONTEXT_HANDOFF context=${HANDOFF_CONTEXT:-0} calls=${HANDOFF_CALLS:-0} handoff=$LOG.handoff.md"
        printf '%s\n' "$handoff_line" >"$LOG.status"
        write_result handoff 79 "$handoff_line"
        jq --arg handoff_file "$LOG.handoff.md" \
           --argjson context_tokens "${HANDOFF_CONTEXT:-0}" \
           --argjson tool_calls "${HANDOFF_CALLS:-0}" \
           --arg thread_id "${HANDOFF_THREAD_ID:-}" \
           '. + {handoff_file:$handoff_file,context_tokens:$context_tokens,tool_calls:$tool_calls,thread_id:$thread_id}' \
           "$LOG.result.json" >"$LOG.result.json.tmp"
        mv "$LOG.result.json.tmp" "$LOG.result.json"
        { echo 79; echo "$handoff_line"; } >"$LOG.failed"
        echo "$handoff_line" >&2
        exit 79
        ;;
    77)
        stats="$(record_usage no_credits)"
        fail 77 "CODEX_NO_CREDITS: Codex reported 'out of credits' ($(usage_line "$stats")). Retry after fixing billing. Log: $LOG"
        ;;
    76)
        stats="$(record_usage budget_exceeded)"
        final_message_after_kill
        fail 76 "CODEX_BUDGET_EXCEEDED: role=$ROLE cap tool_calls=$MAX_TOOL_CALLS tool_output_kb=$MAX_TOOL_OUTPUT_KB; got $(usage_line "$stats"). The prompt let Codex explore: inline the inputs and name file:line ranges. Thread ${THREAD_FILE} is kept; a resume may ask for the verdict with what it has. Log: $LOG"
        ;;
    75)
        record_usage stalled >/dev/null
        fail 75 "CODEX_STALLED: no event-log change for ${STALL_TIMEOUT}s (fresh retry attempted only for zero-progress stalls). Log: $LOG — if progress was made before the stall, triage manually rather than blindly restarting."
        ;;
    0) ;;
    *)
        stats="$(record_usage failed)"
        errors="$(stat_field "$stats" .errors)"
        echo "error: codex exec failed (rc=$rc); stderr tail:" >&2
        tail -20 "$LOG.stderr" >&2
        fail 1 "CODEX_FAILED rc=$rc errors=${errors:-none} $(usage_line "$stats") log=$LOG"
        ;;
esac

if [ "$MODE" = "start" ] && [ ! -s "$THREAD_FILE" ]; then
    echo "error: no thread.started event found in $LOG — cannot persist the session" >&2
    head -5 "$LOG" >&2
    fail 1 "CODEX_FAILED no thread.started event in $LOG"
fi

# Codex exiting 0 with an empty final message means the run was cut off mid-turn.
if [ ! -s "$OUT" ]; then
    stats="$(record_usage no_final_message)"
    fail 1 "CODEX_FAILED codex exited 0 but wrote no final message to $OUT (run cut off?) errors=$(stat_field "$stats" .errors) $(usage_line "$stats")"
fi

stats="$(record_usage ok)"
ok_line="CODEX_OK thread=$(cat "$THREAD_FILE") role=$ROLE model=$MODEL effort=$EFFORT sandbox=$SANDBOX $(usage_line "$stats") budget=${MAX_TOOL_CALLS}calls/${MAX_TOOL_OUTPUT_KB}kb"
printf '%s\n' "$ok_line" >"$LOG.status"
write_result ok 0 "$ok_line"
echo "$ok_line"
echo "--- final message ---"
cat "$OUT"
