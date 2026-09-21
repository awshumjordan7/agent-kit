from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "modules/marketing/skills/content-pipeline/scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_path_check_rejects_paths_outside_root(tmp_path):
    checker = _load("check_paths")
    root = tmp_path / "notes"
    root.mkdir()
    inside = root / "source.md"
    inside.write_text("source", encoding="utf-8")

    assert checker.invalid_paths(root, [inside, tmp_path / "outside.md"]) == [
        tmp_path / "outside.md"
    ]


def test_fidelity_check_requires_source_links_and_code():
    checker = _load("check_fidelity")
    source = "See https://example.com/source\n```python\nprint('x')\n```\n"

    assert checker.missing_evidence(source, source) == []
    assert len(checker.missing_evidence(source, "Draft without evidence")) == 2
