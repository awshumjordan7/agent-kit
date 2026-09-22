from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from aisetup.layers import layer_data, resolve_layers
from aisetup.profile import load_profile, load_recommended_profile, profile_render_context
from aisetup.render import render_text


def _render(repo_root, profile):
    defaults, _ = load_recommended_profile(repo_root)
    layers = resolve_layers(profile)
    context = profile_render_context(
        defaults,
        [fragment for layer in layers.layers for fragment in layer_data(layer)],
        profile,
    )
    template = repo_root / "core/templates/forge.config.json.tmpl"
    return json.loads(render_text(template.read_text(encoding="utf-8"), context, source=template))


def test_forge_config_codex_off_uses_claude_and_disables_stages(repo_root, monkeypatch):
    monkeypatch.chdir(repo_root)
    profile = load_profile(repo_root / "tests/fixtures/profiles/public-default.json")

    rendered = _render(repo_root, profile)

    for role in ("impl", "quick-impl", "review", "plan-review"):
        assert rendered["roles"][role]["provider"] == "claude"
        assert rendered["roles"][role]["model"] == "opus"
    assert rendered["stages"] == {"sandbox": False, "ff_review": False, "qa_login": False}
    assert rendered["thresholds"] == {"quickReviewThreshold": 8}
    assert rendered["ticketUrl"] == ""
    assert rendered["repos"] == {"frontend": "", "backend": ""}
    assert set(rendered["lenses"]) == {"security", "design"}


def test_forge_config_codex_on_uses_codex_role_defaults(repo_root, tmp_path, monkeypatch):
    monkeypatch.chdir(repo_root)
    document = json.loads(
        (repo_root / "tests/fixtures/profiles/public-default.json").read_text(encoding="utf-8")
    )
    document["modules"] = {"codex": True}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    profile = load_profile(path)

    assert profile["forge"]["roles"]["impl"] == {
        "provider": "codex",
        "model": "gpt-5.6-sol",
        "effort": "high",
    }
    assert profile["forge"]["roles"]["quick-impl"]["model"] == "gpt-5.6-luna"


def test_overlay_data_enables_sandbox_and_adds_gate(repo_root, monkeypatch):
    monkeypatch.chdir(repo_root)
    profile = load_profile(repo_root / "tests/fixtures/profiles/overlay-example.json")

    rendered = _render(repo_root, profile)

    assert rendered["stages"]["sandbox"] is True
    assert "~/Projects/example" in rendered["gate"]


def test_codex_exec_resolves_model_and_effort_from_top_level_roles(repo_root, tmp_path):
    if not shutil.which("jq"):
        pytest.skip("jq is not installed")
    skill = tmp_path / "forge"
    (skill / "scripts").mkdir(parents=True)
    shutil.copy2(
        repo_root / "core/skills/forge/scripts/codex-exec.sh",
        skill / "scripts/codex-exec.sh",
    )
    (skill / "forge.config.json").write_text(
        json.dumps(
            {
                "roles": {"impl": {"model": "top-model", "effort": "high"}},
                "codex": {
                    "roles": {"impl": {"model": "old-model", "effort": "low"}},
                    "defaultRole": "review",
                },
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(skill / "scripts/codex-exec.sh"), "config", "--role", "impl"],
        check=False,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if key != "FORGE_CODEX_EXEC_SKILL_DIR"},
    )

    assert result.returncode == 0, result.stderr
    assert "model=top-model" in result.stdout
    assert "effort=high" in result.stdout
