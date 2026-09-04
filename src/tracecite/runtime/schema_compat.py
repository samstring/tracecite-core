"""Static registry and fixture checks for TraceCite persisted schemas.

This module is deliberately separate from the public schema implementations.
It records which persisted (and which explicitly non-persisted) contracts are
versioned, which legacy versions are supported, and where their golden
fixtures live.  The checker uses existing readers/validators; it does not
silently invent migrations for additive, unversioned artifact metadata.

The registry is intentionally data-first so a release review can inspect the
compatibility promise without relying on git history.
"""

from __future__ import annotations

import ast
import importlib
import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple


REGISTRY_SCHEMA_VERSION = 1
_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class SchemaSpec:
    """One persisted/ephemeral contract in the compatibility registry."""

    schema_id: str
    classification: str
    versioning: str
    current_version: Optional[int]
    source_path: Optional[str]
    source_symbol: Optional[str]
    reader: str
    legacy_versions: Tuple[int, ...] = ()
    migration_handler: str = ""
    fixtures: Tuple[Tuple[str, Optional[int]], ...] = ()
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["legacy_versions"] = list(self.legacy_versions)
        payload["fixtures"] = [
            {"path": path, "version": version} for path, version in self.fixtures
        ]
        return payload


def _fixture(name: str, version: Optional[int]) -> Tuple[str, Optional[int]]:
    return (f"tests/fixtures/schema_compat/{name}", version)


# Keep this list explicit and stable.  A source symbol is checked
# with AST rather than importing implementation modules, so the command can
# run before package installation and cannot execute extension code.
SCHEMA_REGISTRY: Tuple[SchemaSpec, ...] = (
    SchemaSpec(
        schema_id="tracecite.agent_result",
        classification="ephemeral_transport",
        versioning="versioned",
        current_version=1,
        source_path="src/tracecite/runtime/schema.py",
        source_symbol="RESULT_SCHEMA_VERSION",
        reader="agent_result",
        fixtures=(_fixture("agent-result-v1.json", 1),),
        notes="AgentResult is a bounded JSON envelope; it is not an on-disk store.",
    ),
    SchemaSpec(
        schema_id="tracecite.investigation_summary",
        classification="ephemeral_transport",
        versioning="versioned",
        current_version=1,
        source_path="src/tracecite/runtime/investigation_summary.py",
        source_symbol="SUMMARY_SCHEMA_VERSION",
        reader="investigation_summary",
        fixtures=(_fixture("investigation-summary-v1.json", 1),),
        notes="Investigation summaries are bounded advisory output, not state files.",
    ),
    SchemaSpec(
        schema_id="tracecite.investigation_timeline",
        classification="ephemeral_transport",
        versioning="versioned",
        current_version=1,
        source_path="src/tracecite/runtime/investigation_compare.py",
        source_symbol="TIMELINE_SCHEMA_VERSION",
        reader="investigation_timeline",
        fixtures=(_fixture("investigation-timeline-v1.json", 1),),
        notes="Investigation timelines expose bounded read-only structural events.",
    ),
    SchemaSpec(
        schema_id="tracecite.investigation_compare",
        classification="ephemeral_transport",
        versioning="versioned",
        current_version=1,
        source_path="src/tracecite/runtime/investigation_compare.py",
        source_symbol="COMPARE_SCHEMA_VERSION",
        reader="investigation_compare",
        fixtures=(_fixture("investigation-compare-v1.json", 1),),
        notes="Investigation comparisons expose bounded structural deltas, not findings.",
    ),
    SchemaSpec(
        schema_id="tracecite.scenario_document",
        classification="persisted_input",
        versioning="versioned",
        current_version=2,
        source_path="src/tracecite/runtime/schema.py",
        source_symbol="SCENARIO_SCHEMA_VERSION",
        reader="scenario_document",
        fixtures=(_fixture("scenario-document-v2.json", 2),),
        notes="Scenario JSON is a user/extension input and is validated before execution.",
    ),
    SchemaSpec(
        schema_id="tracecite.run_manifest",
        classification="persisted_artifact",
        versioning="versioned",
        current_version=2,
        source_path="src/tracecite_core/run.py",
        source_symbol="RUN_SCHEMA_VERSION",
        reader="run_manifest",
        fixtures=(_fixture("run-manifest-v2.json", 2),),
        notes="Manifest integrity is checked by tracecite_core.run.verify_manifest.",
    ),
    SchemaSpec(
        schema_id="tracecite.filter.records_artifact",
        classification="persisted_artifact",
        versioning="unversioned_additive",
        current_version=None,
        source_path="src/tracecite_core/text_filter.py",
        source_symbol=None,
        reader="filter_records_jsonl",
        fixtures=(_fixture("filter-records-unversioned.jsonl", None),),
        notes="JSONL rows have no schema ID; additive metadata is backward-readable and has no invented migration.",
    ),
    SchemaSpec(
        schema_id="tracecite.filter.hits_artifact",
        classification="persisted_artifact",
        versioning="unversioned_additive",
        current_version=None,
        source_path="src/tracecite_core/text_filter.py",
        source_symbol=None,
        reader="filter_hits_jsonl",
        fixtures=(_fixture("filter-hits-unversioned.jsonl", None),),
        notes="JSONL rows have no schema ID; additive metadata is backward-readable and has no invented migration.",
    ),
    SchemaSpec(
        schema_id="tracecite.investigation_state",
        classification="persisted_state",
        versioning="versioned",
        current_version=1,
        source_path="src/tracecite/runtime/investigation.py",
        source_symbol="INVESTIGATION_SCHEMA_VERSION",
        reader="investigation_state",
        fixtures=(_fixture("investigation-state-v1.json", 1),),
        notes="InvestigationState is the cross-tool state document.",
    ),
    SchemaSpec(
        schema_id="tracecite.investigation_budget_policy",
        classification="persisted_nested",
        versioning="versioned",
        current_version=2,
        source_path="src/tracecite/runtime/investigation.py",
        source_symbol="BUDGET_POLICY_SCHEMA_VERSION",
        reader="budget_policy",
        legacy_versions=(1,),
        migration_handler="tracecite.runtime.schema_compat:_migrate_budget_policy",
        fixtures=(
            _fixture("budget-policy-v1.json", 1),
            _fixture("budget-policy-v2.json", 2),
        ),
        notes="v2 exposes only max_rounds and max_input_per_round; v1 execution limits remain readable migration input.",
    ),
    SchemaSpec(
        schema_id="tracecite.investigation_cache",
        classification="persisted_sidecar",
        versioning="versioned",
        current_version=1,
        source_path="src/tracecite/runtime/investigation.py",
        source_symbol="CACHE_SCHEMA_VERSION",
        reader="cache",
        fixtures=(_fixture("investigation-cache-v1.json", 1),),
        notes="The cache is a bounded sidecar and is never evidence by itself.",
    ),
    SchemaSpec(
        schema_id="tracecite.knowledge_governance",
        classification="persisted_state",
        versioning="versioned",
        current_version=2,
        source_path="src/tracecite/knowledge/__init__.py",
        source_symbol="GOVERNANCE_SCHEMA_VERSION",
        reader="knowledge_governance",
        legacy_versions=(1,),
        migration_handler="tracecite.knowledge:KnowledgeGovernanceStore.migrate",
        fixtures=(
            _fixture("knowledge-governance-v1.json", 1),
            _fixture("knowledge-governance-v2.json", 2),
        ),
        notes="v1 is supported by the store's explicit migrate() reader; semantic promotion remains manual.",
    ),
)


READERS: Dict[str, Callable[[Path], Any]] = {}


def registry() -> Tuple[SchemaSpec, ...]:
    """Return the immutable compatibility registry."""

    return SCHEMA_REGISTRY


def registry_report() -> Dict[str, Any]:
    return {
        "registry_schema_version": REGISTRY_SCHEMA_VERSION,
        "schemas": [item.to_dict() for item in SCHEMA_REGISTRY],
    }


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON fixture: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"fixture top level must be an object: {path}")
    return payload


def _read_agent_result(path: Path) -> Any:
    from .schema import AgentResult

    payload = _load_json(path)
    payload.pop("schema_version", None)
    return AgentResult(**payload)


def _read_scenario_document(path: Path) -> Any:
    from .schema import ScenarioDocument

    return ScenarioDocument.from_dict(_load_json(path))


def _read_run_manifest(path: Path) -> Any:
    from tracecite_core.run import verify_manifest

    return verify_manifest(path)


def _read_filter_jsonl(path: Path) -> Any:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"filter artifact row must be an object: {path}")
        rows.append(payload)
    if not rows:
        raise ValueError(f"filter artifact fixture is empty: {path}")
    return rows


def _read_filter_records_jsonl(path: Path) -> Any:
    rows = _read_filter_jsonl(path)
    for row in rows:
        if not isinstance(row.get("text"), str):
            raise ValueError("filter records row requires text")
        metadata = row.get("metadata")
        if not isinstance(metadata, Mapping):
            raise ValueError("filter records row requires metadata")
        for key in ("start_line", "end_line"):
            value = metadata.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"filter records metadata.{key} must be a positive integer")
    return rows


def _read_filter_hits_jsonl(path: Path) -> Any:
    rows = _read_filter_jsonl(path)
    for row in rows:
        for key in ("start_line", "end_line", "term", "hit_lines"):
            if key not in row:
                raise ValueError(f"filter hits row requires {key}")
        for key in ("start_line", "end_line"):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"filter hits {key} must be a positive integer")
        if not isinstance(row.get("term"), str):
            raise ValueError("filter hits term must be text")
        hit_lines = row.get("hit_lines")
        if not isinstance(hit_lines, list) or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in hit_lines
        ):
            raise ValueError("filter hits hit_lines must be positive integer array")
    return rows


def _read_investigation_summary(path: Path) -> Any:
    payload = _load_json(path)
    if payload.get("schema_version") != 1:
        raise ValueError("investigation summary schema_version must be 1")
    if payload.get("advisory") is not True:
        raise ValueError("investigation summary must be advisory")
    if payload.get("status") not in {"ok", "error"}:
        raise ValueError("investigation summary status must be ok or error")
    if not isinstance(payload.get("valid"), bool):
        raise ValueError("investigation summary valid must be boolean")
    if not isinstance(payload.get("progress"), Mapping):
        raise ValueError("investigation summary progress must be an object")
    completeness = payload.get("advisory_completeness")
    if not isinstance(completeness, Mapping) or completeness.get("advisory_only") is not True:
        raise ValueError("investigation summary advisory_completeness is invalid")
    return payload


def _read_investigation_view(path: Path, *, kind: str) -> Any:
    payload = _load_json(path)
    if payload.get("schema_version") != 1:
        raise ValueError(f"investigation {kind} schema_version must be 1")
    if payload.get("kind") != kind:
        raise ValueError(f"investigation view kind must be {kind}")
    if payload.get("status") not in {"ok", "error"}:
        raise ValueError(f"investigation {kind} status must be ok or error")
    if not isinstance(payload.get("valid"), bool):
        raise ValueError(f"investigation {kind} valid must be boolean")
    if not isinstance(payload.get("omitted"), Mapping):
        raise ValueError(f"investigation {kind} omitted must be an object")
    if not isinstance(payload.get("truncated"), bool):
        raise ValueError(f"investigation {kind} truncated must be boolean")
    return payload


def _read_investigation_timeline(path: Path) -> Any:
    payload = _read_investigation_view(path, kind="timeline")
    if not isinstance(payload.get("events"), list):
        raise ValueError("investigation timeline events must be an array")
    return payload


def _read_investigation_compare(path: Path) -> Any:
    payload = _read_investigation_view(path, kind="compare")
    if not isinstance(payload.get("counts"), Mapping):
        raise ValueError("investigation compare counts must be an object")
    return payload


def _read_investigation_state(path: Path) -> Any:
    from .investigation import InvestigationState

    return InvestigationState.from_dict(_load_json(path))


def _read_budget_policy(path: Path) -> Any:
    from .investigation import BudgetPolicy

    return BudgetPolicy.from_mapping(_load_json(path))


def _read_cache(path: Path) -> Any:
    from .investigation import InvestigationCacheStore

    # _load is the existing bounded reader for the sidecar; this compatibility
    # registry does not add a second cache schema implementation.
    return InvestigationCacheStore(path)._load()  # noqa: SLF001


def _read_knowledge_governance(path: Path) -> Any:
    from tracecite.knowledge import KnowledgeGovernanceStore

    return KnowledgeGovernanceStore(path).list_candidates()


READERS.update(
    {
        "agent_result": _read_agent_result,
        "scenario_document": _read_scenario_document,
        "run_manifest": _read_run_manifest,
        "filter_jsonl": _read_filter_jsonl,
        "filter_records_jsonl": _read_filter_records_jsonl,
        "filter_hits_jsonl": _read_filter_hits_jsonl,
        "investigation_summary": _read_investigation_summary,
        "investigation_timeline": _read_investigation_timeline,
        "investigation_compare": _read_investigation_compare,
        "investigation_state": _read_investigation_state,
        "budget_policy": _read_budget_policy,
        "cache": _read_cache,
        "knowledge_governance": _read_knowledge_governance,
    }
)


def _migrate_budget_policy(path: Path) -> Dict[str, Any]:
    from .investigation import BudgetPolicy

    return BudgetPolicy.from_mapping(_load_json(path)).to_dict()


def _migrate_knowledge_governance(path: Path) -> Dict[str, Any]:
    from tracecite.knowledge import KnowledgeGovernanceStore

    return KnowledgeGovernanceStore(path).migrate()


MIGRATORS: Dict[str, Callable[[Path], Mapping[str, Any]]] = {
    "tracecite.investigation_budget_policy": _migrate_budget_policy,
    "tracecite.knowledge_governance": _migrate_knowledge_governance,
}


def _source_constant(root: Path, spec: SchemaSpec) -> Tuple[Optional[Any], Optional[str]]:
    if not spec.source_path:
        return None, None
    path = root / spec.source_path
    try:
        path = path.resolve()
        path.relative_to(root.resolve())
    except (OSError, ValueError):
        return None, f"source path escapes repository root: {spec.source_path}"
    if not path.is_file():
        return None, f"source file missing: {spec.source_path}"
    if not spec.source_symbol:
        return None, None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        return None, f"source parse failed: {spec.source_path}: {exc}"
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == spec.source_symbol for target in node.targets):
            continue
        try:
            return ast.literal_eval(node.value), None
        except (ValueError, TypeError):
            return None, f"source symbol is not a literal: {spec.source_symbol}"
    return None, f"source symbol missing: {spec.source_symbol}"


def _fixture_version(path: Path) -> Optional[int]:
    if path.suffix.lower() == ".jsonl":
        return None
    payload = _load_json(path)
    value = payload.get("schema_version")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _resolve_handler(handler: str) -> Optional[Any]:
    if not handler or ":" not in handler:
        return None
    module_name, attribute_path = handler.split(":", 1)
    try:
        value = importlib.import_module(module_name)
    except Exception:
        return None
    for name in attribute_path.split("."):
        value = getattr(value, name, None)
        if value is None:
            return None
    return value


def _check_fixture(root: Path, spec: SchemaSpec, relative_path: str, expected_version: Optional[int]) -> List[str]:
    findings: List[str] = []
    path = root / relative_path
    if not path.is_file():
        return [f"{spec.schema_id}: fixture missing: {relative_path}"]
    actual_version = _fixture_version(path)
    if actual_version != expected_version:
        findings.append(
            f"{spec.schema_id}: fixture version {actual_version!r} != declared {expected_version!r}: {relative_path}"
        )
    reader = READERS.get(spec.reader)
    if reader is None:
        findings.append(f"{spec.schema_id}: reader is not registered: {spec.reader}")
        return findings
    try:
        reader(path)
    except Exception as exc:
        findings.append(f"{spec.schema_id}: fixture reader failed for {relative_path}: {exc}")
    return findings


def _check_migration_fixture(root: Path, spec: SchemaSpec, relative_path: str, expected_version: int) -> List[str]:
    findings = _check_fixture(root, spec, relative_path, expected_version)
    if findings:
        return findings
    migrator = MIGRATORS.get(spec.schema_id)
    if migrator is None:
        return [f"{spec.schema_id}: migration runner is missing for legacy v{expected_version}"]
    with tempfile.TemporaryDirectory(prefix="tracecite-schema-migration-") as directory:
        temporary = Path(directory) / Path(relative_path).name
        shutil.copy2(root / relative_path, temporary)
        try:
            migrated = dict(migrator(temporary))
        except Exception as exc:
            return [f"{spec.schema_id}: migration failed for legacy v{expected_version}: {exc}"]
    if migrated.get("schema_version") != spec.current_version:
        findings.append(
            f"{spec.schema_id}: legacy v{expected_version} migrated to {migrated.get('schema_version')!r}, expected {spec.current_version!r}"
        )
    return findings


def check_registry(
    root: Path | str,
    *,
    specs: Optional[Sequence[SchemaSpec]] = None,
) -> List[str]:
    """Return deterministic findings for registry/source/fixture drift."""

    root_path = Path(root).resolve()
    entries = tuple(specs or SCHEMA_REGISTRY)
    findings: List[str] = []
    seen: set[str] = set()
    for spec in entries:
        if spec.schema_id in seen:
            findings.append(f"duplicate schema id: {spec.schema_id}")
        seen.add(spec.schema_id)
        if spec.classification not in {
            "ephemeral_transport",
            "persisted_input",
            "persisted_artifact",
            "persisted_state",
            "persisted_nested",
            "persisted_sidecar",
        }:
            findings.append(f"{spec.schema_id}: unknown classification {spec.classification!r}")
        if spec.versioning not in {"versioned", "unversioned_additive"}:
            findings.append(f"{spec.schema_id}: unknown versioning mode {spec.versioning!r}")
        if spec.versioning == "versioned" and spec.current_version is None:
            findings.append(f"{spec.schema_id}: versioned schema has no current version")
        if spec.versioning == "versioned" and (
            not spec.source_path or not spec.source_symbol
        ):
            findings.append(f"{spec.schema_id}: versioned schema needs a source path and symbol")
        if spec.versioning == "versioned" and (
            isinstance(spec.current_version, bool)
            or not isinstance(spec.current_version, int)
            or (spec.current_version is not None and spec.current_version <= 0)
        ):
            findings.append(f"{spec.schema_id}: current version must be a positive integer")
        if len(set(spec.legacy_versions)) != len(spec.legacy_versions):
            findings.append(f"{spec.schema_id}: legacy versions contain duplicates")
        if set(spec.legacy_versions) & {spec.current_version}:
            findings.append(f"{spec.schema_id}: current version is also declared legacy")
        if any(
            isinstance(version, bool) or not isinstance(version, int) or version <= 0
            for version in spec.legacy_versions
        ):
            findings.append(f"{spec.schema_id}: legacy versions must be positive integers")
        if spec.versioning == "unversioned_additive":
            if spec.current_version is not None or spec.legacy_versions or spec.migration_handler:
                findings.append(f"{spec.schema_id}: unversioned additive schema cannot declare versions/migration")
        source_value, source_error = _source_constant(root_path, spec)
        if source_error:
            findings.append(f"{spec.schema_id}: {source_error}")
        elif spec.versioning == "versioned" and source_value != spec.current_version:
            findings.append(
                f"{spec.schema_id}: registry version {spec.current_version!r} != source {source_value!r}"
            )
        if spec.legacy_versions:
            if not spec.migration_handler:
                findings.append(f"{spec.schema_id}: legacy versions require migration_handler")
            elif not callable(_resolve_handler(spec.migration_handler)):
                findings.append(f"{spec.schema_id}: migration handler cannot be resolved: {spec.migration_handler}")
            if spec.schema_id not in MIGRATORS or not callable(MIGRATORS.get(spec.schema_id)):
                findings.append(f"{spec.schema_id}: migration runner is not registered")
        elif spec.migration_handler:
            findings.append(f"{spec.schema_id}: migration_handler declared without legacy versions")
        declared_versions = [version for _path, version in spec.fixtures]
        if len(declared_versions) != len(set(declared_versions)):
            findings.append(f"{spec.schema_id}: fixture versions contain duplicates")
        if spec.versioning == "versioned":
            if spec.current_version not in declared_versions:
                findings.append(f"{spec.schema_id}: current version fixture is missing")
            for version in spec.legacy_versions:
                if version not in declared_versions:
                    findings.append(f"{spec.schema_id}: legacy v{version} fixture is missing")
        for relative_path, expected_version in spec.fixtures:
            if expected_version in spec.legacy_versions:
                findings.extend(_check_migration_fixture(root_path, spec, relative_path, expected_version))
            else:
                findings.extend(_check_fixture(root_path, spec, relative_path, expected_version))
    return sorted(set(findings))


def compatibility_report(root: Path | str = _ROOT) -> Dict[str, Any]:
    findings = check_registry(root)
    return {
        "registry_schema_version": REGISTRY_SCHEMA_VERSION,
        "ok": not findings,
        "findings": findings,
        "schemas": [item.to_dict() for item in SCHEMA_REGISTRY],
    }


__all__ = [
    "MIGRATORS",
    "REGISTRY_SCHEMA_VERSION",
    "READERS",
    "SCHEMA_REGISTRY",
    "SchemaSpec",
    "check_registry",
    "compatibility_report",
    "registry",
    "registry_report",
]
