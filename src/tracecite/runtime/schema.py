"""Stable public schemas returned to Agent tool callers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


SCENARIO_SCHEMA_VERSION = 2
RESULT_SCHEMA_VERSION = 1
RESULT_STATUSES = frozenset({"ok", "no_match", "partial", "error"})
RESULT_OUTCOMES = frozenset({"supported", "contradicted", "unknown", "not_assessed"})
MAX_RESULT_EVIDENCE = 100


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ScenarioDocument:
    """Validated, versioned scenario document."""

    payload: Dict[str, Any]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ScenarioDocument":
        from .scenario import validate_scenario_spec

        return cls(validate_scenario_spec(dict(payload)))

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.payload)


@dataclass(frozen=True)
class EvidencePointer:
    """Line-addressable reference to immutable or hash-checked evidence."""

    uri: str
    source_path: str
    sha256: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    timestamp: Optional[str] = None
    label: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "uri": self.uri,
            "source_path": self.source_path,
        }
        for key in ("sha256", "start_line", "end_line", "timestamp", "label"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass
class AgentResult:
    """Canonical result envelope for every Agent-facing operation.

    ``status`` describes tool execution. ``outcome`` describes the epistemic
    result.  Keeping those axes separate prevents a successful command from
    being mistaken for a proven conclusion.
    """

    operation: str
    status: str = "ok"
    run_id: Optional[str] = None
    verdict: Optional[str] = None
    outcome: str = "not_assessed"
    hypotheses: List[Dict[str, Any]] = field(default_factory=list)
    confidence: Optional[float] = None
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    coverage: Dict[str, Any] = field(default_factory=dict)
    missing_evidence: List[Dict[str, Any]] = field(default_factory=list)
    verification: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    next_queries: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.status not in RESULT_STATUSES:
            raise ValueError(f"未知 Agent result status: {self.status!r}")
        if self.outcome not in RESULT_OUTCOMES:
            raise ValueError(f"未知 Agent result outcome: {self.outcome!r}")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence 必须在 0 到 1 之间")

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "operation": self.operation,
            "status": self.status,
            "outcome": self.outcome,
            "hypotheses": list(self.hypotheses),
            "evidence": list(self.evidence),
            "artifacts": list(self.artifacts),
            "coverage": dict(self.coverage),
            "missing_evidence": list(self.missing_evidence),
            "verification": dict(self.verification),
            "warnings": list(self.warnings),
            "next_queries": list(self.next_queries),
            "data": dict(self.data),
        }
        if self.run_id:
            payload["run_id"] = self.run_id
        if self.verdict:
            payload["verdict"] = self.verdict
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        if self.error:
            payload["error"] = dict(self.error)
        return payload

    @classmethod
    def from_scenario_summary(cls, summary: Mapping[str, Any]) -> "AgentResult":
        results = [row for row in summary.get("results", []) if isinstance(row, dict)]
        evidence: List[Dict[str, Any]] = []
        artifacts: List[Dict[str, Any]] = []
        warnings: List[str] = []
        digest_cache: Dict[str, str] = {}
        for row in results:
            if row.get("error"):
                warnings.append(f"{row.get('input')}: {row['error']}")
                continue
            for warning in row.get("coverage_warning") or []:
                if str(warning) not in warnings:
                    warnings.append(str(warning))
            for key, role in (
                ("output_path", "filtered_log"),
                ("records_path", "matched_records"),
                ("hits_path", "hit_metadata"),
                ("templates_path", "templates"),
                ("events_path", "events"),
            ):
                if row.get(key):
                    artifacts.append({"role": role, "path": str(row[key])})
            events_path = row.get("events_path")
            if events_path and len(evidence) < MAX_RESULT_EVIDENCE:
                try:
                    with Path(str(events_path)).open("r", encoding="utf-8") as handle:
                        for line in handle:
                            if len(evidence) >= MAX_RESULT_EVIDENCE:
                                break
                            event = json.loads(line)
                            raw_ref = event.get("raw_ref") or {}
                            source_path = str(raw_ref.get("source_path") or "")
                            if not source_path:
                                continue
                            digest = digest_cache.get(source_path)
                            if digest is None:
                                digest = _file_sha256(Path(source_path))
                                digest_cache[source_path] = digest
                            start_line = raw_ref.get("start_line")
                            end_line = raw_ref.get("end_line")
                            fragment = f"#L{start_line}" if start_line is not None else ""
                            if end_line is not None and end_line != start_line:
                                fragment += f"-L{end_line}"
                            evidence.append(
                                EvidencePointer(
                                    uri=f"evidence://sha256/{digest}{fragment}",
                                    source_path=source_path,
                                    sha256=digest,
                                    start_line=start_line,
                                    end_line=end_line,
                                    timestamp=event.get("timestamp"),
                                    label=str(event.get("label") or event.get("name") or "")[:240]
                                    or None,
                                    metadata={
                                        "event_id": event.get("event_id"),
                                        "category": event.get("category"),
                                        "name": event.get("name"),
                                        "matched_by": list(
                                            (event.get("attributes") or {}).get("matched_by")
                                            or []
                                        ),
                                    },
                                ).to_dict()
                            )
                except (OSError, ValueError, TypeError) as exc:
                    warnings.append(f"无法生成事件证据引用 {events_path}: {exc}")
        completeness = dict(summary.get("source_completeness") or {})
        if summary.get("verdict") == "error":
            status = "error"
        elif not completeness.get("accepted", True):
            status = "partial"
        elif int(summary.get("total_match_records") or 0) == 0:
            status = "no_match"
        else:
            status = "ok"
        assertions = dict(summary.get("assertions") or {})
        has_assertions = bool(assertions.get("assertions"))
        hypotheses = []
        for assertion in assertions.get("assertions") or []:
            if not isinstance(assertion, dict):
                continue
            details = assertion.get("details") or {}
            hypotheses.append(
                {
                    "id": assertion.get("name"),
                    "kind": assertion.get("kind"),
                    "required": bool(assertion.get("required", True)),
                    "outcome": (
                        "supported" if assertion.get("satisfied") else "contradicted"
                    ),
                    "evidence_ids": list(details.get("matched_event_ids") or []),
                }
            )
        if status in {"partial", "no_match", "error"}:
            outcome = "unknown"
        elif has_assertions and assertions.get("all_required_satisfied") is True:
            outcome = "supported"
        elif has_assertions and assertions.get("all_required_satisfied") is False:
            outcome = "contradicted"
        else:
            outcome = "not_assessed"
        missing_evidence: List[Dict[str, Any]] = []
        for warning in warnings:
            missing_evidence.append({"kind": "coverage_warning", "detail": warning})
        if not completeness.get("accepted", True):
            missing_evidence.append(
                {
                    "kind": "source_completeness",
                    "detail": "required source coverage was not accepted",
                    "context": completeness,
                }
            )
        return cls(
            operation="run",
            status=status,
            run_id=str(summary.get("run_id") or "") or None,
            verdict=str(summary.get("verdict") or "") or None,
            outcome=outcome,
            hypotheses=hypotheses,
            evidence=evidence,
            artifacts=artifacts,
            coverage={
                "match_records": int(summary.get("total_match_records") or 0),
                "source_completeness": completeness,
                "assertions": assertions,
                "evidence_total": int(summary.get("total_match_records") or 0),
                "evidence_returned": len(evidence),
                "evidence_truncated": int(summary.get("total_match_records") or 0)
                > len(evidence),
            },
            missing_evidence=missing_evidence,
            verification={
                "manifest_path": summary.get("manifest_path"),
                "integrity_checked": False,
            },
            warnings=warnings,
            data={
                "scenario": summary.get("scenario"),
                "manifest_path": summary.get("manifest_path"),
                "run_dir": summary.get("run_dir"),
                "filter": summary.get("filter"),
            },
        )
