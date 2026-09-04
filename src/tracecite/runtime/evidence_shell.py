"""Budget-gated Agent evidence shell.

The shell is a mechanical query surface.  The Agent chooses how to search, but
TraceCite owns source/evidence integrity and the transport boundary.  A search
that would expose more complete logical-record text than the host/user policy
allows returns ``too_broad`` and no record bodies/pointers; the Agent must
refine the query instead of increasing the budget.

This first implementation intentionally reuses the proven ``search_text``
engine for the first search stage so all current search scoping/segmenter
semantics remain available.  Later hot-path work can replace its legacy
artifacts without changing this public shell contract.
"""

from __future__ import annotations

import hashlib
import json
import operator
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from tracecite_core.records import estimate_tokens
from tracecite_core.segmenter import build_segmenter, detect_segmenter_kind
from tracecite_core.state_file import state_lock

from .evidence_identity import file_source_version
from .retrieval_session import RetrievalOperation, RetrievalSessionStore
from .schema import AgentResult, EvidencePointer
from .search_engine import search_text


DEFAULT_MAX_EVIDENCE_TOKENS = 12_000
DEFAULT_MAX_EVIDENCE_BYTES = 64 * 1024


@dataclass(frozen=True)
class EvidenceShellPolicy:
    """Host/user-owned evidence transport policy.

    This object is deliberately not part of the Agent tool request.  Hosts may
    construct it from user settings, environment/configuration, or product
    policy.  The Agent can refine its query but cannot override these limits.
    """

    max_evidence_tokens: int = DEFAULT_MAX_EVIDENCE_TOKENS
    max_evidence_bytes: int = DEFAULT_MAX_EVIDENCE_BYTES

    def __post_init__(self) -> None:
        for name in ("max_evidence_tokens", "max_evidence_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


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

    @property
    def start_line(self) -> int:
        value = self.metadata.get("start_line")
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0

    @property
    def end_line(self) -> int:
        value = self.metadata.get("end_line")
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else self.start_line


_COMPARE: dict[str, Callable[[Any, Any], bool]] = {
    "=": operator.eq,
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    return [_Stage(group[0].lower(), tuple(group[1:])) for group in groups]


def _first_search(stages: Sequence[_Stage]) -> tuple[str, bool, tuple[_Stage, ...]]:
    first = stages[0]
    command = first.command
    args = list(first.args)
    if command in {"search", "grep"}:
        regex = False
        if command == "grep" and args and args[0] in {"-e", "--extended-regexp", "-E"}:
            regex = True
            args = args[1:]
        if not args:
            raise ValueError(f"{command} requires a pattern")
        return " ".join(args), regex, tuple(stages[1:])
    if command == "regex":
        if not args:
            raise ValueError("regex requires a pattern")
        return " ".join(args), True, tuple(stages[1:])
    raise ValueError("evidence shell must start with search, grep, or regex")


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
    if key in {"line", "start_line"}:
        return row.start_line
    if key == "end_line":
        return row.end_line
    if key == "timestamp":
        return row.metadata.get("timestamp")
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


def _apply_predicate(row: _RecordRow, stage: _Stage) -> bool:
    command = stage.command
    args = stage.args
    if command in {"search", "grep"}:
        invert = False
        regex = False
        values = list(args)
        while values and values[0] in {"-v", "--invert-match", "-E", "-e", "--extended-regexp"}:
            flag = values.pop(0)
            if flag in {"-v", "--invert-match"}:
                invert = True
            else:
                regex = True
        if not values:
            raise ValueError(f"{command} requires a pattern")
        pattern = " ".join(values)
        matched = bool(re.search(pattern, row.text)) if regex else pattern in row.text
        return not matched if invert else matched
    if command == "regex":
        if not args:
            raise ValueError("regex requires a pattern")
        return bool(re.search(" ".join(args), row.text))
    if command in {"exclude", "exclude-regex"}:
        if not args:
            raise ValueError(f"{command} requires a pattern")
        pattern = " ".join(args)
        matched = bool(re.search(pattern, row.text)) if command == "exclude-regex" else pattern in row.text
        return not matched
    if command == "where":
        if len(args) < 3:
            raise ValueError("where syntax is: where FIELD OP VALUE")
        field, op = args[0], args[1]
        if op not in _COMPARE:
            raise ValueError(f"unsupported where operator: {op}")
        expected = _coerce(" ".join(args[2:]))
        actual = _field_value(row, field)
        if actual is None and expected is not None:
            return False
        try:
            return bool(_COMPARE[op](actual, expected))
        except TypeError:
            return bool(_COMPARE[op](str(actual), str(expected)))
    raise ValueError(f"unsupported evidence shell predicate: {command}")


def _load_records(path: Path) -> Iterable[_RecordRow]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, Mapping):
                continue
            metadata = payload.get("metadata") or {}
            if not isinstance(metadata, Mapping):
                metadata = {}
            yield _RecordRow(str(payload.get("text") or ""), dict(metadata))


def _filter_rows(rows: Iterable[_RecordRow], stages: Sequence[_Stage]) -> Iterable[_RecordRow]:
    for row in rows:
        keep = True
        for stage in stages:
            if stage.command in {"count", "group", "distinct", "first", "last", "take", "emit"}:
                continue
            if not _apply_predicate(row, stage):
                keep = False
                break
        if keep:
            yield row


def _terminal(stages: Sequence[_Stage]) -> _Stage | None:
    terminals = [
        stage
        for stage in stages
        if stage.command in {"count", "group", "distinct", "first", "last", "take"}
    ]
    if len(terminals) > 1:
        raise ValueError("evidence shell currently supports one terminal selection/aggregate stage")
    return terminals[0] if terminals else None


def _aggregate(rows: Iterable[_RecordRow], stage: _Stage) -> dict[str, Any]:
    if stage.command == "count":
        return {"count": sum(1 for _ in rows)}
    if not stage.args:
        raise ValueError(f"{stage.command} requires a field")
    field = stage.args[0]
    counts: dict[str, int] = {}
    for row in rows:
        value = _field_value(row, field)
        key = "<missing>" if value is None else str(value)
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if stage.command == "group":
        return {"field": field, "groups": [{"key": key, "count": count} for key, count in ordered]}
    return {"field": field, "values": [key for key, _ in ordered], "distinct_total": len(ordered)}


def _select_rows(rows: Iterable[_RecordRow], stage: _Stage) -> list[_RecordRow]:
    if not stage.args:
        raise ValueError(f"{stage.command} requires N")
    n = int(stage.args[0])
    if n < 1:
        raise ValueError(f"{stage.command} N must be positive")
    if stage.command in {"take", "first"}:
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


def _budgeted_rows(
    rows: Iterable[_RecordRow],
    policy: EvidenceShellPolicy,
) -> tuple[list[_RecordRow], int, int, bool]:
    selected: list[_RecordRow] = []
    tokens = 0
    bytes_used = 0
    for row in rows:
        row_tokens = estimate_tokens(row.text)
        row_bytes = len(row.text.encode("utf-8", errors="replace"))
        tokens += row_tokens
        bytes_used += row_bytes
        if tokens > policy.max_evidence_tokens or bytes_used > policy.max_evidence_bytes:
            return [], tokens, bytes_used, True
        selected.append(row)
    return selected, tokens, bytes_used, False


def _request_fingerprint(source_version: str, program: str) -> str:
    return hashlib.sha256(f"evidence-shell\0{source_version}\0{program}".encode("utf-8")).hexdigest()


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
        next_state, _ = state.advance(
            evidence=ids,
            operation=RetrievalOperation(
                operation="evidence_shell",
                status=str(payload.get("status") or "ok"),
                request_fingerprint=_request_fingerprint(source_version, program),
                new_evidence=len(new_rows),
                repeated_evidence=repeated,
                source_version=source_version,
            ),
        )
        session.save(next_state)
    payload = dict(payload)
    payload["evidence"] = new_rows
    coverage = dict(payload.get("coverage") or {})
    coverage["new_evidence"] = len(new_rows)
    coverage["repeated_evidence"] = repeated
    payload["coverage"] = coverage
    data = dict(payload.get("data") or {})
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
    payload["data"] = data
    if rows and not new_rows:
        payload["status"] = "no_new_evidence"
    return payload


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

    source = Path(request.source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    stages = _tokenize_program(request.program)
    query, regex, remaining = _first_search(stages)
    terminal = _terminal(remaining)
    kind = detect_segmenter_kind(source) if request.segmenter == "auto" else request.segmenter

    # The first release keeps the legacy engine behind the shell so current
    # regex/time/fold/segmenter semantics remain intact.  The Agent-facing
    # contract no longer exposes its artifacts; a later hot-path refactor can
    # stream Records directly without changing callers.
    run_dir = source.parent / ".tracecite" / "evidence-shell"
    run_dir.mkdir(parents=True, exist_ok=True)
    output_path = run_dir / f"shell-{hashlib.sha256(request.program.encode('utf-8')).hexdigest()[:16]}.log"
    result = search_text(
        source,
        pattern=query if regex else re.escape(query),
        regex=regex,
        output_path=output_path,
        snapshot=True,
        segmenter=build_segmenter(kind),
        last=request.last,
        since=request.since,
        until=request.until,
        fold=request.fold,
        max_line_chars=None,
    )
    records_path = result.records_path
    if records_path is None or not records_path.is_file():
        return AgentResult(
            operation="evidence_shell",
            status="no_match",
            outcome="not_assessed",
            coverage={"match_records": 0},
            data={"program": request.program, "segmenter": kind},
        ).to_dict()

    filtered = _filter_rows(_load_records(records_path), remaining)

    if terminal is not None and terminal.command in {"count", "group", "distinct"}:
        aggregate = _aggregate(filtered, terminal)
        return AgentResult(
            operation="evidence_shell",
            status="ok",
            outcome="not_assessed",
            coverage={"complete": True, "match_records": result.match_records},
            data={
                "program": request.program,
                "segmenter": kind,
                "aggregate": aggregate,
                "evidence_budget": {
                    "max_tokens": policy.max_evidence_tokens,
                    "max_bytes": policy.max_evidence_bytes,
                    "owner": "user_policy",
                },
            },
        ).to_dict()

    explicitly_selected = terminal is not None and terminal.command in {"first", "last", "take"}
    rows: Iterable[_RecordRow] = filtered
    if explicitly_selected and terminal is not None:
        rows = _select_rows(rows, terminal)
    selected, token_count, byte_count, exceeded = _budgeted_rows(rows, policy)
    if exceeded:
        return AgentResult(
            operation="evidence_shell",
            status="too_broad",
            outcome="unknown",
            evidence=[],
            warnings=[
                "Matched evidence exceeds the user-configured evidence budget. Refine the search; the Agent cannot increase this budget."
            ],
            coverage={
                "complete": False,
                "too_broad": True,
                "evidence_returned": 0,
                "observed_at_least_tokens": token_count,
                "observed_at_least_bytes": byte_count,
            },
            data={
                "program": request.program,
                "refine_query": True,
                "reason": "MATCHED_EVIDENCE_BUDGET_EXCEEDED",
                "evidence_budget": {
                    "max_tokens": policy.max_evidence_tokens,
                    "max_bytes": policy.max_evidence_bytes,
                    "owner": "user_policy",
                },
            },
        ).to_dict()

    evidence_source = Path(result.work_input).resolve()
    digest = _sha256(evidence_source)
    source_version = file_source_version(str(evidence_source), digest).key
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
                uri=f"evidence://sha256/{digest}{fragment}",
                source_path=str(evidence_source),
                sha256=digest,
                start_line=start,
                end_line=end,
                timestamp=str(row.metadata.get("timestamp") or "") or None,
                label=label or None,
                metadata={"shell_program": request.program},
            ).to_dict()
        )

    payload = AgentResult(
        operation="evidence_shell",
        status="ok" if evidence else "no_match",
        outcome="not_assessed",
        evidence=evidence,
        coverage={
            "complete": not explicitly_selected,
            "selection_explicit": explicitly_selected,
            "match_records": len(selected),
            "evidence_returned": len(evidence),
            "evidence_tokens": token_count,
            "evidence_bytes": byte_count,
            "too_broad": False,
        },
        data={
            "program": request.program,
            "segmenter": kind,
            "source_sha256": digest,
            "source_version": source_version,
            "evidence_budget": {
                "max_tokens": policy.max_evidence_tokens,
                "max_bytes": policy.max_evidence_bytes,
                "owner": "user_policy",
            },
        },
    ).to_dict()
    return _apply_session(
        payload,
        session=session,
        source_version=source_version,
        program=request.program,
    )


__all__ = [
    "DEFAULT_MAX_EVIDENCE_BYTES",
    "DEFAULT_MAX_EVIDENCE_TOKENS",
    "EvidenceShellPolicy",
    "EvidenceShellRequest",
    "run_evidence_shell",
]
