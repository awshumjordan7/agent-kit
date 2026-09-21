from __future__ import annotations

import tempfile
from pathlib import Path

from tests.golden import EXPECTED, compose_fixture, manifest


def test_public_golden(monkeypatch, repo_root):
    monkeypatch.chdir(repo_root)
    with tempfile.TemporaryDirectory(prefix="agent-kit-golden-test-") as temporary:
        actual = Path(temporary) / "actual"
        compose_fixture(actual)

        assert manifest(actual) == (EXPECTED / "MANIFEST.sha256").read_text(encoding="utf-8")
        for path in (item for item in EXPECTED.rglob("*") if item.is_file()):
            if path.name == "MANIFEST.sha256":
                continue
            relative = path.relative_to(EXPECTED)
            assert (actual / relative).read_bytes() == path.read_bytes()
