from __future__ import annotations

import sys

import pytest

from aisetup.manifest import ManifestError, load_module_manifest, validate_dependencies


def write_manifest(path, body):
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")


def test_manifest_rejects_unknown_keys(tmp_path):
    path = tmp_path / "demo/module.toml"
    write_manifest(path, 'name = "demo"\ndescription = "Demo"\ndefault = true\nextra = 1\n')

    with pytest.raises(ManifestError, match="unknown key"):
        load_module_manifest(path)


def test_enabled_module_requires_enabled_dependency(tmp_path):
    first = tmp_path / "first/module.toml"
    second = tmp_path / "second/module.toml"
    write_manifest(
        first, 'name = "first"\ndescription = "First"\ndefault = true\ndepends = ["second"]\n'
    )
    write_manifest(second, 'name = "second"\ndescription = "Second"\ndefault = false\n')
    manifests = {"first": load_module_manifest(first), "second": load_module_manifest(second)}

    with pytest.raises(ManifestError, match="requires enabled module second"):
        validate_dependencies(manifests, {"first": True, "second": False})


def test_manifest_platforms_control_installation(tmp_path, monkeypatch):
    path = tmp_path / "demo/module.toml"
    write_manifest(
        path,
        'name = "demo"\ndescription = "Demo"\ndefault = true\nplatforms = ["darwin"]\n',
    )
    monkeypatch.setattr(sys, "platform", "linux")

    assert not load_module_manifest(path).supports_current_platform
