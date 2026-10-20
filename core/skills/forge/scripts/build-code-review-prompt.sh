#!/usr/bin/env bash
# Build a code-review prompt for a change made outside forge. It never runs the review.
# Usage: build-code-review-prompt.sh --run-dir <runDir> --repo-dir <repo> [--label change]
#        [--plan <file>] [--base <ref>]
# Without --base the diff is the uncommitted change against HEAD. --base <branch> diffs the whole branch
# from its merge-base with origin/<branch>; any other base (HEAD~1, a sha) diffs from its merge-base with HEAD.
# The plan defaults to <runDir>/plan.md; a missing plan file means the change has no plan.

set -euo pipefail

RUN_DIR="" REPO_DIR="" LABEL="change" PLAN_FILE="" BASE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --run-dir) RUN_DIR="$2"; shift 2 ;;
        --repo-dir) REPO_DIR="$2"; shift 2 ;;
        --label) LABEL="$2"; shift 2 ;;
        --plan) PLAN_FILE="$2"; shift 2 ;;
        --base) BASE="$2"; shift 2 ;;
        *) echo "error: unknown flag: $1" >&2; exit 64 ;;
    esac
done
[ -n "$RUN_DIR" ] && [ -n "$REPO_DIR" ] || {
    echo "usage: build-code-review-prompt.sh --run-dir <d> --repo-dir <r> [--label change] [--plan <f>] [--base <ref>]" >&2
    exit 64
}
[[ "$LABEL" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "error: --label must match [A-Za-z0-9_-]+" >&2; exit 64; }
# context-gate.json marks a forge run, which the ship check exempts.
[ "$LABEL" != "gate" ] || { echo "error: --label gate is reserved for forge runs" >&2; exit 64; }
[ -d "$REPO_DIR" ] || { echo "error: repo dir not found: $REPO_DIR" >&2; exit 64; }

mkdir -p "$RUN_DIR"
RUN_DIR="$(cd "$RUN_DIR" && pwd)"
REPO_DIR="$(cd "$REPO_DIR" && pwd)"
PLAN_FILE="${PLAN_FILE:-$RUN_DIR/plan.md}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE="$SKILL_DIR/references/code-review-prompt.md"
SHIP_RECORD="$SKILL_DIR/../ship-pr/scripts/ship_record.py"
CONFIG_FILE="${FORGE_CODEX_EXEC_SKILL_DIR:-$SKILL_DIR}/forge.config.json"
CONTEXT_JSON="$RUN_DIR/context-$LABEL.json"
OUT="$RUN_DIR/code-review-prompt-$LABEL.md"

context_args=(context --run-dir "$RUN_DIR" --repo "$REPO_DIR" --plan-file "$PLAN_FILE" --label "$LABEL")
[ -z "$BASE" ] || context_args+=(--base "$BASE")
facts="$(python3 "$SCRIPT_DIR/run_context.py" "${context_args[@]}")"
error="$(jq -r '.facts.error // ""' <<<"$facts")"
[ -z "$error" ] || { echo "error: run_context.py context: $error" >&2; exit 1; }
[ "$(jq -r '.facts.diffValid' <<<"$facts")" = "true" ] || { echo "error: no changes to review in $REPO_DIR" >&2; exit 64; }
DIFF="$(jq -r '.facts.diffPath' <<<"$facts")"
BRIEF="$(jq -r '.facts.briefPath' <<<"$facts")"

# The snapshot hashes the files now, as the reviewer will see them, not when the verdict returns.
python3 "$SHIP_RECORD" snapshot --repo "$REPO_DIR" --run-dir "$RUN_DIR" --label "$LABEL" \
    --files-json "$CONTEXT_JSON" >&2

TEMPLATE_FILE="$TEMPLATE" BRIEF_FILE="$BRIEF" OUT_FILE="$OUT" PROJECT_DIR="$REPO_DIR" DIFF_PATH="$DIFF" \
python3 - <<'PY'
import os


def read(name):
    with open(os.environ[name], encoding="utf-8") as handle:
        return handle.read().strip()


text = read("TEMPLATE_FILE")
for token in ("PROJECT_DIR", "DIFF_PATH"):
    text = text.replace("{{" + token + "}}", os.environ[token])
with open(os.environ["OUT_FILE"], "w", encoding="utf-8") as handle:
    handle.write(f"{text}\n\nBRIEF\n{read('BRIEF_FILE')}\n")
PY

PROVIDER="codex"
if [ -f "$CONFIG_FILE" ]; then
    PROVIDER="$(jq -r '.roles.review.provider // "codex"' "$CONFIG_FILE")"
fi

echo "CODE_REVIEW_PROMPT $OUT"
echo "DIFF $DIFF"
echo "BRIEF $BRIEF"
echo "FILES $CONTEXT_JSON"
echo "PROVIDER $PROVIDER"
# A start without --inline-diff sends Codex a prompt that promises a diff it never gets.
if [ "$PROVIDER" = "codex" ]; then
    LOG="$RUN_DIR/codex-review-$LABEL.jsonl"
    FINAL="$RUN_DIR/codex-review-$LABEL-final.md"
    printf 'START bash ~/.claude/skills/forge/scripts/codex-exec.sh start --role review --thread-file %q --prompt-file %q --inline-diff %q --cd %q --sandbox read-only --log %q --out %q\n' \
        "$RUN_DIR/codex-review-$LABEL.thread" "$OUT" "$DIFF" "$REPO_DIR" "$LOG" "$FINAL"
    printf 'WATCH bash ~/.claude/skills/forge/scripts/codex-exec.sh watch --log %q --out %q\n' "$LOG" "$FINAL"
fi
