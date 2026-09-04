from __future__ import annotations

import re
from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing expected block: {label}")
    return text.replace(old, new, 1)


# Scale benchmark uses canonical search semantics; result-page caps are now an
# internal PROGRESSIVE routing concern.
scale_path = Path("benchmarks/agent-investigation/gmi_scale_host.py")
scale = scale_path.read_text(encoding="utf-8")
scale = replace_once(
    scale,
    '''            snapshot=False,\n            segmenter="auto",\n            max_evidence=None,\n            max_line_chars=None,\n            cache=True,''',
    '''            snapshot=False,\n            segmenter="auto",\n            cache=True,''',
    label="scale host legacy search caps",
)
scale_path.write_text(scale, encoding="utf-8")


# Source-identity projection is unrelated to candidate-page sizing.
pi_identity_path = Path("tests/test_pi_source_identity_projection.py")
pi_identity = pi_identity_path.read_text(encoding="utf-8")
pi_identity = replace_once(
    pi_identity,
    '''        "--query",\n        "goroutine",\n        "--max-evidence",\n        "3",\n''',
    '''        "--query",\n        "goroutine",\n''',
    label="Pi identity legacy max-evidence flag",
)
pi_identity_path.write_text(pi_identity, encoding="utf-8")


# Replace old CLI configurability/default tests with the new public-contract
# invariant: candidate/body page limits are not user-visible search options.
runtime_cli_path = Path("tests/test_runtime_cli.py")
runtime_cli = runtime_cli_path.read_text(encoding="utf-8")
runtime_cli = re.sub(
    r'def test_search_agent_limits_are_configurable\(monkeypatch, capsys\) -> None:.*?\n\n\ndef test_search_agent_limits_use_updated_defaults\(monkeypatch, capsys\) -> None:.*?assert calls\["max_line_chars"\] == cli\.DEFAULT_FILTER_MAX_LINE_CHARS\n',
    '''def test_search_does_not_expose_candidate_or_line_budget_flags() -> None:\n    parser = cli.build_parser(prog="tracecite")\n    search_parser = next(\n        action.choices["search"]\n        for action in parser._actions\n        if getattr(action, "choices", None) and "search" in action.choices\n    )\n    option_strings = {\n        option\n        for action in search_parser._actions\n        for option in action.option_strings\n    }\n    assert "--max-evidence" not in option_strings\n    assert "--max-line-chars" not in option_strings\n\n\ndef test_search_default_call_does_not_forward_candidate_or_line_budget(monkeypatch, capsys) -> None:\n    calls: dict[str, object] = {}\n\n    def fake_search(*args, **kwargs):\n        calls.update(kwargs)\n        return _search_payload()\n\n    monkeypatch.setattr(cli, "search", fake_search)\n\n    assert cli.main(["search", "events.log", "matching"]) == 0\n    assert "max_evidence" not in calls\n    assert "max_line_chars" not in calls\n''',
    runtime_cli,
    count=1,
    flags=re.S,
)
runtime_cli_path.write_text(runtime_cli, encoding="utf-8")


# Stateful CLI still proves typed canonical routing, but page-size knobs must no
# longer appear in argv or QueryTarget.
stateful_path = Path("tests/test_stateful_cli.py")
stateful = stateful_path.read_text(encoding="utf-8")
stateful = stateful.replace('"data": {"routing": {"route": "bounded"}}', '"data": {"routing": {"route": "progressive"}}')
stateful = replace_once(
    stateful,
    '''            "--fold",\n            "--max-evidence",\n            "7",\n            "--max-line-chars",\n            "99",\n            "--no-cache",''',
    '''            "--fold",\n            "--no-cache",''',
    label="stateful CLI legacy flags",
)
stateful = replace_once(
    stateful,
    '''    assert request.target.fold is True\n    assert request.target.max_evidence == 7\n    assert request.target.max_line_chars == 99\n    assert request.cache is False''',
    '''    assert request.target.fold is True\n    assert "max_evidence" not in request.target.__dataclass_fields__\n    assert "max_line_chars" not in request.target.__dataclass_fields__\n    assert request.cache is False''',
    label="stateful QueryTarget legacy assertions",
)
stateful = stateful.replace('assert payload["data"]["routing"]["route"] == "bounded"', 'assert payload["data"]["routing"]["route"] == "progressive"')
stateful_path.write_text(stateful, encoding="utf-8")

print("full-suite candidate limit cleanup applied")
