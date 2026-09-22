from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from aisetup.layers import Layer, ResolvedLayers, layer_data, load_json, resolve_layers
from aisetup.manifest import ManifestError
from aisetup.merge import deep_merge
from aisetup.profile import load_recommended_profile, profile_render_context
from aisetup.render import RenderError, render_agent_frontmatter, render_text


class ComposeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ComposeResult:
    files: tuple[str, ...]
    settings: dict[str, Any]
    backup: Path | None = None


@dataclass(frozen=True)
class InstallationPaths:
    preserved: tuple[Path, ...]
    retired: tuple[Path, ...]
    retired_modified: tuple[Path, ...]


DEFAULT_DIRECTORIES = ("hooks", "agents", "skills", "references", "scripts")
COMPILED_SUFFIXES = {".pyc", ".pyo", ".pyd"}
COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.pyd")
MANAGED_PATHS_VERSION = 1
MANAGED_PATHS_FILENAME = "managed-paths.json"


def _is_compiled_artifact(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix in COMPILED_SUFFIXES


def _copy_layer_files(layer: Layer, destination: Path, auxiliary_root: Path) -> None:
    for directory in DEFAULT_DIRECTORIES:
        source = layer.root / directory
        if source.is_dir():
            shutil.copytree(
                source,
                destination / directory,
                dirs_exist_ok=True,
                ignore=COPY_IGNORE,
            )
    for copy in layer.files:
        source = layer.root / copy.src
        if _is_compiled_artifact(source):
            continue
        target = Path(copy.dest)
        if target.is_absolute():
            default_home = Path.home() / ".claude"
            try:
                relative = target.relative_to(default_home)
            except ValueError:
                try:
                    target = auxiliary_root / target.relative_to(Path.home())
                except ValueError as error:
                    raise ComposeError(
                        f"external destination is outside the user home: {target}"
                    ) from error
            else:
                target = destination / relative
        else:
            target = destination / target
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True, ignore=COPY_IGNORE)
        else:
            shutil.copy2(source, target)
    codex = layer.root / "codex"
    if codex.is_dir():
        shutil.copytree(codex, auxiliary_root / ".codex", dirs_exist_ok=True, ignore=COPY_IGNORE)


def _render_claude_md(layers: ResolvedLayers) -> str:
    core = layers.layers[0]
    try:
        text = (core.root / "CLAUDE.md").read_text(encoding="utf-8").rstrip() + "\n"
    except (OSError, UnicodeError) as error:
        raise ComposeError(f"cannot read core CLAUDE.md: {error}") from error
    for layer in layers.layers[1:]:
        if layer.claude_md_fragment is None:
            continue
        fragment = layer.claude_md_fragment.read_text(encoding="utf-8").strip()
        heading = {
            "module": f"## Module: {layer.name}",
            "overlay": f"## Overlay: {layer.name}",
            "local": "## Local",
        }[layer.kind]
        text += f"\n{heading}\n\n{fragment}\n"
    return text


def _render_settings(layers: ResolvedLayers) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    for layer in layers.layers:
        if layer.settings_fragment is not None:
            settings = deep_merge(settings, load_json(layer.settings_fragment))
    return settings


def _render_agents(destination: Path, profile: dict[str, Any]) -> None:
    agents_dir = destination / "agents"
    if not agents_dir.is_dir():
        return
    for path in sorted(agents_dir.glob("*.md")):
        settings = profile["agents"].get(path.stem, {})
        try:
            rendered = render_agent_frontmatter(path.read_text(encoding="utf-8"), settings)
            path.write_text(rendered, encoding="utf-8")
        except (OSError, UnicodeError, RenderError) as error:
            raise ComposeError(f"cannot render agent {path}: {error}") from error


def _render_templates(
    destination: Path,
    layers: ResolvedLayers,
    context: dict[str, Any],
) -> None:
    for layer in layers.layers:
        for template in layer.templates:
            source = layer.root / template.src
            target = Path(template.dest)
            if target.is_absolute():
                default_home = Path.home() / ".claude"
                try:
                    target = destination / target.relative_to(default_home)
                except ValueError as error:
                    raise ComposeError(
                        f"template destination is outside Claude home: {target}"
                    ) from error
            else:
                target = destination / target
            try:
                rendered = render_text(source.read_text(encoding="utf-8"), context, source=source)
            except (OSError, UnicodeError, RenderError) as error:
                raise ComposeError(str(error)) from error
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8")


def compose_tree(
    profile: dict[str, Any], destination: Path, *, auxiliary_root: Path | None = None
) -> ComposeResult:
    if destination.exists():
        if any(destination.iterdir()):
            raise ComposeError(f"compose destination is not empty: {destination}")
    else:
        destination.mkdir(parents=True)
    try:
        layers = resolve_layers(profile)
        auxiliary_root = auxiliary_root or destination.parent
        for layer in layers.layers:
            _copy_layer_files(layer, destination, auxiliary_root)

        settings = _render_settings(layers)
        (destination / "settings.json").write_text(
            json.dumps(settings, indent=2) + "\n",
            encoding="utf-8",
        )
        (destination / "CLAUDE.md").write_text(_render_claude_md(layers), encoding="utf-8")

        repo_root = Path(profile["layers"]["core"]["path"])
        if not repo_root.is_absolute():
            repo_root = (Path.cwd() / repo_root).resolve()
        default_profile, _ = load_recommended_profile(repo_root)
        fragments = [fragment for layer in layers.layers for fragment in layer_data(layer)]
        context = profile_render_context(default_profile, fragments, profile)
        _render_templates(destination, layers, context)
        _render_agents(destination, profile)
    except (ManifestError, OSError, UnicodeError) as error:
        raise ComposeError(str(error)) from error

    files = tuple(
        str(path.relative_to(destination))
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    )
    return ComposeResult(files, settings)


def _backup_path(home: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = home.with_name(f"{home.name}.backup.{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = home.with_name(f"{home.name}.backup.{timestamp}.{counter}")
        counter += 1
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_managed_paths(layers_root: Path) -> dict[str, str]:
    path = layers_root.expanduser() / MANAGED_PATHS_FILENAME
    if not path.is_file():
        return {}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ComposeError(f"cannot read managed path record {path}: {error}") from error
    if not isinstance(record, dict):
        raise ComposeError(f"invalid managed path record: {path}")
    paths = record.get("paths")
    if record.get("version") != MANAGED_PATHS_VERSION or not isinstance(paths, dict):
        raise ComposeError(f"unsupported managed path record: {path}")
    if not all(
        isinstance(relative, str) and isinstance(digest, str) for relative, digest in paths.items()
    ):
        raise ComposeError(f"invalid managed path record: {path}")
    return paths


def _write_managed_paths(layers_root: Path, staged: Path, files: Iterable[str]) -> None:
    layers_root = layers_root.expanduser()
    layers_root.mkdir(parents=True, exist_ok=True)
    path = layers_root / MANAGED_PATHS_FILENAME
    temporary = path.with_suffix(".tmp")
    record = {
        "version": MANAGED_PATHS_VERSION,
        "paths": {relative: _sha256(staged / relative) for relative in sorted(files)},
    }
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def installation_paths(home: Path, staged: Path, layers_root: Path) -> InstallationPaths:
    home = home.expanduser()
    if not home.is_dir():
        return InstallationPaths((), (), ())

    previous = _load_managed_paths(layers_root)
    preserved: list[Path] = []
    retired: list[Path] = []
    retired_modified: list[Path] = []

    def contains_managed_path(relative: Path) -> bool:
        prefix = relative.as_posix().rstrip("/") + "/"
        return any(path.startswith(prefix) for path in previous)

    def collect(source: Path) -> None:
        for entry in sorted(source.iterdir()):
            relative = entry.relative_to(home)
            target = staged / relative
            if not target.exists() and not target.is_symlink():
                recorded_digest = previous.get(relative.as_posix())
                if entry.is_dir() and not entry.is_symlink() and contains_managed_path(relative):
                    collect(entry)
                elif recorded_digest is None:
                    preserved.append(relative)
                elif (
                    not entry.is_symlink() and entry.is_file() and _sha256(entry) == recorded_digest
                ):
                    retired.append(relative)
                else:
                    preserved.append(relative)
                    retired_modified.append(relative)
            elif entry.is_dir() and target.is_dir():
                collect(entry)

    collect(home)
    return InstallationPaths(tuple(preserved), tuple(retired), tuple(retired_modified))


def _restore_unmanaged(backup: Path, home: Path, preserved: Iterable[Path]) -> None:
    def merge_dir(source: Path, target: Path) -> None:
        if target.exists() and not target.is_dir():
            return
        target.mkdir(parents=True, exist_ok=True)
        for entry in sorted(source.iterdir()):
            dst = target / entry.name
            if entry.is_dir() and not entry.is_symlink():
                merge_dir(entry, dst)
            elif not (dst.exists() or dst.is_symlink()):
                shutil.copy2(entry, dst, follow_symlinks=False)

    for relative in preserved:
        source = backup / relative
        target = home / relative
        if source.is_dir() and not source.is_symlink():
            merge_dir(source, target)
        elif not (target.exists() or target.is_symlink()):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)


def install_tree(profile: dict[str, Any], home: Path, layers_root: Path) -> ComposeResult:
    home = home.expanduser().resolve()
    home.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{home.name}.install-", dir=home.parent))
    staging = work / home.name
    auxiliary = work / "auxiliary"
    backup: Path | None = None
    try:
        result = compose_tree(profile, staging, auxiliary_root=auxiliary)
        paths = installation_paths(home, staging, layers_root)
        if home.exists():
            backup = _backup_path(home)
            os.replace(home, backup)
        try:
            os.replace(staging, home)
        except OSError:
            if backup is not None and not home.exists():
                os.replace(backup, home)
            raise
        if backup is not None:
            _restore_unmanaged(backup, home, paths.preserved)
            sys.stdout.write(f"preserved {len(paths.preserved)} unmanaged path(s) from {backup}\n")
            for relative in paths.retired_modified:
                sys.stdout.write(f"retired but locally modified: {relative}\n")
        _install_auxiliary(auxiliary, home.parent)
        _write_managed_paths(layers_root, home, result.files)
        return ComposeResult(result.files, result.settings, backup)
    finally:
        if work.exists():
            shutil.rmtree(work)


def _install_auxiliary(source_root: Path, user_home: Path) -> None:
    if not source_root.is_dir():
        return
    for source in sorted(source_root.rglob("*")):
        if not source.is_file():
            continue
        target = user_home / source.relative_to(source_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            backup = target.with_name(
                f"{target.name}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            shutil.copy2(target, backup)
        shutil.copy2(source, target)
