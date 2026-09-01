from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = ROOT / "benchmarks" / "agent-investigation" / "pi_strict_evidence_boundary.ts"
ENTRYPOINT = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension.ts"
WORKFLOW = ROOT / ".github" / "workflows" / "pi-agent-four-public-cases-ab.yml"


def test_strict_boundary_blocks_native_runtime_evidence_before_execution() -> None:
    text = BOUNDARY.read_text(encoding="utf-8")

    assert 'BENCHMARK_MODE === "tracecite"' in text
    assert 'const NATIVE_PATH_TOOLS = new Set(["read", "grep", "find", "ls"])' in text
    assert 'tool === "bash"' in text
    assert 'within(EVIDENCE_ROOT, resolve(cwd))' in text
    assert 'status: "blocked_before_execution"' in text
    assert 'block: true' in text
    assert "Use TraceCite tools for all supplied evidence content" in text


def test_product_tracecite_mode_is_explicit_and_turn_scoped() -> None:
    text = BOUNDARY.read_text(encoding="utf-8")

    assert 'const PRODUCT_MODE = String(process.env.TRACECITE_MODE' in text
    assert 'process.env.TRACECITE_EVIDENCE_ROOT || process.env.TRACECITE_RUNTIME_EVIDENCE_ROOT' in text
    assert 'process.env.TRACECITE_EVIDENCE_FILES || process.env.TRACECITE_RUNTIME_EVIDENCE_FILES' in text
    assert 'export function explicitlyRequestsTracecite' in text
    assert 'pi.on("input"' in text
    assert '/^\\/trace(?:cite)?' in text
    assert '(?:用|使用)' in text
    assert '(?:use|using)' in text
    assert 'pi.on("agent_end"' in text
    assert 'promptTraceciteMode = false' in text
    assert "TraceCite mode is active" in text


def test_tracecite_extension_always_installs_evidence_guard_hook() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")

    assert 'import traceciteEvidenceGuard from "./pi_strict_evidence_boundary.ts"' in text
    assert "traceciteEvidenceGuard(pi);" in text
    assert "traceciteTools(pi);" in text


def test_four_public_workflow_enables_and_validates_strict_channel() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'TRACECITE_BENCHMARK_MODE=tracecite' in text
    assert 'TRACECITE_RUNTIME_EVIDENCE_ROOT="$INPUT_ROOT"' in text
    assert 'TRACECITE_RUNTIME_EVIDENCE_FILES="$INPUT_FILES"' in text
    assert 'TRACECITE_LOG_ACCESS_ACTIVITY="$RESULT/tracecite-runtime-evidence-access.jsonl"' in text
    assert 'TRACECITE_BLOCKED_NATIVE_EVIDENCE_ACTIVITY="$RESULT/tracecite-blocked-native-evidence-attempts.jsonl"' in text
    assert "channel-status.json" in text
    assert "'channel_valid': trace_calls > 0 and native_calls == 0" in text
    assert "tracecite_strict_evidence_channel_invalid" in text
    assert "tests/test_pi_four_public_strict_boundary.py" in text
