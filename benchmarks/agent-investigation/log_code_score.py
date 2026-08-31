from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from tracecite import root_cause_benchmarking as root
from tracecite.support_scoring import apply_support_levels


_PATH_LINE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?P<path>(?:\.{0,2}/|/)?(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+)"
    r":L?(?P<line>\d+)\b",
    re.IGNORECASE,
)
_MORE_LINES_PATTERN = re.compile(r"^\[\d+ more lines in file\.", re.IGNORECASE)
CitationRef = tuple[str | None, int]


def _normalize_path(path: str, evidence_filenames: Iterable[str]) -> str:
    value = str(path or "").strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    value = re.sub(r"/+", "/", value)

    if "/workspace/source/" in value:
        value = value.split("/workspace/source/", 1)[1]
    elif "/workspace/evidence/" in value:
        value = "evidence/" + value.split("/workspace/evidence/", 1)[1]
    elif value.startswith("source/"):
        value = value[len("source/") :]
    elif value.startswith("/source/"):
        value = value[len("/source/") :]
    elif value.startswith("/evidence/"):
        value = value[1:]

    evidence = {
        Path(str(name)).name.casefold(): Path(str(name)).name
        for name in evidence_filenames
        if str(name).strip()
    }
    basename = Path(value).name
    if basename.casefold() in evidence:
        return f"evidence/{evidence[basename.casefold()]}"
    return value.lstrip("/")


def _path_refs(text: str, evidence_filenames: Iterable[str]) -> tuple[set[CitationRef], list[tuple[int, int]]]:
    refs: set[CitationRef] = set()
    spans: list[tuple[int, int]] = []
    for match in _PATH_LINE_PATTERN.finditer(text):
        try:
            line = int(match.group("line"))
        except (TypeError, ValueError):
            continue
        if line <= 0:
            continue
        refs.add((_normalize_path(match.group("path"), evidence_filenames), line))
        spans.append(match.span())
    return refs, spans


def _citation_refs(text: str, evidence_filenames: Iterable[str]) -> set[CitationRef]:
    refs, path_spans = _path_refs(text, evidence_filenames)
    for pattern in root._CITATION_PATTERNS:
        for match in pattern.finditer(text):
            if any(start <= match.start() < end for start, end in path_spans):
                continue
            try:
                line = int(match.group("line"))
            except (TypeError, ValueError):
                continue
            if line > 0:
                refs.add((None, line))
    return refs


def _output(event: Mapping[str, Any]) -> str:
    value = event.get("output", "")
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _target_path(event: Mapping[str, Any], evidence_filenames: Iterable[str]) -> str | None:
    arguments = event.get("arguments")
    if not isinstance(arguments, Mapping):
        return None
    for key in ("path", "file"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_path(value, evidence_filenames)
    return None


def _visible_data_line_count(output: str) -> int:
    lines = output.splitlines()
    if lines and _MORE_LINES_PATTERN.match(lines[-1].strip()):
        lines.pop()
    return len(lines)


def _tool_refs(event: Mapping[str, Any], evidence_filenames: Iterable[str]) -> set[CitationRef]:
    output = _output(event)
    target = _target_path(event, evidence_filenames)
    refs: set[CitationRef] = set()

    for visible_text in root._tool_visible_texts(output):
        refs.update(_citation_refs(visible_text, evidence_filenames))
        for pattern in (root._TOOL_NUMBERED_LINE_PATTERN, root._TOOL_COLON_LINE_PATTERN):
            for match in pattern.finditer(visible_text):
                try:
                    line = int(match.group("line"))
                except (TypeError, ValueError):
                    continue
                if line > 0:
                    refs.add((target, line))

    name = str(event.get("name") or event.get("tool") or "")
    arguments = event.get("arguments")
    if name == "read" and target and isinstance(arguments, Mapping):
        offset = arguments.get("offset")
        start = offset if isinstance(offset, int) and not isinstance(offset, bool) and offset > 0 else 1
        for line in range(start, start + _visible_data_line_count(output)):
            refs.add((target, line))

    return refs


def _visible_refs(tool_events: Iterable[Mapping[str, Any]], evidence_filenames: Iterable[str]) -> set[CitationRef]:
    refs: set[CitationRef] = set()
    for event in tool_events:
        refs.update(_tool_refs(event, evidence_filenames))
    return refs


def _is_visible(ref: CitationRef, visible: set[CitationRef]) -> bool:
    path, line = ref
    if ref in visible:
        return True
    if path is None:
        return any(candidate_line == line for _, candidate_line in visible)
    if path.startswith("evidence/") and (None, line) in visible:
        return True

    matches = {
        candidate_path
        for candidate_path, candidate_line in visible
        if candidate_path
        and candidate_line == line
        and (
            candidate_path == path
            or candidate_path.endswith("/" + path)
            or path.endswith("/" + candidate_path)
        )
    }
    return len(matches) == 1


def _format_ref(ref: CitationRef) -> str:
    path, line = ref
    return f"{path}:L{line}" if path else f"L{line}"


def _citation_quality(answer: str, tool_events: list[Mapping[str, Any]], evidence_filenames: Iterable[str]) -> dict[str, Any]:
    answer_refs = _citation_refs(answer, evidence_filenames)
    visible = _visible_refs(tool_events, evidence_filenames)
    valid = {ref for ref in answer_refs if _is_visible(ref, visible)}
    invalid = answer_refs - valid
    accuracy = len(valid) / len(answer_refs) if answer_refs else 0.0
    return {
        "citations": len(answer_refs),
        "valid_citations": len(valid),
        "invalid_citations": len(invalid),
        "accuracy": round(accuracy, 4),
        "cited_lines": sorted({line for _, line in answer_refs}),
        "invalid_lines": sorted({line for _, line in invalid}),
        "cited_refs": sorted(_format_ref(ref) for ref in answer_refs),
        "valid_refs": sorted(_format_ref(ref) for ref in valid),
        "invalid_refs": sorted(_format_ref(ref) for ref in invalid),
    }


def _dimension_support(
    answer: str,
    gold: Mapping[str, Any],
    tool_events: list[Mapping[str, Any]],
    evidence_filenames: Iterable[str],
) -> list[dict[str, Any]]:
    visible = _visible_refs(tool_events, evidence_filenames)
    blocks = root._answer_blocks(answer)
    rubric = gold["root_cause"]
    rows: list[dict[str, Any]] = []
    for dimension in root.ROOT_CAUSE_DIMENSIONS:
        patterns = root._patterns(rubric[dimension], field=f"root_cause.{dimension}")
        matching = [block for block in blocks if root._hit(block, patterns)]
        valid: set[CitationRef] = set()
        for block in matching:
            valid.update(ref for ref in _citation_refs(block, evidence_filenames) if _is_visible(ref, visible))
        rows.append(
            {
                "id": dimension,
                "hit": bool(matching),
                "supported": bool(matching and valid),
                "valid_cited_lines": sorted({line for _, line in valid}),
                "valid_cited_refs": sorted(_format_ref(ref) for ref in valid),
            }
        )
    return rows


def _primary_evaluation(score: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce detailed scorer diagnostics to the three benchmark questions that matter.

    The detailed mechanical scorer is intentionally retained underneath this
    view so we can diagnose failures, but it no longer defines the headline.
    The headline asks only whether the answer is substantively correct and
    whether every required causal claim is backed by observed evidence without
    crossing an evidence boundary. Token usage is attached later by run_result.
    """

    quality = score.get("quality") or {}
    if not isinstance(quality, Mapping):
        quality = {}
    support_levels = quality.get("support_levels") or []
    if not isinstance(support_levels, list):
        support_levels = []

    missing_required_dimensions: list[str] = []
    unsupported_overreach_dimensions: list[str] = []
    for row in support_levels:
        if not isinstance(row, Mapping):
            continue
        dimension = str(row.get("id") or "")
        support_level = str(row.get("support_level") or "supported")
        if support_level != "unsupported_from_log" and not bool(row.get("claim_hit")):
            missing_required_dimensions.append(dimension)
        if bool(row.get("overreach")):
            unsupported_overreach_dimensions.append(dimension)

    unsupported_claim_hits = int(quality.get("unsupported_claim_hits") or 0)
    contradiction_hits = int(quality.get("contradiction_hits") or 0)
    overreach_hits = int(quality.get("unsupported_dimension_overreach_hits") or 0)
    dimension_recall = float(quality.get("dimension_recall") or 0.0)
    supported_dimension_recall = float(quality.get("supported_dimension_recall") or 0.0)
    evidence_boundary_recall = float(quality.get("evidence_boundary_recall") or 0.0)
    support_level_accuracy = float(quality.get("support_level_accuracy") or 0.0)

    root_cause_accurate = bool(
        dimension_recall >= 1.0
        and unsupported_claim_hits == 0
        and contradiction_hits == 0
    )
    evidence_boundary_respected = bool(
        evidence_boundary_recall >= 1.0
        and overreach_hits == 0
        and unsupported_claim_hits == 0
        and contradiction_hits == 0
    )
    evidence_chain_complete_and_bounded = bool(
        root_cause_accurate
        and supported_dimension_recall >= 1.0
        and support_level_accuracy >= 1.0
        and evidence_boundary_respected
    )

    return {
        "root_cause_accurate": root_cause_accurate,
        "evidence_chain_complete_and_bounded": evidence_chain_complete_and_bounded,
        "evidence_boundary_respected": evidence_boundary_respected,
        "missing_required_dimensions": missing_required_dimensions,
        "unsupported_overreach_dimensions": unsupported_overreach_dimensions,
    }


def score_log_code(case_dir: Path, transcript_path: Path) -> dict[str, Any]:
    score = root.score_transcript(case_dir, transcript_path)
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    gold_name = str(case.get("gold_file") or "gold.json")
    gold = json.loads((case_dir / gold_name).read_text(encoding="utf-8"))
    evidence_filenames = root._evidence_filenames(case)
    events = list(root._iter_transcript(transcript_path))
    tool_events = [event for event in events if event.get("type") == "tool"]
    final_events = [event for event in events if event.get("type") == "final"]
    answer = str((final_events[-1] if final_events else {}).get("answer") or "")

    quality = dict(score.get("quality") or {})
    quality["citation"] = _citation_quality(answer, tool_events, evidence_filenames)
    support = _dimension_support(answer, gold, tool_events, evidence_filenames)
    quality["dimension_evidence_support"] = support
    quality["supported_dimension_recall"] = round(
        sum(1 for row in support if row["supported"]) / len(support) if support else 1.0,
        4,
    )
    score["quality"] = quality

    # Keep the detailed support-aware scorer as a diagnostic layer, then expose
    # a deliberately small primary evaluation for Native vs TraceCite A/B.
    evaluated = apply_support_levels(score, gold, answer)
    evaluated["primary_evaluation"] = _primary_evaluation(evaluated)
    return evaluated


def main() -> int:
    parser = argparse.ArgumentParser(description="Score log+full-code Pi transcripts with path-aware source citations")
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("transcript", type=Path)
    args = parser.parse_args()
    print(json.dumps(score_log_code(args.case_dir, args.transcript), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
