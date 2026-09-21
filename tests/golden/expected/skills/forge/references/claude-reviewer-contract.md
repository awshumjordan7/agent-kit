<forge_claude_contract>
Everything you need is in this prompt: the diff, plan summary, contract, criteria, checklist, and
standards. Do not re-read them from disk. Read repository files only to confirm a specific file:line
the diff touches, with `sed -n 'A,Bp'` or `grep -n`, at most 120 lines per read. Never print a whole
file. Do not run git commands; the diff is inline. Do not use web search. Budget: at most 30 tool calls;
decide the reads you need before the first one and stop when every checklist item has a verdict. Do not
explore adjacent code, restate the inputs, or narrate. Every finding cites a file:line from the diff or
a confirming read. Return exactly the review schema.

After the Workflow, manual fix rounds get one review per bundle of rounds, not one per round. A
further review runs only once unreviewed new code exceeds about 150 changed lines or a CRITICAL/HIGH
fix lands. Codex still verifies every fix.
</forge_claude_contract>
