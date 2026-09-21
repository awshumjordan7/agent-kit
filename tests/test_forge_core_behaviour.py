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


def test_labelled_and_numeric_phases_parse_in_document_order(repo_root):
    plan = """## Phases
### Phase A1 — first
### Phase 2 — second
### Phase B3 — third
## Checkpoints
| After | Reason |
|---|---|
| Phase A1 | inspect first |
"""

    result = _harness(repo_root, "parse", {"plan": plan})

    assert result == [
        {"from": "A1", "to": "A1", "reason": "inspect first", "final": False},
        {"from": "2", "to": "B3", "reason": "", "final": True},
    ]


def test_quick_impl_requires_every_quick_condition(repo_root):
    plan = "## Phases\n### Phase 1\nFiles: `src/app.py`\n"

    assert (
        _harness(
            repo_root,
            "role",
            {"lane": "quick", "fullySpecified": True, "plan": plan, "threshold": 8},
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
        == "impl"
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


def test_dry_run_records_triage_tests_only_gates_and_full_final_gate(repo_root):
    journal = _harness(repo_root, "dry", {})
    labels = [entry["label"] for entry in journal]

    assert "triage" in labels
    assert "gate-fix-1" in labels
    assert "gate-final" in labels
    assert "--only tests" in next(
        entry["prompt"] for entry in journal if entry["label"] == "gate-fix-1"
    )
    assert labels.count("fix-2") == 2
