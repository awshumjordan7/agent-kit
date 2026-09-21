from __future__ import annotations

import subprocess

from core.hooks import lint_check


def test_lint_check_dispatches_python_to_ruff(tmp_path, monkeypatch):
    path = tmp_path / "example.py"
    path.write_text("print('x')\n", encoding="utf-8")
    monkeypatch.setattr(lint_check.shutil, "which", lambda name: f"/bin/{name}")

    assert lint_check.lint_command(path) == ("ruff", "check", str(path))


def test_lint_check_dispatches_javascript_to_eslint(tmp_path, monkeypatch):
    path = tmp_path / "example.ts"
    path.write_text("export const value = 1;\n", encoding="utf-8")
    monkeypatch.setattr(lint_check, "_project_root", lambda path: None)
    monkeypatch.setattr(lint_check.shutil, "which", lambda name: f"/bin/{name}")

    assert lint_check.lint_command(path) == ("eslint", str(path))


def test_lint_check_is_silent_for_non_code_file(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("notes\n", encoding="utf-8")

    assert lint_check.lint_command(path) is None


def test_lint_check_is_silent_when_linter_times_out(tmp_path, monkeypatch):
    path = tmp_path / "example.py"
    path.write_text("print('x')\n", encoding="utf-8")
    monkeypatch.setattr(lint_check, "lint_command", lambda path: ("ruff", "check", str(path)))

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 10)

    monkeypatch.setattr(lint_check.subprocess, "run", timeout)

    assert lint_check.run({"tool_input": {"file_path": str(path)}}) == ""
