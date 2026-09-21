from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Question:
    id: str
    prompt: str
    type: str
    default: str | bool | int
    secret: bool = False
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class McpServer:
    name: str
    transport: str
    scope: str
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None


@dataclass(frozen=True)
class FileCopy:
    src: str
    dest: str


@dataclass(frozen=True)
class Template:
    src: str
    dest: str


@dataclass(frozen=True)
class ModuleManifest:
    name: str
    description: str
    default: bool
    depends: tuple[str, ...]
    requires: tuple[str, ...]
    platforms: tuple[str, ...]
    claude_md_fragment: str | None
    settings_fragment: str | None
    questions: tuple[Question, ...]
    mcp: tuple[McpServer, ...]
    files: tuple[FileCopy, ...]
    templates: tuple[Template, ...]

    @property
    def supports_current_platform(self) -> bool:
        return not self.platforms or platform_name() in self.platforms


@dataclass(frozen=True)
class OverlayManifest:
    name: str
    description: str
    requires_agent_kit: str | None
    claude_md_fragment: str | None
    settings_fragment: str | None
    files: tuple[FileCopy, ...]
    templates: tuple[Template, ...]


@dataclass(frozen=True)
class LayerManifest:
    schema: int
    modules: tuple[str, ...]
    templates: tuple[Template, ...]


MODULE_KEYS = {
    "name",
    "description",
    "default",
    "depends",
    "requires",
    "platforms",
    "claude_md_fragment",
    "settings_fragment",
    "questions",
    "mcp",
    "files",
    "templates",
}
OVERLAY_KEYS = {
    "name",
    "description",
    "requires_agent_kit",
    "claude_md_fragment",
    "settings_fragment",
    "files",
    "templates",
}
LAYER_KEYS = {"schema", "modules", "templates"}
QUESTION_KEYS = {"id", "prompt", "type", "default", "secret", "choices"}
MCP_KEYS = {"name", "transport", "command", "args", "scope", "env", "url"}
COPY_KEYS = {"src", "dest"}


def platform_name() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "windows"
    return sys.platform


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ManifestError(f"invalid manifest {path}: {error}") from error
    if not isinstance(data, dict):
        raise ManifestError(f"invalid manifest {path}: expected a table")
    return data


def _unknown(data: dict[str, Any], allowed: set[str], path: Path) -> None:
    unknown = sorted(data.keys() - allowed)
    if unknown:
        raise ManifestError(f"unknown key in {path}: {unknown[0]}")


def _strings(value: Any, key: str, path: Path) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ManifestError(f"{path}: {key} must be an array of strings")
    return tuple(value)


def _copies(data: Any, key: str, path: Path) -> tuple[FileCopy, ...]:
    if not isinstance(data, list):
        raise ManifestError(f"{path}: {key} must be an array of tables")
    copies: list[FileCopy] = []
    for item in data:
        if not isinstance(item, dict):
            raise ManifestError(f"{path}: {key} must be an array of tables")
        _unknown(item, COPY_KEYS, path)
        if not isinstance(item.get("src"), str) or not isinstance(item.get("dest"), str):
            raise ManifestError(f"{path}: {key} src and dest must be strings")
        copies.append(FileCopy(item["src"], str(Path(item["dest"]).expanduser())))
    return tuple(copies)


def _templates(data: Any, path: Path) -> tuple[Template, ...]:
    return tuple(Template(item.src, item.dest) for item in _copies(data, "templates", path))


def load_layer_manifest(path: Path) -> LayerManifest:
    data = _read(path)
    _unknown(data, LAYER_KEYS, path)
    schema = data.get("schema")
    if schema != 1:
        raise ManifestError(f"{path}: schema must be 1")
    modules = _strings(data.get("modules", []), "modules", path)
    return LayerManifest(schema, modules, _templates(data.get("templates", []), path))


def load_module_manifest(path: Path) -> ModuleManifest:
    data = _read(path)
    _unknown(data, MODULE_KEYS, path)
    name = data.get("name")
    description = data.get("description")
    default = data.get("default")
    if not isinstance(name, str) or name != path.parent.name:
        raise ManifestError(f"{path}: name must equal directory name {path.parent.name}")
    if not isinstance(description, str) or not isinstance(default, bool):
        raise ManifestError(f"{path}: description must be a string and default must be a boolean")

    questions: list[Question] = []
    for item in data.get("questions", []):
        if not isinstance(item, dict):
            raise ManifestError(f"{path}: questions must be an array of tables")
        _unknown(item, QUESTION_KEYS, path)
        question_type = item.get("type")
        default_value = item.get("default")
        if (
            not isinstance(item.get("id"), str)
            or not isinstance(item.get("prompt"), str)
            or question_type not in {"string", "bool", "int", "choice"}
            or not isinstance(default_value, (str, bool, int))
        ):
            raise ManifestError(f"{path}: invalid question")
        choices = _strings(item.get("choices", []), "choices", path)
        if question_type == "choice" and (not choices or default_value not in choices):
            raise ManifestError(f"{path}: choice questions need choices containing the default")
        questions.append(
            Question(
                item["id"],
                item["prompt"],
                question_type,
                default_value,
                bool(item.get("secret", False)),
                choices,
            )
        )

    servers: list[McpServer] = []
    for item in data.get("mcp", []):
        if not isinstance(item, dict):
            raise ManifestError(f"{path}: mcp must be an array of tables")
        _unknown(item, MCP_KEYS, path)
        if not all(isinstance(item.get(key), str) for key in ("name", "transport", "scope")):
            raise ManifestError(f"{path}: invalid mcp entry")
        transport = item["transport"]
        if transport not in {"stdio", "http"}:
            raise ManifestError(f"{path}: mcp.transport must be stdio or http")
        if transport == "stdio" and not isinstance(item.get("command"), str):
            raise ManifestError(f"{path}: stdio mcp entries require command")
        if transport == "http" and not isinstance(item.get("url"), str):
            raise ManifestError(f"{path}: http mcp entries require url")
        args = _strings(item.get("args", []), "mcp.args", path)
        env = item.get("env", {})
        if not isinstance(env, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in env.items()
        ):
            raise ManifestError(f"{path}: mcp.env must contain strings")
        servers.append(
            McpServer(
                item["name"],
                transport,
                item["scope"],
                item.get("command"),
                args,
                env,
                item.get("url"),
            )
        )

    return ModuleManifest(
        name,
        description,
        default,
        _strings(data.get("depends", []), "depends", path),
        _strings(data.get("requires", []), "requires", path),
        _strings(data.get("platforms", []), "platforms", path),
        data.get("claude_md_fragment"),
        data.get("settings_fragment"),
        tuple(questions),
        tuple(servers),
        _copies(data.get("files", []), "files", path),
        _templates(data.get("templates", []), path),
    )


def load_overlay_manifest(path: Path) -> OverlayManifest:
    data = _read(path)
    _unknown(data, OVERLAY_KEYS, path)
    if not isinstance(data.get("name"), str) or not isinstance(data.get("description"), str):
        raise ManifestError(f"{path}: name and description are required strings")
    return OverlayManifest(
        data["name"],
        data["description"],
        data.get("requires_agent_kit"),
        data.get("claude_md_fragment"),
        data.get("settings_fragment"),
        _copies(data.get("files", []), "files", path),
        _templates(data.get("templates", []), path),
    )


def validate_dependencies(manifests: dict[str, ModuleManifest], enabled: dict[str, bool]) -> None:
    for name, manifest in manifests.items():
        if not enabled.get(name, False):
            continue
        for dependency in manifest.depends:
            if dependency not in manifests:
                raise ManifestError(f"module {name} depends on unknown module {dependency}")
            if not enabled.get(dependency, False):
                raise ManifestError(f"module {name} requires enabled module {dependency}")
