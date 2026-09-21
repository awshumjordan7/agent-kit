from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "initial")
    return repo


def _config(repo: Path, **entry_overrides) -> dict:
    entry = {
        "tests": "true <paths>",
        "lint": "",
        "typecheck": "",
        "migrations": "",
        "testPathRules": [],
        "semgrep": False,
        "parity": [],
    }
    entry.update(entry_overrides)
    return {"gate": {str(repo): entry}}


def _gate(
    repo_root: Path,
    repo: Path,
    tmp_path: Path,
    config: dict,
    *arguments: str,
    env: dict[str, str] | None = None,
) -> dict:
    config_path = tmp_path / "forge.config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    completed = subprocess.run(
        [
            "bash",
            str(repo_root / "core/skills/forge/scripts/gate.sh"),
            "--repo",
            str(repo),
            "--run-dir",
            str(run_dir),
            "--label",
            "test",
            *arguments,
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GATE_CONFIG": str(config_path), **(env or {})},
    )
    return json.loads(completed.stdout)


def test_only_tests_reports_other_stages_as_skipped(repo_root, tmp_path):
    repo = _repo(tmp_path)
    test_file = repo / "tests/test_example.py"
    test_file.parent.mkdir()
    test_file.write_text("pass\n", encoding="utf-8")

    result = _gate(
        repo_root,
        repo,
        tmp_path,
        _config(repo),
        "--only",
        "tests",
        "--files",
        "tests/test_example.py",
    )

    assert result["passed"]
    assert result["skipped"] == ["lint", "typecheck", "migrations", "semgrep", "parity"]


def test_env_and_setup_apply_to_test_command(repo_root, tmp_path):
    repo = _repo(tmp_path)
    source = repo / "src/example.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    tests = repo / "tests"
    tests.mkdir()
    config = _config(
        repo,
        tests='test "$GATE_VALUE" = visible && test -f setup.marker',
        env={"GATE_VALUE": "visible"},
        setup="touch setup.marker",
        testPathRules=[{"match": "src/", "tests": "tests"}],
    )

    result = _gate(
        repo_root, repo, tmp_path, config, "--only", "tests", "--files", "src/example.py"
    )

    assert result["passed"]


def test_setup_failure_fails_the_stage(repo_root, tmp_path):
    repo = _repo(tmp_path)
    test_file = repo / "tests/test_example.py"
    test_file.parent.mkdir()
    test_file.write_text("pass\n", encoding="utf-8")
    config = _config(repo, tests="true", setup="false")

    result = _gate(
        repo_root,
        repo,
        tmp_path,
        config,
        "--only",
        "tests",
        "--files",
        "tests/test_example.py",
    )

    assert not result["passed"]
    assert result["failures"][0]["tool"] == "tests"


def test_rule_commands_are_grouped_separately(repo_root, tmp_path):
    repo = _repo(tmp_path)
    for relative in ("src/a.py", "lib/b.py", "tests/a.py", "tests/b.py"):
        path = repo / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")
    config = _config(
        repo,
        testPathRules=[
            {"match": "src/", "tests": "tests/a.py", "command": "true first <paths>"},
            {"match": "lib/", "tests": "tests/b.py", "command": "true second <paths>"},
        ],
    )

    result = _gate(
        repo_root,
        repo,
        tmp_path,
        config,
        "--only",
        "tests",
        "--files",
        "src/a.py",
        "lib/b.py",
    )

    test_commands = [command for command in result["commands"] if command.startswith("true")]
    assert len(test_commands) == 2


def test_create_db_expands_only_for_migrations(repo_root, tmp_path):
    repo = _repo(tmp_path)
    test_file = repo / "tests/test_example.py"
    test_file.parent.mkdir()
    test_file.write_text("pass\n", encoding="utf-8")
    migration = repo / "app/migrations/0002_x.py"
    migration.parent.mkdir(parents=True)
    migration.write_text("pass\n", encoding="utf-8")
    config = _config(repo, tests="true <create-db>")

    without_migration = _gate(
        repo_root,
        repo,
        tmp_path,
        config,
        "--only",
        "tests",
        "--files",
        "tests/test_example.py",
    )
    with_migration = _gate(
        repo_root,
        repo,
        tmp_path,
        config,
        "--only",
        "tests",
        "--files",
        "tests/test_example.py",
        "app/migrations/0002_x.py",
    )

    assert all("--create-db" not in command for command in without_migration["commands"])
    assert any("--create-db" in command for command in with_migration["commands"])


def test_semgrep_blocks_only_error_security_findings_outside_tests(repo_root, tmp_path):
    repo = _repo(tmp_path)
    source = repo / "src/new.py"
    source.parent.mkdir()
    source.write_text("pass\n", encoding="utf-8")
    test_file = repo / "tests/test_new.py"
    test_file.parent.mkdir()
    test_file.write_text("pass\n", encoding="utf-8")
    fake_semgrep = tmp_path / "semgrep"
    fake_semgrep.write_text("#!/bin/sh\nprintf '%s\\n' \"$FAKE_SEMGREP_JSON\"\n", encoding="utf-8")
    fake_semgrep.chmod(fake_semgrep.stat().st_mode | stat.S_IXUSR)
    config = _config(repo, semgrep=True)

    def finding(path: str, severity: str) -> str:
        return json.dumps(
            {
                "results": [
                    {
                        "check_id": "company.security.rule",
                        "path": path,
                        "start": {"line": 1},
                        "extra": {"severity": severity, "lines": "pass"},
                    }
                ]
            }
        )

    blocking = _gate(
        repo_root,
        repo,
        tmp_path,
        config,
        "--only",
        "semgrep",
        "--files",
        "src/new.py",
        env={
            "GATE_SEMGREP_BIN": str(fake_semgrep),
            "FAKE_SEMGREP_JSON": finding("src/new.py", "ERROR"),
        },
    )
    under_tests = _gate(
        repo_root,
        repo,
        tmp_path,
        config,
        "--only",
        "semgrep",
        "--files",
        "tests/test_new.py",
        env={
            "GATE_SEMGREP_BIN": str(fake_semgrep),
            "FAKE_SEMGREP_JSON": finding("tests/test_new.py", "ERROR"),
        },
    )
    warning = _gate(
        repo_root,
        repo,
        tmp_path,
        config,
        "--only",
        "semgrep",
        "--files",
        "src/new.py",
        env={
            "GATE_SEMGREP_BIN": str(fake_semgrep),
            "FAKE_SEMGREP_JSON": finding("src/new.py", "WARNING"),
        },
    )

    assert not blocking["passed"]
    assert under_tests["passed"] and under_tests["warnings"]
    assert warning["passed"] and warning["warnings"]
