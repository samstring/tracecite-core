from __future__ import annotations

from pathlib import Path


path = Path(".github/workflows/pi-agent-four-public-cases-ab.yml")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise RuntimeError(f"missing workflow block: {label}")
    text = text.replace(old, new, 1)


replace_once(
    """            tests/test_session_novelty_regressions.py \\\n            tests/test_pi_four_public_strict_boundary.py\n""",
    """            tests/test_session_novelty_regressions.py \\\n            tests/test_pi_four_public_strict_boundary.py \\\n            tests/test_pi_four_public_scoring.py\n""",
    "focused scoring regression",
)

replace_once(
    """            python -m tracecite.root_cause_benchmarking score \\\n              \"$CASE_DIR_RUN\" \"$RESULT/pi-${arm}-transcript.jsonl\" \\\n              > \"$RESULT/pi-${arm}-score.json\" || true\n""",
    """            python benchmarks/agent-investigation/pi_four_public_scoring.py score \\\n              \"$CASE_DIR_RUN\" \"$RESULT/pi-${arm}-transcript.jsonl\" \\\n              > \"$RESULT/pi-${arm}-score.json\" || true\n""",
    "schema-aware score command",
)

replace_once(
    """          from pi_ab_runtime import classify_arm_validity\n""",
    """          from pi_ab_runtime import classify_arm_validity\n          from pi_four_public_scoring import project_score\n""",
    "scoring helper import",
)

replace_once(
    """              quality=score.get('quality') if isinstance(score.get('quality'),dict) else {}\n              cost=score.get('context_cost') if isinstance(score.get('context_cost'),dict) else {}\n              usage, tools=transcript_usage(root/f'pi-{name}-transcript.jsonl')\n              thresholds=gold.get('thresholds') if isinstance(gold.get('thresholds'),dict) else {}\n              dim=float(quality.get('dimension_recall') or 0.0)\n              unsupported=int(quality.get('unsupported_claim_hits') or 0)\n              contradictions=int(quality.get('contradiction_hits') or 0)\n              semantic_success=bool(answer) and dim >= float(thresholds.get('concept_recall',0.75)) and unsupported == 0 and contradictions == 0\n""",
    """              cost=score.get('context_cost') if isinstance(score.get('context_cost'),dict) else {}\n              usage, tools=transcript_usage(root/f'pi-{name}-transcript.jsonl')\n              projection=project_score(score, answer_nonempty=bool(answer))\n""",
    "normalized semantic projection",
)

replace_once(
    """                  'answer_success': semantic_success,\n                  'score_passed': score.get('passed'),\n                  'dimension_recall': quality.get('dimension_recall'),\n                  'supported_dimension_recall': quality.get('supported_dimension_recall'),\n                  'citation_accuracy': (quality.get('citation') or {}).get('accuracy') if isinstance(quality.get('citation'),dict) else None,\n                  'unsupported_claim_hits': quality.get('unsupported_claim_hits'),\n                  'contradiction_hits': quality.get('contradiction_hits'),\n""",
    """                  'answer_success': projection['answer_success'],\n                  'score_kind': projection['score_kind'],\n                  'score_passed': projection['score_passed'],\n                  'dimension_recall': projection['dimension_recall'],\n                  'supported_dimension_recall': projection['supported_dimension_recall'],\n                  'citation_accuracy': projection['citation_accuracy'],\n                  'unsupported_claim_hits': projection['unsupported_claim_hits'],\n                  'contradiction_hits': projection['contradiction_hits'],\n                  'concept_recall': projection['concept_recall'],\n                  'evidence_marker_recall': projection['evidence_marker_recall'],\n""",
    "normalized outcome fields",
)

path.write_text(text, encoding="utf-8")
print("four-public scoring workflow migrated")
