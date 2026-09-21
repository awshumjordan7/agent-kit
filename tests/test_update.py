from __future__ import annotations

import subprocess

from aisetup import update
from aisetup.compose import install_tree
from aisetup.profile import load_profile


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True)


def test_update_check_reports_repo_three_commits_behind(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    writer = tmp_path / "writer"
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", str(remote), str(writer)], check=True, capture_output=True)
    _git(writer, "config", "user.name", "Test")
    _git(writer, "config", "user.email", "test@example.com")
    (writer / "file.txt").write_text("0\n", encoding="utf-8")
    _git(writer, "add", "file.txt")
    _git(writer, "commit", "-m", "initial")
    _git(writer, "branch", "-M", "main")
    _git(writer, "push", "-u", "origin", "main")
    subprocess.run(
        ["git", "clone", "--branch", "main", str(remote), str(checkout)],
        check=True,
        capture_output=True,
    )
    for number in range(1, 4):
        (writer / "file.txt").write_text(f"{number}\n", encoding="utf-8")
        _git(writer, "commit", "-am", f"change {number}")
    _git(writer, "push")
    profile = {"layers": {"core": {"path": str(checkout), "track": "main"}, "overlay": None}}

    status = update.check_repositories(profile)[0]

    assert status.behind == 3
    assert status.ahead == 0

    update.update_repositories(profile)

    assert (checkout / "file.txt").read_text(encoding="utf-8") == "3\n"


def test_update_checks_out_overlay_agent_kit_pin(tmp_path):
    core_remote = tmp_path / "core-remote.git"
    core_writer = tmp_path / "core-writer"
    core = tmp_path / "core"
    subprocess.run(["git", "init", "--bare", str(core_remote)], check=True, capture_output=True)
    subprocess.run(
        ["git", "clone", str(core_remote), str(core_writer)], check=True, capture_output=True
    )
    _git(core_writer, "config", "user.name", "Test")
    _git(core_writer, "config", "user.email", "test@example.com")
    (core_writer / "version.txt").write_text("v1\n", encoding="utf-8")
    _git(core_writer, "add", "version.txt")
    _git(core_writer, "commit", "-m", "version one")
    _git(core_writer, "tag", "v1.0.0")
    _git(core_writer, "branch", "-M", "main")
    _git(core_writer, "push", "-u", "origin", "main", "--tags")
    (core_writer / "version.txt").write_text("v2\n", encoding="utf-8")
    _git(core_writer, "commit", "-am", "version two")
    _git(core_writer, "push")
    subprocess.run(
        ["git", "clone", "--branch", "main", str(core_remote), str(core)],
        check=True,
        capture_output=True,
    )

    overlay_remote = tmp_path / "overlay-remote.git"
    overlay_writer = tmp_path / "overlay-writer"
    overlay = tmp_path / "overlay"
    subprocess.run(["git", "init", "--bare", str(overlay_remote)], check=True, capture_output=True)
    subprocess.run(
        ["git", "clone", str(overlay_remote), str(overlay_writer)],
        check=True,
        capture_output=True,
    )
    _git(overlay_writer, "config", "user.name", "Test")
    _git(overlay_writer, "config", "user.email", "test@example.com")
    (overlay_writer / "overlay.toml").write_text(
        'name = "example"\ndescription = "test"\nrequires_agent_kit = "v1.0.0"\n',
        encoding="utf-8",
    )
    _git(overlay_writer, "add", "overlay.toml")
    _git(overlay_writer, "commit", "-m", "pin core")
    _git(overlay_writer, "branch", "-M", "main")
    _git(overlay_writer, "push", "-u", "origin", "main")
    subprocess.run(
        ["git", "clone", "--branch", "main", str(overlay_remote), str(overlay)],
        check=True,
        capture_output=True,
    )
    profile = {
        "layers": {
            "core": {"path": str(core), "track": "main"},
            "overlay": {"path": str(overlay), "track": "main"},
        }
    }

    statuses = update.update_repositories(profile)

    head = subprocess.run(
        ["git", "-C", str(core), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tag = subprocess.run(
        ["git", "-C", str(core), "rev-parse", "v1.0.0"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    core_status = next(status for status in statuses if status.repo == "agent-kit")
    assert head == tag
    assert core_status.behind == 0
    assert core_status.ahead == 0


def test_content_check_reports_unknown_and_agent_override_sources(repo_root, tmp_path, monkeypatch):
    monkeypatch.chdir(repo_root)
    profile = load_profile(repo_root / "tests/fixtures/profiles/public-default.json")
    profile["agents"]["scout"] = {"model": "sonnet", "maxTurns": 76, "effort": None}
    profile_without_override = {**profile, "agents": {**profile["agents"]}}
    profile_without_override["agents"].pop("scout")
    home = tmp_path / ".claude"
    install_tree(profile_without_override, home)
    (home / "settings.json").write_text("{}\n", encoding="utf-8")

    drift = {item.path: item.source for item in update.check_content(profile, home)}

    assert "settings.json" not in drift
    assert drift["agents/scout.md"] == "profile.agents override"

    install_tree(profile, home)
    scout = home / "agents/scout.md"
    scout.write_text(f"{scout.read_text(encoding='utf-8')}\nchanged\n", encoding="utf-8")

    drift = {item.path: item.source for item in update.check_content(profile, home)}

    assert drift["agents/scout.md"] == "unknown"
