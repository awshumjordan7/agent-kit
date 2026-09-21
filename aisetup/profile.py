from __future__ import annotations

import getpass
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from aisetup.manifest import ModuleManifest
from aisetup.merge import deep_merge


class ProfileError(ValueError):
    pass


TOP_LEVEL_KEYS = {
    "schema",
    "installed_at",
    "layers",
    "modules",
    "answers",
    "agents",
    "forge",
    "ship_pr",
    "doctor",
    "auto_update",
}
LAYER_KEYS = {"path", "commit", "track"}
AGENT_KEYS = {"model", "maxTurns", "effort"}
FORGE_KEYS = {"roles", "stages", "gate", "workspace", "codex"}
ROLE_KEYS = {"provider", "model", "effort"}
STAGE_KEYS = {"sandbox", "ff_review", "qa_login"}
DOCTOR_KEYS = {"repo_roots", "codex", "known_repos", "metrics"}
CODEX_DOCTOR_KEYS = {"agents_md", "exclude_sections", "exclude_bullets"}
METRICS_KEYS = {"since", "until", "timezone", "transcripts"}
CODEX_ROLE_DEFAULTS = {
    "impl": {"provider": "codex", "model": "gpt-5.6-sol", "effort": "high"},
    "quick-impl": {"provider": "codex", "model": "gpt-5.6-luna", "effort": "high"},
    "review": {"provider": "codex", "model": "gpt-5.6-sol", "effort": "high"},
    "plan-review": {"provider": "codex", "model": "gpt-5.6-sol", "effort": "high"},
}


def _unknown(data: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(data.keys() - allowed)
    if unknown:
        raise ProfileError(f"unknown key {context}.{unknown[0]}")


def _table(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileError(f"{context} must be an object")
    return value


def validate_profile(profile: dict[str, Any]) -> None:
    _unknown(profile, TOP_LEVEL_KEYS, "profile")
    if profile.get("schema") != 1:
        raise ProfileError("profile.schema must be 1")

    layers = _table(profile.get("layers"), "profile.layers")
    _unknown(layers, {"core", "overlay", "local"}, "profile.layers")
    core = _table(layers.get("core"), "profile.layers.core")
    _unknown(core, LAYER_KEYS, "profile.layers.core")
    if not isinstance(core.get("path"), str):
        raise ProfileError("profile.layers.core.path must be a string")
    if any(key in core and not isinstance(core[key], str) for key in ("commit", "track")):
        raise ProfileError("profile.layers.core commit and track must be strings")
    overlay = layers.get("overlay")
    if overlay is not None:
        overlay = _table(overlay, "profile.layers.overlay")
        _unknown(overlay, LAYER_KEYS, "profile.layers.overlay")
        if not isinstance(overlay.get("path"), str):
            raise ProfileError("profile.layers.overlay.path must be a string")
        if any(key in overlay and not isinstance(overlay[key], str) for key in ("commit", "track")):
            raise ProfileError("profile.layers.overlay commit and track must be strings")
    if not isinstance(layers.get("local"), str):
        raise ProfileError("profile.layers.local must be a string")

    modules = _table(profile.get("modules"), "profile.modules")
    if not all(
        isinstance(name, str) and isinstance(enabled, bool) for name, enabled in modules.items()
    ):
        raise ProfileError("profile.modules values must be booleans")
    answers = _table(profile.get("answers"), "profile.answers")
    if not all(
        isinstance(key, str) and isinstance(value, (str, bool, int))
        for key, value in answers.items()
    ):
        raise ProfileError("profile.answers contains an invalid value")

    agents = _table(profile.get("agents"), "profile.agents")
    for name, value in agents.items():
        agent = _table(value, f"profile.agents.{name}")
        _unknown(agent, AGENT_KEYS, f"profile.agents.{name}")
        if not isinstance(agent.get("model"), str):
            raise ProfileError(f"profile.agents.{name}.model must be a string")
        if (
            "maxTurns" in agent
            and agent["maxTurns"] is not None
            and not isinstance(agent["maxTurns"], int)
        ):
            raise ProfileError(f"profile.agents.{name}.maxTurns must be an integer or null")
        if (
            "effort" in agent
            and agent["effort"] is not None
            and not isinstance(agent["effort"], str)
        ):
            raise ProfileError(f"profile.agents.{name}.effort must be a string or null")

    forge = _table(profile.get("forge"), "profile.forge")
    _unknown(forge, FORGE_KEYS, "profile.forge")
    roles = _table(forge.get("roles"), "profile.forge.roles")
    for name, value in roles.items():
        role = _table(value, f"profile.forge.roles.{name}")
        _unknown(role, ROLE_KEYS, f"profile.forge.roles.{name}")
        if not all(isinstance(role.get(key), str) for key in ROLE_KEYS):
            raise ProfileError(f"profile.forge.roles.{name} fields must be strings")
        if role["provider"] not in {"claude", "codex"}:
            raise ProfileError(f"profile.forge.roles.{name}.provider must be claude or codex")
    stages = _table(forge.get("stages"), "profile.forge.stages")
    _unknown(stages, STAGE_KEYS, "profile.forge.stages")
    if not all(isinstance(key, str) and isinstance(value, bool) for key, value in stages.items()):
        raise ProfileError("profile.forge.stages values must be booleans")
    _table(forge.get("gate"), "profile.forge.gate")

    ship_pr = _table(profile.get("ship_pr"), "profile.ship_pr")
    _unknown(ship_pr, {"base_branches"}, "profile.ship_pr")
    base_branches = _table(ship_pr.get("base_branches"), "profile.ship_pr.base_branches")
    for name, value in base_branches.items():
        entry = _table(value, f"profile.ship_pr.base_branches.{name}")
        _unknown(entry, {"branch"}, f"profile.ship_pr.base_branches.{name}")
        if not isinstance(entry.get("branch"), str):
            raise ProfileError(f"profile.ship_pr.base_branches.{name}.branch must be a string")

    doctor = _table(profile.get("doctor"), "profile.doctor")
    _unknown(doctor, DOCTOR_KEYS, "profile.doctor")
    if not isinstance(doctor.get("repo_roots"), list) or not all(
        isinstance(item, str) for item in doctor["repo_roots"]
    ):
        raise ProfileError("profile.doctor.repo_roots must be an array of strings")
    doctor_codex = _table(doctor.get("codex"), "profile.doctor.codex")
    _unknown(doctor_codex, CODEX_DOCTOR_KEYS, "profile.doctor.codex")
    if not isinstance(doctor_codex.get("agents_md"), str):
        raise ProfileError("profile.doctor.codex.agents_md must be a string")
    for key in ("exclude_sections", "exclude_bullets"):
        if not isinstance(doctor_codex.get(key), list) or not all(
            isinstance(item, str) for item in doctor_codex[key]
        ):
            raise ProfileError(f"profile.doctor.codex.{key} must be an array of strings")
    known_repos = doctor.get("known_repos", [])
    if not isinstance(known_repos, list) or not all(isinstance(item, str) for item in known_repos):
        raise ProfileError("profile.doctor.known_repos must be an array of strings")
    metrics = _table(doctor.get("metrics", {}), "profile.doctor.metrics")
    _unknown(metrics, METRICS_KEYS, "profile.doctor.metrics")
    if not all(value is None or isinstance(value, str) for value in metrics.values()):
        raise ProfileError("profile.doctor.metrics values must be strings or null")
    if not isinstance(profile.get("auto_update"), bool):
        raise ProfileError("profile.auto_update must be a boolean")
    if "installed_at" in profile and not isinstance(profile["installed_at"], str):
        raise ProfileError("profile.installed_at must be a string")


def _expand_profile_paths(profile: dict[str, Any]) -> None:
    layers = profile["layers"]
    layers["core"]["path"] = str(Path(layers["core"]["path"]).expanduser())
    if layers["overlay"] is not None:
        layers["overlay"]["path"] = str(Path(layers["overlay"]["path"]).expanduser())
    layers["local"] = str(Path(layers["local"]).expanduser())
    doctor = profile["doctor"]
    doctor["repo_roots"] = [str(Path(path).expanduser()) for path in doctor["repo_roots"]]
    doctor["codex"]["agents_md"] = str(Path(doctor["codex"]["agents_md"]).expanduser())


def _data_fragments(root: Path) -> list[dict[str, Any]]:
    data_dir = root / "data"
    if not data_dir.is_dir():
        return []
    fragments: list[dict[str, Any]] = []
    for path in sorted(data_dir.glob("*.json")):
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ProfileError(f"invalid profile data {path}: {error}") from error
        if not isinstance(fragment, dict):
            raise ProfileError(f"invalid profile data {path}: expected an object")
        fragments.append(fragment)
    return fragments


def _apply_layer_data(
    defaults: dict[str, Any], supplied: dict[str, Any], repo_root: Path
) -> dict[str, Any]:
    effective = deepcopy(defaults)
    modules = deep_merge(defaults.get("modules", {}), supplied.get("modules", {}))
    for name, enabled in modules.items():
        if enabled:
            for fragment in _data_fragments(repo_root / "modules" / name):
                effective = deep_merge(effective, fragment)

    layers = deep_merge(defaults.get("layers", {}), supplied.get("layers", {}))
    overlay = layers.get("overlay")
    if isinstance(overlay, dict) and isinstance(overlay.get("path"), str):
        for fragment in _data_fragments(Path(overlay["path"]).expanduser()):
            effective = deep_merge(effective, fragment)
    local = layers.get("local")
    if isinstance(local, str):
        for fragment in _data_fragments(Path(local).expanduser()):
            effective = deep_merge(effective, fragment)
    return effective


def load_profile(path: Path) -> dict[str, Any]:
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProfileError(f"invalid profile {path}: {error}") from error
    if not isinstance(profile, dict):
        raise ProfileError(f"invalid profile {path}: expected an object")
    layers = profile.get("layers")
    if isinstance(layers, dict) and isinstance(layers.get("local"), str):
        local = Path(layers["local"]).expanduser()
        if not local.is_absolute():
            layers["local"] = str((path.parent / local).resolve())
    core_path = profile.get("layers", {}).get("core", {}).get("path", ".")
    if not isinstance(core_path, str):
        raise ProfileError("profile.layers.core.path must be a string")
    repo_root = Path(core_path).expanduser()
    if not repo_root.is_absolute():
        repo_root = (Path.cwd() / repo_root).resolve()
    defaults, _ = load_recommended_profile(repo_root)
    supplied_roles = profile.get("forge", {}).get("roles")
    defaults = _apply_layer_data(defaults, profile, repo_root)
    profile = deep_merge(defaults, profile)
    if profile["modules"].get("codex", False) and supplied_roles is None:
        profile["forge"]["roles"] = deep_merge(profile["forge"]["roles"], CODEX_ROLE_DEFAULTS)
    validate_profile(profile)
    _expand_profile_paths(profile)
    return profile


def load_recommended_profile(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = repo_root / "core/profile.default.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProfileError(f"invalid recommended profile {path}: {error}") from error
    if not isinstance(document, dict) or not isinstance(document.get("profile"), dict):
        raise ProfileError(f"invalid recommended profile {path}")
    profile = deepcopy(document["profile"])
    profile["layers"]["core"]["path"] = str(repo_root)
    validate_profile(profile)
    _expand_profile_paths(profile)
    return profile, document.get("recommendations", {})


def _parse_answer(raw: str, default: str | bool | int, answer_type: str) -> str | bool | int:
    if not raw:
        return default
    if answer_type == "bool":
        lowered = raw.lower()
        if lowered in {"y", "yes", "true", "1"}:
            return True
        if lowered in {"n", "no", "false", "0"}:
            return False
        raise ProfileError(f"invalid boolean answer: {raw}")
    if answer_type == "int":
        try:
            return int(raw)
        except ValueError as error:
            raise ProfileError(f"invalid integer answer: {raw}") from error
    return raw


def build_interactive_profile(
    repo_root: Path,
    manifests: dict[str, ModuleManifest],
    *,
    yes: bool,
    input_fn: Callable[[str], str] = input,
    secret_input_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    secret_input_fn = secret_input_fn or getpass.getpass
    profile, recommendations = load_recommended_profile(repo_root)
    for name, enabled in profile["modules"].items():
        if name not in manifests or yes:
            continue
        raw = input_fn(f"Enable {name}? [{'Y/n' if enabled else 'y/N'}] ").strip().lower()
        if raw:
            profile["modules"][name] = raw in {"y", "yes"}

    for name, manifest in manifests.items():
        if not profile["modules"].get(name, False):
            continue
        for question in manifest.questions:
            if yes:
                value = question.default
            else:
                confidence = recommendations.get(f"answers.{name}.{question.id}", {}).get(
                    "confidence", "n/a"
                )
                prompt = (
                    f"{question.prompt} [hidden; confidence: {confidence}] "
                    if question.secret
                    else f"{question.prompt} [{question.default!s}; confidence: {confidence}] "
                )
                raw = (secret_input_fn if question.secret else input_fn)(prompt)
                value = _parse_answer(raw, question.default, question.type)
                if question.type == "choice" and value not in question.choices:
                    raise ProfileError(f"invalid choice for {name}.{question.id}: {value}")
            profile["answers"][f"{name}.{question.id}"] = value

    if profile["modules"].get("codex", False):
        profile["forge"]["roles"] = deep_merge(profile["forge"]["roles"], CODEX_ROLE_DEFAULTS)

    if not yes:
        for dotted_key, recommendation in recommendations.items():
            if not dotted_key.startswith("agents.") and dotted_key != "auto_update":
                continue
            current: Any = profile
            parts = dotted_key.split(".")
            for part in parts[:-1]:
                current = current[part]
            default = current[parts[-1]]
            raw = input_fn(
                f"{dotted_key} [{default!s}; confidence: {recommendation.get('confidence', 'n/a')}] "
            )
            current[parts[-1]] = _parse_answer(
                raw,
                default,
                "bool"
                if isinstance(default, bool)
                else "int"
                if isinstance(default, int)
                else "string",
            )
    validate_profile(profile)
    return profile


def profile_render_context(
    defaults: dict[str, Any], data: list[dict[str, Any]], profile: dict[str, Any]
) -> dict[str, Any]:
    context = deepcopy(defaults)
    for fragment in data:
        context = deep_merge(context, fragment)
    context = deep_merge(context, profile)
    nested_answers: dict[str, dict[str, Any]] = {}
    for key, value in profile.get("answers", {}).items():
        module, _, question = key.partition(".")
        nested_answers.setdefault(module, {})[question] = value
    context["answers"] = nested_answers
    return context


def installed_profile(profile: dict[str, Any]) -> dict[str, Any]:
    installed = deepcopy(profile)
    installed["installed_at"] = datetime.now(UTC).isoformat()
    return installed


def write_profile(path: Path, profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(json.dumps(installed_profile(profile), indent=2) + "\n", encoding="utf-8")
