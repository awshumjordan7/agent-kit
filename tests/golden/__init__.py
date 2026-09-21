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
        digest = _digest(path)
        lines.append(f"{digest}  {path.relative_to(root)}")
    return "\n".join(lines) + "\n"


def compose_fixture(destination: Path) -> None:
    profile = load_profile(REPO_ROOT / "tests/fixtures/profiles/public-default.json")
    compose_tree(profile, destination)


SOURCE_ROOTS = (REPO_ROOT / "core", REPO_ROOT / "modules")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digests() -> set[str]:
    return {
        _digest(path)
        for root in SOURCE_ROOTS
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


# A composed file whose bytes match a file under core/ or modules/ was copied verbatim;
# the manifest hash is enough for it. Anything else was merged or rendered and is stored
# so a diff shows the effect.
def rendered_files(root: Path) -> list[Path]:
    known = source_digests()
    return [
        path for path in sorted(root.rglob("*")) if path.is_file() and _digest(path) not in known
    ]


def update_expected() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-kit-golden-") as temporary:
        composed = Path(temporary) / "composed"
        compose_fixture(composed)
        manifest_text = manifest(composed)
        if EXPECTED.exists():
            shutil.rmtree(EXPECTED)
        for path in rendered_files(composed):
            destination = EXPECTED / path.relative_to(composed)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    (EXPECTED / "MANIFEST.sha256").write_text(manifest_text, encoding="utf-8")
