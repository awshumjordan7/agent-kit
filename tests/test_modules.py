from __future__ import annotations

import json

import pytest

from aisetup.manifest import (
    ManifestError,
    load_layer_manifest,
    load_module_manifest,
    validate_dependencies,
)


def test_every_module_has_valid_manifest_and_plugin(repo_root):
    layer = load_layer_manifest(repo_root / "core/layer.toml")
    manifests = {}
    for name in layer.modules:
        root = repo_root / "modules" / name
        manifests[name] = load_module_manifest(root / "module.toml")
        plugin = json.loads((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        assert plugin["name"] == name
    validate_dependencies(manifests, {name: True for name in manifests})


def test_marketing_requires_firecrawl(repo_root):
    layer = load_layer_manifest(repo_root / "core/layer.toml")
    manifests = {
        name: load_module_manifest(repo_root / "modules" / name / "module.toml")
        for name in layer.modules
    }

    with pytest.raises(ManifestError, match="requires enabled module firecrawl"):
        validate_dependencies(manifests, {"marketing": True, "firecrawl": False})
