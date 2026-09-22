#!/usr/bin/env bash
# Assemble a bounded plan-review prompt from a plan, investigation, and cited excerpts.
# Usage: build-plan-review-prompt.sh --run-dir <runDir> --repo-dir <repo> [--recon <file>]
#        [--repo-name <name>] [--checks <file>] [--max-excerpt-kb 60] [--context-lines 40]
# The excerpt pack is capped at 60 KB by default.

set -euo pipefail

RUN_DIR="" REPO_DIR="" REPO_NAME="" RECON_FILE="" CHECKS_FILE="" MAX_KB=60 CONTEXT=40
while [ $# -gt 0 ]; do
    case "$1" in
        --run-dir) RUN_DIR="$2"; shift 2 ;;
        --repo-dir) REPO_DIR="$2"; shift 2 ;;
        --repo-name) REPO_NAME="$2"; shift 2 ;;
        --recon) RECON_FILE="$2"; shift 2 ;;
        --checks) CHECKS_FILE="$2"; shift 2 ;;
        --max-excerpt-kb) MAX_KB="$2"; shift 2 ;;
        --context-lines) CONTEXT="$2"; shift 2 ;;
        *) echo "error: unknown flag: $1" >&2; exit 64 ;;
    esac
done
[ -n "$RUN_DIR" ] && [ -n "$REPO_DIR" ] || {
    echo "usage: build-plan-review-prompt.sh --run-dir <d> --repo-dir <r> [--recon <f>] [--max-excerpt-kb 60]" >&2
    exit 64
}
[ -f "$RUN_DIR/plan.md" ] || { echo "error: $RUN_DIR/plan.md not found" >&2; exit 64; }
if [ -z "$RECON_FILE" ]; then
    if [ -f "$RUN_DIR/recon.md" ]; then RECON_FILE="$RUN_DIR/recon.md"; else RECON_FILE="$RUN_DIR/triage.md"; fi
elif [[ "$RECON_FILE" != /* ]] && [ -f "$RUN_DIR/$RECON_FILE" ]; then
    RECON_FILE="$RUN_DIR/$RECON_FILE"
fi
[ -f "$RECON_FILE" ] || { echo "error: investigation file not found: $RECON_FILE" >&2; exit 64; }

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$SKILL_DIR/references/plan-review-prompt.md"
STANDARDS="$SKILL_DIR/references/code-standards.md"
REPO_NAME="${REPO_NAME:-$(basename "$REPO_DIR")}"
EXCERPTS="$RUN_DIR/excerpts.md"
OUT="$RUN_DIR/plan-review-prompt.md"

resolve_path() {
    local path="$1" matches
    if [ -f "$REPO_DIR/$path" ]; then printf '%s\n' "$path"; return; fi
    matches=$(find "$REPO_DIR" -type f -path "*/$path" -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/.venv/*' 2>/dev/null | head -3)
    if [ "$(printf '%s\n' "$matches" | grep -c .)" -eq 1 ]; then printf '%s\n' "${matches#"$REPO_DIR"/}"; fi
}

build_excerpts() {
    local budget=$((MAX_KB * 1024)) written=0 ref path range start end total chunk
    : >"$EXCERPTS"
    while IFS= read -r ref; do
        path="$(resolve_path "${ref%%:*}")"; range="${ref##*:}"
        [ -n "$path" ] && [ -f "$REPO_DIR/$path" ] || continue
        total=$(wc -l <"$REPO_DIR/$path" | tr -d ' ')
        if [[ "$range" == *-* ]]; then start="${range%-*}"; end="${range#*-}"; else start="$range"; end=$((start + CONTEXT)); fi
        [ "$start" -ge 1 ] || start=1
        [ "$end" -le "$total" ] || end="$total"
        [ $((end - start)) -le 119 ] || end=$((start + 119))
        [ "$end" -ge "$start" ] || continue
        chunk="$(printf '### %s:%s-%s\n```\n' "$path" "$start" "$end"; sed -n "${start},${end}p" "$REPO_DIR/$path" | nl -ba -v "$start" -w 5 -s '  '; printf '```\n\n')"
        if [ $((written + ${#chunk})) -gt "$budget" ]; then
            printf '(excerpt budget of %s KB reached; remaining references omitted)\n' "$MAX_KB" >>"$EXCERPTS"
            break
        fi
        printf '%s\n' "$chunk" >>"$EXCERPTS"
        written=$((written + ${#chunk}))
    done < <(grep -oE '[A-Za-z0-9_./-]+\.[A-Za-z]{1,5}:[0-9]+(-[0-9]+)?' "$RECON_FILE" | sed 's#^\./##' | awk -F: '!seen[$0]++')
    [ -s "$EXCERPTS" ] || echo "(no file:line references found in the investigation)" >"$EXCERPTS"
}
build_excerpts

if [ -n "$CHECKS_FILE" ] && [ -s "$CHECKS_FILE" ]; then
    CHECKS="$(cat "$CHECKS_FILE")"
else
    CHECKS="(no additional checks; verify the plan's phases and public API contract against the investigation)"
fi

PLAN_FILE="$RUN_DIR/plan.md" RECON_FILE="$RECON_FILE" EXCERPTS_FILE="$EXCERPTS" STANDARDS_FILE="$STANDARDS" \
TEMPLATE_FILE="$TEMPLATE" OUT_FILE="$OUT" REPO_NAME="$REPO_NAME" REPO_DIR="$REPO_DIR" CHECKS="$CHECKS" \
REVIEW_OUT="$RUN_DIR/plan-review.md" python3 - <<'PY'
import os


def read(name):
    with open(os.environ[name], encoding="utf-8") as handle:
        return handle.read().strip()


text = read("TEMPLATE_FILE")
for token, value in {
    "{{REPO}}": os.environ["REPO_NAME"],
    "{{REPO_DIR}}": os.environ["REPO_DIR"],
    "{{CHECKS}}": os.environ["CHECKS"],
    "{{OUT_PATH}}": os.environ["REVIEW_OUT"],
    "{{PLAN}}": read("PLAN_FILE"),
    "{{RECON}}": read("RECON_FILE"),
    "{{EXCERPTS}}": read("EXCERPTS_FILE"),
    "{{STANDARDS}}": read("STANDARDS_FILE"),
}.items():
    text = text.replace(token, value)
with open(os.environ["OUT_FILE"], "w", encoding="utf-8") as handle:
    handle.write(text + "\n")
PY
echo "PLAN_REVIEW_PROMPT $OUT bytes=$(wc -c <"$OUT" | tr -d ' ') excerpts_bytes=$(wc -c <"$EXCERPTS" | tr -d ' ') refs=$(grep -c '^### ' "$EXCERPTS" || true)"
