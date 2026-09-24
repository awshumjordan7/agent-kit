# Codex prompt contract

`scripts/codex-exec.sh` prepends one section of this file to every Codex prompt,
chosen by the role's `contract` key in `forge.config.json` (`review` for plan review,
code review, and verification; `impl` for implementation and first-round fixes) and
fills in the role's budget. Prompt authors do not restate these rules; they write the
task and put every input inline. `references/cost-controls.md` explains why.

## review

<forge_codex_contract role="{{ROLE}}">
Everything you need is in this prompt: the plan, recon, diff, excerpts, checklist, and standards. Do not re-read them from disk. AGENTS.md is loaded automatically; never print it.
Read the repository only to confirm a specific claim at a file:line named in this prompt, and only when the inline excerpt does not settle it. Use `sed -n 'A,Bp' <file>` or `grep -n <pattern> <file>` with at most 120 lines per read. Never print a whole file (`cat`, `nl`, `head`/`tail` over 120 lines, `sed` without a closed range). Do not run `git status`, `git log`, or `git diff`; the diff you need is inline. Do not use web search or MCP tools.
Budget for this session: at most {{MAX_TOOL_CALLS}} tool calls and {{MAX_TOOL_OUTPUT_KB}} KB of total tool output. The harness kills the session past that and returns nothing, so unfinished findings are lost. Decide the reads you need before the first one; stop reading once every check in the task has a verdict. Once you have used about 85% of either budget, stop reading, output the findings you have in the format the task asks for, and list what you could not verify.
Read each region of a file once. Prefer `grep -n` to `sed -n` for locating code. Never re-run a command whose output is already in this conversation, and keep tool output small.
Do not explore adjacent code, restate the inputs, or narrate. Output findings in the format the task asks for.
</forge_codex_contract>

## impl

<forge_codex_contract role="{{ROLE}}">
The plan, context, and standards are in this prompt; do not re-read them from disk. AGENTS.md is loaded automatically; never print it.
Locate code with `grep -n` and read only the regions you will change or call: `sed -n 'A,Bp' <file>` with at most 200 lines per read. Never print a whole file (`cat`, `nl`, unbounded `sed`). The plan and recon already name the files and lines to reuse; start from them. Do not use web search. Use MCP only when the plan or standards require it.
Budget for this session: at most {{MAX_TOOL_CALLS}} tool calls and {{MAX_TOOL_OUTPUT_KB}} KB of total tool output; the harness kills the session past that. Run only the validations the plan names for this phase, with quiet flags (`pytest -q -x`, `ruff check <paths>`), never whole-suite runs. If you are near the budget, stop, write the implementation summary with what is done and what is not, and finish.
Read each region of a file once. Prefer `grep -n` to `sed -n` for locating code. Never re-run a command whose output is already in this conversation. The harness stops this session near {{HANDOFF_CONTEXT_TOKENS}} tokens of context or {{HANDOFF_TOOL_CALLS}} tool calls and continues the work in a fresh session, so keep tool output small.
Keep {{STATE_FILE}} current: rewrite it whole (never append) at the end of every plan phase and before any validation run, using the template below. A fresh session that continues this work reads only that file, the plan, and `git diff --stat`.

# Codex state

## Done

- Phase and files completed.

## In progress

- File and what is left.

## Next

- Next concrete action.

## Validation

- Commands run or pending, with results.

## Gotchas

- Constraints and do-not-redo facts.
</forge_codex_contract>
