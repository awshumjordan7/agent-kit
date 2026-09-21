from __future__ import annotations

import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "core/scripts"))


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def claude_home(tmp_path: Path) -> Path:
    return tmp_path / ".claude"


@pytest.fixture
def layers_root(tmp_path: Path) -> Path:
    return tmp_path / ".ai-setup"


@pytest.fixture
def fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str, str], Path]:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    monkeypatch.setenv("PATH", f"{binary_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    def create(name: str, body: str = "raise SystemExit(0)\n") -> Path:
        path = binary_dir / name
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    return create
