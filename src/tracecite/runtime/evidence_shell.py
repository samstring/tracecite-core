"""User-budgeted, artifact-free Evidence Shell for Agent retrieval.

The Agent supplies one mechanical search pipeline. TraceCite binds the request to
one immutable QuestionSourceView, executes every intermediate operation inside
Runtime, restores complete logical records through the selected Segmenter, and
admits Evidence only when the final record payload fits user/host policy.

No Agent request field can increase the Evidence budget.
"""

from __future__ import annotations

import hashlib
import json
import operator
import os
import shlex
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from tracecite_core.matcher import Matcher
from tracecite_core.record_search import iter_matching_records
from tracecite_core.records import Record, estimate_tokens
from tracecite_core.segmenter import build_segmenter, detect_segmenter_kind
from tracecite_core.state_file import state_lock
from tracecite_core.text_filter import parse_last_duration, record_timestamp, reference_datetime

from .retrieval_session import RetrievalOperation, RetrievalSessionStore
from .schema import AgentResult, EvidencePointer
from .source_versions import QuestionSourceView, SourceSegment, SourceVersionStore


DEFAULT_MAX_EVIDENCE_TOKENS = 12_000
DEFAULT_MAX_EVIDENCE_BYTES = 64 * 1024


@dataclass(frozen=True)
class EvidenceShellPolicy:
    """User/host-owned policy. None of these fields are Agent parameters."""

    max_evidence_tokens: int = DEFAULT_MAX_EVIDENCE_TOKENS
    max_evidence_bytes: int = DEFAULT_MAX_EVIDENCE_BYTES
    source_mode: str = field(
        default_factory=lambda: str(os.environ.get("TRACECITE_SOURCE_MODE") or "mutable")
    )
    live_cut_timeout_seconds: float = field(
        default_factory=lambda: max(
            0.0,
            float(os.environ.get("TRACECITE_LIVE_CUT_TIMEOUT_SECONDS") or "0.25"),
        )
    )

    def __post_init__(self) -> None:
        for name in ("max_evidence_tokens", "max_evidence_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        mode = str(self.source_mode or "").strip().lower()
        if mode not in {"auto", "static", "mutable", "live"}:
            raise ValueError("source_mode must be auto, static, mutable, or live")
        if self.live_cut_timeout_seconds < 0:
            raise ValueError("live_cut_timeout_seconds cannot be negative")
        object.__setattr__(self, "source_mode", mode)


@dataclass(frozen=True)
class EvidenceShellRequest:
    """One caller-selected mechanical evidence program."""

    source: str | Path
    program: str
    segmenter: str = "auto"
    last: str | None = None
    since: str | None = None
    until: str | None = None
    fold: bool = False

    def __post_init__(self) -> None:
        if not str(self.program or "").strip():
            raise ValueError("evidence shell program must be non-empty")


@dataclass(frozen=True)
class _Stage:
    command: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class _RecordRow:
    text: str
    metadata: Mapping[str, Any]
    source_path: str
    sha256: str
    line_base: int = 1

    @property
    def start_line(self) -> int:
        value = self.metadata.get("start_line")
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0

    @property
    def end_line(self) -> int:
        value = self.metadata.get("end_line")
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else self.start_line

    @property
    def global_start_line(self) -> int:
        return self.line_base + max(0, self.start_line - 1)

    @property
    def global_end_line(self) -> int:
        return self.line_base + max(0, self.end_line - 1)


_COMPARE: dict[str, Callable[[Any, Any], bool]] = {
    "=": operator.eq,
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}
_PREDICATES = frozenset(
    {
        "search",
        "grep",
        "regex",
        "exclude",
        "exclude-regex",
        "where",
        "exists",
        "missing",
        "lines",
    }
)
_SELECTIONS = frozenset({"take", "head", "first", "last", "tail", "near", "seek"})
_AGGREGATES = frozenset({"count", "group", "distinct", "uniq"})
_TRANSFORMS = frozenset({"sort", "reverse"})
_SUPPORTED = _PREDICATES | _SELECTIONS | _AGGREGATES | _TRANSFORMS | frozenset({"emit", "all"})


def _tokenize_program(program: str) -> list[_Stage]:
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

    stages = [_Stage(group[0].lower(), tuple(group[1:])) for group in groups]
    unknown = [item.command for item in stages if item.command not in _SUPPORTED]
    if unknown:
        raise ValueError(f"unsupported evidence shell command: {unknown[0]}")
    return stages


def _simple_first_search(
    stages: Sequence[_Stage],
) -> tuple[str | None, bool, tuple[_Stage, ...]]:
    """Push a safe first literal/regex into the Record scanner when possible."""
    first = stages[0]
    if first.command == "all":
        return None, False, tuple(stages[1:])
    if first.command == "search":
        if not first.args:
            raise ValueError("search requires a pattern")
        return " ".join(first.args), False, tuple(stages[1:])
    if first.command == "regex":
        if not first.args:
            raise ValueError("regex requires a pattern")
        return " ".join(first.args), True, tuple(stages[1:])
    if first.command == "grep":
        args = list(first.args)
        flags: set[str] = set()
        while args and args[0].startswith("-"):
            flags.add(args.pop(0))
        if not args:
            raise ValueError("grep requires a pattern")
        if flags & {"-i", "--ignore-case", "-v", "--invert-match"}:
            return None, False, tuple(stages)
        regex = bool(flags & {"-E", "-e", "--extended-regexp"})
        return " ".join(args), regex, tuple(stages[1:])
    return None, False, tuple(stages)


def _json_value(text: str, field: str) -> Any:
    try:
        value: Any = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    for part in field.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _field_value(row: _RecordRow, field: str) -> Any:
    key = str(field).strip()
    if key in {"line", "start_line", "global_line"}:
        return row.global_start_line
    if key == "end_line":
        return row.global_end_line
    if key == "local_start_line":
        return row.start_line
    if key == "local_end_line":
        return row.end_line
    if key == "timestamp":
        return row.metadata.get("timestamp")
    if key == "source":
        return row.source_path
    fields = row.metadata.get("fields")
    if isinstance(fields, Mapping) and key in fields:
        return fields[key]
    return _json_value(row.text, key)


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


def _safe_regex(pattern: str, text: str, *, ignore_case: bool = False) -> bool:
    if ignore_case:
        pattern = f"(?i:{pattern})"
    return Matcher(pattern).match(text)[0]


def _grep_match(row: _RecordRow, args: Sequence[str]) -> bool:
    values = list(args)
    invert = False
    regex = False
    ignore_case = False
    while values and values[0].startswith("-"):
        flag = values.pop(0)
        if flag in {"-v", "--invert-match"}:
            invert = True
        elif flag in {"-E", "-e", "--extended-regexp"}:
            regex = True
        elif flag in {"-F", "--fixed-strings"}:
            regex = False
        elif flag in {"-i", "--ignore-case"}:
            ignore_case = True
        else:
            raise ValueError(f"unsupported grep option: {flag}")
    if not values:
        raise ValueError("grep requires a pattern")
    pattern = " ".join(values)
    if regex:
        matched = _safe_regex(pattern, row.text, ignore_case=ignore_case)
    elif ignore_case:
        matched = pattern.casefold() in row.text.casefold()
    else:
        matched = pattern in row.text
    return not matched if invert else matched


def _predicate(row: _RecordRow, stage: _Stage) -> bool:
    command = stage.command
    args = list(stage.args)

    if command == "search":
        if not args:
            raise ValueError("search requires a pattern")
        return " ".join(args) in row.text
    if command == "grep":
        return _grep_match(row, args)
    if command == "regex":
        if not args:
            raise ValueError("regex requires a pattern")
        return _safe_regex(" ".join(args), row.text)
    if command in {"exclude", "exclude-regex"}:
        if not args:
            raise ValueError(f"{command} requires a pattern")
        pattern = " ".join(args)
        matched = (
            _safe_regex(pattern, row.text)
            if command == "exclude-regex"
            else pattern in row.text
        )
        return not matched
    if command == "exists":
        if len(args) != 1:
            raise ValueError("exists syntax is: exists FIELD")
        return _field_value(row, args[0]) is not None
    if command == "missing":
        if len(args) != 1:
            raise ValueError("missing syntax is: missing FIELD")
        return _field_value(row, args[0]) is None
    if command == "lines":
        if len(args) not in {1, 2}:
            raise ValueError("lines syntax is: lines START [END]")
        start = int(args[0])
        end = int(args[1]) if len(args) == 2 else start
        return row.global_end_line >= start and row.global_start_line <= end
    if command == "where":
        if len(args) < 2:
            raise ValueError("where syntax is: where FIELD OP VALUE")
        field, op = args[0], args[1].lower()
        actual = _field_value(row, field)
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
            expected_text = " ".join(args[2:])
            actual_text = "" if actual is None else str(actual)
            if op == "contains":
                return expected_text in actual_text
            if op == "startswith":
                return actual_text.startswith(expected_text)
            if op == "endswith":
                return actual_text.endswith(expected_text)
            return _safe_regex(expected_text, actual_text)
        raise ValueError(f"unsupported where operator: {op}")
    raise ValueError(f"unsupported evidence shell predicate: {command}")


def _filter(rows: Iterable[_RecordRow], stage: _Stage) -> Iterator[_RecordRow]:
    for row in rows:
        if _predicate(row, stage):
            yield row


def _sort_rows(rows: Iterable[_RecordRow], stage: _Stage) -> list[_RecordRow]:
    if not stage.args:
        raise ValueError("sort requires a field")
    field = stage.args[0]
    direction = stage.args[1].lower() if len(stage.args) > 1 else "asc"
    if direction not in {"asc", "desc"}:
        raise ValueError("sort direction must be asc or desc")

    def key(row: _RecordRow) -> tuple[int, str]:
        value = _field_value(row, field)
        return (1 if value is None else 0, "" if value is None else str(value))

    return sorted(rows, key=key, reverse=direction == "desc")


def _select(rows: Iterable[_RecordRow], stage: _Stage) -> list[_RecordRow]:
    command = stage.command
    if command in {"near", "seek"}:
        args = list(stage.args)
        center: int | None = None
        before = 3
        after = 3
        positional: list[str] = []
        for arg in args:
            if "=" in arg:
                key, raw = arg.split("=", 1)
                if key in {"line", "center"}:
                    center = int(raw)
                elif key == "before":
                    before = max(0, int(raw))
                elif key == "after":
                    after = max(0, int(raw))
                else:
                    raise ValueError(f"unsupported {command} option: {key}")
            else:
                positional.append(arg)
        if center is None and positional:
            center = int(positional.pop(0))
        if positional:
            before = max(0, int(positional.pop(0)))
        if positional:
            after = max(0, int(positional.pop(0)))
        if center is None or center < 1:
            raise ValueError(f"{command} requires a positive line")
        materialized = list(rows)
        if not materialized:
            return []
        index = min(
            range(len(materialized)),
            key=lambda i: abs(materialized[i].global_start_line - center),
        )
        return materialized[max(0, index - before) : index + after + 1]

    if not stage.args:
        raise ValueError(f"{command} requires N")
    n = int(stage.args[0])
    if n < 1:
        raise ValueError(f"{command} N must be positive")
    if command in {"take", "head", "first"}:
        selected: list[_RecordRow] = []
        for row in rows:
            selected.append(row)
            if len(selected) >= n:
                break
        return selected
    selected = []
    for row in rows:
        selected.append(row)
        if len(selected) > n:
            del selected[0]
    return selected


def _aggregate(rows: Iterable[_RecordRow], stage: _Stage) -> tuple[dict[str, Any], int]:
    if stage.command == "count":
        count = sum(1 for _ in rows)
        return {"count": count}, count

    if not stage.args:
        raise ValueError(f"{stage.command} requires a field")
    field = stage.args[0]
    counts: dict[str, int] = {}
    matched = 0
    for row in rows:
        matched += 1
        value = _field_value(row, field)
        key = "<missing>" if value is None else str(value)
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if stage.command == "group":
        return {
            "field": field,
            "groups": [{"key": key, "count": count} for key, count in ordered],
            "group_total": len(ordered),
        }, matched
    return {
        "field": field,
        "values": [key for key, _ in ordered],
        "distinct_total": len(ordered),
    }, matched


def _budgeted(
    rows: Iterable[_RecordRow], policy: EvidenceShellPolicy
) -> tuple[list[_RecordRow], int, int, bool]:
    selected: list[_RecordRow] = []
    tokens = 0
    bytes_used = 0
    for row in rows:
        row_tokens = max(1, estimate_tokens(row.text)) if row.text else 0
        tokens += row_tokens
        bytes_used += len(row.text.encode("utf-8", errors="replace"))
        if tokens > policy.max_evidence_tokens or bytes_used > policy.max_evidence_bytes:
            return [], tokens, bytes_used, True
        selected.append(row)
    return selected, tokens, bytes_used, False


def _payload_fits(value: Mapping[str, Any], policy: EvidenceShellPolicy) -> tuple[bool, int, int]:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    byte_count = len(text.encode("utf-8"))
    token_count = max(1, estimate_tokens(text)) if text else 0
    return (
        token_count <= policy.max_evidence_tokens
        and byte_count <= policy.max_evidence_bytes,
        token_count,
        byte_count,
    )


def _request_fingerprint(source_version: str, program: str) -> str:
    return hashlib.sha256(
        f"evidence-shell\0{source_version}\0{program}".encode("utf-8")
    ).hexdigest()


def _apply_session(
    payload: dict[str, Any],
    *,
    session: RetrievalSessionStore | None,
    source_version: str,
    program: str,
) -> dict[str, Any]:
    if session is None or payload.get("status") == "too_broad":
        return payload

    rows = [item for item in payload.get("evidence") or [] if isinstance(item, Mapping)]
    ids = tuple(str(item.get("uri") or "") for item in rows if str(item.get("uri") or ""))
    with state_lock(session.path):
        state = session.load()
        prior = set(state.seen_evidence)
        new_rows = [dict(item) for item in rows if str(item.get("uri") or "") not in prior]
        repeated = max(0, len(rows) - len(new_rows))
        operation_status = (
            "no_new_evidence" if rows and not new_rows else str(payload.get("status") or "ok")
        )
        next_state, _ = state.advance(
            evidence=ids,
            operation=RetrievalOperation(
                operation="evidence_shell",
                status=operation_status,
                request_fingerprint=_request_fingerprint(source_version, program),
                new_evidence=len(new_rows),
                repeated_evidence=repeated,
                source_version=source_version,
            ),
        )
        session.save(next_state)

    result = dict(payload)
    result["evidence"] = new_rows
    coverage = dict(result.get("coverage") or {})
    coverage["new_evidence"] = len(new_rows)
    coverage["repeated_evidence"] = repeated
    result["coverage"] = coverage

    data = dict(result.get("data") or {})
    if repeated:
        data["matched_existing_evidence"] = [
            {"uri": str(item.get("uri") or "")}
            for item in rows
            if str(item.get("uri") or "") in prior
        ]
    data["novelty"] = {
        "state": "new_evidence" if new_rows else ("no_new_evidence" if rows else "no_match"),
        "new_evidence": len(new_rows),
        "repeated_evidence": repeated,
        "source_version": source_version,
    }
    result["data"] = data
    return result


def _budget_data(policy: EvidenceShellPolicy) -> dict[str, Any]:
    return {
        "max_tokens": policy.max_evidence_tokens,
        "max_bytes": policy.max_evidence_bytes,
        "owner": "user_policy",
    }


def _too_broad(
    *,
    request: EvidenceShellRequest,
    policy: EvidenceShellPolicy,
    view: QuestionSourceView,
    reason: str,
    tokens: int,
    bytes_used: int,
) -> dict[str, Any]:
    return AgentResult(
        operation="evidence_shell",
        status="too_broad",
        outcome="unknown",
        evidence=[],
        warnings=[
            "Matched evidence exceeds the user-configured Evidence budget. "
            "Refine the search; the Agent cannot increase this budget."
        ],
        coverage={
            "complete": False,
            "too_broad": True,
            "evidence_returned": 0,
            "observed_at_least_tokens": tokens,
            "observed_at_least_bytes": bytes_used,
        },
        data={
            "program": request.program,
            "refine_query": True,
            "reason": reason,
            "source_view": view.to_dict(),
            "evidence_budget": _budget_data(policy),
        },
    ).to_dict()


def _row(record: Record, segment: SourceSegment) -> _RecordRow:
    timestamp = record.timestamp.isoformat(timespec="milliseconds") if record.timestamp else None
    return _RecordRow(
        text=record.text if record.text.endswith("\n") else record.text + "\n",
        metadata={
            "start_line": record.start_line,
            "end_line": record.end_line,
            "timestamp": timestamp,
            "fields": dict(record.fields),
        },
        source_path=segment.path,
        sha256=segment.sha256,
        line_base=segment.line_base,
    )


def _global_last_scope(
    view: QuestionSourceView,
    *,
    kind: Any,
    last: str | None,
    since: str | None,
    until: str | None,
) -> tuple[str | None, str | None, str | None]:
    if last is None or len(view.segments) <= 1:
        return last, since, until

    duration = parse_last_duration(last)
    final_ts: datetime | None = None
    for segment in reversed(view.segments):
        path = Path(segment.path)
        selected = build_segmenter(kind)
        ref = reference_datetime(path, segmenter=selected)
        for record in selected.segment_file(path):
            ts = record_timestamp(record, ref=ref, segmenter=selected)
            if ts is not None and (final_ts is None or ts > final_ts):
                final_ts = ts
        if final_ts is not None:
            break
    if final_ts is None:
        return last, since, until
    derived_since = (final_ts - duration).isoformat(timespec="milliseconds")
    derived_until = final_ts.isoformat(timespec="milliseconds")
    return None, since or derived_since, until or derived_until


def _initial_rows(
    view: QuestionSourceView,
    *,
    query: str | None,
    regex: bool,
    kind: Any,
    request: EvidenceShellRequest,
) -> Iterator[_RecordRow]:
    last, since, until = _global_last_scope(
        view,
        kind=kind,
        last=request.last,
        since=request.since,
        until=request.until,
    )
    for segment in view.segments:
        selected = build_segmenter(kind)
        for record in iter_matching_records(
            Path(segment.path),
            query=query,
            regex=regex,
            segmenter=selected,
            last=last,
            since=since,
            until=until,
        ):
            yield _row(record, segment)


def _execute_pipeline(
    rows: Iterable[_RecordRow],
    stages: Sequence[_Stage],
) -> tuple[Iterable[_RecordRow] | None, dict[str, Any] | None, int, bool]:
    current: Iterable[_RecordRow] = rows
    selected_subset = False
    for index, stage in enumerate(stages):
        if stage.command == "emit":
            continue
        if stage.command in _PREDICATES:
            current = _filter(current, stage)
            continue
        if stage.command == "sort":
            current = _sort_rows(current, stage)
            continue
        if stage.command == "reverse":
            current = list(reversed(list(current)))
            continue
        if stage.command in _SELECTIONS:
            current = _select(current, stage)
            selected_subset = True
            continue
        if stage.command in _AGGREGATES:
            trailing = [item for item in stages[index + 1 :] if item.command != "emit"]
            if trailing:
                raise ValueError("aggregate stages must be terminal except for emit")
            aggregate, matched = _aggregate(current, stage)
            return None, aggregate, matched, selected_subset
        if stage.command == "all":
            continue
        raise ValueError(f"unsupported evidence shell stage: {stage.command}")
    return current, None, 0, selected_subset


def run_evidence_shell(
    request: EvidenceShellRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None = None,
) -> dict[str, Any]:
    """Execute one safe evidence-search pipeline under a fixed user budget."""

    if not isinstance(request, EvidenceShellRequest):
        raise TypeError("run_evidence_shell requires EvidenceShellRequest")
    if not isinstance(policy, EvidenceShellPolicy):
        raise TypeError("policy must be EvidenceShellPolicy")
    if request.fold:
        raise ValueError(
            "fold is not part of artifact-free Evidence Shell; use group/distinct explicitly"
        )

    source = Path(request.source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    stages = _tokenize_program(request.program)
    query, regex, remaining = _simple_first_search(stages)
    kind = detect_segmenter_kind(source) if request.segmenter == "auto" else request.segmenter

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

    rows = _initial_rows(
        view,
        query=query,
        regex=regex,
        kind=kind,
        request=request,
    )
    final_rows, aggregate, matched, selected_subset = _execute_pipeline(rows, remaining)

    if aggregate is not None:
        aggregate_payload = {
            "aggregate": aggregate,
            "match_records": matched,
        }
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
                "program": request.program,
                "segmenter": str(kind),
                "aggregate": aggregate,
                "source_view": view.to_dict(),
                "source_version": view.key,
                "evidence_budget": _budget_data(policy),
            },
        ).to_dict()

    assert final_rows is not None
    selected, token_count, byte_count, exceeded = _budgeted(final_rows, policy)
    if exceeded:
        return _too_broad(
            request=request,
            policy=policy,
            view=view,
            reason="MATCHED_EVIDENCE_BUDGET_EXCEEDED",
            tokens=token_count,
            bytes_used=byte_count,
        )

    if not selected:
        payload = AgentResult(
            operation="evidence_shell",
            status="no_match",
            outcome="not_assessed",
            coverage={
                "complete": not selected_subset,
                "selection_explicit": selected_subset,
                "match_records": 0,
                "evidence_returned": 0,
                "evidence_tokens": 0,
                "evidence_bytes": 0,
                "too_broad": False,
            },
            data={
                "program": request.program,
                "segmenter": str(kind),
                "source_view": view.to_dict(),
                "source_version": view.key,
                "evidence_budget": _budget_data(policy),
            },
        ).to_dict()
        return _apply_session(
            payload,
            session=session,
            source_version=view.key,
            program=request.program,
        )

    evidence: list[dict[str, Any]] = []
    for row in selected:
        start = row.start_line or None
        end = row.end_line or start
        fragment = f"#L{start}" if start is not None else ""
        if start is not None and end is not None and end != start:
            fragment += f"-L{end}"
        label = next((line.strip() for line in row.text.splitlines() if line.strip()), "")[:240]
        evidence.append(
            EvidencePointer(
                uri=f"evidence://sha256/{row.sha256}{fragment}",
                source_path=row.source_path,
                sha256=row.sha256,
                start_line=start,
                end_line=end,
                timestamp=str(row.metadata.get("timestamp") or "") or None,
                label=label or None,
                metadata={
                    "shell_program": request.program,
                    "source_view": view.key,
                    "global_start_line": row.global_start_line,
                    "global_end_line": row.global_end_line,
                },
            ).to_dict()
        )

    payload = AgentResult(
        operation="evidence_shell",
        status="ok",
        outcome="not_assessed",
        evidence=evidence,
        coverage={
            "complete": not selected_subset,
            "selection_explicit": selected_subset,
            "match_records": len(selected),
            "evidence_returned": len(evidence),
            "evidence_tokens": token_count,
            "evidence_bytes": byte_count,
            "too_broad": False,
        },
        data={
            "program": request.program,
            "segmenter": str(kind),
            "source_view": view.to_dict(),
            "source_version": view.key,
            "evidence_budget": _budget_data(policy),
        },
    ).to_dict()
    return _apply_session(
        payload,
        session=session,
        source_version=view.key,
        program=request.program,
    )


__all__ = [
    "DEFAULT_MAX_EVIDENCE_BYTES",
    "DEFAULT_MAX_EVIDENCE_TOKENS",
    "EvidenceShellPolicy",
    "EvidenceShellRequest",
    "run_evidence_shell",
]
