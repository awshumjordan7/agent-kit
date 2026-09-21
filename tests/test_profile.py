from __future__ import annotations

import json

import pytest

from aisetup.manifest import load_layer_manifest, load_module_manifest
from aisetup.profile import ProfileError, build_interactive_profile, load_profile, write_profile


def manifests(repo_root):
    layer = load_layer_manifest(repo_root / "core/layer.toml")
    return {
        name: load_module_manifest(repo_root / "modules" / name / "module.toml")
        for name in layer.modules
    }


def test_profile_replay_matches_defaults_selected_interactively(repo_root, tmp_path):
    interactive = build_interactive_profile(repo_root, manifests(repo_root), yes=True)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(interactive), encoding="utf-8")

    replayed = load_profile(path)

    assert replayed == interactive


def test_profile_rejects_unknown_keys(repo_root, tmp_path, monkeypatch):
    monkeypatch.chdir(repo_root)
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps({"schema": 1, "layers": {"core": {"path": "."}}, "mystery": True}),
        encoding="utf-8",
    )

    with pytest.raises(ProfileError, match=r"unknown key profile\.mystery"):
        load_profile(path)


def test_profile_rejects_unknown_forge_stage(repo_root, tmp_path, monkeypatch):
    monkeypatch.chdir(repo_root)
    document = json.loads(
        (repo_root / "tests/fixtures/profiles/public-default.json").read_text(encoding="utf-8")
    )
    document["forge"] = {"stages": {"mystery": True}}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ProfileError, match=r"unknown key profile\.forge\.stages\.mystery"):
        load_profile(path)


def test_profile_rejects_unknown_forge_key(repo_root, tmp_path, monkeypatch):
    monkeypatch.chdir(repo_root)
    document = json.loads(
        (repo_root / "tests/fixtures/profiles/public-default.json").read_text(encoding="utf-8")
    )
    document["forge"] = {"mystery": True}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ProfileError, match=r"unknown key profile\.forge\.mystery"):
        load_profile(path)


def test_secret_question_uses_hidden_input(repo_root):
    context7 = load_module_manifest(repo_root / "modules/context7/module.toml")
    hidden_prompts = []

    profile = build_interactive_profile(
        repo_root,
        {"context7": context7},
        yes=False,
        input_fn=lambda prompt: "",
        secret_input_fn=lambda prompt: hidden_prompts.append(prompt) or "secret-value",
    )

    assert profile["answers"]["context7.api_key"] == "secret-value"
    assert hidden_prompts == [
        "Context7 API key (optional; raises limits) [hidden; confidence: n/a] "
    ]


def test_write_profile_restricts_permissions(repo_root, tmp_path):
    profile = build_interactive_profile(repo_root, manifests(repo_root), yes=True)
    path = tmp_path / "profile.json"

    write_profile(path, profile)

    assert path.stat().st_mode & 0o777 == 0o600


def test_relative_local_layer_resolves_from_profile_directory(repo_root, tmp_path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    path = profiles / "profile.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "layers": {
                    "core": {"path": str(repo_root), "track": "main"},
                    "local": "../local-layer",
                },
            }
        ),
        encoding="utf-8",
    )

    profile = load_profile(path)

    assert profile["layers"]["local"] == str(tmp_path / "local-layer")
