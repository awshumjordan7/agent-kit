from __future__ import annotations

import sys

from aisetup.compose import compose_tree
from aisetup.layers import resolve_layers
from aisetup.manifest import load_module_manifest
from aisetup.profile import load_recommended_profile


def test_terminal_module_is_darwin_only(repo_root, monkeypatch):
    manifest = load_module_manifest(repo_root / "modules/terminal/module.toml")
    monkeypatch.setattr(sys, "platform", "linux")
    assert not manifest.supports_current_platform
    monkeypatch.setattr(sys, "platform", "darwin")
    assert manifest.supports_current_platform


def test_terminal_module_is_reported_when_platform_is_unsupported(repo_root, monkeypatch):
    profile, _ = load_recommended_profile(repo_root)
    profile["modules"]["terminal"] = True
    monkeypatch.setattr(sys, "platform", "linux")

    assert resolve_layers(profile).skipped_platforms == ("terminal",)


def test_terminal_module_installs_ghostty_config_on_macos(repo_root, tmp_path, monkeypatch):
    profile, _ = load_recommended_profile(repo_root)
    profile["modules"]["terminal"] = True
    monkeypatch.setattr(sys, "platform", "darwin")

    compose_tree(profile, tmp_path / ".claude")

    assert (tmp_path / ".config/ghostty/config").is_file()
