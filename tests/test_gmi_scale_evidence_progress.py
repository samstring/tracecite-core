from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks" / "agent-investigation"


def _run_scale_script(tmp_path: Path, body: str) -> str:
    env = os.environ.copy()
    pythonpath = [str(ROOT / "src")]
    if env.get("PYTHONPATH"):
        pythonpath.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(BENCH)!r})\n"
        "import gmi_scale_host as scale\n"
        f"tmp = Path({str(tmp_path)!r})\n"
        + body
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return completed.stdout


def test_context_window_failure_is_declared_explicitly(tmp_path: Path) -> None:
    output = _run_scale_script(
        tmp_path,
        "assert scale._host_failure_reason(RuntimeError('context window exceeds limit (2013)')) == 'context_window_exceeded'\n"
        "assert scale._host_failure_reason(subprocess.TimeoutExpired('x', 1)) == 'tool_timeout'\n"
        "print('ok')\n".replace(
            "assert scale._host_failure_reason(subprocess.TimeoutExpired",
            "import subprocess\nassert scale._host_failure_reason(subprocess.TimeoutExpired",
        ),
    )
    assert output.strip() == "ok"


def test_signal_retention_prefers_late_high_severity_signature(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    scratch = tmp_path / "scratch"
    input_root.mkdir()
    scratch.mkdir()

    def letters(index: int) -> str:
        value = index
        chars = []
        for _ in range(4):
            chars.append(chr(ord("a") + value % 26))
            value //= 26
        return "".join(chars)

    lines = [f"invalid low-{letters(index)}" for index in range(256)]
    lines.append("fatal high-priority-corruption")
    (input_root / "runtime.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    output = _run_scale_script(
        tmp_path,
        "runtime = scale.ScaleRuntime(mode='tracecite', input_root=tmp/'inputs', scratch=tmp/'scratch', context_id='')\n"
        "result = runtime._scan_incident_signals('runtime.log', tmp/'inputs'/'runtime.log')\n"
        "assert result['signal_signatures'] == 256\n"
        "assert result['omitted_signatures'] == 1\n"
        "assert any(item['severity'] == 4 and 'fatal high-priority-corruption' in item['signature'] for item in result['clusters'])\n"
        "print(json.dumps({'signatures': result['signal_signatures'], 'omitted': result['omitted_signatures']}))\n",
    )
    assert json.loads(output) == {"signatures": 256, "omitted": 1}


def test_get_hard_stops_when_union_coverage_already_contains_range(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    scratch = tmp_path / "scratch"
    input_root.mkdir()
    scratch.mkdir()
    (input_root / "runtime.log").write_text(
        "".join(f"line-{index}\n" for index in range(1, 31)),
        encoding="utf-8",
    )

    output = _run_scale_script(
        tmp_path,
        "runtime = scale.ScaleRuntime(mode='tracecite', input_root=tmp/'inputs', scratch=tmp/'scratch', context_id='')\n"
        "runtime._inspected_files.add('runtime.log')\n"
        "first = runtime._tracecite_get({'file':'runtime.log','line':5,'radius':1})\n"
        "second = runtime._tracecite_get({'file':'runtime.log','line':9,'radius':1})\n"
        "bridge = runtime._tracecite_get({'file':'runtime.log','line':7,'radius':0})\n"
        "covered = runtime._tracecite_get({'file':'runtime.log','line':7,'radius':3})\n"
        "assert 'status=ok' in first and 'status=ok' in second and 'status=ok' in bridge\n"
        "assert 'status=no_new_evidence' in covered\n"
        "assert 'requested_range_already_covered=True' in covered\n"
        "assert '#L4' not in covered and '#L10' not in covered\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"


def test_different_search_query_hard_stops_when_evidence_is_not_novel(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    scratch = tmp_path / "scratch"
    input_root.mkdir()
    scratch.mkdir()
    (input_root / "runtime.log").write_text(
        "before\nalpha needle beta\nafter\n",
        encoding="utf-8",
    )

    output = _run_scale_script(
        tmp_path,
        "runtime = scale.ScaleRuntime(mode='tracecite', input_root=tmp/'inputs', scratch=tmp/'scratch', context_id='')\n"
        "runtime._inspected_files.add('runtime.log')\n"
        "first = runtime._tracecite_search_scale({'file':'runtime.log','query':'needle','regex':False})\n"
        "second = runtime._tracecite_search_scale({'file':'runtime.log','query':'alpha','regex':False})\n"
        "assert '@TCF 1 search' in first\n"
        "assert 'status=no_new_evidence' in second\n"
        "assert 'search_returned_only_seen_evidence=True' in second\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"
