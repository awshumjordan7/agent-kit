You are reviewing a short plan for a change its author judges small and low risk, before any code is written. Repository: {{REPO}} at {{REPO_DIR}}. The plan and code excerpts for the file:line references it cites are below.

Check:
(a) every path, name and line claim in the plan matches the excerpts;
(b) the change as described would not fail or break a caller;
(c) the change is small and low risk: it touches no stored data, migration, public API shape, sign-in, permissions, tenant isolation, secrets or money; one revert undoes it; what it should do is already clear, with no design choice left for the user; and the plan has one phase, no seam with another repository or service, and no open question;
(d) `## Tests` is present, as the test table or the line `None: <reason>`.
Extra checks: {{CHECKS}}

Output. Print the review; the caller saves it to {{OUT_PATH}}:
- First line, the verdict: PLAN OK | NEEDS CHANGES | NOT SMALL. Answer NOT SMALL when (c) fails.
- Then at most five numbered findings, one or two sentences each, with file:line.
No praise, no summary of the plan, and no request for a section a short plan leaves out. Do not modify any file.

PLAN
{{PLAN}}

CODE EXCERPTS (from the plan's file:line references; the line numbers are real)
{{EXCERPTS}}
