from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks" / "agent-investigation"


def _run_host_script(tmp_path: Path, body: str) -> str:
    env = os.environ.copy()
    pythonpath = [str(ROOT / "src")]
    if env.get("PYTHONPATH"):
        pythonpath.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(BENCH)!r})\n"
        "import gmi_investigation_host as host\n"
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
        timeout=90,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return completed.stdout


def _prepare(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    scratch = tmp_path / "scratch"
    input_root.mkdir()
    scratch.mkdir()
    (input_root / "runtime.log").write_text(
        "INFO start request=7\nERROR checksum failed request=7\nINFO retry request=7\n",
        encoding="utf-8",
    )


def test_full_investigation_tool_surface_is_exposed(tmp_path: Path) -> None:
    _prepare(tmp_path)
    output = _run_host_script(
        tmp_path,
        "runtime = host.InvestigationRuntime(mode='tracecite', input_root=tmp/'inputs', scratch=tmp/'scratch', context_id='')\n"
        "names = [item['name'] for item in host._tools_for_mode('tracecite', runtime.files)]\n"
        "expected = {'tracecite_probe','tracecite_sample','tracecite_survey','tracecite_hypothesis','tracecite_test','tracecite_search','tracecite_expand','tracecite_verify','tracecite_finding','tracecite_investigation_summary','tracecite_investigation_stop'}\n"
        "assert expected.issubset(set(names))\n"
        "print(json.dumps(names))\n",
    )
    names = json.loads(output)
    assert "tracecite_probe" in names
    assert "tracecite_expand" in names
    assert "tracecite_investigation_stop" in names


def test_probe_gate_search_expand_and_state_lifecycle(tmp_path: Path) -> None:
    _prepare(tmp_path)
    output = _run_host_script(
        tmp_path,
        "runtime = host.InvestigationRuntime(mode='tracecite', input_root=tmp/'inputs', scratch=tmp/'scratch', context_id='')\n"
        "blocked = runtime.call('tracecite_search', {'file':'runtime.log','query':'checksum','regex':False})\n"
        "assert 'probe_required' in blocked\n"
        "probed = runtime.call('tracecite_probe', {'file':'runtime.log'})\n"
        "assert 'runtime.log' in probed and 'sha256' in probed\n"
        "hyp = json.loads(runtime.call('tracecite_hypothesis', {'claim':'checksum failure explains the incident'}))['result']\n"
        "test = json.loads(runtime.call('tracecite_test', {'hypothesis_id':hyp['id'],'intent':'look for checksum failure','expected_observation':'checksum failure is present','contradicting_observation':'checksum failure is absent'}))['result']\n"
        "searched = runtime.call('tracecite_search', {'file':'runtime.log','query':'checksum','regex':False,'hypothesis_id':hyp['id'],'test_id':test['id']})\n"
        "assert 'checksum failed request=7' in searched\n"
        "expanded = runtime.call('tracecite_expand', {'file':'runtime.log','start_line':2,'before':1,'after':1,'hypothesis_id':hyp['id'],'test_id':test['id']})\n"
        "assert 'INFO start request=7' in expanded and 'INFO retry request=7' in expanded\n"
        "finding = json.loads(runtime.call('tracecite_finding', {'hypothesis_id':hyp['id'],'outcome':'unknown','summary':'fixture only validates lifecycle'}))\n"
        "assert finding['status'] == 'ok'\n"
        "summary = json.loads(runtime.call('tracecite_investigation_summary', {}))\n"
        "assert summary\n"
        "stopped = json.loads(runtime.call('tracecite_investigation_stop', {'reason':'fixture complete','kind':'completed'}))\n"
        "assert stopped['status'] == 'ok'\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"


def test_provider_retry_policy_is_bounded_and_uses_longer_backoff(tmp_path: Path) -> None:
    output = _run_host_script(
        tmp_path,
        "host.os.environ['TRACECITE_BENCH_PROVIDER_MAX_ATTEMPTS'] = '2'\n"
        "host.os.environ['TRACECITE_BENCH_PROVIDER_BACKOFF_SECONDS'] = '20'\n"
        "calls = []\n"
        "sleeps = []\n"
        "def fake_post(payload):\n"
        "    calls.append(payload)\n"
        "    if len(calls) == 1: raise RuntimeError('GMI API HTTP 429: busy')\n"
        "    return {'choices':[{'message':{'content':'ok'},'finish_reason':'stop'}]}\n"
        "host.canonical._ORIGINAL_POST_CHAT = fake_post\n"
        "host.time.sleep = lambda seconds: sleeps.append(seconds)\n"
        "result = host._post_chat_resilient({'messages':[{'role':'user','content':'x'}]})\n"
        "assert len(calls) == 2\n"
        "assert sleeps == [20]\n"
        "assert result['choices'][0]['message']['content'] == 'ok'\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"
