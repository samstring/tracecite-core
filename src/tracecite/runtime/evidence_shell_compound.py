"""Agent-facing post-processing for compact aggregate results.

Canonical Evidence Shell aggregates remain the source of truth. This module
allows a single Agent tool call to keep mechanically sorting/trimming a compact
aggregate result Runtime-side instead of forcing another model round trip.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .evidence_shell_compat import normalize_evidence_shell_program


@dataclass(frozen=True)
class CompoundAggregate:
    base_program: str
    normalized_program: str
    command: str
    post_stages: tuple[tuple[str, tuple[str, ...]], ...]


def _stages(program: str) -> list[tuple[str, tuple[str, ...]]]:
    lexer = shlex.shlex(program, posix=True, punctuation_chars="|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    groups: list[list[str]] = [[]]
    for token in tokens:
        if token == "|":
            if not groups[-1]:
                raise ValueError("empty evidence shell stage")
            groups.append([])
        else:
            groups[-1].append(token)
    if not groups or not groups[-1]:
        raise ValueError("empty evidence shell stage")
    return [(group[0].lower(), tuple(group[1:])) for group in groups]


def split_compound_aggregate_program(program: str) -> CompoundAggregate | None:
    normalized = normalize_evidence_shell_program(program)
    stages = _stages(normalized)
    index = next((i for i, (command, _args) in enumerate(stages) if command in {"group", "distinct"}), None)
    if index is None or index == len(stages) - 1:
        return None
    command, aggregate_args = stages[index]
    if len(aggregate_args) != 1:
        return None
    trailing = stages[index + 1 :]
    if any(item[0] not in {"sort", "head", "take", "first"} for item in trailing):
        return None
    base = stages[: index + 1]
    base_program = " | ".join(shlex.join([name, *args]) for name, args in base)
    return CompoundAggregate(
        base_program=base_program,
        normalized_program=normalized,
        command=command,
        post_stages=tuple(trailing),
    )


def _sort_key(value: Any, *, numeric: bool) -> tuple[int, float | str]:
    if value is None:
        return (1, 0.0 if numeric else "")
    if numeric:
        try:
            return (0, float(str(value).strip()))
        except ValueError:
            return (1, 0.0)
    return (0, str(value))


def _positive_limit(command: str, args: Sequence[str]) -> int:
    if len(args) != 1 or not args[0].isdigit() or int(args[0]) < 1:
        raise ValueError(f"{command} requires a positive N")
    return int(args[0])


def apply_compound_aggregate(payload: Mapping[str, Any], plan: CompoundAggregate) -> dict[str, Any]:
    result = dict(payload)
    if str(result.get("status") or "") != "ok":
        return result
    data_raw = result.get("data")
    if not isinstance(data_raw, Mapping):
        return result
    data = dict(data_raw)
    aggregate_raw = data.get("aggregate")
    if not isinstance(aggregate_raw, Mapping):
        return result
    aggregate = dict(aggregate_raw)

    if plan.command == "group":
        rows = [dict(item) for item in aggregate.get("groups") or [] if isinstance(item, Mapping)]
        for command, args in plan.post_stages:
            if command == "sort":
                if not args:
                    raise ValueError("post-group sort syntax is: sort count|key [asc|desc] [numeric]")
                field = args[0]
                direction = args[1].lower() if len(args) > 1 else "asc"
                numeric = len(args) > 2 and args[2].lower() == "numeric"
                if field not in {"count", "key"}:
                    raise ValueError("post-group sort field must be count or key")
                if direction not in {"asc", "desc"} or len(args) > 3:
                    raise ValueError("post-group sort syntax is: sort count|key [asc|desc] [numeric]")
                rows.sort(
                    key=lambda item: _sort_key(item.get(field), numeric=numeric),
                    reverse=direction == "desc",
                )
            else:
                rows = rows[: _positive_limit(command, args)]
        aggregate["groups"] = rows
        aggregate["groups_returned"] = len(rows)
    else:
        values = list(aggregate.get("values") or [])
        for command, args in plan.post_stages:
            if command == "sort":
                if not args:
                    field, direction, numeric = "value", "asc", False
                else:
                    field = args[0]
                    direction = args[1].lower() if len(args) > 1 else "asc"
                    numeric = len(args) > 2 and args[2].lower() == "numeric"
                if field not in {"value", "text"}:
                    raise ValueError("post-distinct sort field must be value")
                if direction not in {"asc", "desc"} or len(args) > 3:
                    raise ValueError("post-distinct sort syntax is: sort value [asc|desc] [numeric]")
                values.sort(key=lambda item: _sort_key(item, numeric=numeric), reverse=direction == "desc")
            else:
                values = values[: _positive_limit(command, args)]
        aggregate["values"] = values
        aggregate["values_returned"] = len(values)

    data["aggregate"] = aggregate
    data["program"] = plan.normalized_program
    data["compound_postprocess"] = True
    result["data"] = data
    return result


__all__ = ["CompoundAggregate", "apply_compound_aggregate", "split_compound_aggregate_program"]
