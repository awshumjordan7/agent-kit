from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

from aisetup.compose import compose_tree
from aisetup.profile import load_profile

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED = Path(__file__).with_name("expected")


def manifest(root: Path) -> str:
    lines = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "MANIFEST.sha256":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(root)}")
    return "\n".join(lines) + "\n"


def compose_fixture(destination: Path) -> None:
    profile = load_profile(REPO_ROOT / "tests/fixtures/profiles/public-default.json")
    compose_tree(profile, destination)


def update_expected() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-kit-golden-") as temporary:
        composed = Path(temporary) / "composed"
        compose_fixture(composed)
        if EXPECTED.exists():
            shutil.rmtree(EXPECTED)
        shutil.copytree(composed, EXPECTED)
    (EXPECTED / "MANIFEST.sha256").write_text(manifest(EXPECTED), encoding="utf-8")
