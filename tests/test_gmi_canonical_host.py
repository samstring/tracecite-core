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
        "import gmi_canonical_host as host\n"
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


def test_provider_failure_taxonomy_is_stable(tmp_path: Path) -> None:
    output = _run_host_script(
        tmp_path,
        "assert host._host_failure_reason(RuntimeError('context window exceeds limit')) == 'context_window_exceeded'\n"
        "assert host._host_failure_reason(RuntimeError('GMI API HTTP 402: insufficient balance')) == 'provider_insufficient_balance'\n"
        "assert host._host_failure_reason(RuntimeError('GMI API HTTP 429: busy')) == 'provider_rate_limited'\n"
        "assert host._host_failure_reason(RuntimeError('GMI API HTTP 503: unavailable')) == 'provider_unavailable'\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"


def test_request_context_records_attempted_payload_before_provider_usage(tmp_path: Path) -> None:
    output = _run_host_script(
        tmp_path,
        "event = host._request_context_event({'messages':[{'role':'user','content':'hello'}], 'tools':[]})\n"
        "assert event['serialized_chars'] > 0\n"
        "assert event['message_chars'] > 0\n"
        "assert event['estimated_tokens_chars_div_4'] > 0\n"
        "print(json.dumps(event))\n",
    )
    event = json.loads(output)
    assert event["type"] == "request_context"


def test_canonical_host_preserves_visible_evidence_and_clamps_radius(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    scratch = tmp_path / "scratch"
    input_root.mkdir()
    scratch.mkdir()
    (input_root / "runtime.log").write_text(
        "INFO start\nERROR checksum failed request=7\nINFO end\n",
        encoding="utf-8",
    )

    output = _run_host_script(
        tmp_path,
        "runtime = host.CanonicalRuntime(mode='tracecite', input_root=tmp/'inputs', scratch=tmp/'scratch', context_id='')\n"
        "first = runtime._tracecite_search({'file':'runtime.log','query':'checksum','regex':False})\n"
        "second = runtime._tracecite_search({'file':'runtime.log','query':'checksum','regex':False})\n"
        "clamped = runtime._tracecite_get({'file':'runtime.log','line':2,'radius':10})\n"
        "assert 'checksum failed request=7' in first\n"
        "assert 'no_new_evidence' in second.lower()\n"
        "assert 'radius_clamped_from=10 radius=8' in clamped\n"
        "assert 'INFO start' in clamped and 'INFO end' in clamped\n"
        "assert 'runtime.log:1' in clamped and 'runtime.log:3' in clamped\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"


def test_no_growth_detection_requires_explicit_stop_not_false_fields(tmp_path: Path) -> None:
    output = _run_host_script(
        tmp_path,
        "productive = {'status':'ok','data':{'progress':{'frontier_exhausted':False,'scope_exhausted':False}}}\n"
        "no_match = {'status':'no_match','data':{'progress':{'frontier_exhausted':False}}}\n"
        "duplicate = {'status':'no_new_evidence','data':{}}\n"
        "exhausted = {'status':'ok','data':{'stop_reason':{'kind':'frontier_exhausted'}}}\n"
        "assert host._tool_output_no_growth(json.dumps(productive)) is False\n"
        "assert host._tool_output_no_growth(json.dumps(no_match)) is False\n"
        "assert host._tool_output_no_growth(json.dumps(duplicate)) is True\n"
        "assert host._tool_output_no_growth(json.dumps(exhausted)) is True\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"


def test_stop_policy_forces_final_only_after_two_explicit_no_growth_rounds(tmp_path: Path) -> None:
    output = _run_host_script(
        tmp_path,
        "messages = [\n"
        " {'role':'system','content':'s'}, {'role':'user','content':'u'},\n"
        " {'role':'assistant','content':'','tool_calls':[{'id':'1'}]},\n"
        " {'role':'tool','content':'{\\\"status\\\":\\\"no_new_evidence\\\",\\\"data\\\":{} }'},\n"
        " {'role':'assistant','content':'','tool_calls':[{'id':'2'}]},\n"
        " {'role':'tool','content':'{\\\"status\\\":\\\"no_new_evidence\\\",\\\"data\\\":{} }'},\n"
        "]\n"
        "request, event = host._apply_stop_policy({'messages':messages,'tools':[{'type':'function'}],'tool_choice':'auto'})\n"
        "assert event is not None and event['reason'] == 'consecutive_no_growth'\n"
        "assert 'tools' not in request and 'tool_choice' not in request\n"
        "assert request['messages'][-1]['role'] == 'user'\n"
        "assert 'Evidence acquisition has stopped' in request['messages'][-1]['content']\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"


def test_stop_policy_max_round_is_a_safety_cap(tmp_path: Path) -> None:
    output = _run_host_script(
        tmp_path,
        "messages = [{'role':'system','content':'s'},{'role':'user','content':'u'}]\n"
        "for i in range(12):\n"
        "    messages.append({'role':'assistant','content':'','tool_calls':[{'id':str(i)}]})\n"
        "    messages.append({'role':'tool','content':'{\\\"status\\\":\\\"ok\\\",\\\"data\\\":{}}'})\n"
        "request, event = host._apply_stop_policy({'messages':messages,'tools':[{'type':'function'}],'tool_choice':'auto'})\n"
        "assert event is not None and event['reason'] == 'max_rounds'\n"
        "assert 'tools' not in request\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"
