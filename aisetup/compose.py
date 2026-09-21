from __future__ import annotations

import json
import os
import shutil
import tempfile
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


DEFAULT_DIRECTORIES = ("hooks", "agents", "skills", "references", "scripts")
COMPILED_SUFFIXES = {".pyc", ".pyo", ".pyd"}
COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.pyd")


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


def install_tree(profile: dict[str, Any], home: Path) -> ComposeResult:
    home = home.expanduser().resolve()
    home.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{home.name}.install-", dir=home.parent))
    staging = work / home.name
    auxiliary = work / "auxiliary"
    backup: Path | None = None
    try:
        result = compose_tree(profile, staging, auxiliary_root=auxiliary)
        if home.exists():
            backup = _backup_path(home)
            os.replace(home, backup)
        try:
            os.replace(staging, home)
        except OSError:
            if backup is not None and not home.exists():
                os.replace(backup, home)
            raise
        _install_auxiliary(auxiliary, home.parent)
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
