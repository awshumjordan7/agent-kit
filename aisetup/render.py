from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class RenderError(ValueError):
    pass


TOKEN_RE = re.compile(r"{{\s*(?:(json)\s+)?([A-Za-z0-9_.-]+)\s*}}")


def lookup(context: dict[str, Any], dotted_key: str) -> Any:
    value: Any = context
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(dotted_key)
        value = value[part]
    return value


def render_text(template: str, context: dict[str, Any], *, source: str | Path) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(2)
        try:
            value = lookup(context, key)
        except KeyError as error:
            raise RenderError(f"missing template key {key} in {source}") from error
        if match.group(1):
            return json.dumps(value, sort_keys=True)
        if isinstance(value, (dict, list)):
            raise RenderError(f"template key {key} in {source} requires the json formatter")
        if value is None:
            return ""
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)

    return TOKEN_RE.sub(replace, template)


def render_agent_frontmatter(text: str, settings: dict[str, Any]) -> str:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise RenderError("agent file has no frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise RenderError("agent file has unterminated frontmatter") from error

    fields: dict[str, int] = {}
    for index in range(1, end):
        match = re.match(r"([A-Za-z][A-Za-z0-9]*):", lines[index])
        if match:
            fields[match.group(1)] = index

    wanted = {
        "model": settings.get("model", ...),
        "maxTurns": settings.get("maxTurns", ...),
        "effort": settings.get("effort", ...),
    }
    remove: set[int] = set()
    additions: list[str] = []
    for key, value in wanted.items():
        if value is ...:
            continue
        if value is None:
            if key in fields:
                remove.add(fields[key])
            continue
        rendered = f"{key}: {value}"
        if key in fields:
            lines[fields[key]] = rendered
        else:
            additions.append(rendered)

    rendered_lines = [line for index, line in enumerate(lines) if index not in remove]
    new_end = rendered_lines.index("---", 1)
    rendered_lines[new_end:new_end] = additions
    return "\n".join(rendered_lines) + ("\n" if text.endswith("\n") else "")
