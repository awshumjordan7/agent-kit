from __future__ import annotations

import json
import math
import re
from typing import Any

_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
_INT_MIN = -(2**63)
_INT_MAX = 2**63 - 1


class TomlWriteError(ValueError):
    pass


def dumps(data: dict[str, Any]) -> str:
    """Serialize plain TOML data: tables, scalars, and single-line arrays of scalars.

    Datetimes and arrays of tables are rejected rather than approximated.
    """
    if not isinstance(data, dict):
        raise TomlWriteError(f"top-level value must be a table, got {type(data).__name__}")
    blocks: list[list[str]] = []
    _collect_blocks((), data, blocks)
    return "\n".join("\n".join(block) + "\n" for block in blocks)


def _collect_blocks(
    path: tuple[str, ...], table: dict[str, Any], blocks: list[list[str]]
) -> None:
    own: list[str] = []
    subtables: list[tuple[str, dict[str, Any]]] = []
    for key, value in table.items():
        if isinstance(value, dict):
            subtables.append((key, value))
        else:
            own.append(f"{_format_key(key, path)} = {_format_value(value, path + (key,))}")

    if path and (own or not subtables):
        header = ".".join(_format_key(part, path) for part in path)
        blocks.append([f"[{header}]", *own])
    elif own:
        blocks.append(own)

    for key, value in subtables:
        _collect_blocks(path + (key,), value, blocks)


def _format_key(key: object, path: tuple[str, ...]) -> str:
    if not isinstance(key, str):
        raise TomlWriteError(f"{_where(path)}: key {key!r} is not a string")
    if _BARE_KEY.fullmatch(key):
        return key
    return _format_string(key, path)


def _format_value(value: object, path: tuple[str, ...]) -> str:
    # bool is a subclass of int, so it must be checked first.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if not _INT_MIN <= value <= _INT_MAX:
            raise TomlWriteError(f"{_where(path)}: integer {value} is outside the 64-bit range")
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, str):
        return _format_string(value, path)
    if isinstance(value, list):
        items = []
        for index, item in enumerate(value):
            if isinstance(item, dict):
                raise TomlWriteError(f"{_where(path)}: arrays of tables are not supported")
            items.append(_format_value(item, path + (f"[{index}]",)))
        return "[" + ", ".join(items) + "]"
    raise TomlWriteError(
        f"{_where(path)}: unsupported value type {type(value).__name__}"
    )


def _format_string(value: str, path: tuple[str, ...]) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise TomlWriteError(f"{_where(path)}: string is not valid UTF-8") from exc
    # ensure_ascii=True would emit surrogate pairs, which TOML rejects; JSON leaves DEL raw, which TOML forbids.
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _where(path: tuple[str, ...]) -> str:
    return ".".join(path) if path else "<root>"
