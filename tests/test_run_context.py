from __future__ import annotations

import json
import subprocess


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_context_returns_only_post_baseline_files_and_reuses_gate_diff(repo_root, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "tracked.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "tracked.py")
    _git(repo, "commit", "-m", "initial")
    (repo / "preexisting.py").write_text("old = True\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    script = repo_root / "core/skills/forge/scripts/run_context.py"
    subprocess.run(
        ["python3", str(script), "baseline", "--run-dir", str(run_dir), "--repo", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "new.py").write_text("new = True\n", encoding="utf-8")
    (run_dir / "gate-review.diff").write_text("expected gate diff\n", encoding="utf-8")
    plan = tmp_path / "plan.md"
    plan.write_text("## Summary\nExample\n", encoding="utf-8")

    completed = subprocess.run(
        [
            "python3",
            str(script),
            "context",
            "--run-dir",
            str(run_dir),
            "--repo",
            str(repo),
            "--plan-file",
            str(plan),
            "--label",
            "review",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["files"] == ["new.py"]
    assert result["preexisting"] == ["preexisting.py"]
    assert result["diff"] == "expected gate diff\n"


def test_context_all_dirty_includes_files_present_at_baseline(repo_root, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "tracked.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "tracked.py")
    _git(repo, "commit", "-m", "initial")
    (repo / "preexisting.py").write_text("old = True\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    script = repo_root / "core/skills/forge/scripts/run_context.py"
    subprocess.run(
        ["python3", str(script), "baseline", "--run-dir", str(run_dir), "--repo", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    plan = tmp_path / "plan.md"
    plan.write_text("## Summary\nExample\n", encoding="utf-8")

    completed = subprocess.run(
        [
            "python3",
            str(script),
            "context",
            "--run-dir",
            str(run_dir),
            "--repo",
            str(repo),
            "--plan-file",
            str(plan),
            "--label",
            "review",
            "--all-dirty",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["files"] == ["preexisting.py"]
    assert result["preexisting"] == []
    assert "preexisting.py" in result["diff"]


def test_read_plan_returns_exact_text(repo_root, tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\nExact text\n", encoding="utf-8")

    completed = subprocess.run(
        [
            "python3",
            str(repo_root / "core/skills/forge/scripts/run_context.py"),
            "read-plan",
            "--plan-file",
            str(plan),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {"planText": "# Plan\nExact text\n"}
