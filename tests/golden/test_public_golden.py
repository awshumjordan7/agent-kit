from __future__ import annotations

import tempfile
from pathlib import Path

from tests.golden import EXPECTED, _digest, compose_fixture, manifest, source_digests


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


def test_golden_stores_only_rendered_files():
    known = source_digests()
    stored = [p for p in EXPECTED.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256"]
    assert stored, "golden must keep the rendered files"
    assert [p for p in stored if _digest(p) in known] == []
