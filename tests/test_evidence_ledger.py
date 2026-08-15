from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracecite.integrations import cli
from tracecite.integrations.evidence_ledger import EvidenceLedger, expand_many
from tracecite.runtime.tools import expand, search


def _stored_search(tmp_path: Path) -> tuple[EvidenceLedger, str, dict]:
    source = tmp_path / "events.log"
    source.write_text("alpha\ntarget one\nbeta\ntarget two\nomega\n", encoding="utf-8")
    result = search(source, "target", output_path=tmp_path / "evidence.log")
    ledger = EvidenceLedger(tmp_path / "ledger")
    return ledger, ledger.store(result), result


def test_ledger_round_trips_and_verifies_canonical_result(tmp_path: Path) -> None:
    ledger, result_id, canonical = _stored_search(tmp_path)

    assert len(result_id) == 64
    assert ledger.load(result_id) == canonical
    assert ledger.store(canonical) == result_id

    entry = ledger.root / result_id[:2] / f"{result_id}.json"
    record = json.loads(entry.read_text(encoding="utf-8"))
    record["result"]["data"]["query"] = "tampered"
    entry.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="content verification"):
        ledger.load(result_id)


def test_expand_many_recovers_selected_refs_with_explicit_coverage(tmp_path: Path) -> None:
    ledger, result_id, canonical = _stored_search(tmp_path)
    refs = [pointer["uri"].split("#", 1)[1] for pointer in canonical["evidence"]]
    refs = [f"#{ref}" for ref in refs]

    result = expand_many(ledger, result_id, refs + ["#L999"], before=1, after=1)

    assert result["status"] == "ok"
    assert result["outcome"] == "unknown"
    columns = result["evidence"]["columns"]
    rows = [dict(zip(columns, row)) for row in result["evidence"]["rows"]]
    assert [row["ref"] for row in rows] == refs
    assert {row["context"] for row in rows} == {"c1"}
    assert len(result["contexts"]) == 1
    assert "target one" in result["contexts"][0]["text"]
    assert "target two" in result["contexts"][0]["text"]
    assert result["coverage"]["requested"] == 3
    assert result["coverage"]["returned"] == 2
    assert result["coverage"]["contexts"] == 1
    assert result["coverage"]["merged_contexts"] == 1
    assert result["coverage"]["missing_refs"] == ["#L999"]
    assert result["coverage"]["truncated"] is True
    merged_text = result["contexts"][0]["text"]
    for pointer in canonical["evidence"]:
        direct = expand(
            pointer["source_path"],
            pointer["start_line"],
            end_line=pointer["end_line"],
            expected_sha256=pointer["sha256"],
            before=0,
            after=0,
            cache=False,
        )
        assert direct["data"]["text"] in merged_text


def test_expand_many_cli_returns_bounded_valid_json(tmp_path: Path, capsys) -> None:
    ledger, result_id, canonical = _stored_search(tmp_path)
    refs = [pointer["uri"].split("#", 1)[1] for pointer in canonical["evidence"]]

    assert cli.main(
        [
            "expand-many",
            str(ledger.root),
            result_id,
            *[f"#{ref}" for ref in refs],
            "--before",
            "1",
            "--after",
            "1",
            "--max-output-chars",
            "1024",
        ]
    ) == 0
    rendered = capsys.readouterr().out.strip()
    payload = json.loads(rendered)

    assert len(rendered) <= 1024
    assert payload["operation"] == "expand_many"
    assert payload["coverage"]["returned"] == 2
    assert payload["coverage"]["contexts"] == 1
    assert "target one" in payload["contexts"][0]["text"]
