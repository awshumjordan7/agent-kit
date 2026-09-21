from __future__ import annotations

import json

from aisetup.compose import install_tree
from aisetup.profile import load_profile
from aisetup.selfcheck import run_selfcheck

EXPECTED_IDS = {
    "python_version",
    "claude_cli",
    "git",
    "mcp_list",
    "home_writable",
    "layers_root_writable",
    "settings_json_parses",
    "profile_valid",
    "claude_md_present",
    "hooks_python_only",
    "forge_config_valid",
    "managed_content",
    "mcp_registered_set",
}


def test_selfcheck_emits_every_capability(claude_home, layers_root, fake_cli):
    fake_cli("claude")
    fake_cli("git")

    results = run_selfcheck(claude_home, layers_root)

    assert {result.id for result in results} == EXPECTED_IDS
    assert all(result.status in {"pass", "fail", "skip"} for result in results)
    assert all(isinstance(result.evidence, str) for result in results)


def test_selfcheck_fails_when_claude_is_missing(claude_home, layers_root, monkeypatch):
    monkeypatch.setenv("PATH", "")

    results = run_selfcheck(claude_home, layers_root)

    claude = next(result for result in results if result.id == "claude_cli")
    assert claude.status == "fail"


def test_selfcheck_skips_mcp_list_for_nondefault_home(tmp_path, layers_root, fake_cli):
    fake_cli("claude")

    results = run_selfcheck(tmp_path / "custom-home", layers_root)

    mcp_list = next(result for result in results if result.id == "mcp_list")
    assert mcp_list.status == "skip"
    assert mcp_list.evidence == "--home is not the default"


def test_managed_content_and_mcp_registered_set_pass_on_clean_home(
    repo_root, claude_home, layers_root, fake_cli, monkeypatch, tmp_path
):
    document = json.loads(
        (repo_root / "tests/fixtures/profiles/public-default.json").read_text(encoding="utf-8")
    )
    document["modules"] = {
        "firecrawl": False,
        "context7": False,
        "memory": False,
        "codex": False,
        "playwright": False,
        "github": False,
        "marketing": False,
        "terminal": False,
    }
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(document), encoding="utf-8")
    profile = load_profile(profile_path)
    install_tree(profile, claude_home)
    layers_root.mkdir()
    (layers_root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    fake_cli(
        "claude",
        'import sys\nraise SystemExit(0 if sys.argv[1:3] == ["mcp", "list"] else 1)\n',
    )
    monkeypatch.setattr("aisetup.selfcheck.is_default_claude_home", lambda _home: True)

    results = run_selfcheck(claude_home, layers_root)

    by_id = {result.id: result for result in results}
    assert by_id["managed_content"].status == "pass"
    assert by_id["mcp_registered_set"].status == "pass"
