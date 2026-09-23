from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from aisetup import __version__
from aisetup.compose import ACTION_KEEP, ComposeError, install_tree, prepare_install
from aisetup.denylist import load_entries, scan_tree
from aisetup.deps import (
    CORE_DEPENDENCIES,
    MissingDependencyError,
    check_dependencies,
    format_missing_dependencies,
)
from aisetup.layers import ResolvedLayers, resolve_layers
from aisetup.manifest import ManifestError, load_layer_manifest, load_module_manifest
from aisetup.mcp import McpError, register_servers, registration_for_layers
from aisetup.profile import (
    ProfileError,
    apply_overlay_question_defaults,
    build_interactive_profile,
    format_profile_path,
    load_profile,
    profile_overrides,
    unknown_name_warnings,
    write_profile,
)
from aisetup.selfcheck import print_selfcheck, run_selfcheck
from aisetup.tune import TuneError, collect_metrics, format_report, recommendations
from aisetup.update import (
    UpdateError,
    check_content,
    check_repositories,
    commit_subjects,
    core_head,
    update_profile_commits,
    update_repositories,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
# Set on the re-executed update so a core checkout that moves again cannot loop.
REEXEC_ENV = "AGENT_KIT_UPDATE_REEXEC"


def _path(value: str) -> Path:
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py", description="Install and maintain agent-kit"
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install", help="compose and install the configured layers")
    install.add_argument("--profile", type=_path)
    install.add_argument("--yes", action="store_true")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--home", type=_path, default=Path("~/.claude").expanduser())
    install.add_argument("--layers-root", type=_path, default=Path("~/.ai-setup").expanduser())

    update = subparsers.add_parser("update", help="update layer repositories")
    update.add_argument("--profile", type=_path)
    update.add_argument("--check", action="store_true")
    update.add_argument("--home", type=_path, default=Path("~/.claude").expanduser())
    update.add_argument("--layers-root", type=_path, default=Path("~/.ai-setup").expanduser())

    doctor = subparsers.add_parser("doctor", help="check the installed setup")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--quiet", action="store_true")
    doctor.add_argument("--fix", action="store_true")
    doctor.add_argument("--selfcheck", action="store_true")
    doctor.add_argument("--home", type=_path, default=Path("~/.claude").expanduser())
    doctor.add_argument("--layers-root", type=_path, default=Path("~/.ai-setup").expanduser())
    doctor.add_argument("--denylist", type=_path)
    doctor.add_argument("--root", type=_path)
    doctor.add_argument("--tokens-only", action="store_true")

    tune = subparsers.add_parser("tune", help="propose profile changes from transcript metrics")
    tune.add_argument("--since")
    tune.add_argument("--until")
    tune.add_argument("--tz")
    tune.add_argument("--transcripts", type=_path)
    tune.add_argument("--out", type=_path)
    tune.add_argument("--layers-root", type=_path, default=Path("~/.ai-setup").expanduser())
    return parser


def _module_manifests(repo_root: Path) -> dict[str, object]:
    layer = load_layer_manifest(repo_root / "core/layer.toml")
    return {
        name: load_module_manifest(repo_root / "modules" / name / "module.toml")
        for name in layer.modules
        if (repo_root / "modules" / name / "module.toml").is_file()
    }


def _print_name_warnings(profile: dict[str, Any], resolved: ResolvedLayers) -> None:
    known_agents = {
        path.stem for layer in resolved.layers for path in (layer.root / "agents").glob("*.md")
    }
    for warning in unknown_name_warnings(profile, known_agents):
        print(warning, file=sys.stderr)


def _print_overrides(profile: dict[str, Any]) -> None:
    for path, value, default in profile_overrides(profile):
        repo_default = (
            "no repo default" if default is ... else f"repo default: {json.dumps(default)}"
        )
        print(
            f"profile override: {format_profile_path(path)} = {json.dumps(value)} ({repo_default})"
        )


def _install(args: argparse.Namespace) -> int:
    try:
        check_dependencies(CORE_DEPENDENCIES)
        if args.profile:
            profile = load_profile(args.profile)
        else:
            profile = build_interactive_profile(
                REPO_ROOT,
                _module_manifests(REPO_ROOT),
                yes=args.yes,
                input_fn=input,
            )
            profile["layers"]["local"] = str(args.layers_root / "local")
        resolved = resolve_layers(profile)
        if args.profile:
            apply_overlay_question_defaults(profile, resolved)
        check_dependencies(resolved.requirements)
    except MissingDependencyError as error:
        print(format_missing_dependencies(error), file=sys.stderr)
        return 3
    except (ManifestError, ProfileError) as error:
        print(f"agent-kit: {error}", file=sys.stderr)
        return 4
    _print_name_warnings(profile, resolved)

    try:
        if args.dry_run:
            with tempfile.TemporaryDirectory(prefix="agent-kit-dry-run-") as temporary:
                plan = prepare_install(
                    profile,
                    args.home,
                    Path(temporary) / "claude",
                    Path(temporary) / "auxiliary",
                    args.layers_root,
                )
            print("Planned files:")
            for path in plan.files:
                print(path)
            print("Preserved (unmanaged):")
            for path in plan.paths.preserved:
                print(path)
            print("Retired (managed):")
            for path in plan.paths.retired:
                print(path)
            for path in plan.paths.retired_modified:
                print(f"retired but locally modified: {path}")
            print("Kept (locally modified):")
            for path, status in plan.kept:
                print(f"{path} ({status})")
            for item in plan.auxiliary:
                if item.action == ACTION_KEEP:
                    print(f"{item.target} ({item.status})")
            print("Settings changes:")
            for change in plan.settings_changes:
                detail = f" ({change.detail})" if change.detail else ""
                print(f"{change.kind} {change.key_path}{detail}")
            print("MCP commands:")
            plans, retire = registration_for_layers(resolved, profile)
            for command in register_servers(plans, home=args.home, dry_run=True, retire=retire):
                print(command)
            for name in resolved.skipped_platforms:
                print(f"Skipped module {name}: unsupported on this platform")
            return 0
        local_root = args.layers_root / "local"
        if not local_root.exists():
            shutil.copytree(REPO_ROOT / "core/templates/local", local_root)
        result = install_tree(profile, args.home, args.layers_root)
        plans, retire = registration_for_layers(resolved, profile)
        register_servers(plans, home=args.home, retire=retire)
        write_profile(args.layers_root / "profile.json", profile)
    except ComposeError as error:
        print(f"agent-kit: {error}", file=sys.stderr)
        return 5
    except (McpError, OSError, ProfileError) as error:
        print(f"agent-kit: {error}", file=sys.stderr)
        return 6

    print(f"Installed {len(result.files)} files into {args.home}")
    if result.backup:
        print(f"Backup: {result.backup}")
    for name in resolved.skipped_platforms:
        print(f"Skipped module {name}: unsupported on this platform")
    return 0


def _doctor(args: argparse.Namespace) -> int:
    if args.denylist is not None or args.tokens_only:
        root = (args.root or REPO_ROOT).resolve()
        try:
            entries = () if args.tokens_only else load_entries(args.denylist)
            hits = scan_tree(root, entries)
        except OSError as error:
            print(f"agent-kit: {error}", file=sys.stderr)
            return 1
        for hit in hits:
            print(f"{hit.path}:{hit.line}: {hit.entry}")
        return 1 if hits else 0
    if args.selfcheck:
        results = run_selfcheck(args.home, args.layers_root)
        print_selfcheck(results, json_output=args.json, quiet=args.quiet)
        return 1 if any(result.status == "fail" for result in results) else 0

    command = [sys.executable, str(REPO_ROOT / "core/scripts/doctor.py"), "--root", str(args.home)]
    if args.json:
        command.append("--json")
    if args.quiet:
        command.append("--quiet")
    if args.fix:
        command.append("--fix")
    completed = subprocess.run(command, check=False)
    if not args.quiet:
        profile_path = args.layers_root / "profile.json"
        if profile_path.is_file():
            try:
                resolved = resolve_layers(load_profile(profile_path))
            except (ManifestError, ProfileError):
                pass
            else:
                for name in resolved.skipped_platforms:
                    print(f"SKIP module_{name}: unsupported on this platform")
    return completed.returncode


def _update(args: argparse.Namespace) -> int:
    profile_path = args.profile or args.layers_root / "profile.json"
    try:
        profile = load_profile(profile_path)
        if args.check:
            statuses = check_repositories(profile)
            for status in statuses:
                print(status.as_json())
            drifts = check_content(profile, args.home)
            if drifts:
                print(
                    f"Managed content: {len(drifts)} managed file(s) differ from the composed tree"
                )
                for drift in drifts:
                    print(f"{drift.path}: drift (source: {drift.source})")
            _print_overrides(profile)
            _print_name_warnings(profile, resolve_layers(profile))
            return 1 if any(status.behind for status in statuses) or drifts else 0
        head_before = core_head(profile)
        update_repositories(profile)
        if core_head(profile) != head_before and os.environ.get(REEXEC_ENV) != "1":
            _reexec_update(args, Path(profile["layers"]["core"]["path"]))
        # Reload so layer data pulled above is merged before the profile is installed and saved.
        profile = load_profile(profile_path)
        resolved = resolve_layers(profile)
        _print_name_warnings(profile, resolved)
        for repo, subject in commit_subjects(profile):
            print(f"{repo}: {subject}")
        update_profile_commits(profile)
        result = install_tree(profile, args.home, args.layers_root)
        plans, retire = registration_for_layers(resolved, profile)
        register_servers(plans, home=args.home, retire=retire)
        write_profile(args.layers_root / "profile.json", profile)
    except (ProfileError, ManifestError) as error:
        print(f"agent-kit: {error}", file=sys.stderr)
        return 4
    except ComposeError as error:
        print(
            "agent-kit: repositories updated, but the install did not replay: "
            f"{error}. Re-run install.py update.",
            file=sys.stderr,
        )
        return 6
    except (UpdateError, McpError, OSError) as error:
        print(f"agent-kit: {error}", file=sys.stderr)
        return 6
    doctor = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "install.py"),
            "doctor",
            "--quiet",
            "--home",
            str(args.home),
        ],
        check=False,
    )
    if doctor.returncode:
        return doctor.returncode
    print(f"Updated {len(result.files)} files in {args.home}")
    return 0


def _reexec_update(args: argparse.Namespace, core_path: Path) -> None:
    # Modules imported before the checkout are stale; the checked-out code must validate and
    # install the new tree.
    command = [sys.executable, str(core_path / "install.py"), "update"]
    if args.profile:
        command.extend(["--profile", str(args.profile)])
    command.extend(["--home", str(args.home), "--layers-root", str(args.layers_root)])
    sys.stdout.flush()
    sys.stderr.flush()
    os.environ[REEXEC_ENV] = "1"
    os.execv(sys.executable, command)


def _tune(args: argparse.Namespace) -> int:
    profile_path = args.layers_root / "profile.json"
    try:
        profile = load_profile(profile_path)
        repo_root = Path(profile["layers"]["core"]["path"])
        metrics_config = profile.get("doctor", {}).get("metrics", {})
        transcripts = (
            args.transcripts
            or Path(metrics_config.get("transcripts", "~/.claude/projects")).expanduser()
        )
        metrics = collect_metrics(
            repo_root,
            profile,
            transcripts,
            since=args.since or metrics_config.get("since"),
            until=args.until or metrics_config.get("until"),
            timezone_offset=args.tz or metrics_config.get("timezone"),
        )
        report = format_report(recommendations(profile, metrics), metrics)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(report, encoding="utf-8")
        else:
            print(report, end="")
    except ProfileError as error:
        print(f"agent-kit: {error}", file=sys.stderr)
        return 4
    except (OSError, TuneError) as error:
        print(f"agent-kit: {error}", file=sys.stderr)
        return 6
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "install":
        return _install(args)
    if args.command == "doctor":
        return _doctor(args)
    if args.command == "update":
        return _update(args)
    if args.command == "tune":
        return _tune(args)
    print(f"{args.command} is not yet implemented", file=sys.stderr)
    return 2
