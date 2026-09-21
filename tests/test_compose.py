from __future__ import annotations

import hashlib
import json

from aisetup import cli
from aisetup.compose import compose_tree, install_tree
from aisetup.profile import load_profile


def tree_hash(root):
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_compose_orders_claude_sections_and_layered_settings(repo_root, tmp_path, monkeypatch):
    monkeypatch.chdir(repo_root)
    profile = load_profile(repo_root / "tests/fixtures/profiles/overlay-example.json")
    destination = tmp_path / "composed"

    compose_tree(profile, destination)

    claude_md = (destination / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude_md.index("# Collaboration Contract") < claude_md.index("## Overlay: example")
    settings = (destination / "settings.json").read_text(encoding="utf-8")
    assert '"theme": "local"' in settings
    assert settings.index('"matcher": "overlay"') < settings.index('"matcher": "local"')
    agent = (destination / "agents/example-agent.md").read_text(encoding="utf-8")
    assert "model: sonnet" in agent
    assert "maxTurns: 15" in agent


def test_install_replaces_managed_files_and_preserves_unmanaged_paths(
    repo_root, tmp_path, monkeypatch
):
    monkeypatch.chdir(repo_root)
    profile = load_profile(repo_root / "tests/fixtures/profiles/public-default.json")
    home = tmp_path / ".claude"
    (home / "projects").mkdir(parents=True)
    (home / "CLAUDE.md").write_text("old managed", encoding="utf-8")
    (home / "old.txt").write_text("old", encoding="utf-8")
    (home / "projects/session.jsonl").write_text("session", encoding="utf-8")

    result = install_tree(profile, home)

    assert result.backup is not None
    assert (home / "CLAUDE.md").read_text(encoding="utf-8") != "old managed"
    assert (home / "old.txt").read_text(encoding="utf-8") == "old"
    assert (home / "projects/session.jsonl").read_text(encoding="utf-8") == "session"
    assert (result.backup / "CLAUDE.md").read_text(encoding="utf-8") == "old managed"
    assert (result.backup / "old.txt").read_text(encoding="utf-8") == "old"
    assert (result.backup / "projects/session.jsonl").read_text(encoding="utf-8") == "session"


def test_install_preserves_unmanaged_symlink(repo_root, tmp_path, monkeypatch):
    monkeypatch.chdir(repo_root)
    profile = load_profile(repo_root / "tests/fixtures/profiles/public-default.json")
    home = tmp_path / ".claude"
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "session.jsonl").write_text("session", encoding="utf-8")
    home.mkdir()
    (home / "projects").symlink_to(projects, target_is_directory=True)

    install_tree(profile, home)

    assert (home / "projects").is_symlink()
    assert (home / "projects").readlink() == projects


def test_install_dry_run_lists_unmanaged_paths(repo_root, tmp_path, monkeypatch, capsys, fake_cli):
    monkeypatch.chdir(repo_root)
    fake_cli("claude")
    profile = repo_root / "tests/fixtures/profiles/public-default.json"
    home = tmp_path / ".claude"
    (home / "projects").mkdir(parents=True)
    (home / "old.txt").write_text("old", encoding="utf-8")
    (home / "projects/session.jsonl").write_text("session", encoding="utf-8")

    result = cli.main(
        [
            "install",
            "--profile",
            str(profile),
            "--dry-run",
            "--home",
            str(home),
            "--layers-root",
            str(tmp_path / "layers"),
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    preserved = output.split("Preserved (unmanaged):\n", 1)[1].split("Merged settings:\n", 1)[0]
    assert preserved.splitlines() == ["old.txt", "projects"]


def test_install_fills_missing_overlay_answer_from_default(
    repo_root, tmp_path, monkeypatch, fake_cli, capsys
):
    monkeypatch.chdir(repo_root)
    fake_cli("claude")
    profile_path = tmp_path / "profile.json"
    document = json.loads(
        (repo_root / "tests/fixtures/profiles/overlay-example.json").read_text(encoding="utf-8")
    )
    document["answers"].pop("overlay.api_key")
    profile_path.write_text(json.dumps(document), encoding="utf-8")

    result = cli.main(
        [
            "install",
            "--profile",
            str(profile_path),
            "--dry-run",
            "--layers-root",
            str(tmp_path / "layers"),
        ]
    )

    assert result == 0
    assert "https://example.invalid/mcp?api_key=" in capsys.readouterr().out


def test_install_rejects_missing_overlay_answer_without_default(
    repo_root, tmp_path, monkeypatch, fake_cli, capsys
):
    monkeypatch.chdir(repo_root)
    fake_cli("claude")
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    manifest = (repo_root / "tests/fixtures/overlay-example/overlay.toml").read_text(
        encoding="utf-8"
    )
    (overlay / "overlay.toml").write_text(manifest.replace('default = ""\n', ""), encoding="utf-8")
    profile_path = tmp_path / "profile.json"
    document = json.loads(
        (repo_root / "tests/fixtures/profiles/overlay-example.json").read_text(encoding="utf-8")
    )
    document["layers"]["overlay"]["path"] = str(overlay)
    document["answers"].pop("overlay.api_key")
    profile_path.write_text(json.dumps(document), encoding="utf-8")

    result = cli.main(["install", "--profile", str(profile_path), "--dry-run"])

    assert result == 4
    assert "overlay.api_key" in capsys.readouterr().err


def test_compose_is_byte_identical_on_replay(repo_root, tmp_path, monkeypatch):
    monkeypatch.chdir(repo_root)
    profile = load_profile(repo_root / "tests/fixtures/profiles/public-default.json")
    first = tmp_path / "first"
    second = tmp_path / "second"

    compose_tree(profile, first)
    compose_tree(profile, second)

    assert tree_hash(first) == tree_hash(second)


def test_local_claude_fragment_uses_local_heading(repo_root, tmp_path, monkeypatch):
    monkeypatch.chdir(repo_root)
    profile = load_profile(repo_root / "tests/fixtures/profiles/public-default.json")
    local = tmp_path / "local"
    local.mkdir()
    (local / "CLAUDE.fragment.md").write_text("Local rules\n", encoding="utf-8")
    profile["layers"]["local"] = str(local)

    compose_tree(profile, tmp_path / "composed")

    text = (tmp_path / "composed/CLAUDE.md").read_text(encoding="utf-8")
    assert "## Local\n\nLocal rules" in text


def test_install_maps_missing_template_key_to_exit_five(repo_root, tmp_path, monkeypatch, fake_cli):
    monkeypatch.chdir(repo_root)
    fake_cli("claude")
    profile = json.loads(
        (repo_root / "tests/fixtures/profiles/public-default.json").read_text(encoding="utf-8")
    )
    overlay = tmp_path / "overlay"
    (overlay / "templates").mkdir(parents=True)
    (overlay / "overlay.toml").write_text(
        'name = "missing-key"\ndescription = "test"\n'
        '[[templates]]\nsrc = "templates/missing.tmpl"\ndest = "missing.txt"\n',
        encoding="utf-8",
    )
    (overlay / "templates/missing.tmpl").write_text("{{missing.value}}", encoding="utf-8")
    profile["layers"]["overlay"] = {"path": str(overlay)}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")

    result = cli.main(
        [
            "install",
            "--profile",
            str(path),
            "--dry-run",
            "--home",
            str(tmp_path / "home"),
            "--layers-root",
            str(tmp_path / "layers"),
        ]
    )

    assert result == 5
