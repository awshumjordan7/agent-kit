You are reviewing an implementation plan before any code is written. Repository: {{REPO}} at {{REPO_DIR}}. The plan, the recon (what exists to reuse, with file:line evidence), code excerpts for every file:line the recon cites, and the code standards are all below. The recon was verified against this checkout; treat its file:line claims as evidence and check the plan against them.

Your job: find what will fail, what already exists that the plan duplicates, and what the plan gets wrong about this codebase. Verify each of these specific checks and give each a verdict:
{{CHECKS}}

Check the plan's `## Tests` section. A missing section is a finding. Unless it contains the
single line `None: <reason>`, it must contain one table where every test row fills all five
columns: `Section`, `Test`, `Pins`, `How`, and `Why`. Each `Why` must tie the test to a plan risk
or acceptance criterion; a test that pins nothing the plan risks or requires is a finding.

Output format. Write the file {{OUT_PATH}} and also print it:
- One line verdict: PLAN OK | PLAN NEEDS CHANGES | PLAN WRONG.
- Findings as a numbered list. Each: severity (CRITICAL | HIGH | MEDIUM | LOW), file:line evidence, what fails or is wrong, the concrete fix. CRITICAL only for something that makes the plan wrong. Do not pad.
- One line per specific check above: check number, verdict (holds | fails | could not verify), evidence.
- A short "Already exists, reuse instead" list if any.
Do not modify any file other than {{OUT_PATH}}. Do not implement anything.

PLAN
{{PLAN}}

RECON
{{RECON}}

CODE EXCERPTS (from the recon's file:line references; the line numbers are real)
{{EXCERPTS}}

CODE STANDARDS (the plan's approved test table and comments must comply)
{{STANDARDS}}
