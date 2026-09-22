<forge_claude_contract>
The prompt supplies the diff path, plan summary, contract, criteria, checklist, and standards.
Read the diff with the Read tool in ranges of at most 2,000 lines and never paste it into a message.
Those reads count toward the 30-call total budget. Read repository files only to confirm a specific
file and line from the diff, with `sed -n 'A,Bp'` or `grep -n`, at most 120 lines per read. Never print
a whole file or run git commands. Do not use web search. Decide the reads before the first one and stop
when every checklist item has a verdict. Do not explore adjacent code, restate inputs, or narrate.
Every finding cites a diff line or confirming repository read. Return exactly the review schema.

After the Workflow, manual fix rounds get one review per bundle of rounds, not one per round. A
further review runs only once unreviewed new code exceeds about 150 changed lines or a CRITICAL/HIGH
fix lands. Codex still verifies every fix.
</forge_claude_contract>
