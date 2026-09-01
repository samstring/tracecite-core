from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from benchmarking import prepare_case
from tracecite.runtime.evidence_selection import signal_severity, structural_signature


@dataclass(frozen=True)
class HistoricalQuery:
    query: str
    regex: bool
    file_name: str


@dataclass(frozen=True)
class Candidate:
    line: int
    text: str
    neighborhood: str


TRACE_TOOL_NAMES = {
    "tracecite_search",
    "tracecite_retrieve",
    "tracecite_probe",
}
QUERY_KEYS = ("query", "pattern")
ARGS_KEYS = ("arguments", "args", "params", "input", "parameters")
TOOL_KEYS = ("tool", "tool_name", "name")


def _walk_json(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _mapping_query(mapping: Mapping[str, Any]) -> HistoricalQuery | None:
    tool_name = ""
    for key in TOOL_KEYS:
        raw = mapping.get(key)
        if isinstance(raw, str) and "tracecite" in raw.casefold():
            tool_name = raw.casefold()
            break
    operation = str(mapping.get("operation") or "").casefold()

    candidates: list[Mapping[str, Any]] = [mapping]
    for key in ARGS_KEYS:
        raw = mapping.get(key)
        if isinstance(raw, Mapping):
            candidates.append(raw)
        elif isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, Mapping):
                candidates.append(parsed)

    if not tool_name and operation not in {"search", "retrieve", "probe"}:
        return None
    if tool_name and not any(name in tool_name for name in TRACE_TOOL_NAMES):
        return None

    for args in candidates:
        query = next(
            (str(args[key]).strip() for key in QUERY_KEYS if isinstance(args.get(key), str) and str(args[key]).strip()),
            "",
        )
        if not query:
            continue
        raw_file = str(args.get("file") or args.get("path") or args.get("source") or "").strip()
        file_name = Path(raw_file).name if raw_file else ""
        return HistoricalQuery(query=query, regex=bool(args.get("regex")), file_name=file_name)
    return None


def extract_historical_queries(root: Path, *, limit: int = 200) -> list[HistoricalQuery]:
    found: list[HistoricalQuery] = []
    seen: set[tuple[str, bool, str]] = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
            continue
        if path.suffix.casefold() not in {".json", ".jsonl", ".txt", ".log", ".md"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        values: list[Any] = []
        if path.suffix.casefold() == ".jsonl":
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    values.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        else:
            try:
                values.append(json.loads(text))
            except json.JSONDecodeError:
                # Some transcripts embed JSON tool calls in otherwise textual logs.
                for match in re.finditer(r"\{[^\n]{0,4000}\}", text):
                    try:
                        values.append(json.loads(match.group(0)))
                    except json.JSONDecodeError:
                        pass
        for value in values:
            for mapping in _walk_json(value):
                item = _mapping_query(mapping)
                if item is None:
                    continue
                key = (item.query, item.regex, item.file_name)
                if key in seen:
                    continue
                seen.add(key)
                found.append(item)
                if len(found) >= limit:
                    return found
    return found


def _compile_matcher(query: HistoricalQuery):
    if query.regex:
        try:
            pattern = re.compile(query.query, re.IGNORECASE)
        except re.error:
            return None
        return lambda line: pattern.search(line) is not None
    needle = query.query.casefold()
    return lambda line: needle in line.casefold()


def acquire_candidates(
    lines: Sequence[str],
    query: HistoricalQuery,
    *,
    candidate_limit: int,
    radius: int,
    neighborhood_char_limit: int,
) -> list[Candidate]:
    matcher = _compile_matcher(query)
    if matcher is None:
        return []
    matches: list[int] = []
    for index, line in enumerate(lines):
        if matcher(line):
            matches.append(index)
            if len(matches) >= candidate_limit:
                break
    result: list[Candidate] = []
    for index in matches:
        left = max(0, index - radius)
        right = min(len(lines), index + radius + 1)
        neighborhood = "".join(lines[left:right])[:neighborhood_char_limit]
        result.append(Candidate(line=index + 1, text=lines[index].rstrip("\n"), neighborhood=neighborhood))
    return result


def _stack_like(text: str) -> bool:
    lower = text.casefold()
    if "goroutine " in lower or "java.lang.thread.state" in lower or "thread " in lower and " crashed" in lower:
        return True
    frameish = 0
    for line in text.splitlines():
        stripped = line.strip()
        if re.search(r"\([^)]*\)(?:\s|$)", stripped) and ("/" in stripped or "." in stripped):
            frameish += 1
        if stripped.startswith("at ") and "." in stripped:
            frameish += 1
    return frameish >= 2


def _drain_cluster_ids(candidates: Sequence[Candidate]) -> list[str]:
    config = TemplateMinerConfig()
    config.profiling_enabled = False
    miner = TemplateMiner(config=config)
    ids: list[str] = []
    for candidate in candidates:
        result = miner.add_log_message(candidate.text)
        ids.append(str(result["cluster_id"]))
    return ids


def _group_keys(candidates: Sequence[Candidate], mode: str) -> list[str]:
    if mode == "structural":
        return [structural_signature(item.neighborhood) or structural_signature(item.text) for item in candidates]
    if mode == "drain":
        return _drain_cluster_ids(candidates)
    if mode == "hybrid":
        drain_ids = _drain_cluster_ids(candidates)
        keys: list[str] = []
        for item, drain_id in zip(candidates, drain_ids):
            if _stack_like(item.neighborhood):
                keys.append("stack:" + (structural_signature(item.neighborhood) or structural_signature(item.text)))
            else:
                keys.append("log:" + drain_id)
        return keys
    raise ValueError(mode)


def _group_representatives(candidates: Sequence[Candidate], mode: str) -> tuple[list[Candidate], list[int]]:
    keys = _group_keys(candidates, mode)
    counts = Counter(keys)
    first: dict[str, Candidate] = {}
    max_severity: dict[str, int] = defaultdict(int)
    for key, candidate in zip(keys, candidates):
        first.setdefault(key, candidate)
        max_severity[key] = max(max_severity[key], signal_severity(candidate.neighborhood))
    ordered = sorted(
        first,
        key=lambda key: (-max_severity[key], -counts[key], first[key].line),
    )
    return [first[key] for key in ordered], [counts[key] for key in ordered]


def _mmr_select(query: str, candidates: Sequence[Candidate], limit: int, *, lambda_mult: float = 0.65) -> list[Candidate]:
    if len(candidates) <= limit:
        return list(candidates)
    texts = [item.neighborhood for item in candidates]
    vectorizer = HashingVectorizer(
        n_features=2**15,
        alternate_sign=False,
        norm="l2",
        analyzer="char_wb",
        ngram_range=(3, 5),
    )
    matrix = vectorizer.transform([query, *texts])
    relevance = cosine_similarity(matrix[1:], matrix[0:1]).ravel()
    pairwise = cosine_similarity(matrix[1:])
    selected: list[int] = []
    remaining = set(range(len(candidates)))
    while remaining and len(selected) < limit:
        best_index = None
        best_score = -math.inf
        for index in remaining:
            redundancy = max((pairwise[index, chosen] for chosen in selected), default=0.0)
            severity_bonus = min(0.08, signal_severity(candidates[index].neighborhood) * 0.02)
            score = lambda_mult * float(relevance[index]) - (1.0 - lambda_mult) * float(redundancy) + severity_bonus
            if score > best_score or (score == best_score and (best_index is None or candidates[index].line < candidates[best_index].line)):
                best_score = score
                best_index = index
        assert best_index is not None
        selected.append(best_index)
        remaining.remove(best_index)
    return [candidates[index] for index in selected]


def select_strategy(name: str, query: HistoricalQuery, candidates: Sequence[Candidate], limit: int) -> list[Candidate]:
    if name == "topk":
        return list(candidates[:limit])
    if name == "structural":
        reps, _counts = _group_representatives(candidates, "structural")
        return reps[:limit]
    if name == "drain":
        reps, _counts = _group_representatives(candidates, "drain")
        return reps[:limit]
    if name == "mmr":
        return _mmr_select(query.query, candidates, limit)
    if name == "hybrid_mmr":
        reps, _counts = _group_representatives(candidates, "hybrid")
        return _mmr_select(query.query, reps, limit)
    raise ValueError(name)


def _marker_hits(markers: Sequence[str], selected: Sequence[Candidate]) -> set[str]:
    body = "\n".join(item.neighborhood for item in selected).casefold()
    return {marker for marker in markers if marker.casefold() in body}


def _structure_count(selected: Sequence[Candidate]) -> int:
    return len({structural_signature(item.neighborhood) or structural_signature(item.text) for item in selected})


def evaluate_case(
    case_dir: Path,
    artifact_dir: Path,
    work_dir: Path,
    *,
    candidate_limit: int,
    max_evidence: int,
    radius: int,
    neighborhood_char_limit: int,
) -> dict[str, Any]:
    prepared = prepare_case(case_dir, work_dir)
    manifest = json.loads(Path(prepared["manifest"]).read_text(encoding="utf-8"))
    sources = {Path(item["path"]).name: Path(item["path"]) for item in manifest["inputs"]}
    source_lines = {name: path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) for name, path in sources.items()}
    gold = json.loads((case_dir / "gold.json").read_text(encoding="utf-8"))
    markers = [str(item) for item in gold.get("evidence_markers", []) if isinstance(item, str)]
    queries = extract_historical_queries(artifact_dir)

    strategies = ("topk", "structural", "drain", "mmr", "hybrid_mmr")
    stats: dict[str, dict[str, Any]] = {
        name: {
            "queries": 0,
            "candidate_records": 0,
            "selected_records": 0,
            "selected_chars": 0,
            "selected_structures": 0,
            "marker_hits": set(),
            "elapsed_ms": 0.0,
        }
        for name in strategies
    }
    rescues: dict[str, set[str]] = {name: set() for name in strategies if name != "topk"}
    evaluated_queries = 0

    for historical in queries:
        matching_sources: list[tuple[str, Sequence[str]]] = []
        if historical.file_name and historical.file_name in source_lines:
            matching_sources.append((historical.file_name, source_lines[historical.file_name]))
        else:
            matching_sources.extend(source_lines.items())
        for source_name, lines in matching_sources:
            candidates = acquire_candidates(
                lines,
                historical,
                candidate_limit=candidate_limit,
                radius=radius,
                neighborhood_char_limit=neighborhood_char_limit,
            )
            if not candidates:
                continue
            evaluated_queries += 1
            selections: dict[str, list[Candidate]] = {}
            for name in strategies:
                started = time.perf_counter()
                selected = select_strategy(name, historical, candidates, max_evidence)
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                selections[name] = selected
                row = stats[name]
                row["queries"] += 1
                row["candidate_records"] += len(candidates)
                row["selected_records"] += len(selected)
                row["selected_chars"] += sum(len(item.text) for item in selected)
                row["selected_structures"] += _structure_count(selected)
                row["marker_hits"].update(_marker_hits(markers, selected))
                row["elapsed_ms"] += elapsed_ms
            baseline_hits = _marker_hits(markers, selections["topk"])
            for name in rescues:
                rescues[name].update(_marker_hits(markers, selections[name]) - baseline_hits)

    serialised: dict[str, Any] = {}
    for name, row in stats.items():
        selected = int(row["selected_records"])
        structures = int(row["selected_structures"])
        serialised[name] = {
            **{key: value for key, value in row.items() if key != "marker_hits"},
            "marker_hits": sorted(row["marker_hits"]),
            "marker_recall": round(len(row["marker_hits"]) / len(markers), 4) if markers else 1.0,
            "duplicate_fraction_proxy": round(1.0 - structures / selected, 4) if selected else 0.0,
            "estimated_visible_tokens_chars_div_4": math.ceil(int(row["selected_chars"]) / 4),
            "elapsed_ms": round(float(row["elapsed_ms"]), 2),
        }

    return {
        "case_id": manifest["case_id"],
        "historical_queries_found": len(queries),
        "query_source_pairs_evaluated": evaluated_queries,
        "source_files": sorted(source_lines),
        "marker_count": len(markers),
        "strategies": serialised,
        "rescued_markers_vs_topk": {name: sorted(values) for name, values in rescues.items()},
    }


def write_markdown(report: Mapping[str, Any], target: Path) -> None:
    lines = [
        "# Offline Retrieval Diversity Evaluation",
        "",
        "No model calls are made. Historical TraceCite queries are replayed against the original public case inputs. Gold markers are evaluator-only and are never supplied to a selector.",
        "",
        "| Case | Strategy | Queries | Marker recall | Duplicate proxy | Visible chars | Est. tokens | CPU ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for case in report["cases"]:
        for name, row in case["strategies"].items():
            lines.append(
                f"| {case['case_id']} | {name} | {row['queries']} | {row['marker_recall']:.4f} | "
                f"{row['duplicate_fraction_proxy']:.4f} | {row['selected_chars']} | "
                f"{row['estimated_visible_tokens_chars_div_4']} | {row['elapsed_ms']:.2f} |"
            )
        rescues = {name: values for name, values in case["rescued_markers_vs_topk"].items() if values}
        if rescues:
            lines.extend(["", f"## {case['case_id']} rescued markers vs Top-K", "", "```json", json.dumps(rescues, ensure_ascii=False, indent=2), "```", ""])
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", nargs=2, metavar=("CASE_DIR", "ARTIFACT_DIR"), required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--candidate-limit", type=int, default=512)
    parser.add_argument("--max-evidence", type=int, default=20)
    parser.add_argument("--radius", type=int, default=8)
    parser.add_argument("--neighborhood-char-limit", type=int, default=6000)
    args = parser.parse_args()

    work_dir = Path(args.work_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    for case_raw, artifact_raw in args.case:
        cases.append(
            evaluate_case(
                Path(case_raw).resolve(),
                Path(artifact_raw).resolve(),
                work_dir,
                candidate_limit=args.candidate_limit,
                max_evidence=args.max_evidence,
                radius=args.radius,
                neighborhood_char_limit=args.neighborhood_char_limit,
            )
        )
    report = {
        "schema_version": 1,
        "candidate_limit": args.candidate_limit,
        "max_evidence": args.max_evidence,
        "neighborhood_radius": args.radius,
        "neighborhood_char_limit": args.neighborhood_char_limit,
        "strategies": ["topk", "structural", "drain", "mmr", "hybrid_mmr"],
        "cases": cases,
    }
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, output_dir / "report.md")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
