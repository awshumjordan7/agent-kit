from __future__ import annotations

import runpy
import sys

import pytest


def test_python_floor_exits_before_loading_package(repo_root, monkeypatch, capsys):
    monkeypatch.setattr(sys, "version_info", (3, 10, 9))
    sys.modules.pop("aisetup.cli", None)

    with pytest.raises(SystemExit) as raised:
        runpy.run_path(repo_root / "install.py", run_name="__main__")

    assert raised.value.code == 3
    assert "Python 3.11" in capsys.readouterr().err
    assert "aisetup.cli" not in sys.modules
