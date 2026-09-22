from __future__ import annotations

import json
import subprocess


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _run_context(script, run_dir, repo, plan, *extra):
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
            *extra,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _repo_with_baseline(repo_root, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "tracked.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "tracked.py")
    _git(repo, "commit", "-m", "initial")
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
    return repo, run_dir, script, plan


def test_context_writes_review_diff_and_reports_validity(repo_root, tmp_path):
    repo, run_dir, script, plan = _repo_with_baseline(repo_root, tmp_path)
    (repo / "new.py").write_text("new = True\n", encoding="utf-8")

    result = _run_context(script, run_dir, repo, plan)

    diff_path = run_dir / "review-review.diff"
    assert diff_path.read_text(encoding="utf-8").startswith("diff --git")
    assert result["diffPath"] == str(diff_path)
    assert result["diffBytes"] == diff_path.stat().st_size
    assert result["diffLines"] > 0
    assert result["diffValid"] is True
    assert "diff" not in result

    (run_dir / "gate-review.diff").write_text("corrupt\n", encoding="utf-8")
    assert _run_context(script, run_dir, repo, plan)["diffValid"] is False

    (run_dir / "gate-review.diff").write_text("", encoding="utf-8")
    empty = _run_context(script, run_dir, repo, plan)
    assert empty["diffBytes"] == 0
    assert empty["diffLines"] == 0
    assert empty["diffValid"] is False


def test_context_base_includes_committed_files(repo_root, tmp_path):
    repo, run_dir, script, plan = _repo_with_baseline(repo_root, tmp_path)
    _git(repo, "checkout", "-b", "feature")
    (repo / "tracked.py").write_text("value = 2\n", encoding="utf-8")
    _git(repo, "add", "tracked.py")
    _git(repo, "commit", "-m", "feature change")
    subprocess.run(
        ["python3", str(script), "baseline", "--run-dir", str(run_dir), "--repo", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )

    result = _run_context(script, run_dir, repo, plan, "--base", "main")

    assert result["files"] == ["tracked.py"]
    assert (run_dir / "review-review.diff").read_text(encoding="utf-8").startswith("diff --git")
