from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping

DIMENSIONS = (
    "failure_localization",
    "immediate_failure_mechanism",
    "upstream_contributor",
    "fix_alignment",
)
ALLOWED_SUPPORT = {"supported", "inference_supported", "unsupported_from_log"}
INFERENCE_RE = re.compile(
    r"\b(?:likely|plausible|suggests?|indicat(?:e|es|ed)|consistent\s+with|"
    r"may|might|could|appears?|inference|infer(?:red|ence)?|should|would|"
    r"not\s+directly\s+(?:shown|proven|established|observed))\b",
    re.IGNORECASE,
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _patterns(value: Any, key: str = "patterns") -> tuple[str, ...]:
    if isinstance(value, Mapping):
        value = value.get(key)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{key} must contain non-empty strings")
        re.compile(item)
        result.append(item)
    return tuple(result)


def _hit(text: str, patterns: tuple[str, ...]) -> bool:
    return bool(patterns) and any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) is not None
        for pattern in patterns
    )


def _blocks(answer: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*\n", answer) if block.strip()]


def _index(items: Any) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    if not isinstance(items, list):
        return result
    for item in items:
        if isinstance(item, Mapping):
            item_id = str(item.get("id") or "")
            if item_id:
                result[item_id] = item
    return result


def apply_support_levels(
    score: Mapping[str, Any], gold: Mapping[str, Any], answer: str
) -> dict[str, Any]:
    out = dict(score)
    quality = dict(out.get("quality") or {})
    rubric = gold.get("root_cause") or {}
    if not isinstance(rubric, Mapping):
        raise ValueError("gold.root_cause must be an object")

    raw_levels = gold.get("evidence_sufficiency") or {}
    if not isinstance(raw_levels, Mapping):
        raise ValueError("gold.evidence_sufficiency must be an object")
    levels: dict[str, str] = {}
    for dimension in DIMENSIONS:
        level = str(raw_levels.get(dimension) or "supported")
        if level not in ALLOWED_SUPPORT:
            raise ValueError(f"unsupported evidence_sufficiency value for {dimension}: {level}")
        levels[dimension] = level

    dimension_rows = _index(quality.get("dimensions"))
    support_rows = _index(quality.get("dimension_evidence_support"))
    answer_blocks = _blocks(answer)
    support_level_rows: list[dict[str, Any]] = []
    required_claims: list[str] = []
    unsupported_dimensions: list[str] = []
    unsupported_overreach = 0

    for dimension in DIMENSIONS:
        entry = rubric.get(dimension)
        if not isinstance(entry, Mapping):
            raise ValueError(f"gold.root_cause.{dimension} must be an object")
        claim_patterns = _patterns(entry, "patterns")
        boundary_patterns = _patterns(entry, "boundary_patterns")
        hit = bool(dimension_rows.get(dimension, {}).get("hit"))
        cited = bool(support_rows.get(dimension, {}).get("supported"))
        matching_blocks = [block for block in answer_blocks if _hit(block, claim_patterns)]
        inference_qualified = any(INFERENCE_RE.search(block) for block in matching_blocks)
        boundary_hit = _hit(answer, boundary_patterns)
        level = levels[dimension]

        if level == "supported":
            required_claims.append(dimension)
            level_ok = bool(hit and cited)
            overreach = False
        elif level == "inference_supported":
            required_claims.append(dimension)
            level_ok = bool(hit and cited and inference_qualified)
            overreach = bool(hit and not inference_qualified)
        else:
            unsupported_dimensions.append(dimension)
            overreach = bool(hit and not boundary_hit)
            level_ok = bool(boundary_hit and not overreach)

        unsupported_overreach += int(overreach)
        support_level_rows.append(
            {
                "id": dimension,
                "support_level": level,
                "claim_hit": hit,
                "evidence_cited_in_claim_block": cited,
                "inference_qualified": inference_qualified,
                "boundary_hit": boundary_hit,
                "overreach": overreach,
                "support_level_ok": level_ok,
            }
        )

    claim_hits = sum(bool(dimension_rows.get(dim, {}).get("hit")) for dim in required_claims)
    claim_supported = sum(
        bool(support_rows.get(dim, {}).get("supported")) for dim in required_claims
    )
    dimension_recall = claim_hits / len(required_claims) if required_claims else 1.0
    supported_dimension_recall = (
        claim_supported / len(required_claims) if required_claims else 1.0
    )
    boundary_recall = (
        sum(
            row["boundary_hit"]
            for row in support_level_rows
            if row["support_level"] == "unsupported_from_log"
        )
        / len(unsupported_dimensions)
        if unsupported_dimensions
        else 1.0
    )
    support_level_accuracy = sum(row["support_level_ok"] for row in support_level_rows) / len(
        support_level_rows
    )

    quality["legacy_dimension_recall"] = quality.get("dimension_recall")
    quality["legacy_supported_dimension_recall"] = quality.get("supported_dimension_recall")
    quality["dimension_recall"] = round(dimension_recall, 4)
    quality["supported_dimension_recall"] = round(supported_dimension_recall, 4)
    quality["evidence_boundary_recall"] = round(boundary_recall, 4)
    quality["support_level_accuracy"] = round(support_level_accuracy, 4)
    quality["unsupported_dimension_overreach_hits"] = unsupported_overreach
    quality["support_levels"] = support_level_rows
    out["quality"] = quality

    thresholds = gold.get("root_cause_thresholds") or {}
    if not isinstance(thresholds, Mapping):
        thresholds = {}
    min_dimensions = float(thresholds.get("dimension_recall", 0.75))
    min_supported = float(thresholds.get("supported_dimension_recall", 0.0))
    min_citations = float(thresholds.get("citation_accuracy", 0.5))
    min_markers = float(thresholds.get("evidence_marker_recall", 0.0))
    min_boundary = float(thresholds.get("evidence_boundary_recall", 0.0))
    min_support_level = float(thresholds.get("support_level_accuracy", 0.0))
    max_unsupported = int(thresholds.get("max_unsupported_claim_hits", 0))
    max_contradictions = int(thresholds.get("max_contradiction_hits", 0))
    max_dimension_overreach = int(thresholds.get("max_unsupported_dimension_overreach_hits", 0))

    citation = quality.get("citation") or {}
    if not isinstance(citation, Mapping):
        citation = {}
    support_aware_passed = bool(answer.strip()) and all(
        (
            dimension_recall >= min_dimensions,
            supported_dimension_recall >= min_supported,
            float(citation.get("accuracy") or 0.0) >= min_citations,
            float(quality.get("evidence_marker_recall") or 0.0) >= min_markers,
            boundary_recall >= min_boundary,
            support_level_accuracy >= min_support_level,
            int(quality.get("unsupported_claim_hits") or 0) <= max_unsupported,
            int(quality.get("contradiction_hits") or 0) <= max_contradictions,
            unsupported_overreach <= max_dimension_overreach,
        )
    )
    out["legacy_passed"] = bool(score.get("passed"))
    out["support_aware_passed"] = support_aware_passed
    out["passed"] = support_aware_passed
    return out


def _self_test() -> None:
    score = {
        "passed": False,
        "quality": {
            "dimension_recall": 0.75,
            "supported_dimension_recall": 0.75,
            "dimensions": [
                {"id": "failure_localization", "hit": True},
                {"id": "immediate_failure_mechanism", "hit": True},
                {"id": "upstream_contributor", "hit": True},
                {"id": "fix_alignment", "hit": False},
            ],
            "dimension_evidence_support": [
                {"id": "failure_localization", "supported": True},
                {"id": "immediate_failure_mechanism", "supported": True},
                {"id": "upstream_contributor", "supported": True},
                {"id": "fix_alignment", "supported": False},
            ],
            "citation": {"accuracy": 1.0},
            "evidence_marker_recall": 1.0,
            "unsupported_claim_hits": 0,
            "contradiction_hits": 0,
        },
    }
    gold = {
        "root_cause": {
            "failure_localization": {"patterns": ["worker queue"]},
            "immediate_failure_mechanism": {"patterns": ["checksum mismatch"]},
            "upstream_contributor": {"patterns": ["stale cache"]},
            "fix_alignment": {
                "patterns": ["invalidate cache"],
                "boundary_patterns": ["fix.{0,80}(?:not established|cannot be determined)"],
            },
        },
        "evidence_sufficiency": {
            "failure_localization": "supported",
            "immediate_failure_mechanism": "supported",
            "upstream_contributor": "inference_supported",
            "fix_alignment": "unsupported_from_log",
        },
        "root_cause_thresholds": {
            "dimension_recall": 1.0,
            "supported_dimension_recall": 1.0,
            "citation_accuracy": 1.0,
            "evidence_marker_recall": 1.0,
            "evidence_boundary_recall": 1.0,
            "support_level_accuracy": 1.0,
            "max_unsupported_claim_hits": 0,
            "max_contradiction_hits": 0,
            "max_unsupported_dimension_overreach_hits": 0,
        },
    }
    answer = (
        "The worker queue hit a checksum mismatch. L12.\n\n"
        "This likely reflects a stale cache entry. L12.\n\n"
        "The corrective fix is not established by the supplied evidence and cannot be determined."
    )
    updated = apply_support_levels(score, gold, answer)
    assert updated["support_aware_passed"] is True
    assert updated["quality"]["dimension_recall"] == 1.0
    assert updated["quality"]["evidence_boundary_recall"] == 1.0
    assert updated["quality"]["unsupported_dimension_overreach_hits"] == 0



def main() -> int:
    parser = argparse.ArgumentParser(description="Apply evidence-support-level scoring to a root-cause score.")
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--answer", type=Path)
    parser.add_argument("--score", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        print(json.dumps({"status": "ok"}))
        return 0
    if args.gold is None or args.answer is None or args.score is None:
        parser.error("--gold, --answer and --score are required unless --self-test is used")
    gold = _read_json(args.gold)
    score = _read_json(args.score)
    answer = args.answer.read_text(encoding="utf-8", errors="replace")
    updated = apply_support_levels(score, gold, answer)
    print(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
