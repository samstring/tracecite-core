from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
USER_AGENT = "TraceCite-Agent-Investigation-Benchmark/1"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _case_paths(case_dir: Path) -> tuple[dict[str, Any], Path, Path]:
    case_path = case_dir / "case.json"
    case = _read_json(case_path)
    question_path = case_dir / str(case.get("question_file", "question.md"))
    gold_path = case_dir / str(case.get("gold_file", "gold.json"))
    return case, question_path, gold_path


def validate_case(case_dir: Path) -> dict[str, Any]:
    case, question_path, gold_path = _case_paths(case_dir)
    errors: list[str] = []

    if case.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id.strip():
        errors.append("id must be a non-empty string")
    if not question_path.is_file():
        errors.append(f"missing question file: {question_path.name}")
    if not gold_path.is_file():
        errors.append(f"missing gold file: {gold_path.name}")

    inputs = case.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        errors.append("inputs must be a non-empty list")
    else:
        for index, item in enumerate(inputs):
            if not isinstance(item, Mapping):
                errors.append(f"inputs[{index}] must be an object")
                continue
            for key in ("id", "url", "filename"):
                if not isinstance(item.get(key), str) or not str(item[key]).strip():
                    errors.append(f"inputs[{index}].{key} must be a non-empty string")

    gold: dict[str, Any] = {}
    if gold_path.is_file():
        try:
            gold = _read_json(gold_path)
        except Exception as exc:  # pragma: no cover - surfaced as validation error
            errors.append(f"invalid gold file: {exc}")

    if question_path.is_file() and gold:
        question = question_path.read_text(encoding="utf-8").casefold()
        for term in gold.get("leak_terms", []):
            if isinstance(term, str) and term.casefold() in question:
                errors.append(f"question leaks evaluator-only term: {term!r}")

    if errors:
        raise ValueError("; ".join(errors))

    return {
        "status": "ok",
        "case_id": case_id,
        "inputs": len(inputs),
        "question_file": question_path.name,
        "gold_file": gold_path.name,
    }


def _download(url: str, target: Path) -> tuple[int, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def prepare_case(case_dir: Path, work_dir: Path) -> dict[str, Any]:
    validation = validate_case(case_dir)
    case, _, _ = _case_paths(case_dir)
    case_root = work_dir / str(case["id"])
    input_root = case_root / "inputs"
    prepared: list[dict[str, Any]] = []

    for source in case["inputs"]:
        target = input_root / str(source["filename"])
        size, sha256 = _download(str(source["url"]), target)
        expected = source.get("sha256")
        if expected and expected != sha256:
            target.unlink(missing_ok=True)
            raise ValueError(
                f"sha256 mismatch for {source['id']}: expected {expected}, got {sha256}"
            )
        prepared.append(
            {
                "id": source["id"],
                "path": str(target),
                "bytes": size,
                "sha256": sha256,
                "source_url": source["url"],
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case["id"],
        "question": str((case_dir / str(case.get("question_file", "question.md"))).resolve()),
        "inputs": prepared,
    }
    case_root.mkdir(parents=True, exist_ok=True)
    (case_root / "prepared.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {**validation, "prepared": prepared, "manifest": str(case_root / "prepared.json")}


def _iter_transcript(path: Path) -> Iterable[dict[str, Any]]:
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"transcript line {line_number} must be a JSON object")
        yield value


def _concept_hit(text: str, concept: Mapping[str, Any]) -> bool:
    patterns = concept.get("patterns", [])
    if not isinstance(patterns, list) or not patterns:
        return False
    return any(
        isinstance(pattern, str) and re.search(pattern, text, flags=re.IGNORECASE) is not None
        for pattern in patterns
    )


def _marker_hit(text: str, marker: str) -> bool:
    return marker.casefold() in text.casefold()


def score_transcript(case_dir: Path, transcript_path: Path) -> dict[str, Any]:
    validate_case(case_dir)
    _, _, gold_path = _case_paths(case_dir)
    gold = _read_json(gold_path)
    events = list(_iter_transcript(transcript_path))

    tool_events = [event for event in events if event.get("type") == "tool"]
    final_events = [event for event in events if event.get("type") == "final"]
    final = final_events[-1] if final_events else {}
    answer = str(final.get("answer", ""))
    evidence = final.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = []

    visible_outputs: list[str] = []
    reported_input_tokens = 0
    reported_output_tokens = 0
    token_events = 0
    for event in tool_events:
        output = event.get("output", "")
        if not isinstance(output, str):
            output = json.dumps(output, ensure_ascii=False, sort_keys=True)
        visible_outputs.append(output)
        if isinstance(event.get("input_tokens"), int):
            reported_input_tokens += int(event["input_tokens"])
            token_events += 1
        if isinstance(event.get("output_tokens"), int):
            reported_output_tokens += int(event["output_tokens"])

    output_chars = sum(len(item) for item in visible_outputs)
    unique_hashes: set[str] = set()
    unique_chars = 0
    duplicate_chars = 0
    for output in visible_outputs:
        digest = hashlib.sha256(output.encode("utf-8")).hexdigest()
        if digest in unique_hashes:
            duplicate_chars += len(output)
        else:
            unique_hashes.add(digest)
            unique_chars += len(output)

    concept_results: list[dict[str, Any]] = []
    concepts = gold.get("required_concepts", [])
    for concept in concepts:
        if not isinstance(concept, Mapping):
            continue
        hit = _concept_hit(answer, concept)
        concept_results.append({"id": concept.get("id"), "hit": hit})

    evidence_text = "\n".join(visible_outputs + [answer] + [str(item) for item in evidence])
    marker_results: list[dict[str, Any]] = []
    for marker in gold.get("evidence_markers", []):
        if not isinstance(marker, str):
            continue
        marker_results.append({"marker": marker, "hit": _marker_hit(evidence_text, marker)})

    concept_recall = (
        sum(1 for item in concept_results if item["hit"]) / len(concept_results)
        if concept_results
        else 1.0
    )
    evidence_recall = (
        sum(1 for item in marker_results if item["hit"]) / len(marker_results)
        if marker_results
        else 1.0
    )
    thresholds = gold.get("thresholds", {})
    min_concepts = float(thresholds.get("concept_recall", 1.0))
    min_evidence = float(thresholds.get("evidence_marker_recall", 0.0))
    passed = bool(answer.strip()) and concept_recall >= min_concepts and evidence_recall >= min_evidence

    session = next((event for event in events if event.get("type") == "session"), {})
    result = {
        "schema_version": SCHEMA_VERSION,
        "case_id": _read_json(case_dir / "case.json").get("id"),
        "mode": session.get("mode"),
        "model": session.get("model"),
        "passed": passed,
        "quality": {
            "concept_recall": round(concept_recall, 4),
            "evidence_marker_recall": round(evidence_recall, 4),
            "concepts": concept_results,
            "evidence_markers": marker_results,
        },
        "context_cost": {
            "tool_calls": len(tool_events),
            "tool_output_chars": output_chars,
            "unique_tool_output_chars": unique_chars,
            "exact_duplicate_tool_output_chars": duplicate_chars,
            "estimated_tool_output_tokens_chars_div_4": math.ceil(output_chars / 4),
            "reported_input_tokens": reported_input_tokens if token_events else None,
            "reported_output_tokens": reported_output_tokens if token_events else None,
        },
    }
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TraceCite real-world Agent benchmark helper")
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
    args = _build_parser().parse_args(argv)
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
