from __future__ import annotations

import json
import subprocess


def _harness(repo_root, action, payload):
    completed = subprocess.run(
        [
            "node",
            str(repo_root / "tests/forge_core_harness.mjs"),
            "core/skills/forge/references/forge-core.js",
            action,
            json.dumps(payload),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_quick_impl_requires_specified_small_plan(repo_root):
    plan = """## Phases
`args.dryRun`
### Phase 1
#### Files
`src/app.py`
"""

    assert (
        _harness(
            repo_root,
            "role",
            {"lane": "quick", "fullySpecified": True, "plan": plan, "threshold": 1},
        )
        == "quick-impl"
    )
    assert (
        _harness(
            repo_root,
            "role",
            {"lane": "quick", "fullySpecified": False, "plan": plan, "threshold": 8},
        )
        == "impl"
    )
    assert (
        _harness(
            repo_root,
            "role",
            {"lane": "dev", "fullySpecified": True, "plan": plan, "threshold": 8},
        )
        == "quick-impl"
    )


def test_triage_partition_routes_confirmed_uncertain_and_dropped(repo_root):
    findings = [
        {"file": "a.py", "line": 1, "claim": "a"},
        {"file": "b.py", "line": 2, "claim": "b"},
        {"file": "c.py", "line": 3, "claim": "c"},
    ]
    verdicts = [
        {"file": "a.py", "line": 1, "real": "yes", "worthIt": True, "why": "real"},
        {"file": "b.py", "line": 2, "real": "uncertain", "worthIt": True, "why": "unclear"},
        {"file": "c.py", "line": 3, "real": "no", "worthIt": True, "why": "stale"},
    ]

    result = _harness(
        repo_root, "triage", {"findings": findings, "verdicts": verdicts, "auto": False}
    )

    assert [item["file"] for item in result["fix"]] == ["a.py"]
    assert [item["finding"]["file"] for item in result["disputes"]] == ["b.py"]
    assert [item["finding"]["file"] for item in result["dropped"]] == ["c.py"]


def test_sandbox_requires_enabled_stage_and_configured_repo(repo_root):
    repos = {"frontend": "web", "backend": "api"}

    assert _harness(repo_root, "sandbox", {"stageOn": True, "repo": "owner/api", "repos": repos})
    assert not _harness(
        repo_root, "sandbox", {"stageOn": False, "repo": "owner/api", "repos": repos}
    )
    assert not _harness(
        repo_root, "sandbox", {"stageOn": True, "repo": "owner/tooling", "repos": repos}
    )


def test_sandbox_checks_use_configured_repo_roots(repo_root):
    result = _harness(
        repo_root,
        "sandbox-checks",
        {"repos": {"frontend": "web-app", "backend": "api-server"}},
    )

    assert result["backend"].startswith("cd /app/api-server && { [ -f /app/env.sh ]")
    assert result["frontend"].startswith("cd /app/web-app &&")


def test_dry_run_resolves_findings_in_first_round(repo_root):
    journal = _harness(repo_root, "dry", {})
    labels = [entry["label"] for entry in journal]

    assert all(
        label in labels for label in ("triage", "fix-1", "verify-1", "gate-fix-1", "gate-final")
    )
    assert "--only tests" in next(
        entry["prompt"] for entry in journal if entry["label"] == "gate-fix-1"
    )
    assert not any(label.startswith("judge-") for label in labels)


def test_ship_stages_deleted_paths_and_only_skips_untracked_missing_paths(repo_root):
    journal = _harness(repo_root, "dry", {})
    ship = next(entry for entry in journal if entry["label"] == "ship")

    assert "git add --" in ship["prompt"]
    assert "deletion" in ship["prompt"]
    assert "does not exist is skipped" not in ship["prompt"]


def test_codex_budget_error_is_not_retried(repo_root):
    result = _harness(repo_root, "codex-budget", {})

    assert result["error"].startswith("CODEX_BUDGET_EXCEEDED")


def test_codex_handoff_exhaustion_is_not_retried(repo_root):
    result = _harness(repo_root, "codex-handoff-exhausted", {})

    assert result["error"].startswith("CODEX_HANDOFF_EXHAUSTED")


def test_dry_run_stubborn_findings_stop_after_two_judgments(repo_root):
    journal = _harness(repo_root, "dry", {"dryRunStubborn": True})
    labels = [entry["label"] for entry in journal]

    assert all(label in labels for label in ("judge-1", "fix-2", "judge-2"))
    red_journal = _harness(repo_root, "dry", {"dryRunFailGate": "gate-fix-1"})
    red_labels = [entry["label"] for entry in red_journal]
    assert "ship-sync" not in red_labels[red_labels.index("gate-fix-1") + 1 :]


# The Workflow runtime evaluates everything after the meta export as a script,
# so a second top-level `export` keyword breaks loading.
def test_forge_core_has_single_meta_export(repo_root):
    source = (repo_root / "core/skills/forge/references/forge-core.js").read_text()
    export_lines = [line for line in source.splitlines() if line.startswith("export ")]

    assert len(export_lines) == 1
    assert export_lines[0].startswith("export const meta")
