from __future__ import annotations

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
