from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

KIND_KIT = "kit"
KIND_USER = "user"
KIND_CONFLICT = "conflict"

ELEMENT_LIST_PATHS = frozenset(
    {("permissions", "allow"), ("permissions", "deny"), ("permissions", "ask")}
)

_ABSENT = object()


@dataclass(frozen=True)
class SettingsChange:
    kind: str
    key_path: str
    detail: str | None = None


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


def _identity(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _same(left: Any, right: Any) -> bool:
    if left is _ABSENT or right is _ABSENT:
        return left is right
    return _identity(left) == _identity(right)


def _is_element_list(path: tuple[str, ...]) -> bool:
    return path in ELEMENT_LIST_PATHS or (len(path) == 2 and path[0] == "hooks")


def _count_detail(before: list[Any], after: list[Any]) -> str:
    old = Counter(_identity(item) for item in before)
    new = Counter(_identity(item) for item in after)
    added = sum((new - old).values())
    removed = sum((old - new).values())
    return f"+{added}/-{removed} entries"


def _merge_list(
    base: Any, ours: list[Any], theirs: list[Any], key_path: str, changes: list[SettingsChange]
) -> list[Any]:
    base_list = base if isinstance(base, list) else []
    base_ids = {_identity(item) for item in base_list}
    ours_ids = {_identity(item) for item in ours}
    theirs_ids = {_identity(item) for item in theirs}
    removed_by_user = base_ids - theirs_ids
    result = [deepcopy(item) for item in ours if _identity(item) not in removed_by_user]
    added: set[str] = set()
    for item in theirs:
        identity = _identity(item)
        if identity in base_ids or identity in ours_ids or identity in added:
            continue
        added.add(identity)
        result.append(deepcopy(item))
    if not _same(result, theirs):
        changes.append(SettingsChange(KIND_KIT, key_path, _count_detail(theirs, result)))
    if not _same(theirs, base_list):
        changes.append(SettingsChange(KIND_USER, key_path, _count_detail(base_list, theirs)))
    return result


def _merge_value(
    base: Any, ours: Any, theirs: Any, path: tuple[str, ...], changes: list[SettingsChange]
) -> Any:
    key_path = ".".join(path)
    if isinstance(ours, dict) and isinstance(theirs, dict):
        base_dict = base if isinstance(base, dict) else {}
        result: dict[str, Any] = {}
        for key in [*theirs, *(key for key in ours if key not in theirs)]:
            value = _merge_value(
                base_dict.get(key, _ABSENT),
                ours.get(key, _ABSENT),
                theirs.get(key, _ABSENT),
                (*path, key),
                changes,
            )
            if value is not _ABSENT:
                result[key] = value
        return result
    if _is_element_list(path) and isinstance(ours, list) and isinstance(theirs, list):
        return _merge_list(base, ours, theirs, key_path, changes)
    if _same(theirs, base):
        if not _same(ours, base):
            changes.append(SettingsChange(KIND_KIT, key_path))
        chosen = ours
    elif _same(ours, base):
        changes.append(SettingsChange(KIND_USER, key_path))
        chosen = theirs
    elif _same(ours, theirs):
        chosen = ours
    else:
        changes.append(SettingsChange(KIND_CONFLICT, key_path))
        chosen = theirs
    return chosen if chosen is _ABSENT else deepcopy(chosen)


def merge_settings(
    base: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any]
) -> tuple[dict[str, Any], list[SettingsChange]]:
    """Three-way merge of settings: base is the previous kit render, ours the new
    kit render, theirs the live file. The live value wins every conflict."""
    changes: list[SettingsChange] = []
    merged = _merge_value(base, ours, theirs, (), changes)
    return merged, changes
