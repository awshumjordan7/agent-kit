# Changelog

One line per instruction change. A change adds its lines under today's `## YYYY-MM-DD`
heading, creating it at the top if missing. Each line reads `- <paths or area>: <reason in one sentence>`.

## 2026-10-08
- core/CLAUDE.md: cut duplicated and narrow text (routing table to a pointer, artifacts and handoff duplicates); replace the fan-out cap with "no cap; batch parallel sub-agents into one Workflow".
- modules/marketing: fragment removed; its rule now lives in the two marketing skills that use it.
- core/agents (locator, triage, scout, worker): skip CLAUDE.md (about 3.7k fewer start tokens everywhere, more in platform-api; to be measured); scout and worker carry their own secret, attribution, contract-capture and repo-conventions lines.
- core/skills/ship-pr, forge, brainstorming: instruction changes need the user's OK on record and a CHANGELOG line.
- CHANGELOG.md: history before this change is in git log and docs/intentional-changes.md.
