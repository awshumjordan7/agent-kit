from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from aisetup.layers import ResolvedLayers
from aisetup.paths import is_default_claude_home


@dataclass(frozen=True)
class Capability:
    id: str
    status: str
    evidence: str
    error: str | None


def _result(
    capability_id: str,
    passed: bool,
    evidence: str,
    error: str | None = None,
) -> Capability:
    return Capability(capability_id, "pass" if passed else "fail", evidence, error)


def _skip(capability_id: str, evidence: str) -> Capability:
    return Capability(capability_id, "skip", evidence, None)


def _writable(path: Path) -> bool:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK)


def _json_file(capability_id: str, path: Path) -> Capability:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _result(capability_id, False, str(path), "file does not exist")
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return _result(capability_id, False, str(path), str(error))
    return _result(capability_id, True, str(path))


def _agent_owner(resolved_layers: ResolvedLayers, filename: str) -> str:
    for layer in reversed(resolved_layers.layers):
        if (layer.root / "agents" / filename).is_file():
            return layer.name
    return "unknown"


def run_selfcheck(home: Path, layers_root: Path) -> list[Capability]:
    from aisetup.compose import KEPT_STATUSES, ComposeError, compose_tree
    from aisetup.layers import resolve_layers
    from aisetup.manifest import ManifestError
    from aisetup.mcp import McpError, _matches, registration_for_layers
    from aisetup.profile import ProfileError, load_profile
    from aisetup.update import ContentDrift, check_content

    home = home.expanduser()
    layers_root = layers_root.expanduser()
    results = [
        _result(
            "python_version",
            sys.version_info >= (3, 11),
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            None if sys.version_info >= (3, 11) else "Python 3.11 or newer is required",
        )
    ]

    claude = shutil.which("claude")
    results.append(
        _result(
            "claude_cli", claude is not None, claude or "not found", None if claude else "missing"
        )
    )
    git = shutil.which("git")
    results.append(_result("git", git is not None, git or "not found", None if git else "missing"))

    if not is_default_claude_home(home):
        results.append(_skip("mcp_list", "--home is not the default"))
    elif claude is None:
        results.append(_skip("mcp_list", "claude CLI unavailable"))
    else:
        try:
            completed = subprocess.run(
                [claude, "mcp", "list"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            results.append(
                _result(
                    "mcp_list",
                    completed.returncode == 0,
                    "claude mcp list",
                    completed.stderr.strip() or None if completed.returncode else None,
                )
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            results.append(_result("mcp_list", False, "claude mcp list", str(error)))

    results.extend(
        [
            _result(
                "home_writable",
                _writable(home),
                str(home),
                None if _writable(home) else "not writable",
            ),
            _result(
                "layers_root_writable",
                _writable(layers_root),
                str(layers_root),
                None if _writable(layers_root) else "not writable",
            ),
            _json_file("settings_json_parses", home / "settings.json"),
        ]
    )

    profile_path = layers_root / "profile.json"
    profile = None
    if profile_path.exists():
        try:
            profile = load_profile(profile_path)
        except ProfileError as error:
            results.append(_result("profile_valid", False, str(profile_path), str(error)))
        else:
            results.append(_result("profile_valid", True, str(profile_path)))
    else:
        results.append(_skip("profile_valid", f"{profile_path} not installed"))

    if profile is None:
        results.append(_skip("managed_content", "valid profile unavailable"))
        results.append(_skip("installed_agents_match", "valid profile unavailable"))
        results.append(_skip("mcp_registered_set", "valid profile unavailable"))
    else:
        items: list[ContentDrift] = []
        try:
            items = check_content(profile, home, layers_root)
        except (ComposeError, OSError) as error:
            results.append(_result("managed_content", False, str(home), str(error)))
        else:
            drift = [item.line() for item in items if item.drift]
            results.append(
                _result(
                    "managed_content",
                    not drift,
                    ", ".join(drift) or "composed tree matches",
                    None if not drift else "managed files differ",
                )
            )
        kept_agents = {
            Path(item.path).name
            for item in items
            if item.path.startswith("agents/") and item.status in KEPT_STATUSES
        }

        try:
            resolved = resolve_layers(profile)
            with tempfile.TemporaryDirectory(prefix="agent-kit-agent-check-") as temporary:
                composed = Path(temporary) / "claude"
                compose_tree(profile, composed)
                mismatches = []
                for expected in sorted((composed / "agents").glob("*.md")):
                    installed = home / "agents" / expected.name
                    if expected.name in kept_agents or (
                        installed.is_file() and installed.read_bytes() == expected.read_bytes()
                    ):
                        continue
                    mismatches.append(
                        f"{expected.name} (owning layer: {_agent_owner(resolved, expected.name)})"
                    )
        except (ComposeError, ManifestError, OSError) as error:
            results.append(
                _result("installed_agents_match", False, str(home / "agents"), str(error))
            )
        else:
            kept = [f"kept locally modified: {name}" for name in sorted(kept_agents)]
            evidence = ", ".join(mismatches + kept) or "installed agents match composed layers"
            results.append(
                _result(
                    "installed_agents_match",
                    not mismatches,
                    evidence,
                    None if not mismatches else "installed agents differ",
                )
            )

        if not is_default_claude_home(home):
            results.append(_skip("mcp_registered_set", "--home is not the default"))
        elif claude is None:
            results.append(_skip("mcp_registered_set", "claude CLI unavailable"))
        else:
            try:
                resolved = resolve_layers(profile)
                plans, retire = registration_for_layers(resolved, profile)
                problems: list[str] = []
                for plan in plans:
                    completed = subprocess.run(
                        [claude, "mcp", "get", plan.server.name],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    if completed.returncode != 0 or not _matches(plan, completed.stdout):
                        problems.append(plan.server.name)
                for name in retire:
                    completed = subprocess.run(
                        [claude, "mcp", "get", name],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    if completed.returncode == 0:
                        problems.append(f"extra:{name}")
                evidence = ", ".join(problems) or "registered set matches"
                results.append(
                    _result(
                        "mcp_registered_set",
                        not problems,
                        evidence,
                        None if not problems else "registered servers differ",
                    )
                )
            except (ManifestError, McpError, OSError, subprocess.TimeoutExpired) as error:
                results.append(_result("mcp_registered_set", False, "claude mcp get", str(error)))

    claude_md = home / "CLAUDE.md"
    results.append(
        _result(
            "claude_md_present",
            claude_md.is_file(),
            str(claude_md),
            None if claude_md.is_file() else "file does not exist",
        )
    )
    hooks = home / "hooks"
    non_python = (
        sorted(
            path.name
            for path in hooks.iterdir()
            if path.is_file() and not path.name.startswith(".") and path.suffix != ".py"
        )
        if hooks.is_dir()
        else []
    )
    results.append(
        _result(
            "hooks_python_only",
            hooks.is_dir() and not non_python,
            str(hooks),
            f"non-Python hooks: {', '.join(non_python)}"
            if non_python
            else (None if hooks.is_dir() else "directory does not exist"),
        )
    )
    results.append(_json_file("forge_config_valid", home / "skills/forge/forge.config.json"))
    return results


def print_selfcheck(results: list[Capability], *, json_output: bool, quiet: bool) -> None:
    if json_output:
        print(json.dumps([asdict(result) for result in results]))
        return
    for result in results:
        if quiet and result.status == "pass":
            continue
        suffix = f": {result.error}" if result.error else ""
        print(f"{result.status.upper():<4} {result.id}: {result.evidence}{suffix}")
