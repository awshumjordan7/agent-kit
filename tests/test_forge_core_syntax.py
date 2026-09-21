from __future__ import annotations

import shutil
import subprocess

import pytest


def test_forge_core_has_valid_javascript_syntax(repo_root):
    if not shutil.which("node"):
        pytest.skip("node is not installed")

    result = subprocess.run(
        ["node", "--check", str(repo_root / "core/skills/forge/references/forge-core.js")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
