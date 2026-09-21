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


def test_install_backs_up_existing_home_before_replacement(repo_root, tmp_path, monkeypatch):
    monkeypatch.chdir(repo_root)
    profile = load_profile(repo_root / "tests/fixtures/profiles/public-default.json")
    home = tmp_path / ".claude"
    home.mkdir()
    (home / "old.txt").write_text("old", encoding="utf-8")

    result = install_tree(profile, home)

    assert result.backup is not None
    assert (result.backup / "old.txt").read_text(encoding="utf-8") == "old"
    assert (home / "CLAUDE.md").is_file()
    assert not (home / "old.txt").exists()


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


def test_install_maps_missing_template_key_to_exit_five(repo_root, tmp_path, monkeypatch):
    monkeypatch.chdir(repo_root)
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
