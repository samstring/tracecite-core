from __future__ import annotations

import json

from tracecite_core.cli import build_parser, main


def test_core_cli_filter_smoke(tmp_path, capsys) -> None:
    source = tmp_path / "example.log"
    source.write_text("ok\ntimeout\n", encoding="utf-8")
    assert main(["filter", str(source), "--grep", "timeout", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["match_records"] == 1


def test_core_cli_is_independent() -> None:
    parser = build_parser()
    assert parser.prog == "tracecite-core"
    assert parser.parse_args(["plugin"]).command == "plugin"

