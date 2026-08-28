from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import benchmarking as legacy


ROOT_CAUSE_SCHEMA_VERSION = 1
ROOT_CAUSE_DIMENSIONS = (
    "failure_localization",
    "immediate_failure_mechanism",
    "upstream_contributor",
    "fix_alignment",
)
_CITATION_PATTERNS = (
    re.compile(r"#L(?P<line>\d+)\b", re.IGNORECASE),
    re.compile(r"\bL(?P<line>\d+)\b", re.IGNORECASE),
    re.compile(r"\bline\s+(?P<line>\d+)\b", re.IGNORECASE),
    re.compile(r"\b[\w.\-/]+:(?P<line>\d+)\b"),
)
# ``cat -n`` and ``nl`` render line-addressable evidence as ``N<TAB>text``.
# This pattern is intentionally tool-output-only: applying it to the final
# answer would turn ordinary numbered lists into fabricated citations.
_TOOL_NUMBERED_LINE_PATTERN = re.compile(r"(?m)^\s*(?P<line>\d+)\t")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _iter_transcript(path: Path) -> Iterable[dict[str, Any]]:
    yield from legacy._iter_transcript(path)


def _patterns(value: Any, *, field: str) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        value = value.get("patterns")
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field}.patterns must be a non-empty list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field}.patterns must contain non-empty strings")
        re.compile(item)
        result.append(item)
    return tuple(result)


def validate_gold(gold: Mapping[str, Any]) -> None:
    if gold.get("root_cause_schema_version") != ROOT_CAUSE_SCHEMA_VERSION:
        raise ValueError(f"root_cause_schema_version must be {ROOT_CAUSE_SCHEMA_VERSION}")
    rubric = gold.get("root_cause")
    if not isinstance(rubric, Mapping):
        raise ValueError("root_cause must be an object")
    for dimension in ROOT_CAUSE_DIMENSIONS:
        _patterns(rubric.get(dimension), field=f"root_cause.{dimension}")

    for field in ("unsupported_claims", "contradictions"):
        values = gold.get(field, [])
        if not isinstance(values, list):
            raise ValueError(f"{field} must be a list")
        for index, item in enumerate(values):
            if isinstance(item, str):
                re.compile(item)
            elif isinstance(item, Mapping):
                _patterns(item, field=f"{field}[{index}]")
            else:
                raise ValueError(f"{field}[{index}] must be a string or object")


def validate_case(case_dir: Path) -> dict[str, Any]:
    base = legacy.validate_case(case_dir)
    _, _, gold_path = legacy._case_paths(case_dir)
    gold = _read_json(gold_path)
    validate_gold(gold)
    return {**base, "root_cause_schema_version": ROOT_CAUSE_SCHEMA_VERSION}


def prepare_case(case_dir: Path, work_dir: Path) -> dict[str, Any]:
    """Prepare either legacy URL inputs or committed local evidence snapshots.

    Local snapshots make the 30-case GitHub suite reproducible without spending
    GitHub API quota during every model run. They must contain reporter-visible
    runtime evidence only; maintainer diagnosis/fix truth stays in gold.json.
    """

    case_path = case_dir / "case.json"
    case = _read_json(case_path)
    local_inputs = case.get("local_inputs")
    if local_inputs is None:
        return legacy.prepare_case(case_dir, work_dir)
    validate_case(case_dir)
    if not isinstance(local_inputs, list) or not local_inputs:
        raise ValueError("local_inputs must be a non-empty list")

    case_root = work_dir / str(case["id"])
    input_root = case_root / "inputs"
    input_root.mkdir(parents=True, exist_ok=True)
    prepared: list[dict[str, Any]] = []
    for index, item in enumerate(local_inputs):
        if not isinstance(item, Mapping):
            raise ValueError(f"local_inputs[{index}] must be an object")
        rel = str(item.get("path") or "").strip()
        input_id = str(item.get("id") or "").strip()
        if not rel or not input_id:
            raise ValueError(f"local_inputs[{index}] requires id/path")
        source = (case_dir / rel).resolve()
        if case_dir.resolve() not in source.parents or not source.is_file():
            raise ValueError(f"local input must be a file below case directory: {rel}")
        target = input_root / source.name
        shutil.copyfile(source, target)
        raw = target.read_bytes()
        prepared.append(
            {
                "id": input_id,
                "path": str(target),
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "source_issue": case.get("source_issue"),
            }
        )

    manifest = {
        "schema_version": ROOT_CAUSE_SCHEMA_VERSION,
        "case_id": case["id"],
        "question": str((case_dir / str(case.get("question_file", "question.md"))).resolve()),
        "inputs": prepared,
    }
    manifest_path = case_root / "prepared.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "ok", "case_id": case["id"], "prepared": prepared, "manifest": str(manifest_path)}


def _hit(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) is not None for pattern in patterns)


def _dimension_results(answer: str, gold: Mapping[str, Any]) -> list[dict[str, Any]]:
    rubric = gold["root_cause"]
    results: list[dict[str, Any]] = []
    for dimension in ROOT_CAUSE_DIMENSIONS:
        pats = _patterns(rubric[dimension], field=f"root_cause.{dimension}")
        results.append({"id": dimension, "hit": _hit(answer, pats)})
    return results


def _negative_results(answer: str, gold: Mapping[str, Any], field: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, item in enumerate(gold.get(field, [])):
        if isinstance(item, str):
            item_id = f"{field}-{index + 1}"
            pats = (item,)
        else:
            item_id = str(item.get("id") or f"{field}-{index + 1}")
            pats = _patterns(item, field=f"{field}[{index}]")
        results.append({"id": item_id, "hit": _hit(answer, pats)})
    return results


def _line_refs(text: str) -> set[int]:
    result: set[int] = set()
    for pattern in _CITATION_PATTERNS:
        for match in pattern.finditer(text):
            try:
                line = int(match.group("line"))
            except (TypeError, ValueError):
                continue
            if line > 0:
                result.add(line)
    return result


def _tool_line_refs(text: str) -> set[int]:
    result = _line_refs(text)
    for match in _TOOL_NUMBERED_LINE_PATTERN.finditer(text):
        try:
            line = int(match.group("line"))
        except (TypeError, ValueError):
            continue
        if line > 0:
            result.add(line)
    return result


def _visible_line_refs(tool_outputs: Iterable[str]) -> set[int]:
    visible: set[int] = set()
    for output in tool_outputs:
        visible.update(_tool_line_refs(output))
    return visible


def _citation_quality(answer: str, tool_outputs: list[str]) -> dict[str, Any]:
    answer_refs = _line_refs(answer)
    visible_refs = _visible_line_refs(tool_outputs)
    valid = answer_refs & visible_refs
    invalid = answer_refs - visible_refs
    accuracy = len(valid) / len(answer_refs) if answer_refs else 0.0
    return {
        "citations": len(answer_refs),
        "valid_citations": len(valid),
        "invalid_citations": len(invalid),
        "accuracy": round(accuracy, 4),
        "cited_lines": sorted(answer_refs),
        "invalid_lines": sorted(invalid),
    }


def _answer_blocks(answer: str) -> list[str]:
    """Return paragraph-sized claim units without interpreting semantics."""

    return [
        block.strip()
        for block in re.split(r"\n\s*\n", answer)
        if block.strip()
    ]


def _dimension_evidence_support(
    answer: str,
    gold: Mapping[str, Any],
    tool_outputs: list[str],
) -> list[dict[str, Any]]:
    """Bind each root-cause rubric hit to valid evidence cited in that block.

    Global citation accuracy alone can be gamed accidentally: an answer may hit
    a correct root-cause regex in one paragraph and cite an unrelated visible
    line elsewhere.  This mechanical check requires the paragraph containing
    the dimension claim itself to carry at least one line reference that the
    model actually saw in tool output.
    """

    rubric = gold["root_cause"]
    visible = _visible_line_refs(tool_outputs)
    blocks = _answer_blocks(answer)
    results: list[dict[str, Any]] = []
    for dimension in ROOT_CAUSE_DIMENSIONS:
        pats = _patterns(rubric[dimension], field=f"root_cause.{dimension}")
        matching = [block for block in blocks if _hit(block, pats)]
        refs: set[int] = set()
        for block in matching:
            refs.update(_line_refs(block) & visible)
        results.append(
            {
                "id": dimension,
                "hit": bool(matching),
                "supported": bool(matching and refs),
                "valid_cited_lines": sorted(refs),
            }
        )
    return results


def _attempted_context(events: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = [event for event in events if event.get("type") == "request_context"]
    serialized = [event.get("serialized_chars") for event in attempts]
    serialized = [value for value in serialized if isinstance(value, int) and value >= 0]
    estimated = [event.get("estimated_tokens_chars_div_4") for event in attempts]
    estimated = [value for value in estimated if isinstance(value, int) and value >= 0]
    return {
        "attempted_context_requests": len(attempts),
        "cumulative_attempted_context_chars": sum(serialized),
        "peak_attempted_context_chars": max(serialized, default=0),
        "estimated_attempted_context_tokens_chars_div_4": sum(estimated),
    }


def score_transcript(case_dir: Path, transcript_path: Path) -> dict[str, Any]:
    validate_case(case_dir)
    case, _, gold_path = legacy._case_paths(case_dir)
    gold = _read_json(gold_path)
    events = list(_iter_transcript(transcript_path))
    tool_events = [event for event in events if event.get("type") == "tool"]
    model_events = [event for event in events if event.get("type") == "model"]
    final_events = [event for event in events if event.get("type") == "final"]
    final = final_events[-1] if final_events else {}
    answer = str(final.get("answer") or "")

    tool_outputs: list[str] = []
    durations: list[float] = []
    for event in tool_events:
        output = event.get("output", "")
        if not isinstance(output, str):
            output = json.dumps(output, ensure_ascii=False, sort_keys=True)
        tool_outputs.append(output)
        duration = event.get("duration_ms")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
            durations.append(float(duration))

    output_chars = sum(len(item) for item in tool_outputs)
    unique_hashes: set[str] = set()
    unique_chars = 0
    duplicate_chars = 0
    for output in tool_outputs:
        digest = hashlib.sha256(output.encode("utf-8")).hexdigest()
        if digest in unique_hashes:
            duplicate_chars += len(output)
        else:
            unique_hashes.add(digest)
            unique_chars += len(output)

    dimensions = _dimension_results(answer, gold)
    dimension_recall = sum(1 for item in dimensions if item["hit"]) / len(dimensions)
    dimension_support = _dimension_evidence_support(answer, gold, tool_outputs)
    supported_dimension_recall = (
        sum(1 for item in dimension_support if item["supported"])
        / len(dimension_support)
    )
    unsupported = _negative_results(answer, gold, "unsupported_claims")
    contradictions = _negative_results(answer, gold, "contradictions")
    unsupported_hits = sum(1 for item in unsupported if item["hit"])
    contradiction_hits = sum(1 for item in contradictions if item["hit"])
    citations = _citation_quality(answer, tool_outputs)

    evidence_text = "\n".join(tool_outputs + [answer])
    marker_results = [
        {"marker": marker, "hit": str(marker).casefold() in evidence_text.casefold()}
        for marker in gold.get("evidence_markers", [])
        if isinstance(marker, str)
    ]
    marker_recall = (
        sum(1 for item in marker_results if item["hit"]) / len(marker_results)
        if marker_results else 1.0
    )

    thresholds = gold.get("root_cause_thresholds") or {}
    min_dimensions = float(thresholds.get("dimension_recall", 0.75))
    min_supported_dimensions = float(
        thresholds.get("supported_dimension_recall", 0.0)
    )
    min_citations = float(thresholds.get("citation_accuracy", 0.5))
    min_markers = float(thresholds.get("evidence_marker_recall", 0.0))
    max_unsupported = int(thresholds.get("max_unsupported_claim_hits", 0))
    max_contradictions = int(thresholds.get("max_contradiction_hits", 0))
    passed = bool(answer.strip()) and all(
        (
            dimension_recall >= min_dimensions,
            supported_dimension_recall >= min_supported_dimensions,
            citations["accuracy"] >= min_citations,
            marker_recall >= min_markers,
            unsupported_hits <= max_unsupported,
            contradiction_hits <= max_contradictions,
        )
    )

    reported_usage, usage_source, usage_events = legacy._reported_usage(events, tool_events)
    session = next((event for event in events if event.get("type") == "session"), {})
    host_error = next((event for event in reversed(events) if event.get("type") == "host_error"), None)
    attempted = _attempted_context(events)
    repeated_ratio = duplicate_chars / output_chars if output_chars else 0.0

    return {
        "schema_version": ROOT_CAUSE_SCHEMA_VERSION,
        "case_id": case.get("id"),
        "project": (case.get("provenance") or {}).get("project"),
        "source_issue": case.get("source_issue"),
        "fix_reference": case.get("fix_reference"),
        "mode": session.get("mode"),
        "model": session.get("model"),
        "passed": passed,
        "quality": {
            "dimension_recall": round(dimension_recall, 4),
            "dimensions": dimensions,
            "supported_dimension_recall": round(supported_dimension_recall, 4),
            "dimension_evidence_support": dimension_support,
            "evidence_marker_recall": round(marker_recall, 4),
            "evidence_markers": marker_results,
            "citation": citations,
            "unsupported_claim_hits": unsupported_hits,
            "unsupported_claims": unsupported,
            "contradiction_hits": contradiction_hits,
            "contradictions": contradictions,
        },
        "context_cost": {
            "tool_calls": len(tool_events),
            "model_calls": len(model_events),
            "tool_output_chars": output_chars,
            "unique_tool_output_chars": unique_chars,
            "exact_duplicate_tool_output_chars": duplicate_chars,
            "repeated_tool_output_ratio": round(repeated_ratio, 4),
            "estimated_tool_output_tokens_chars_div_4": math.ceil(output_chars / 4),
            "tool_wall_time_ms": round(sum(durations), 3),
            "max_tool_call_ms": round(max(durations, default=0.0), 3),
            **attempted,
            "usage_source": usage_source,
            "usage_events": usage_events,
            "reported_input_tokens": reported_usage["input_tokens"],
            "reported_output_tokens": reported_usage["output_tokens"],
            "reported_reasoning_tokens": reported_usage["reasoning_tokens"],
            "reported_cached_input_tokens": reported_usage["cached_input_tokens"],
            "reported_cache_read_input_tokens": reported_usage["cache_read_input_tokens"],
            "reported_cache_creation_input_tokens": reported_usage["cache_creation_input_tokens"],
        },
        "failure": (
            {
                "reason": host_error.get("failure_reason") or "host_error",
                "error": host_error.get("error"),
            }
            if isinstance(host_error, Mapping)
            else None
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TraceCite fixed root-cause benchmark evaluator")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("case_dir", type=Path)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("case_dir", type=Path)
    prepare.add_argument("--work-dir", type=Path, required=True)
    score = sub.add_parser("score")
    score.add_argument("case_dir", type=Path)
    score.add_argument("transcript", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            payload = validate_case(args.case_dir)
        elif args.command == "prepare":
            payload = prepare_case(args.case_dir, args.work_dir)
        else:
            payload = score_transcript(args.case_dir, args.transcript)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())