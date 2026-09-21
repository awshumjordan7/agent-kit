from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aisetup.compose import compose_tree
from aisetup.manifest import load_overlay_manifest


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepoStatus:
    repo: str
    path: Path
    behind: int
    ahead: int
    command: str

    def as_json(self) -> str:
        return json.dumps(
            {
                "repo": self.repo,
                "behind": self.behind,
                "ahead": self.ahead,
                "command": self.command,
            },
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class ContentDrift:
    path: str
    source: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_content(profile: dict[str, Any], home: Path) -> list[ContentDrift]:
    with tempfile.TemporaryDirectory(prefix="agent-kit-check-") as temporary:
        composed = Path(temporary) / "claude"
        result = compose_tree(profile, composed)
        drifts: list[ContentDrift] = []
        agent_overrides = profile.get("agents", {})
        for relative in result.files:
            expected = composed / relative
            installed = home / relative
            if installed.is_file() and _sha256(installed) == _sha256(expected):
                continue
            agent_name = Path(relative).stem if relative.startswith("agents/") else ""
            source = (
                "profile.agents override"
                if agent_name and agent_name in agent_overrides
                else "unknown"
            )
            drifts.append(ContentDrift(relative, source))
        return drifts


def _git(path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(path), *args],
            check=check,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        raise UpdateError(f"git failed for {path}: {error}") from error


def _counts(path: Path, upstream: str) -> tuple[int, int]:
    result = _git(path, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
    ahead, behind = (int(value) for value in result.stdout.split())
    return behind, ahead


def _layer_repositories(profile: dict[str, Any]) -> list[tuple[str, Path, str]]:
    layers = profile["layers"]
    repositories: list[tuple[str, Path, str]] = []
    core = layers["core"]
    repositories.append(("agent-kit", Path(core["path"]), core.get("track", "main")))
    overlay = layers.get("overlay")
    if overlay:
        repositories.append(("overlay", Path(overlay["path"]), overlay.get("track", "main")))
    return repositories


def _pinned_core_tag(profile: dict[str, Any]) -> str | None:
    overlay = profile["layers"].get("overlay")
    if not overlay:
        return None
    manifest = load_overlay_manifest(Path(overlay["path"]) / "overlay.toml")
    return manifest.requires_agent_kit


def check_repositories(profile: dict[str, Any]) -> list[RepoStatus]:
    statuses: list[RepoStatus] = []
    pinned_core_tag = _pinned_core_tag(profile)
    for name, path, track in _layer_repositories(profile):
        _git(path, "fetch")
        upstream = pinned_core_tag if name == "agent-kit" and pinned_core_tag else f"origin/{track}"
        behind, ahead = _counts(path, upstream)
        command = (
            f"git -C {path} checkout {upstream}"
            if name == "agent-kit" and pinned_core_tag
            else f"git -C {path} merge --ff-only {upstream}"
        )
        statuses.append(RepoStatus(name, path, behind, ahead, command))
    return statuses


def update_repositories(profile: dict[str, Any]) -> list[RepoStatus]:
    statuses = check_repositories(profile)
    overlay = profile["layers"].get("overlay")
    overlay_status = next((status for status in statuses if status.repo == "overlay"), None)
    if overlay_status and overlay_status.behind:
        track = overlay.get("track", "main")
        _git(overlay_status.path, "merge", "--ff-only", f"origin/{track}")

    pinned_core_tag = _pinned_core_tag(profile)

    for status in statuses:
        if status.repo == "overlay":
            continue
        if status.repo == "agent-kit" and pinned_core_tag:
            _git(status.path, "checkout", pinned_core_tag)
        elif status.behind:
            track = profile["layers"]["core"].get("track", "main")
            _git(status.path, "merge", "--ff-only", f"origin/{track}")
    return check_repositories(profile)


def commit_subjects(profile: dict[str, Any]) -> list[tuple[str, str]]:
    subjects: list[tuple[str, str]] = []
    for name, path, _track in _layer_repositories(profile):
        layer_name = "core" if name == "agent-kit" else "overlay"
        previous = profile["layers"][layer_name].get("commit", "")
        if not previous:
            continue
        result = _git(path, "log", "--format=%s", f"{previous}..HEAD")
        subjects.extend((name, subject) for subject in result.stdout.splitlines() if subject)
    return subjects


def update_profile_commits(profile: dict[str, Any]) -> None:
    for name, path, _track in _layer_repositories(profile):
        layer_name = "core" if name == "agent-kit" else "overlay"
        profile["layers"][layer_name]["commit"] = _git(path, "rev-parse", "HEAD").stdout.strip()
