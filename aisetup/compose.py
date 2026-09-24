from __future__ import annotations

import errno
import filecmp
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aisetup.layers import Layer, ResolvedLayers, layer_data, load_json, resolve_layers
from aisetup.manifest import ManifestError
from aisetup.merge import (
    KIND_CONFLICT,
    KIND_KIT,
    SettingsChange,
    _identity,
    deep_merge,
    merge_settings,
)
from aisetup.profile import load_recommended_profile, profile_render_context
from aisetup.render import RenderError, render_agent_frontmatter, render_text
from aisetup.tomlwrite import TomlWriteError, dumps as toml_dumps


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
    stale: tuple[Path, ...]


@dataclass(frozen=True)
class AuxiliaryFile:
    relative: str
    target: Path
    status: str | None
    action: str
    remove_kit_new: bool
    back_up_kit_new: bool
    content: bytes | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CodexConfigMerge:
    status: str | None
    changes: tuple[SettingsChange, ...]
    base: dict[str, Any]


@dataclass(frozen=True)
class InstallPlan:
    files: tuple[str, ...]
    settings: dict[str, Any]
    paths: InstallationPaths
    kept: tuple[tuple[str, str], ...]
    digests: dict[str, str]
    auxiliary: tuple[AuxiliaryFile, ...]
    auxiliary_digests: dict[str, str]
    settings_changes: tuple[SettingsChange, ...]
    settings_base: dict[str, Any]
    settings_status: str | None
    codex_config: CodexConfigMerge | None


DEFAULT_DIRECTORIES = ("hooks", "agents", "skills", "references", "scripts")
COMPILED_SUFFIXES = {".pyc", ".pyo", ".pyd"}
COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.pyd")
MANAGED_PATHS_VERSION = 1
MANAGED_PATHS_FILENAME = "managed-paths.json"
SETTINGS_BASE_FILENAME = "settings.base.json"
CODEX_CONFIG_BASE_FILENAME = "codex-config.base.json"
KIT_NEW_SUFFIX = ".kit-new"
SETTINGS_PATH = "settings.json"
CODE_STANDARDS_PATH = "skills/forge/references/code-standards.md"
CODEX_AGENTS_PATH = ".codex/AGENTS.md"
CODEX_CONFIG_PATH = ".codex/config.toml"
FALLBACK_COMMENTS = "the live file has comments, which a rewrite would drop"
FALLBACK_UNSUPPORTED = "the live file holds a value the TOML writer cannot write"

STATUS_MISSING = "missing"
STATUS_KIT_UPDATE = "kit update pending"
STATUS_UNRECORDED = "unrecorded"
STATUS_LOCALLY_MODIFIED = "locally modified"
STATUS_CONFLICT = "conflict"
STATUS_INVALID = "invalid"
KEPT_STATUSES = frozenset({STATUS_UNRECORDED, STATUS_LOCALLY_MODIFIED, STATUS_CONFLICT})

ACTION_NONE = "none"
ACTION_WRITE = "write"
ACTION_REPLACE = "replace"
ACTION_KEEP = "keep"

BACKUPS_DIRNAME = "backups"
BACKUP_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
BACKUP_RUN_NAME = re.compile(r"\d{8}_\d{6}(\.\d+)?")
BACKUP_RETENTION = timedelta(days=30)


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


STAGED_DOCTOR_MODULE = "_aisetup_staged_doctor"


def _render_derived(destination: Path, auxiliary_root: Path) -> None:
    doctor_path = destination / "scripts/doctor.py"
    if not doctor_path.is_file():
        raise ComposeError(f"staged doctor.py is missing: {doctor_path}")
    spec = importlib.util.spec_from_file_location(STAGED_DOCTOR_MODULE, doctor_path)
    if spec is None or spec.loader is None:
        raise ComposeError(f"cannot load staged doctor.py: {doctor_path}")
    doctor = importlib.util.module_from_spec(spec)
    # A bytecode cache here would be installed as a managed file. The dataclasses in
    # doctor.py need the module registered in sys.modules while it executes.
    write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.modules[STAGED_DOCTOR_MODULE] = doctor
    try:
        spec.loader.exec_module(doctor)
        ctx = doctor.Context(root=destination, config=doctor.load_config())
    except (ImportError, AttributeError, SyntaxError, OSError, tomllib.TOMLDecodeError) as error:
        raise ComposeError(f"cannot load staged doctor.py: {error}") from error
    finally:
        sys.modules.pop(STAGED_DOCTOR_MODULE, None)
        sys.dont_write_bytecode = write_bytecode

    targets = (
        (destination / CODE_STANDARDS_PATH, doctor.expected_code_standards),
        (auxiliary_root / CODEX_AGENTS_PATH, doctor.expected_codex_agents),
    )
    for target, generate in targets:
        if not target.is_file():
            continue
        text, error = generate(ctx)
        if error is not None or text is None:
            raise ComposeError(f"cannot render {target}: {error or 'no content'}")
        target.write_text(text, encoding="utf-8")


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
        _render_derived(destination, auxiliary_root)
    except (ManifestError, OSError, UnicodeError) as error:
        raise ComposeError(str(error)) from error

    files = tuple(
        str(path.relative_to(destination))
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    )
    return ComposeResult(files, settings)


def _backup_run_dir(layers_root: Path) -> Path:
    backups = layers_root.expanduser() / BACKUPS_DIRNAME
    timestamp = datetime.now().strftime(BACKUP_TIMESTAMP_FORMAT)
    candidate = backups / timestamp
    counter = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = backups / f"{timestamp}.{counter}"
        counter += 1
    return candidate


def _move(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, target)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        shutil.move(source, target)


def _count_backup_files(run_dir: Path) -> int:
    count = 0
    for dirpath, dirnames, filenames in os.walk(run_dir):
        count += len(filenames)
        # os.walk lists a symlink to a directory under dirnames without descending into it.
        count += sum(1 for name in dirnames if (Path(dirpath) / name).is_symlink())
    return count


def _prune_backup_runs(layers_root: Path) -> None:
    backups = layers_root.expanduser() / BACKUPS_DIRNAME
    cutoff = datetime.now() - BACKUP_RETENTION
    try:
        entries = sorted(backups.iterdir()) if backups.is_dir() else []
    except OSError as error:
        sys.stderr.write(f"warning: cannot list backups in {backups}: {error}\n")
        return
    for entry in entries:
        if not BACKUP_RUN_NAME.fullmatch(entry.name):
            continue
        if entry.is_symlink() or not entry.is_dir():
            continue
        try:
            created = datetime.strptime(entry.name[:15], BACKUP_TIMESTAMP_FORMAT)
        except ValueError:
            continue
        if created >= cutoff:
            continue
        try:
            shutil.rmtree(entry)
        except OSError as error:
            sys.stderr.write(f"warning: cannot delete old backup {entry}: {error}\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_managed_record(layers_root: Path) -> tuple[dict[str, str], dict[str, str]]:
    path = layers_root.expanduser() / MANAGED_PATHS_FILENAME
    if not path.is_file():
        return {}, {}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ComposeError(f"cannot read managed path record {path}: {error}") from error
    if not isinstance(record, dict):
        raise ComposeError(f"invalid managed path record: {path}")
    paths = record.get("paths")
    auxiliary = record.get("auxiliary", {})
    if record.get("version") != MANAGED_PATHS_VERSION or not isinstance(paths, dict):
        raise ComposeError(f"unsupported managed path record: {path}")
    for digests in (paths, auxiliary):
        if not isinstance(digests, dict) or not all(
            isinstance(relative, str) and isinstance(digest, str)
            for relative, digest in digests.items()
        ):
            raise ComposeError(f"invalid managed path record: {path}")
    return paths, auxiliary


def _write_managed_record(
    layers_root: Path, paths: dict[str, str], auxiliary: dict[str, str]
) -> None:
    layers_root = layers_root.expanduser()
    layers_root.mkdir(parents=True, exist_ok=True)
    path = layers_root / MANAGED_PATHS_FILENAME
    temporary = path.with_suffix(".tmp")
    record = {
        "version": MANAGED_PATHS_VERSION,
        "paths": dict(sorted(paths.items())),
        "auxiliary": dict(sorted(auxiliary.items())),
    }
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def classify_file(live: Path, kit_digest: str, recorded_digest: str | None) -> str | None:
    if not live.is_file():
        return STATUS_MISSING
    live_digest = _sha256(live)
    if live_digest == kit_digest:
        return None
    if recorded_digest is None:
        return STATUS_UNRECORDED
    if live_digest == recorded_digest:
        return STATUS_KIT_UPDATE
    if recorded_digest == kit_digest:
        return STATUS_LOCALLY_MODIFIED
    return STATUS_CONFLICT


def _derived_status(live: Path, kit_digest: str) -> str | None:
    status = classify_file(live, kit_digest, None)
    return STATUS_KIT_UPDATE if status == STATUS_UNRECORDED else status


def _kit_new_path(path: Path) -> Path:
    return path.with_name(path.name + KIT_NEW_SUFFIX)


def installation_paths(home: Path, staged: Path, layers_root: Path) -> InstallationPaths:
    home = home.expanduser()
    if not home.is_dir():
        return InstallationPaths((), (), (), ())

    previous, _ = load_managed_record(layers_root)
    preserved: list[Path] = []
    retired: list[Path] = []
    retired_modified: list[Path] = []
    stale: list[Path] = []

    def contains_managed_path(relative: Path) -> bool:
        prefix = relative.as_posix().rstrip("/") + "/"
        return any(path.startswith(prefix) for path in previous)

    # A kept file's record holds its kit hash, which is exactly the content of its .kit-new.
    def is_kit_owned_kit_new(entry: Path, relative: Path) -> bool:
        if entry.is_symlink() or not entry.is_file() or not entry.name.endswith(KIT_NEW_SUFFIX):
            return False
        recorded_digest = previous.get(relative.as_posix()[: -len(KIT_NEW_SUFFIX)])
        return recorded_digest is not None and _sha256(entry) == recorded_digest

    def collect(source: Path) -> None:
        for entry in sorted(source.iterdir()):
            relative = entry.relative_to(home)
            target = staged / relative
            if not target.exists() and not target.is_symlink():
                recorded_digest = previous.get(relative.as_posix())
                if is_kit_owned_kit_new(entry, relative):
                    stale.append(relative)
                elif entry.is_dir() and not entry.is_symlink() and contains_managed_path(relative):
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
    return InstallationPaths(
        tuple(preserved), tuple(retired), tuple(retired_modified), tuple(stale)
    )


def _settings_text(settings: dict[str, Any]) -> str:
    return json.dumps(settings, indent=2) + "\n"


def _load_settings_base(
    layers_root: Path, filename: str = SETTINGS_BASE_FILENAME
) -> dict[str, Any] | None:
    path = layers_root.expanduser() / filename
    if not path.is_file():
        return None
    try:
        base = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        sys.stderr.write(f"warning: ignoring unreadable {path}: {error}\n")
        return None
    if not isinstance(base, dict):
        sys.stderr.write(f"warning: ignoring {path}: not a JSON object\n")
        return None
    return base


def _write_settings_base(
    layers_root: Path, settings: dict[str, Any], filename: str = SETTINGS_BASE_FILENAME
) -> None:
    path = layers_root.expanduser() / filename
    temporary = path.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(_settings_text(settings))
    os.replace(temporary, path)


def _merge_live_file(
    ours: dict[str, Any],
    live: Path,
    layers_root: Path,
    recorded_digest: str | None,
    base_filename: str,
    parse: Callable[[str], Any],
) -> tuple[dict[str, Any], tuple[SettingsChange, ...], str | None, dict[str, Any] | None]:
    """Three-way merge of a live file; also returns the parsed live data when it parsed."""
    if not live.is_file():
        return ours, (), STATUS_MISSING, None
    try:
        theirs = parse(live.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError):
        return ours, (), STATUS_INVALID, None
    if not isinstance(theirs, dict):
        return ours, (), STATUS_INVALID, None
    base = _load_settings_base(layers_root, base_filename)
    if base is None:
        # Without the previous kit render, a live file still matching the record is that render.
        base = theirs if _sha256(live) == recorded_digest else {}
    merged, changes = merge_settings(base, ours, theirs)
    return merged, tuple(changes), None, theirs


def _merge_live_settings(
    ours: dict[str, Any], live: Path, layers_root: Path, recorded_digest: str | None
) -> tuple[dict[str, Any], tuple[SettingsChange, ...], str | None]:
    merged, changes, status, _ = _merge_live_file(
        ours, live, layers_root, recorded_digest, SETTINGS_BASE_FILENAME, json.loads
    )
    return merged, changes, status


def _classify_codex_config(
    source: Path, target: Path, layers_root: Path, kit_digest: str, recorded_digest: str | None
) -> tuple[str | None, bytes | None, str | None, CodexConfigMerge | None]:
    """Return the status, merged bytes to write, fallback reason, and key-level merge result."""
    try:
        kit = tomllib.loads(source.read_text(encoding="utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ComposeError(f"cannot parse kit {CODEX_CONFIG_PATH}: {error}") from error
    merged, changes, status, theirs = _merge_live_file(
        kit, target, layers_root, recorded_digest, CODEX_CONFIG_BASE_FILENAME, tomllib.loads
    )
    content: bytes | None = None
    reason: str | None = None
    # _identity keeps TOML types apart: plain == treats True as 1 and 1.0 as 1.
    if status is None and _identity(merged) != _identity(theirs):
        if "#" in target.read_text(encoding="utf-8"):
            reason = FALLBACK_COMMENTS
        else:
            try:
                content = toml_dumps(merged).encode("utf-8")
            except TomlWriteError:
                reason = FALLBACK_UNSUPPORTED
    if reason is not None:
        return classify_file(target, kit_digest, recorded_digest), None, reason, None
    return status, content, None, CodexConfigMerge(status, changes, kit)


def _auxiliary_action(status: str | None) -> str:
    if status is None:
        return ACTION_NONE
    if status == STATUS_MISSING:
        return ACTION_WRITE
    if status in KEPT_STATUSES:
        return ACTION_KEEP
    return ACTION_REPLACE


def _rerender_derived(staging: Path, auxiliary: Path, kept_claude_md: Path) -> None:
    derived = (staging / CODE_STANDARDS_PATH, auxiliary / CODEX_AGENTS_PATH)
    kit_versions = {path: path.read_bytes() for path in derived if path.is_file()}
    try:
        _render_derived(staging, auxiliary)
    except (ComposeError, OSError, UnicodeError) as error:
        for path, data in kit_versions.items():
            path.write_bytes(data)
        sys.stderr.write(
            f"warning: cannot render derived files from kept {kept_claude_md}: {error}; "
            "installing the kit versions\n"
        )


def _classify_auxiliary(
    auxiliary: Path, user_home: Path, previous: dict[str, str], layers_root: Path
) -> tuple[tuple[AuxiliaryFile, ...], dict[str, str], CodexConfigMerge | None]:
    files: list[AuxiliaryFile] = []
    digests: dict[str, str] = {}
    codex_config: CodexConfigMerge | None = None
    if not auxiliary.is_dir():
        return (), digests, codex_config
    for source in sorted(auxiliary.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(auxiliary).as_posix()
        target = user_home / relative
        kit_digest = _sha256(source)
        recorded_digest = previous.get(relative)
        content: bytes | None = None
        reason: str | None = None
        if relative == CODEX_AGENTS_PATH:
            status = _derived_status(target, kit_digest)
        elif relative == CODEX_CONFIG_PATH:
            status, content, reason, codex_config = _classify_codex_config(
                source, target, layers_root, kit_digest, recorded_digest
            )
        else:
            status = classify_file(target, kit_digest, recorded_digest)
        if status is None and content is not None:
            action = ACTION_REPLACE
        else:
            action = _auxiliary_action(status)
        kit_new = _kit_new_path(target)
        remove_kit_new = (
            action != ACTION_KEEP
            and recorded_digest is not None
            and not kit_new.is_symlink()
            and kit_new.is_file()
            and _sha256(kit_new) == recorded_digest
        )
        back_up_kit_new = (
            action == ACTION_KEEP
            and _is_regular_file(kit_new)
            and _sha256(kit_new) not in (kit_digest, recorded_digest)
        )
        files.append(
            AuxiliaryFile(
                relative,
                target,
                status,
                action,
                remove_kit_new,
                back_up_kit_new,
                content,
                reason,
            )
        )
        digests[relative] = kit_digest
    return tuple(files), digests, codex_config


def prepare_install(
    profile: dict[str, Any],
    home: Path,
    staging: Path,
    auxiliary: Path,
    layers_root: Path,
) -> InstallPlan:
    home = home.expanduser()
    result = compose_tree(profile, staging, auxiliary_root=auxiliary)
    previous, previous_auxiliary = load_managed_record(layers_root)
    try:
        kept: list[tuple[str, str]] = []
        kit_digests: dict[str, str] = {}
        for relative in result.files:
            if relative in (SETTINGS_PATH, CODE_STANDARDS_PATH):
                continue
            staged = staging / relative
            live = home / relative
            kit_digest = _sha256(staged)
            status = classify_file(live, kit_digest, previous.get(relative))
            if status in KEPT_STATUSES:
                os.replace(staged, _kit_new_path(staged))
                shutil.copy2(live, staged, follow_symlinks=False)
                kept.append((relative, status))
                kit_digests[relative] = kit_digest
        if "CLAUDE.md" in kit_digests:
            _rerender_derived(staging, auxiliary, home / "CLAUDE.md")
        staged_settings = staging / SETTINGS_PATH
        kit_digests[SETTINGS_PATH] = _sha256(staged_settings)
        settings, settings_changes, settings_status = _merge_live_settings(
            result.settings, home / SETTINGS_PATH, layers_root, previous.get(SETTINGS_PATH)
        )
        staged_settings.write_text(_settings_text(settings), encoding="utf-8")
        digests = {
            relative: kit_digests.get(relative) or _sha256(staging / relative)
            for relative in result.files
        }
        auxiliary_files, auxiliary_digests, codex_config = _classify_auxiliary(
            auxiliary, home.parent, previous_auxiliary, layers_root
        )
        # Runs after the keep substitution so regenerated .kit-new files count as staged.
        paths = installation_paths(home, staging, layers_root)
    except (OSError, UnicodeError) as error:
        raise ComposeError(str(error)) from error
    return InstallPlan(
        files=result.files,
        settings=settings,
        paths=paths,
        kept=tuple(kept),
        digests=digests,
        auxiliary=auxiliary_files,
        auxiliary_digests=auxiliary_digests,
        settings_changes=settings_changes,
        settings_base=result.settings,
        settings_status=settings_status,
        codex_config=codex_config,
    )


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _has_identical_copy(entry: Path, home: Path, relative: Path) -> bool:
    if any((home / parent).is_symlink() for parent in relative.parents):
        return False
    live = home / relative
    if not _is_regular_file(live):
        return False
    try:
        return filecmp.cmp(entry, live, shallow=False)
    except OSError:
        return False


def _has_identical_link(entry: Path, home: Path, relative: Path) -> bool:
    live = home / relative
    if not (entry.is_symlink() and live.is_symlink()):
        return False
    if any((home / parent).is_symlink() for parent in relative.parents):
        return False
    try:
        return os.readlink(entry) == os.readlink(live)
    except OSError:
        return False


def _is_real_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()


def _occupied(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _is_unchanged(entry: Path, home: Path, relative: Path) -> bool:
    if entry.is_symlink():
        return _has_identical_link(entry, home, relative)
    if not _has_identical_copy(entry, home, relative):
        return False
    try:
        return stat.S_IMODE(entry.lstat().st_mode) == stat.S_IMODE(
            (home / relative).lstat().st_mode
        )
    except OSError:
        return False


def _check_no_symlinked_parents(staging: Path, home: Path, retired: Iterable[Path]) -> None:
    def fail(link: Path) -> None:
        raise ComposeError(
            f"{link} is a symbolic link, but the kit installs files inside it; "
            "replace it with a folder and run again"
        )

    for dirpath, dirnames, filenames in os.walk(staging):
        relative = Path(dirpath).relative_to(staging)
        if (dirnames or filenames) and relative != Path(".") and (home / relative).is_symlink():
            fail(home / relative)
    for relative in retired:
        for parent in relative.parents:
            if parent != Path(".") and (home / parent).is_symlink():
                fail(home / parent)


def _undo_swap(journal: list[tuple[str, Path, Path | None]]) -> list[str]:
    failures: list[str] = []
    for kind, live, saved in reversed(journal):
        try:
            if kind == "aside" and saved is not None:
                _move(saved, live)
            elif kind == "placed":
                live.unlink()
            elif kind == "created":
                live.rmdir()
        except OSError as error:
            failures.append(f"{live}: {error}")
    return failures


def _remove_empty_parents(home: Path, relative: Path) -> None:
    for parent in relative.parents:
        if parent == Path("."):
            return
        try:
            (home / parent).rmdir()
        except OSError:
            return


def _swap_in_place(staging: Path, home: Path, run_dir: Path, paths: InstallationPaths) -> None:
    """Move changed staged entries into home, setting aside what they replace under run_dir.

    Unchanged and unmanaged live paths are never touched, so home itself stays in place.
    """
    if not _is_real_dir(home):
        raise ComposeError(f"{home} exists but is not a directory")
    _check_no_symlinked_parents(staging, home, paths.retired)
    backup_root = run_dir / "claude"
    journal: list[tuple[str, Path, Path | None]] = []

    def set_aside(relative: Path) -> None:
        live = home / relative
        saved = backup_root / relative
        _move(live, saved)
        journal.append(("aside", live, saved))

    def install(directory: Path) -> None:
        for entry in sorted(directory.iterdir()):
            relative = entry.relative_to(staging)
            live = home / relative
            if _is_real_dir(entry):
                if _occupied(live) and not _is_real_dir(live):
                    set_aside(relative)
                if not _occupied(live):
                    live.mkdir()
                    journal.append(("created", live, None))
                install(entry)
            elif not _is_unchanged(entry, home, relative):
                if _occupied(live):
                    set_aside(relative)
                _move(entry, live)
                journal.append(("placed", live, None))

    try:
        install(staging)
        for relative in paths.retired:
            if _occupied(home / relative):
                set_aside(relative)
    except OSError as error:
        failures = _undo_swap(journal)
        if _count_backup_files(run_dir) == 0:
            shutil.rmtree(run_dir, ignore_errors=True)
        message = f"cannot update {home}: {error}; restored the previous files"
        if failures:
            message = (
                f"cannot update {home}: {error}; could not restore {'; '.join(failures)}; "
                f"old copies are in {backup_root}"
            )
        raise ComposeError(message) from error

    for relative in paths.stale:
        try:
            (home / relative).unlink(missing_ok=True)
        except OSError as error:
            sys.stderr.write(f"warning: cannot remove stale kit copy {home / relative}: {error}\n")
    for relative in (*paths.retired, *paths.stale):
        _remove_empty_parents(home, relative)


def install_tree(profile: dict[str, Any], home: Path, layers_root: Path) -> ComposeResult:
    home = home.expanduser().resolve()
    home.parent.mkdir(parents=True, exist_ok=True)
    run_dir = _backup_run_dir(layers_root)
    work = Path(tempfile.mkdtemp(prefix=f".{home.name}.install-", dir=home.parent))
    staging = work / home.name
    auxiliary = work / "auxiliary"
    try:
        plan = prepare_install(profile, home, staging, auxiliary, layers_root)
        paths = plan.paths
        if home.exists():
            _swap_in_place(staging, home, run_dir, paths)
            sys.stdout.write(f"retired {len(paths.retired)} managed path(s)\n")
            for relative in paths.retired:
                sys.stdout.write(f"retired: {relative}\n")
            for relative in paths.retired_modified:
                sys.stdout.write(f"retired but locally modified: {relative}\n")
        else:
            os.replace(staging, home)
        for relative, status in plan.kept:
            sys.stdout.write(
                f"kept locally modified: {relative} "
                f"({status}; kit version in {relative}{KIT_NEW_SUFFIX})\n"
            )
        _print_key_changes(SETTINGS_PATH, "JSON", plan.settings_status, plan.settings_changes)
        _install_auxiliary(auxiliary, plan.auxiliary, run_dir)
        if plan.codex_config is not None:
            _print_key_changes(
                CODEX_CONFIG_PATH, "TOML", plan.codex_config.status, plan.codex_config.changes
            )
        backup = run_dir if run_dir.exists() else None
        if backup is not None:
            sys.stdout.write(f"backup: {backup} ({_count_backup_files(backup)} file(s))\n")
        else:
            sys.stdout.write("no files replaced\n")
        _write_managed_record(layers_root, plan.digests, plan.auxiliary_digests)
        _write_settings_base(layers_root, plan.settings_base)
        # A fallback leaves codex_config unset, so the parked kit change stays pending.
        if plan.codex_config is not None:
            _write_settings_base(
                layers_root, plan.codex_config.base, CODEX_CONFIG_BASE_FILENAME
            )
        _prune_backup_runs(layers_root)
        return ComposeResult(plan.files, plan.settings, backup)
    finally:
        if work.exists():
            shutil.rmtree(work)


def _print_key_changes(
    label: str, file_format: str, status: str | None, changes: Iterable[SettingsChange]
) -> None:
    if status == STATUS_INVALID:
        sys.stdout.write(
            f"{label}: invalid {file_format} replaced by the kit version (old copy in backup)\n"
        )
    if status is not None:
        return
    changes = tuple(changes)
    applied = sum(1 for change in changes if change.kind == KIND_KIT)
    kept = len(changes) - applied
    sys.stdout.write(f"{label}: {applied} kit change(s) applied, {kept} local value(s) kept\n")
    for change in changes:
        if change.kind == KIND_CONFLICT:
            sys.stdout.write(f"{label} conflict: {change.key_path} (local value kept)\n")


def _install_auxiliary(
    source_root: Path, files: Iterable[AuxiliaryFile], run_dir: Path
) -> None:
    for item in files:
        source = source_root / item.relative
        target = item.target
        kit_new = _kit_new_path(target)
        backup = run_dir / "home" / item.relative
        kit_new_backup = _kit_new_path(backup)
        if item.reason is not None:
            sys.stdout.write(f"{target}: key merge skipped: {item.reason}\n")
        if item.action != ACTION_NONE:
            target.parent.mkdir(parents=True, exist_ok=True)
        if item.action == ACTION_REPLACE:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            if item.content is not None:
                target.write_bytes(item.content)
            else:
                shutil.copy2(source, target)
        elif item.action == ACTION_WRITE:
            shutil.copy2(source, target)
        elif item.action == ACTION_KEEP:
            if kit_new.is_symlink():
                kit_new_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(kit_new, kit_new_backup)
                sys.stdout.write(f"backed up kit copy link: {kit_new} -> {kit_new_backup}\n")
            elif item.back_up_kit_new:
                kit_new_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(kit_new, kit_new_backup)
                sys.stdout.write(f"backed up edited kit copy: {kit_new} -> {kit_new_backup}\n")
            shutil.copy2(source, kit_new)
            sys.stdout.write(
                f"kept locally modified: {target} ({item.status}; kit version in {kit_new})\n"
            )
        if item.remove_kit_new:
            kit_new.unlink(missing_ok=True)
