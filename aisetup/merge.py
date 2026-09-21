from __future__ import annotations

from copy import deepcopy
from typing import Any


def _append_unique(current: list[Any], incoming: list[Any]) -> list[Any]:
    result = deepcopy(current)
    for item in incoming:
        if item not in result:
            result.append(deepcopy(item))
    return result


def deep_merge(
    base: dict[str, Any], incoming: dict[str, Any], path: tuple[str, ...] = ()
) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in incoming.items():
        current_path = (*path, key)
        if key not in result:
            result[key] = deepcopy(value)
        elif isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value, current_path)
        elif isinstance(result[key], list) and isinstance(value, list):
            if len(current_path) == 2 and current_path[0] == "hooks":
                result[key] = deepcopy(result[key]) + deepcopy(value)
            elif current_path in {
                ("permissions", "allow"),
                ("permissions", "deny"),
                ("permissions", "ask"),
            }:
                result[key] = _append_unique(result[key], value)
            else:
                result[key] = deepcopy(value)
        else:
            result[key] = deepcopy(value)
    return result
