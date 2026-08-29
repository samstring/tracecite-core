from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks" / "agent-investigation"
_EVIDENCE_URI_RE = re.compile(r"evidence://sha256/[0-9a-f]{64}#L\d+(?:-L\d+)?")


def _run_host_script(tmp_path: Path, body: str) -> str:
    env = os.environ.copy()
    pythonpath = [str(ROOT / "src")]
    if env.get("PYTHONPATH"):
        pythonpath.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    script = (
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(BENCH)!r})\n"
        "import gmi_evidence_contract_host as host\n"
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


def _setup(tmp_path: Path) -> None:
    (tmp_path / "inputs").mkdir()
    (tmp_path / "scratch").mkdir()
    (tmp_path / "inputs" / "runtime.log").write_text(
        "INFO start\nERROR checksum failed request=7\nINFO end\n",
        encoding="utf-8",
    )


def test_linked_test_can_be_assessed_and_closed(tmp_path: Path) -> None:
    _setup(tmp_path)
    output = _run_host_script(
        tmp_path,
        "runtime = host.EvidenceContractRuntime(mode='tracecite', input_root=tmp/'inputs', scratch=tmp/'scratch', context_id='')\n"
        "runtime.call('tracecite_hypothesis', {'claim':'checksum failure caused request failure','hypothesis_id':'H1','rationale':''})\n"
        "runtime.call('tracecite_test', {'hypothesis_id':'H1','intent':'inspect checksum failure','expected_observation':'checksum failure is present','contradicting_observation':'request has no checksum failure','test_id':'T1'})\n"
        "search = runtime.call('tracecite_search', {'file':'runtime.log','query':'checksum','regex':False,'hypothesis_id':'H1','test_id':'T1'})\n"
        "import re\n"
        "match = re.search(r'evidence://sha256/[0-9a-f]{64}#L\\d+(?:-L\\d+)?', search)\n"
        "assert match, search\n"
        "ref = match.group(0)\n"
        "assessment = json.loads(runtime.call('tracecite_assess_test', {'test_id':'T1','outcome':'supported','evidence_refs':[ref]}))\n"
        "assert assessment['outcome'] == 'supported'\n"
        "finding = json.loads(runtime.call('tracecite_finding', {'hypothesis_id':'H1','outcome':'supported','summary':'checksum failure observed','supporting_evidence':[ref],'contradicting_evidence':[],'limitations':[]}))\n"
        "assert finding['outcome'] == 'supported'\n"
        "state = json.loads(runtime.call('tracecite_state', {}))\n"
        "assert state['tests'][0]['assessment'] == 'supported'\n"
        "assert state['findings'][0]['outcome'] == 'supported'\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"


def test_decisive_finding_is_rejected_when_declared_test_is_unassessed(tmp_path: Path) -> None:
    _setup(tmp_path)
    output = _run_host_script(
        tmp_path,
        "runtime = host.EvidenceContractRuntime(mode='tracecite', input_root=tmp/'inputs', scratch=tmp/'scratch', context_id='')\n"
        "runtime.call('tracecite_hypothesis', {'claim':'checksum failure caused request failure','hypothesis_id':'H1','rationale':''})\n"
        "runtime.call('tracecite_test', {'hypothesis_id':'H1','intent':'inspect checksum failure','expected_observation':'checksum failure is present','contradicting_observation':'request has no checksum failure','test_id':'T1'})\n"
        "search = runtime.call('tracecite_search', {'file':'runtime.log','query':'checksum','regex':False,'hypothesis_id':'H1','test_id':'T1'})\n"
        "import re\n"
        "ref = re.search(r'evidence://sha256/[0-9a-f]{64}#L\\d+(?:-L\\d+)?', search).group(0)\n"
        "try:\n"
        "    runtime.call('tracecite_finding', {'hypothesis_id':'H1','outcome':'supported','summary':'too early','supporting_evidence':[ref],'contradicting_evidence':[],'limitations':[]})\n"
        "except Exception as exc:\n"
        "    assert 'test_not_assessed' in str(exc)\n"
        "else:\n"
        "    raise AssertionError('unassessed decisive finding must fail')\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"


def test_stop_policy_keeps_only_epistemic_closure_tools_without_finding(tmp_path: Path) -> None:
    _setup(tmp_path)
    output = _run_host_script(
        tmp_path,
        "os.environ['TRACECITE_BENCH_SCRATCH'] = str(tmp/'scratch')\n"
        "runtime = host.EvidenceContractRuntime(mode='tracecite', input_root=tmp/'inputs', scratch=tmp/'scratch', context_id='')\n"
        "messages = [\n"
        " {'role':'system','content':'s'}, {'role':'user','content':'u'},\n"
        " {'role':'assistant','content':'','tool_calls':[{'id':'1'}]},\n"
        " {'role':'tool','content':'{\\\"status\\\":\\\"no_new_evidence\\\",\\\"data\\\":{} }'},\n"
        " {'role':'assistant','content':'','tool_calls':[{'id':'2'}]},\n"
        " {'role':'tool','content':'{\\\"status\\\":\\\"no_new_evidence\\\",\\\"data\\\":{} }'},\n"
        "]\n"
        "tools = host._tools_for_mode('tracecite', runtime.files)\n"
        "request, event = host._closure_only_stop_policy({'messages':messages,'tools':tools,'tool_choice':'auto'})\n"
        "assert event is not None and event['event'] == 'force_epistemic_closure'\n"
        "names = {tool['name'] for tool in request['tools']}\n"
        "assert names == host._CLOSURE_TOOL_NAMES\n"
        "assert 'tracecite_search' not in names and 'tracecite_get' not in names\n"
        "assert request['tool_choice'] == 'required'\n"
        "assert 'Never upgrade retrieval exhaustion into proof' in request['messages'][-1]['content']\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"


def test_repeated_evidence_remains_referenceable_when_formal_test_starts_late(tmp_path: Path) -> None:
    _setup(tmp_path)
    output = _run_host_script(
        tmp_path,
        "runtime = host.EvidenceContractRuntime(mode='tracecite', input_root=tmp/'inputs', scratch=tmp/'scratch', context_id='')\n"
        "explore = runtime.call('tracecite_search', {'file':'runtime.log','query':'checksum','regex':False,'hypothesis_id':None,'test_id':None})\n"
        "assert '@EVIDENCE_REF ' in explore\n"
        "runtime.call('tracecite_hypothesis', {'claim':'checksum failure caused request failure','hypothesis_id':'H1','rationale':''})\n"
        "runtime.call('tracecite_test', {'hypothesis_id':'H1','intent':'inspect checksum failure','expected_observation':'checksum failure is present','contradicting_observation':'request has no checksum failure','test_id':'T1'})\n"
        "linked = runtime.call('tracecite_search', {'file':'runtime.log','query':'checksum','regex':False,'hypothesis_id':'H1','test_id':'T1'})\n"
        "import re\n"
        "match = re.search(r'@EVIDENCE_REF (evidence://sha256/[0-9a-f]{64}#L\\d+(?:-L\\d+)?)', linked)\n"
        "assert match, linked\n"
        "ref = match.group(1)\n"
        "runtime.call('tracecite_assess_test', {'test_id':'T1','outcome':'supported','evidence_refs':[ref]})\n"
        "finding = json.loads(runtime.call('tracecite_finding', {'hypothesis_id':'H1','outcome':'supported','summary':'checksum failure observed','supporting_evidence':[ref],'contradicting_evidence':[],'limitations':[]}))\n"
        "assert finding['outcome'] == 'supported'\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"


def test_transport_requires_tools_until_finding_exists(tmp_path: Path) -> None:
    _setup(tmp_path)
    output = _run_host_script(
        tmp_path,
        "os.environ['TRACECITE_BENCH_SCRATCH'] = str(tmp/'scratch')\n"
        "runtime = host.EvidenceContractRuntime(mode='tracecite', input_root=tmp/'inputs', scratch=tmp/'scratch', context_id='')\n"
        "host._ORIGINAL_TRANSPORT = lambda payload: dict(payload)\n"
        "first = host._required_tool_transport({'messages':[],'tools':[{'name':'tracecite_state'}],'tool_choice':'auto'})\n"
        "assert first['tool_choice'] == 'required'\n"
        "runtime.call('tracecite_hypothesis', {'claim':'unknown cause','hypothesis_id':'H1','rationale':''})\n"
        "runtime.call('tracecite_test', {'hypothesis_id':'H1','intent':'determine cause','expected_observation':'evidence supports the proposed cause','contradicting_observation':'evidence contradicts or cannot establish the cause','test_id':'T1'})\n"
        "runtime.call('tracecite_assess_test', {'test_id':'T1','outcome':'unknown','evidence_refs':[]})\n"
        "runtime.call('tracecite_finding', {'hypothesis_id':'H1','outcome':'unknown','summary':'insufficient evidence','supporting_evidence':[],'contradicting_evidence':[],'limitations':['not enough evidence']})\n"
        "second = host._required_tool_transport({'messages':[],'tools':[{'name':'tracecite_state'}],'tool_choice':'auto'})\n"
        "assert second['tool_choice'] == 'auto'\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"
