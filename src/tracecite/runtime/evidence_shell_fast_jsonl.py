"""Fast, semantics-preserving JSONL field aggregates for Evidence Shell.

The generic Record pipeline remains canonical for Evidence retrieval. This module
only accelerates aggregate-only JSONL programs that can be evaluated in one
streaming pass. It resolves the same immutable SessionSourceView and never emits
raw Evidence bodies, so Agent-visible Evidence budget/provenance rules stay
unchanged.
"""

from __future__ import annotations

from functools import lru_cache
import json
import operator
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tracecite_core.matcher import Matcher
from tracecite_core.segmenter import detect_segmenter_kind

from .evidence_shell import _budget_data, _payload_fits, _too_broad
from .evidence_shell_compat import normalize_evidence_shell_program
from .evidence_shell_public import EvidenceShellPolicy, EvidenceShellRequest
from .retrieval_session import RetrievalSessionStore
from .schema import AgentResult
from .source_versions import SourceVersionStore


@dataclass(frozen=True)
class _Stage:
    command: str
    args: tuple[str, ...]


_COMPARE: dict[str, Callable[[Any, Any], bool]] = {
    "=": operator.eq,
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}
_SPECIAL_FIELDS = {
    "timestamp",
    "source",
    "text",
    "line",
    "start_line",
    "end_line",
    "global_line",
    "local_start_line",
    "local_end_line",
    # JsonLineSegmenter exposes these as normalized aliases, not necessarily
    # direct JSON keys. Fall back to the canonical pipeline for them.
    "level",
    "msg",
}
_PREDICATES = {"search", "regex", "exclude", "exclude-regex", "where", "exists", "missing", "all"}
_AGGREGATES = {"count", "group", "distinct"}
_POST = {"sort", "head", "take", "first"}


@lru_cache(maxsize=256)
def _cached_matcher(pattern: str) -> Matcher:
    """Compile one safe Matcher per distinct runtime pattern, not per input row."""

    return Matcher(pattern)


def _tokenize(program: str) -> list[_Stage]:
    lexer = shlex.shlex(program, posix=True, punctuation_chars="|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    if not tokens:
        raise ValueError("empty evidence shell program")
    groups: list[list[str]] = [[]]
    for token in tokens:
        if token == "|":
            if not groups[-1]:
                raise ValueError("empty evidence shell stage")
            groups.append([])
        else:
            groups[-1].append(token)
    if not groups[-1]:
        raise ValueError("empty evidence shell stage")
    return [_Stage(group[0].lower(), tuple(group[1:])) for group in groups]


def _coerce(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _value(obj: Mapping[str, Any], field: str) -> Any:
    current: Any = obj
    for part in field.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _matches(obj: Mapping[str, Any], raw: str, stage: _Stage) -> bool:
    command = stage.command
    args = list(stage.args)
    if command == "all":
        return True
    if command in {"search", "exclude"}:
        if not args:
            raise ValueError(f"{command} requires a pattern")
        matched = " ".join(args) in raw
        return not matched if command == "exclude" else matched
    if command in {"regex", "exclude-regex"}:
        if not args:
            raise ValueError(f"{command} requires a pattern")
        matched = _cached_matcher(" ".join(args)).match(raw)[0]
        return not matched if command == "exclude-regex" else matched
    if command in {"exists", "missing"}:
        if len(args) != 1:
            raise ValueError(f"{command} syntax is: {command} FIELD")
        actual = _value(obj, args[0])
        return actual is not None if command == "exists" else actual is None
    if command == "where":
        if len(args) < 2:
            raise ValueError("where syntax is: where FIELD OP VALUE")
        field, op = args[0], args[1].lower()
        actual = _value(obj, field)
        if op in _COMPARE:
            if len(args) < 3:
                raise ValueError("where comparison requires a value")
            expected = _coerce(" ".join(args[2:]))
            if actual is None and expected is not None:
                return False
            try:
                return bool(_COMPARE[op](actual, expected))
            except TypeError:
                return bool(_COMPARE[op](str(actual), str(expected)))
        if op in {"contains", "startswith", "endswith", "matches"}:
            if len(args) < 3:
                raise ValueError(f"where {op} requires a value")
            expected = " ".join(args[2:])
            actual_text = "" if actual is None else str(actual)
            if op == "contains":
                return expected in actual_text
            if op == "startswith":
                return actual_text.startswith(expected)
            if op == "endswith":
                return actual_text.endswith(expected)
            return _cached_matcher(expected).match(actual_text)[0]
        raise ValueError(f"unsupported where operator: {op}")
    raise ValueError(f"unsupported fast JSONL predicate: {command}")


def _referenced_fields(stages: Sequence[_Stage]) -> set[str]:
    fields: set[str] = set()
    for stage in stages:
        if stage.command in {"where", "exists", "missing", "group", "distinct"} and stage.args:
            fields.add(stage.args[0])
    return fields


def _split(stages: Sequence[_Stage]) -> tuple[list[_Stage], _Stage, list[_Stage]] | None:
    aggregate_index = next((i for i, stage in enumerate(stages) if stage.command in _AGGREGATES), None)
    if aggregate_index is None:
        return None
    before = list(stages[:aggregate_index])
    aggregate = stages[aggregate_index]
    after = list(stages[aggregate_index + 1 :])
    if any(stage.command not in _PREDICATES for stage in before):
        return None
    if any(stage.command not in _POST for stage in after):
        return None
    # Count is scalar; post-processing it cannot add information.
    if aggregate.command == "count" and after:
        return None
    if aggregate.command in {"group", "distinct"} and len(aggregate.args) != 1:
        return None
    return before, aggregate, after


def _sort_key(value: Any, *, numeric: bool) -> tuple[int, float | str]:
    if value is None:
        return (1, 0.0 if numeric else "")
    if numeric:
        try:
            return (0, float(str(value).strip()))
        except ValueError:
            return (1, 0.0)
    return (0, str(value))


def _postprocess(aggregate: dict[str, Any], command: str, stages: Sequence[_Stage]) -> dict[str, Any]:
    result = dict(aggregate)
    if command == "group":
        rows = [dict(row) for row in result.get("groups") or []]
        for stage in stages:
            if stage.command == "sort":
                if not stage.args:
                    raise ValueError("post-group sort syntax is: sort count|key [asc|desc] [numeric]")
                field = stage.args[0]
                if field not in {"count", "key"}:
                    raise ValueError("post-group sort field must be count or key")
                direction = stage.args[1].lower() if len(stage.args) > 1 else "asc"
                numeric = len(stage.args) > 2 and stage.args[2].lower() == "numeric"
                if direction not in {"asc", "desc"} or len(stage.args) > 3:
                    raise ValueError("post-group sort syntax is: sort count|key [asc|desc] [numeric]")
                rows.sort(key=lambda row: _sort_key(row.get(field), numeric=numeric), reverse=direction == "desc")
            else:
                if len(stage.args) != 1 or not stage.args[0].isdigit() or int(stage.args[0]) < 1:
                    raise ValueError(f"{stage.command} requires a positive N")
                rows = rows[: int(stage.args[0])]
        result["groups"] = rows
        result["groups_returned"] = len(rows)
        return result

    values = list(result.get("values") or [])
    for stage in stages:
        if stage.command == "sort":
            if not stage.args:
                field = "value"
                direction = "asc"
                numeric = False
            else:
                field = stage.args[0]
                direction = stage.args[1].lower() if len(stage.args) > 1 else "asc"
                numeric = len(stage.args) > 2 and stage.args[2].lower() == "numeric"
            if field not in {"value", "text"}:
                raise ValueError("post-distinct sort field must be value")
            if direction not in {"asc", "desc"} or len(stage.args) > 3:
                raise ValueError("post-distinct sort syntax is: sort value [asc|desc] [numeric]")
            values.sort(key=lambda item: _sort_key(item, numeric=numeric), reverse=direction == "desc")
        else:
            if len(stage.args) != 1 or not stage.args[0].isdigit() or int(stage.args[0]) < 1:
                raise ValueError(f"{stage.command} requires a positive N")
            values = values[: int(stage.args[0])]
    result["values"] = values
    result["values_returned"] = len(values)
    return result


def try_run_fast_jsonl_aggregate(
    request: EvidenceShellRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None = None,
) -> dict[str, Any] | None:
    """Return a fast aggregate payload, or None when canonical fallback is required."""

    if request.fold or request.last is not None or request.since is not None or request.until is not None:
        return None
    source = Path(request.source).expanduser().resolve()
    if not source.is_file():
        return None
    kind = detect_segmenter_kind(source) if request.segmenter == "auto" else request.segmenter
    if not isinstance(kind, str) or kind.strip().lower() not in {"jsonline", "json", "jsonl"}:
        return None

    normalized = normalize_evidence_shell_program(request.program)
    stages = _tokenize(normalized)
    split = _split(stages)
    if split is None:
        return None
    predicates, aggregate_stage, post = split
    if _referenced_fields(stages) & _SPECIAL_FIELDS:
        return None

    version_store = (
        SourceVersionStore.for_session(session)
        if session is not None
        else SourceVersionStore(source.parent / ".tracecite")
    )
    view = version_store.resolve(
        source,
        mode=policy.source_mode,
        live_cut_timeout_seconds=policy.live_cut_timeout_seconds,
    )

    matched = 0
    counts: dict[str, int] = {}
    aggregate_field = aggregate_stage.args[0] if aggregate_stage.args else None
    raw_only = [
        stage
        for stage in predicates
        if stage.command in {"search", "regex", "exclude", "exclude-regex", "all"}
    ]
    field_predicates = [
        stage
        for stage in predicates
        if stage.command not in {"search", "regex", "exclude", "exclude-regex", "all"}
    ]
    for segment in view.segments:
        with Path(segment.path).open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                if not raw.strip():
                    continue
                # Do literal/regex predicates on raw text before JSON decoding when possible.
                if any(not _matches({}, raw, stage) for stage in raw_only):
                    continue
                try:
                    decoded = json.loads(raw)
                    obj = decoded if isinstance(decoded, Mapping) else {}
                except json.JSONDecodeError:
                    obj = {}
                if any(not _matches(obj, raw, stage) for stage in field_predicates):
                    continue
                matched += 1
                if aggregate_stage.command != "count":
                    value = _value(obj, str(aggregate_field))
                    key = "<missing>" if value is None else str(value)
                    counts[key] = counts.get(key, 0) + 1

    if aggregate_stage.command == "count":
        aggregate: dict[str, Any] = {"count": matched}
    else:
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if aggregate_stage.command == "group":
            aggregate = {
                "field": aggregate_field,
                "groups": [{"key": key, "count": count} for key, count in ordered],
                "group_total": len(ordered),
            }
        else:
            aggregate = {
                "field": aggregate_field,
                "values": [key for key, _ in ordered],
                "distinct_total": len(ordered),
            }
        aggregate = _postprocess(aggregate, aggregate_stage.command, post)
        aggregate_payload = {"aggregate": aggregate, "match_records": matched}
        fits, token_count, byte_count = _payload_fits(aggregate_payload, policy)
        if not fits:
            return _too_broad(
                request=request,
                policy=policy,
                view=view,
                reason="AGGREGATE_OUTPUT_BUDGET_EXCEEDED",
                tokens=token_count,
                bytes_used=byte_count,
            )

    return AgentResult(
        operation="evidence_shell",
        status="ok",
        outcome="not_assessed",
        coverage={"complete": True, "match_records": matched},
        data={
            "program": normalized,
            "segmenter": str(kind),
            "aggregate": aggregate,
            "source_view": view.to_dict(),
            "source_version": view.key,
            "evidence_budget": _budget_data(policy),
            "execution_engine": "jsonl_single_pass_field_aggregate",
        },
    ).to_dict()


__all__ = ["try_run_fast_jsonl_aggregate"]
