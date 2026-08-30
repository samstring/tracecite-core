from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = "__FINAL_IMPL_SHA__"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing replacement marker: {label}")
    return text.replace(old, new, 1)


def _run_result_source() -> str:
    return r'''from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

PROVIDER_PATTERNS = (
    ("provider_rate_limited", re.compile(r"\b429\b|rate\s*limit(?:ed)?|overload(?:ed)?", re.I)),
    ("provider_quota_exhausted", re.compile(r"\b402\b|insufficient\s+balance|quota\s+(?:exhausted|exceeded)", re.I)),
    ("provider_unavailable", re.compile(r"\b50[234]\b|service\s+unavailable|bad\s+gateway|gateway\s+timeout", re.I)),
)


def _read_text(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _events(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            result.append(item)
    return result


def classify_provider_contamination(text: str) -> str | None:
    for name, pattern in PROVIDER_PATTERNS:
        if pattern.search(text):
            return name
    return None


def _tracecite_shape(event: Mapping[str, Any]) -> tuple[bool, bool, bool]:
    name = str(event.get("name") or event.get("tool") or "")
    if name not in {"tracecite_search", "tracecite_expand"}:
        return False, False, False
    output = event.get("output")
    if not isinstance(output, str):
        return True, False, False
    try:
        payload = json.loads(output)
    except Exception:
        return True, bool(output.strip()), False
    if not isinstance(payload, Mapping):
        return True, False, False
    status = str(payload.get("status") or "")
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), Mapping) else {}
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
    text = payload.get("text")
    new_evidence = coverage.get("new_evidence") if isinstance(coverage, Mapping) else None
    repeated = coverage.get("repeated_evidence") if isinstance(coverage, Mapping) else None
    added = bool(evidence) or bool(text) or (isinstance(new_evidence, int) and new_evidence > 0)
    low_novelty = status in {"no_match", "no_new_evidence"} or (
        isinstance(new_evidence, int)
        and new_evidence == 0
        and isinstance(repeated, int)
        and repeated > 0
    )
    return True, added, low_novelty


def trajectory_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    tool_events = [event for event in events if event.get("type") == "tool"]
    names = [str(event.get("name") or event.get("tool") or "unknown") for event in tool_events]
    counts = Counter(names)
    categories: Counter[str] = Counter()
    for event in tool_events:
        activity = event.get("activity")
        if isinstance(activity, Mapping):
            categories[str(activity.get("category") or "other")] += 1
        else:
            name = str(event.get("name") or event.get("tool") or "")
            if name in {"tracecite_search", "tracecite_expand"}:
                categories["tracecite_evidence"] += 1
            elif name in {"grep", "find"}:
                categories["native_search"] += 1
            elif name == "read":
                categories["native_read"] += 1
            elif name == "bash":
                categories["opaque_shell"] += 1
            else:
                categories["native_other"] += 1

    first_core: int | None = None
    tracecite_calls = 0
    low_novelty = 0
    for index, event in enumerate(tool_events, start=1):
        is_tracecite, added, low = _tracecite_shape(event)
        if is_tracecite:
            tracecite_calls += 1
            low_novelty += int(low)
            if added and first_core is None:
                first_core = index

    final_event_index = next(
        (index for index, event in enumerate(events, start=1) if event.get("type") == "final"),
        None,
    )
    return {
        "tool_calls": len(tool_events),
        "tool_names": dict(sorted(counts.items())),
        "tool_categories": dict(sorted(categories.items())),
        "core_evidence_first_tool_index": first_core,
        "final_answer_after_tool_count": len(tool_events),
        "final_answer_event_index": final_event_index,
        "post_core_tool_calls": (len(tool_events) - first_core) if first_core is not None else None,
        "tracecite_evidence_calls": categories.get("tracecite_evidence", 0),
        "native_search_calls": categories.get("native_search", 0),
        "native_read_calls": categories.get("native_read", 0),
        "opaque_shell_calls": categories.get("opaque_shell", 0),
        "tracecite_low_novelty_calls": low_novelty,
        "tracecite_low_novelty_ratio": round(low_novelty / tracecite_calls, 4) if tracecite_calls else None,
    }


def build_run_result(
    score: Mapping[str, Any],
    *,
    exit_code: int,
    stderr: str = "",
    session_text: str = "",
    transcript_text: str = "",
    transcript_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    diagnostics = "\n".join((stderr, session_text, transcript_text))
    provider_contamination = classify_provider_contamination(diagnostics)
    timed_out = exit_code == 124 or re.search(r"\b(?:timed out|timeout)\b", diagnostics, re.I) is not None
    if provider_contamination is not None:
        validity_reason = provider_contamination
    elif timed_out:
        validity_reason = "timeout"
    elif exit_code != 0:
        validity_reason = "host_exit_nonzero"
    else:
        validity_reason = "clean"
    valid = exit_code == 0 and provider_contamination is None and not timed_out
    events = transcript_events or []
    return {
        "schema_version": 1,
        "task_result": {
            "passed": score.get("passed"),
            "legacy_passed": score.get("legacy_passed"),
            "support_aware_passed": score.get("support_aware_passed", score.get("passed")),
            "quality": score.get("quality") or {},
            "context_cost": score.get("context_cost") or {},
            "failure": score.get("failure"),
        },
        "run_validity": {
            "valid_for_comparison": valid,
            "reason": validity_reason,
            "exit_code": exit_code,
            "provider_contamination": provider_contamination,
            "timeout": timed_out,
        },
        "trajectory": trajectory_summary(events),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the canonical Pi benchmark task_result/run_validity contract.")
    parser.add_argument("--score", type=Path, required=True)
    parser.add_argument("--exit-code-file", type=Path, required=True)
    parser.add_argument("--stderr", type=Path)
    parser.add_argument("--session", type=Path)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    score = _read_json(args.score)
    exit_code = int(args.exit_code_file.read_text(encoding="utf-8").strip())
    events = _events(args.transcript)
    result = build_run_result(
        score,
        exit_code=exit_code,
        stderr=_read_text(args.stderr),
        session_text=_read_text(args.session),
        transcript_text=_read_text(args.transcript),
        transcript_events=events,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _run_result_test_source() -> str:
    return r'''from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks" / "agent-investigation" / "run_result.py"
SPEC = importlib.util.spec_from_file_location("tracecite_benchmark_run_result", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _score(passed: bool = True):
    return {
        "passed": passed,
        "legacy_passed": False,
        "support_aware_passed": passed,
        "quality": {"support_level_accuracy": 1.0},
        "context_cost": {"tool_calls": 3},
    }


def test_clean_run_is_valid_independently_of_task_result() -> None:
    result = MODULE.build_run_result(_score(True), exit_code=0)
    assert result["task_result"]["passed"] is True
    assert result["run_validity"] == {
        "valid_for_comparison": True,
        "reason": "clean",
        "exit_code": 0,
        "provider_contamination": None,
        "timeout": False,
    }


def test_provider_contamination_is_not_product_loss() -> None:
    result = MODULE.build_run_result(
        _score(False),
        exit_code=1,
        stderr="HTTP 429 rate limited by provider",
    )
    assert result["task_result"]["passed"] is False
    assert result["run_validity"]["valid_for_comparison"] is False
    assert result["run_validity"]["reason"] == "provider_rate_limited"
    assert result["run_validity"]["provider_contamination"] == "provider_rate_limited"


def test_timeout_is_separate_from_provider_failure() -> None:
    result = MODULE.build_run_result(_score(False), exit_code=124, stderr="command timed out")
    assert result["run_validity"]["valid_for_comparison"] is False
    assert result["run_validity"]["reason"] == "timeout"
    assert result["run_validity"]["provider_contamination"] is None


def test_trajectory_counts_native_and_tracecite_activity() -> None:
    events = [
        {"type": "tool", "name": "tracecite_search", "output": '{"status":"ok","evidence":[{"ref":"x:L1"}],"coverage":{"new_evidence":1}}', "activity": {"category": "tracecite_evidence"}},
        {"type": "tool", "name": "grep", "output": "x", "activity": {"category": "native_search"}},
        {"type": "tool", "name": "bash", "output": "x", "activity": {"category": "opaque_shell"}},
        {"type": "tool", "name": "tracecite_search", "output": '{"status":"no_new_evidence","evidence":[],"coverage":{"new_evidence":0,"repeated_evidence":1}}', "activity": {"category": "tracecite_evidence"}},
        {"type": "final", "answer": "done"},
    ]
    summary = MODULE.trajectory_summary(events)
    assert summary["core_evidence_first_tool_index"] == 1
    assert summary["post_core_tool_calls"] == 3
    assert summary["native_search_calls"] == 1
    assert summary["opaque_shell_calls"] == 1
    assert summary["tracecite_low_novelty_ratio"] == 0.5
'''


def _ab_workflow() -> str:
    return r'''name: Pi Evidence Runtime A/B

on:
  workflow_dispatch:
    inputs:
      scope:
        description: "smoke = first small case only; four = one pass over all four; stability = 4 x 3 paired repetitions"
        required: true
        default: smoke
        type: choice
        options:
          - smoke
          - four
          - stability

permissions:
  contents: read

jobs:
  plan:
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.matrix.outputs.value }}
    steps:
      - id: matrix
        env:
          SCOPE: ${{ inputs.scope }}
        shell: bash
        run: |
          python - <<'PY' >> "$GITHUB_OUTPUT"
          import json, os
          cases = [
              {"case_id": "kubernetes-140039-runc-5347-scale", "case_dir": "benchmarks/agent-investigation/scale-cases/kubernetes-140039-runc-5347"},
              {"case_id": "kubernetes-139417-scale", "case_dir": "benchmarks/agent-investigation/scale-cases/kubernetes-139417"},
              {"case_id": "kubernetes-140848-scale", "case_dir": "benchmarks/agent-investigation/scale-cases/kubernetes-140848"},
              {"case_id": "kubernetes-140268", "case_dir": "benchmarks/agent-investigation/scale-cases/kubernetes-140268"},
          ]
          scope = os.environ["SCOPE"]
          if scope == "smoke":
              chosen = [(cases[0], 1)]
          elif scope == "four":
              chosen = [(case, 1) for case in cases]
          elif scope == "stability":
              chosen = [(case, repetition) for repetition in range(1, 4) for case in cases]
          else:
              raise SystemExit(f"unknown scope: {scope}")
          include = []
          for index, (case, repetition) in enumerate(chosen):
              row = dict(case)
              row["repetition"] = repetition
              row["arm_order"] = "native tracecite" if (index + repetition) % 2 == 0 else "tracecite native"
              include.append(row)
          print("value=" + json.dumps({"include": include}, separators=(",", ":")))
          PY

  compare:
    needs: plan
    runs-on: ubuntu-latest
    timeout-minutes: 35
    strategy:
      fail-fast: false
      max-parallel: 1
      matrix: ${{ fromJSON(needs.plan.outputs.matrix) }}
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      OPENAI_BASE_URL: ${{ vars.TRACECITE_BENCH_BASE_URL || 'https://api.gmi-serving.com/v1' }}
      BENCH_MODEL: ${{ vars.TRACECITE_BENCH_MODEL }}
      PI_CODING_AGENT_DIR: /tmp/pi-agent-config
      PI_SKIP_VERSION_CHECK: "1"
      PI_TELEMETRY: "0"
      CASE_ID: ${{ matrix.case_id }}
      CASE_DIR: ${{ matrix.case_dir }}
      REPETITION: ${{ matrix.repetition }}
      ARM_ORDER: ${{ matrix.arm_order }}
      RESULT_ROOT: /tmp/pi-evidence-ab/${{ matrix.case_id }}/r${{ matrix.repetition }}
      PREP: /tmp/pi-evidence-ab/${{ matrix.case_id }}/r${{ matrix.repetition }}/prepared

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - uses: actions/setup-node@v4
        with:
          node-version: "24"

      - name: Install Pi and TraceCite
        shell: bash
        run: |
          set -euo pipefail
          npm install -g --ignore-scripts @earendil-works/pi-coding-agent@0.84.4
          python -m pip install -e ".[dev]"

      - name: Verify final benchmark contracts
        shell: bash
        run: |
          set -euo pipefail
          python -m pytest -q \
            tests/test_canonical_evidence_contract.py \
            tests/test_runtime_session_retrieval.py \
            tests/test_session_novelty_regressions.py \
            tests/test_evidence_routing.py \
            tests/test_evidence_selection.py \
            tests/test_pi_host_tool_activity.py \
            tests/test_pi_session_to_transcript.py \
            tests/test_root_cause_benchmarking.py \
            tests/test_support_aware_root_cause_benchmarking.py \
            tests/test_benchmark_run_result.py
          python scripts/check_architecture.py

      - name: Configure model
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p "$PI_CODING_AGENT_DIR"
          python - <<'PY'
          import json, os
          from pathlib import Path
          model = os.environ['BENCH_MODEL']
          if not model:
              raise SystemExit('BENCH_MODEL is empty')
          payload = {'providers': {'gmi': {
              'name': 'GMI OpenAI-compatible',
              'baseUrl': os.environ['OPENAI_BASE_URL'],
              'api': 'openai-completions',
              'models': [{
                  'id': model,
                  'name': model,
                  'reasoning': False,
                  'input': ['text'],
                  'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0},
                  'contextWindow': 1_000_000,
                  'maxTokens': 4_096,
                  'compat': {'supportsDeveloperRole': False, 'supportsReasoningEffort': False},
              }],
          }}}
          (Path(os.environ['PI_CODING_AGENT_DIR']) / 'models.json').write_text(json.dumps(payload, indent=2) + '\n')
          PY

      - name: Prepare case
        shell: bash
        run: |
          set -euo pipefail
          rm -rf "$RESULT_ROOT"
          mkdir -p "$RESULT_ROOT" "$PREP"
          python -m tracecite.root_cause_benchmarking validate "$CASE_DIR" > "$RESULT_ROOT/validate.json"
          python -m tracecite.root_cause_benchmarking prepare "$CASE_DIR" --work-dir "$PREP" > "$RESULT_ROOT/prepare.json"
          PREPARED="$(find "$PREP" -name prepared.json -type f -print -quit)"
          test -n "$PREPARED"
          python - "$PREPARED" >> "$GITHUB_ENV" <<'PY'
          import json, sys
          from pathlib import Path
          data = json.loads(Path(sys.argv[1]).read_text())
          inputs = data.get('inputs') or []
          if len(inputs) != 1:
              raise SystemExit(f'expected one input, got {len(inputs)}')
          f = Path(inputs[0]['path']).resolve()
          print(f'INPUT_ROOT={f.parent}')
          print(f'INPUT_FILE={f.name}')
          print(f'INPUT_BYTES={f.stat().st_size}')
          print(f'QUESTION_FILE={Path(data["question"]).resolve()}')
          PY

      - name: Run one paired A/B
        shell: bash
        run: |
          set -euo pipefail
          QUESTION="$(cat "$QUESTION_FILE")"
          BASE_PROMPT='You are a real coding agent investigating supplied runtime evidence. Use only evidence from files in the current working directory; do not use external knowledge. You own hypotheses, causal reasoning, tool choice, investigation order, conclusions, evidence sufficiency, and when to stop. Keep exploration bounded. Every material factual claim must cite exact line numbers you actually observed. Distinguish direct observation from inference and explicitly state when the supplied evidence is insufficient.'

          run_arm() {
            arm="$1"
            mkdir -p "$RESULT_ROOT/pi-${arm}-session"
            cd "$INPUT_ROOT"
            set +e
            if [[ "$arm" == native ]]; then
              timeout -k 30s 600s pi \
                --provider gmi --model "$BENCH_MODEL" --api-key "$OPENAI_API_KEY" \
                --thinking off --mode text --print \
                --session-dir "$RESULT_ROOT/pi-native-session" \
                --tools read,bash,grep,find,ls \
                --no-extensions --no-skills --no-prompt-templates --no-context-files \
                --system-prompt "$BASE_PROMPT" "$QUESTION" \
                > "$RESULT_ROOT/pi-native-answer.md" 2> "$RESULT_ROOT/pi-native-stderr.log"
            else
              TRACE_PROMPT="$BASE_PROMPT TraceCite Evidence Runtime tools and the TraceCite skill are available for evidence operations they can express. Native tools remain available. TraceCite provides mechanical evidence, provenance, novelty, identity-safety, and activity semantics only; it does not choose hypotheses, causal conclusions, evidence sufficiency, or stopping."
              TRACECITE_PI_SESSION="$RESULT_ROOT/tracecite-retrieval-session.json" \
              TRACECITE_PI_ACTIVITY="$RESULT_ROOT/tracecite-host-tool-activity.json" \
              timeout -k 30s 600s pi \
                --provider gmi --model "$BENCH_MODEL" --api-key "$OPENAI_API_KEY" \
                --thinking off --mode text --print \
                --session-dir "$RESULT_ROOT/pi-tracecite-session" \
                --extension "$GITHUB_WORKSPACE/benchmarks/agent-investigation/pi_tracecite_extension.ts" \
                --tools read,bash,grep,find,ls,tracecite_search,tracecite_expand \
                --no-skills --skill "$GITHUB_WORKSPACE/.pi/skills/tracecite/SKILL.md" \
                --no-prompt-templates --no-context-files \
                --system-prompt "$TRACE_PROMPT" "$QUESTION" \
                > "$RESULT_ROOT/pi-tracecite-answer.md" 2> "$RESULT_ROOT/pi-tracecite-stderr.log"
            fi
            code=$?
            set -e
            echo "$code" > "$RESULT_ROOT/pi-${arm}-exit.txt"
          }

          echo "$ARM_ORDER" > "$RESULT_ROOT/arm-order.txt"
          first="${ARM_ORDER%% *}"
          second="${ARM_ORDER##* }"
          run_arm "$first"
          sleep 5
          run_arm "$second"

      - name: Convert, score, and classify validity
        if: always()
        shell: bash
        run: |
          set -euo pipefail
          for arm in native tracecite; do
            SESSION="$(find "$RESULT_ROOT/pi-${arm}-session" -type f -name '*.jsonl' -print -quit 2>/dev/null || true)"
            ANSWER="$RESULT_ROOT/pi-${arm}-answer.md"
            EXIT="$RESULT_ROOT/pi-${arm}-exit.txt"
            if [[ -z "$SESSION" || ! -f "$ANSWER" || ! -f "$EXIT" ]]; then
              continue
            fi
            TRANSCRIPT="$RESULT_ROOT/pi-${arm}-transcript.jsonl"
            SCORE="$RESULT_ROOT/pi-${arm}-score.json"
            RUN_RESULT="$RESULT_ROOT/pi-${arm}-run-result.json"
            python benchmarks/agent-investigation/pi_session_to_transcript.py \
              "$SESSION" "$ANSWER" "$TRANSCRIPT" \
              --mode "pi-${arm}" --model "$BENCH_MODEL"
            python -m tracecite.root_cause_benchmarking score \
              "$CASE_DIR" "$TRANSCRIPT" > "$SCORE" || true
            if [[ -f "$SCORE" ]]; then
              python benchmarks/agent-investigation/run_result.py \
                --score "$SCORE" \
                --exit-code-file "$EXIT" \
                --stderr "$RESULT_ROOT/pi-${arm}-stderr.log" \
                --session "$SESSION" \
                --transcript "$TRANSCRIPT" \
                --output "$RUN_RESULT" || true
            fi
          done

      - name: Summarize comparison
        if: always()
        shell: bash
        run: |
          set -euo pipefail
          python - <<'PY'
          import json, os
          from pathlib import Path
          root = Path(os.environ['RESULT_ROOT'])
          def read(name):
              path = root / name
              return json.loads(path.read_text()) if path.is_file() else None
          native = read('pi-native-run-result.json')
          tracecite = read('pi-tracecite-run-result.json')
          report = {
              'schema_version': 1,
              'case_id': os.environ['CASE_ID'],
              'repetition': int(os.environ['REPETITION']),
              'input_bytes': int(os.environ.get('INPUT_BYTES') or 0),
              'arm_order': (root / 'arm-order.txt').read_text().strip() if (root / 'arm-order.txt').is_file() else None,
              'native': native,
              'tracecite': tracecite,
              'tracecite_host_activity': read('tracecite-host-tool-activity.json'),
          }
          def valid(value):
              return bool(value and (value.get('run_validity') or {}).get('valid_for_comparison'))
          report['comparison_valid'] = valid(native) and valid(tracecite)
          (root / 'comparison.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
          print(json.dumps(report, indent=2, sort_keys=True))
          PY

      - name: Upload artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: pi-evidence-ab-${{ matrix.case_id }}-r${{ matrix.repetition }}
          path: ${{ env.RESULT_ROOT }}
          if-no-files-found: warn
'''


def _canonical_ci_workflow() -> str:
    return r'''name: Evidence Intelligence Benchmark

on:
  push:
    branches:
      - experiment/evidence-intelligence
  workflow_dispatch:

permissions:
  contents: read

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install package
        run: python -m pip install -e ".[dev]"
      - name: Run architecture governance
        run: python scripts/check_architecture.py
      - name: Run canonical Evidence Runtime and evaluation contracts
        run: >-
          python -m pytest -q
          tests/test_canonical_evidence_contract.py
          tests/test_runtime_session_retrieval.py
          tests/test_session_novelty_regressions.py
          tests/test_evidence_routing.py
          tests/test_evidence_selection.py
          tests/test_pi_host_tool_activity.py
          tests/test_pi_session_to_transcript.py
          tests/test_root_cause_benchmarking.py
          tests/test_support_aware_root_cause_benchmarking.py
          tests/test_benchmark_run_result.py
      - name: Run support-level mechanical self-test
        run: python -c "from tracecite.support_scoring import self_test; self_test()"
'''


def apply() -> None:
    extension_path = "benchmarks/agent-investigation/pi_tracecite_extension.ts"
    extension = _read(extension_path)
    extension = _replace_once(
        extension,
        'type HostToolCategory = "tracecite_evidence" | "native_search" | "native_read" | "native_other" | "other";',
        'type HostToolCategory = "tracecite_evidence" | "native_search" | "native_read" | "opaque_shell" | "native_other" | "other";',
        label="host category type",
    )
    extension = _replace_once(
        extension,
        '  if (tool === "bash" || tool === "ls") return "native_other";',
        '  if (tool === "bash") return "opaque_shell";\n  if (tool === "ls") return "native_other";',
        label="bash host category",
    )
    _write(extension_path, extension)

    host_test_path = "tests/test_pi_host_tool_activity.py"
    host_test = _read(host_test_path)
    if 'assert \'return "opaque_shell"\' in text' not in host_test:
        host_test = host_test.replace(
            '    assert \'tool === "bash"\' in text\n',
            '    assert \'tool === "bash"\' in text\n    assert \'return "opaque_shell"\' in text\n',
            1,
        )
    _write(host_test_path, host_test)

    support_test_path = "tests/test_support_aware_root_cause_benchmarking.py"
    support_test = _read(support_test_path)
    marker = "def test_scale_case_gold_does_not_require_hidden_upstream_truth"
    if marker not in support_test:
        support_test += r'''


def test_scale_case_gold_does_not_require_hidden_upstream_truth() -> None:
    root = Path(__file__).resolve().parents[1]
    for case_name in ("kubernetes-139417", "kubernetes-140268"):
        case_dir = root / "benchmarks" / "agent-investigation" / "scale-cases" / case_name
        gold = json.loads((case_dir / "gold.json").read_text(encoding="utf-8"))
        sufficiency = gold["evidence_sufficiency"]
        assert sufficiency["upstream_contributor"] == "unsupported_from_log"
        assert sufficiency["fix_alignment"] == "unsupported_from_log"
        assert gold["root_cause"]["upstream_contributor"]["boundary_patterns"]
        assert gold["root_cause"]["fix_alignment"]["boundary_patterns"]
'''
    _write(support_test_path, support_test)

    _write("benchmarks/agent-investigation/run_result.py", _run_result_source())
    _write("tests/test_benchmark_run_result.py", _run_result_test_source())

    _write(".github/workflows/pi-evidence-runtime-ab.yml", _ab_workflow())
    old_workflow = ROOT / ".github/workflows/pi-scale-4case-progress-once.yml"
    if old_workflow.exists():
        old_workflow.unlink()
    _write(".github/workflows/evidence-intelligence.yml", _canonical_ci_workflow())

    plan_path = "docs/evidence-runtime-refactor-plan.zh-CN.md"
    plan = _read(plan_path)
    plan = _replace_once(
        plan,
        "# F. Host Observation Contract\n\n状态：**IN PROGRESS**",
        "# F. Host Observation Contract\n\n状态：**F1 COMPLETE；F2 DEFERRED UNTIL AFTER I**",
        label="F status",
    )
    plan = _replace_once(
        plan,
        "# G. Evaluation Contract\n\n状态：**IN PROGRESS**",
        "# G. Evaluation Contract\n\n状态：**COMPLETE**",
        label="G status",
    )
    for old in (
        "- [ ] `139417` 不要求 Agent 为日志无法建立的 upstream cause 编确定结论。",
        "- [ ] `140268` 不要求日志直接证明不存在的 internal lookup implementation。",
        "- [ ] correctness truth 与 known upstream fix 可区分：known fix 不能自动等于 supplied-log-supported truth。",
        "- [ ] 429/overload 不计 product loss。",
        "- [ ] contaminated run 可用于 trajectory diagnosis，但不能进入 clean A/B win/loss。",
    ):
        plan = plan.replace(old, old.replace("[ ]", "[x]"), 1)
    plan = _replace_once(
        plan,
        "# H. 文档与 Adapter 收敛\n\n状态：**IN PROGRESS**",
        "# H. 文档与 Adapter 收敛\n\n状态：**CORE COMPLETE；H3 上层同步冻结至 I/J 后**",
        label="H status",
    )
    plan = plan.replace("- [ ] 不更新 MCP。", "- [x] 不更新 MCP。", 1)
    plan = plan.replace("- [ ] 不更新 Mobile。", "- [x] 不更新 Mobile。", 1)
    plan = _replace_once(
        plan,
        "# I. 4-Case 验证 Gate\n\n状态：**当前旧 session-progress 实验仍在运行/收尾；新架构实现后需重跑。**",
        "# I. 4-Case 验证 Gate\n\n状态：**READY；最终实现已收口，但新 case 尚未运行。先 smoke 第一个小 case。**",
        label="I status",
    )

    exp_start = plan.index("## 3. 明确删除/不再继续的实验性方向")
    exp_end = plan.index("## 4. 每个代码提交的强制记录格式", exp_start)
    exp = plan[exp_start:exp_end].replace("- [ ] ", "- [x] ")
    plan = plan[:exp_start] + exp + plan[exp_end:]

    seq_start = plan.index("## 5. 当前立即执行顺序")
    seq_end = plan.index("\n---\n\n## 6.", seq_start)
    sequence = '''## 5. 当前立即执行顺序

代码与 contract 收口完成后，验证严格按：

1. 先完成 G2/G3、Host activity 分类与 benchmark workflow 最终化；
2. 跑 post-finalization canonical unit/architecture gate；
3. **只跑第一个小 case `kubernetes-140039-runc-5347-scale` smoke paired A/B**；
4. smoke 的入口、trajectory telemetry、canonical scorer、`task_result/run_validity` 与 artifact 全部正常后，才跑 4-case 单轮；
5. 4-case 单轮方向有效后，才跑 `4 × 3` paired stability；
6. stability 串行、短 arm 间隔；不再使用固定 45 秒 repeat delay；
7. F2 optional checkpoint 是否继续实验，必须由单独 A/B 决定，不作为 Core gate；
8. MCP / Mobile 最后同步。

任何新想法若不属于上述工作项，先更新本文档说明“为什么需要新增工作项”，再实现。'''
    plan = plan[:seq_start] + sequence + plan[seq_end:]

    marker = "### G2 — Hidden-answer pressure removed from case truth"
    if marker not in plan:
        plan += f'''

### G2 — Hidden-answer pressure removed from case truth

Status: **COMPLETE**  
Commit: `{PLACEHOLDER}`  
Tests: 新增 case-level regression，锁定 `kubernetes-139417` 与 `kubernetes-140268` 的 `upstream_contributor/fix_alignment=unsupported_from_log` 与 boundary patterns；post-finalization gate 尚未运行。  
Why: supplied log 无法直接证明 known upstream implementation/fix 时，不应把 upstream knowledge 伪装成日志 direct truth。  
Behavior change: correctness 仍可保留 known upstream fix reference，但 canonical scoring 根据 supplied-evidence support level 奖励明确 boundary，而不是强迫 Agent 编出确定结论。  
Remaining risk: 真实回答是否稳定遵守 boundary 仍需 I/J。

### G3 — Infra validity separated from task result

Status: **COMPLETE**  
Commit: `{PLACEHOLDER}`  
Tests: 新增 `tests/test_benchmark_run_result.py`；post-finalization gate 尚未运行。  
Why: 429/402/502/503/504、provider overload 与 timeout 会污染 paired A/B，不能自动算 TraceCite/native product loss。  
Behavior change: `benchmarks/agent-investigation/run_result.py` 为每个 arm 生成独立 `task_result` 与 `run_validity`；provider contamination、timeout、host nonzero exit 与 answer quality 分离；trajectory 同时输出 core evidence 首次到达、post-core tools、native/TraceCite/opaque-shell 计数与 low-novelty ratio。  
Remaining risk: provider-clean paired sample 数量仍由 I/J 决定。

### Pre-case A/B workflow convergence

Status: **COMPLETE**  
Commit: `{PLACEHOLDER}`  
Tests: workflow 尚未 dispatch；按“改完再测”要求等待全部代码收口后再执行。  
Why: 旧 four-case workflow 引用了已删除的 `pi_tracecite_extension_progress.ts`、旧 telemetry test 与 support overlay，且不能先 smoke 最小 case。  
Behavior change: 新 `.github/workflows/pi-evidence-runtime-ab.yml` 只有显式 `workflow_dispatch`；`scope=smoke/four/stability`；smoke 只跑 `140039`；four 单轮 4 case；stability 为 `4×3`、`max-parallel=1`、arm 间仅 `sleep 5`，没有 45 秒 repeat delay；使用 canonical `pi_tracecite_extension.ts` 与 canonical scorer。  
Remaining risk: workflow 的真实 Pi/Provider 集成必须由 smoke 首轮验证。
'''
    _write(plan_path, plan)


def backfill(sha: str) -> None:
    if not sha or len(sha) < 7:
        raise SystemExit("backfill requires implementation sha")
    plan_path = "docs/evidence-runtime-refactor-plan.zh-CN.md"
    plan = _read(plan_path)
    if PLACEHOLDER not in plan:
        raise SystemExit("no implementation sha placeholder found")
    _write(plan_path, plan.replace(PLACEHOLDER, sha))


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: finalize_evidence_intelligence.py apply | backfill <sha>")
    if sys.argv[1] == "apply":
        apply()
    elif sys.argv[1] == "backfill" and len(sys.argv) == 3:
        backfill(sys.argv[2])
    else:
        raise SystemExit("invalid arguments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
