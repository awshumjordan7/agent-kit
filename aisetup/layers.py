from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aisetup.manifest import (
    FileCopy,
    LayerManifest,
    ManifestError,
    ModuleManifest,
    OverlayManifest,
    Template,
    load_layer_manifest,
    load_module_manifest,
    load_overlay_manifest,
    validate_dependencies,
)


@dataclass(frozen=True)
class Layer:
    kind: str
    name: str
    root: Path
    settings_fragment: Path | None
    claude_md_fragment: Path | None
    templates: tuple[Template, ...]
    files: tuple[FileCopy, ...]
    module: ModuleManifest | None = None
    overlay: OverlayManifest | None = None


@dataclass(frozen=True)
class ResolvedLayers:
    layers: tuple[Layer, ...]
    layer_manifest: LayerManifest
    module_manifests: dict[str, ModuleManifest]
    skipped_platforms: tuple[str, ...]

    @property
    def requirements(self) -> tuple[str, ...]:
        names: list[str] = []
        for layer in self.layers:
            if layer.module is None:
                continue
            for requirement in layer.module.requires:
                if requirement not in names:
                    names.append(requirement)
        return tuple(names)


def _optional(root: Path, configured: str | None, default: str) -> Path | None:
    relative = configured or default
    path = root / relative
    return path if path.is_file() else None


def resolve_layers(profile: dict[str, Any]) -> ResolvedLayers:
    repo_root = Path(profile["layers"]["core"]["path"])
    if not repo_root.is_absolute():
        repo_root = (Path.cwd() / repo_root).resolve()
    core_root = repo_root / "core"
    layer_manifest = load_layer_manifest(core_root / "layer.toml")
    layers = [
        Layer(
            "core",
            "core",
            core_root,
            _optional(core_root, None, "settings.fragment.json"),
            None,
            layer_manifest.templates,
            (),
        )
    ]

    manifests: dict[str, ModuleManifest] = {}
    for name in layer_manifest.modules:
        path = repo_root / "modules" / name / "module.toml"
        if not path.is_file():
            if profile["modules"].get(name, False):
                raise ManifestError(f"enabled module {name} has no manifest at {path}")
            continue
        manifests[name] = load_module_manifest(path)
    unknown_enabled = sorted(
        name for name, enabled in profile["modules"].items() if enabled and name not in manifests
    )
    if unknown_enabled:
        raise ManifestError(f"enabled module has no manifest: {unknown_enabled[0]}")
    validate_dependencies(manifests, profile["modules"])

    skipped_platforms: list[str] = []
    for name in layer_manifest.modules:
        manifest = manifests.get(name)
        if manifest is None or not profile["modules"].get(name, False):
            continue
        if not manifest.supports_current_platform:
            skipped_platforms.append(name)
            continue
        root = repo_root / "modules" / name
        layers.append(
            Layer(
                "module",
                name,
                root,
                _optional(root, manifest.settings_fragment, "settings.fragment.json"),
                _optional(root, manifest.claude_md_fragment, "CLAUDE.fragment.md"),
                manifest.templates,
                manifest.files,
                module=manifest,
            )
        )

    overlay_config = profile["layers"].get("overlay")
    if overlay_config:
        overlay_root = Path(overlay_config["path"])
        if not overlay_root.is_absolute():
            overlay_root = (Path.cwd() / overlay_root).resolve()
        overlay = load_overlay_manifest(overlay_root / "overlay.toml")
        layers.append(
            Layer(
                "overlay",
                overlay.name,
                overlay_root,
                _optional(overlay_root, overlay.settings_fragment, "settings.fragment.json"),
                _optional(overlay_root, overlay.claude_md_fragment, "CLAUDE.fragment.md"),
                overlay.templates,
                overlay.files,
                overlay=overlay,
            )
        )

    local_root = Path(profile["layers"]["local"])
    if not local_root.is_absolute():
        local_root = (Path.cwd() / local_root).resolve()
    if local_root.is_dir():
        layers.append(
            Layer(
                "local",
                "local",
                local_root,
                _optional(local_root, None, "settings.fragment.json"),
                _optional(local_root, None, "CLAUDE.fragment.md"),
                (),
                (),
            )
        )
    return ResolvedLayers(tuple(layers), layer_manifest, manifests, tuple(skipped_platforms))


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"invalid JSON fragment {path}: {error}") from error
    if not isinstance(data, dict):
        raise ManifestError(f"invalid JSON fragment {path}: expected an object")
    return data


def layer_data(layer: Layer) -> list[dict[str, Any]]:
    data_dir = layer.root / "data"
    if not data_dir.is_dir():
        return []
    return [load_json(path) for path in sorted(data_dir.glob("*.json"))]
