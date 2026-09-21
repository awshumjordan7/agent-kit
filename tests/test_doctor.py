from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import doctor
import pytest

CLAUDE_MD = """# Global instructions

### Don't

- Do not guess.

### Comments

Explain only constraints.

### Tests

Test behavior.
"""


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def claude_root(tmp_path: Path) -> Path:
    root = tmp_path / ".claude"
    write(root / "CLAUDE.md", CLAUDE_MD)
    write(
        root / "settings.json",
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "bash $HOME/.claude/hooks/healthy.sh",
                                }
                            ],
                        }
                    ]
                },
                "skillOverrides": {"forge": "on"},
                "enabledPlugins": {},
            }
        ),
    )
    write(
        root / "agents/worker.md",
        """---
name: worker
description: Executes work
model: sonnet
---
# Worker
Keep the body short.
""",
    )
    write(
        root / "skills/forge/SKILL.md",
        """---
name: forge
description: Runs a workflow
---
# Forge
Read references/guide.md.
""",
    )
    write(root / "skills/forge/references/guide.md", "Use GPT-5.6.\n")
    write(
        root / "skills/forge/references/forge-core.js",
        """export function run() {
  return agent("prompt", { model: "sonnet", effort: "low" });
}
""",
    )
    write(root / "hooks/healthy.sh", "#!/bin/sh\nexit 0\n")
    write(
        root / "projects/example/memory/MEMORY.md",
        "- [Useful note](useful-note.md) — reminder\n",
    )
    write(root / "projects/example/memory/useful-note.md", "# Useful note\n")
    expected = (
        doctor.HEADER
        + "### Don't\n\n- Do not guess.\n\n"
        + "### Comments\n\nExplain only constraints.\n\n"
        + "### Tests\n\nTest behavior.\n"
    )
    write(root / "skills/forge/references/code-standards.md", expected)
    ctx = doctor.Context(root, doctor.load_config())
    agents, _ = doctor.expected_codex_agents(ctx)
    write(root.parent / ".codex/AGENTS.md", agents or "")
    return root


def assert_only_issue(root: Path, check: str, level: str) -> doctor.Finding:
    findings = doctor.run_checks(root)
    issues = [finding for finding in findings if finding.level in {"WARN", "FAIL"}]
    assert [(finding.check, finding.level) for finding in issues] == [(check, level)]
    return issues[0]


def test_clean_tree_passes(claude_root: Path) -> None:
    findings = doctor.run_checks(claude_root)
    assert doctor.summary(findings) == {"pass": 13, "warn": 0, "fail": 0}


def test_paths_exist_reports_source_line(claude_root: Path) -> None:
    skill = claude_root / "skills/forge/SKILL.md"
    skill.write_text(skill.read_text() + "Read references/missing.md.\n", encoding="utf-8")

    finding = assert_only_issue(claude_root, "paths-exist", "FAIL")

    assert finding.path == "skills/forge/SKILL.md"
    assert finding.line == 7


def test_no_scratch_reports_artifact(claude_root: Path) -> None:
    write(claude_root / "skills/forge/notes.tmp", "scratch\n")

    finding = assert_only_issue(claude_root, "no-scratch", "FAIL")

    assert finding.path == "skills/forge/notes.tmp"


def test_hooks_resolve_reports_missing_script(claude_root: Path) -> None:
    settings = json.loads((claude_root / "settings.json").read_text())
    settings["hooks"]["SessionStart"][0]["hooks"][0]["command"] = (
        "python3 $HOME/.claude/hooks/missing.py"
    )
    write(claude_root / "settings.json", json.dumps(settings))

    finding = assert_only_issue(claude_root, "hooks-resolve", "FAIL")

    assert finding.path == "settings.json"


def test_hooks_resolve_reports_invalid_json(claude_root: Path) -> None:
    write(claude_root / "settings.json", "{not json\n")

    finding = assert_only_issue(claude_root, "hooks-resolve", "FAIL")

    assert finding.line == 1
    assert "invalid JSON" in finding.message


def test_model_names_reports_old_gpt_version(claude_root: Path) -> None:
    write(claude_root / "skills/forge/references/guide.md", "Use GPT-5.5.\n")

    finding = assert_only_issue(claude_root, "model-names", "FAIL")

    assert finding.path == "skills/forge/references/guide.md"
    assert finding.line == 1


def test_explicit_model_reports_agent_without_model(claude_root: Path) -> None:
    write(
        claude_root / "skills/forge/references/forge-core.js",
        """export function run() {
  return agent("model: text in the prompt", { effort: "low" });
}
""",
    )

    finding = assert_only_issue(claude_root, "explicit-model", "FAIL")

    assert finding.line == 2


def test_explicit_model_ignores_long_template_literal_with_key(claude_root: Path) -> None:
    filler = "line of prompt text with ) and { and } characters in it.\n" * 12
    write(
        claude_root / "skills/forge/references/forge-core.js",
        f"""export function run() {{
  return agent(
    `{filler}Interpolated: ${{value}} and more text.`,
    {{ model: 'sonnet', effort: 'high' }}
  );
}}
""",
    )

    findings = doctor.run_checks(claude_root)
    issues = [f for f in findings if f.level in {"WARN", "FAIL"}]

    assert issues == []


def test_explicit_model_ignores_long_template_literal_with_shorthand(claude_root: Path) -> None:
    filler = "line of prompt text with ) and { and } characters in it.\n" * 12
    write(
        claude_root / "skills/forge/references/forge-core.js",
        f"""export function run() {{
  return agent(
    `{filler}Interpolated: ${{value}} and more text.`,
    {{ model, effort: 'high' }}
  );
}}
""",
    )

    findings = doctor.run_checks(claude_root)
    issues = [f for f in findings if f.level in {"WARN", "FAIL"}]

    assert issues == []


def test_explicit_model_reports_options_object_missing_model(claude_root: Path) -> None:
    write(
        claude_root / "skills/forge/references/forge-core.js",
        """export function run() {
  return agent("prompt text", { effort: "low", schema: FIX_SCHEMA });
}
""",
    )

    finding = assert_only_issue(claude_root, "explicit-model", "FAIL")

    assert finding.line == 2


def test_explicit_model_ignores_agentT_call_without_model(claude_root: Path) -> None:
    write(
        claude_root / "skills/forge/references/forge-core.js",
        """export function run() {
  return agentT("prompt text", { effort: "low" });
}
""",
    )

    findings = doctor.run_checks(claude_root)
    issues = [f for f in findings if f.level in {"WARN", "FAIL"}]

    assert issues == []


def test_builtin_agents_reports_unpinned_agent_type(claude_root: Path) -> None:
    skill = claude_root / "skills/forge/SKILL.md"
    skill.write_text(
        skill.read_text() + "Spawn Explore sub-agents to map the code.\n", encoding="utf-8"
    )

    finding = assert_only_issue(claude_root, "builtin-agents", "FAIL")

    assert finding.path == "skills/forge/SKILL.md"
    assert finding.line == 7


def test_builtin_agents_allows_prohibition_wording(claude_root: Path) -> None:
    skill = claude_root / "skills/forge/SKILL.md"
    skill.write_text(
        skill.read_text() + "Use worker instead of the general-purpose agent.\n", encoding="utf-8"
    )

    findings = doctor.run_checks(claude_root)

    assert doctor.summary(findings) == {"pass": 13, "warn": 0, "fail": 0}


def test_agent_defers_warns_on_long_restated_skill(claude_root: Path) -> None:
    body = "# Worker\nUse skills/forge.\n" + "\n".join(f"Rule {index}" for index in range(61))
    write(
        claude_root / "agents/worker.md",
        "---\nname: worker\ndescription: Executes work\nmodel: sonnet\n---\n" + body + "\n",
    )

    finding = assert_only_issue(claude_root, "agent-defers", "WARN")

    assert finding.line == 7
    assert finding.message == "restates skill rules; should defer"


def test_code_standards_sync_reports_drift(claude_root: Path) -> None:
    write(claude_root / "skills/forge/references/code-standards.md", "stale\n")

    finding = assert_only_issue(claude_root, "code-standards-sync", "FAIL")

    assert finding.path == "skills/forge/references/code-standards.md"


def test_codex_agents_sync_reports_drift(claude_root: Path) -> None:
    write(claude_root.parent / ".codex/AGENTS.md", "stale\n")

    finding = assert_only_issue(claude_root, "codex-agents-sync", "FAIL")

    assert finding.path.endswith(".codex/AGENTS.md")


def test_codex_agents_strips_claude_only_parts(claude_root: Path) -> None:
    write(
        claude_root / "CLAUDE.md",
        "# Contract\n\n## Keep\n\n- **memory & auto-memory**: Claude only\n"
        "  continued line\n- **semgrep**: keep me\n\n"
        "## Model Routing (Sub-Agents)\n\n| a | b |\n\n## Also keep\n\nText.\n",
    )
    config = doctor.load_config()
    config["codex"] = {
        "exclude_sections": ["Model Routing (Sub-Agents)"],
        "exclude_bullets": ["memory & auto-memory"],
    }

    expected, error = doctor.expected_codex_agents(doctor.Context(claude_root, config))

    assert error is None
    assert expected == (
        doctor.CODEX_HEADER
        + "# Contract\n\n## Keep\n\n- **semgrep**: keep me\n\n## Also keep\n\nText.\n"
    )


def test_fix_regenerates_codex_agents(claude_root: Path) -> None:
    target = claude_root.parent / ".codex/AGENTS.md"
    write(target, "stale\n")

    findings = doctor.run_checks(claude_root, fix=True)

    fixed = [finding for finding in findings if finding.level == "FIXED"]
    assert [finding.check for finding in fixed] == ["codex-agents-sync"]
    assert target.read_text().startswith(doctor.CODEX_HEADER + "# Global instructions")


def test_overrides_exist_warns_on_unknown_skill(claude_root: Path) -> None:
    settings = json.loads((claude_root / "settings.json").read_text())
    settings["skillOverrides"] = {"missing-skill": "off"}
    write(claude_root / "settings.json", json.dumps(settings))

    finding = assert_only_issue(claude_root, "overrides-exist", "WARN")

    assert "missing-skill" in finding.message


def test_base_branches_warns_on_unmapped_origin(claude_root: Path) -> None:
    reference = claude_root / "skills/ship-pr/references/base-branches.json"
    write(reference, "{}\n")
    repo = claude_root.parent / "Projects/work/unity/widget"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:Acme/widget.git"],
        check=True,
    )

    finding = assert_only_issue(claude_root, "base-branches", "WARN")

    assert finding.path == str(repo)
    assert "Acme/widget" in finding.message


def test_memory_index_warns_on_unlinked_file(claude_root: Path) -> None:
    write(claude_root / "projects/example/memory/orphan.md", "# Orphan\n")

    finding = assert_only_issue(claude_root, "memory-index", "WARN")

    assert finding.path == "projects/example/memory/orphan.md"


def test_frontmatter_reports_missing_required_key(claude_root: Path) -> None:
    agent = claude_root / "agents/worker.md"
    agent.write_text(
        agent.read_text().replace("description: Executes work\n", ""), encoding="utf-8"
    )

    finding = assert_only_issue(claude_root, "frontmatter", "FAIL")

    assert finding.path == "agents/worker.md"
    assert "description" in finding.message


def test_fix_regenerates_code_standards(claude_root: Path) -> None:
    target = claude_root / "skills/forge/references/code-standards.md"
    write(target, "stale\n")

    findings = doctor.run_checks(claude_root, fix=True)

    fixed = [finding for finding in findings if finding.level == "FIXED"]
    assert [finding.check for finding in fixed] == ["code-standards-sync"]
    expected, error = doctor.expected_code_standards(
        doctor.Context(claude_root, doctor.load_config())
    )
    assert error is None
    assert target.read_text() == expected
    assert doctor.summary(findings) == {"pass": 13, "warn": 0, "fail": 0}


def test_json_output_shape(claude_root: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(Path(doctor.__file__)), "--root", str(claude_root), "--json"],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["summary"] == {"pass": 13, "warn": 0, "fail": 0}
    assert len(payload["findings"]) == 13
    assert set(payload["findings"][0]) == {"level", "check", "path", "line", "message"}
