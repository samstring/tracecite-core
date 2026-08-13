from __future__ import annotations

import argparse
import json
from pathlib import Path

from tracecite.runtime import scenario


def _spec(source: str = "logs/app.log") -> dict:
    return {
        "schema_version": 2,
        "name": "base-dir-test",
        "source": {"type": "file", "path": source},
        "filter": {"grep": "target"},
    }


def test_cmd_scenario_uses_explicit_base_dir(tmp_path: Path, capsys) -> None:
    bundle = tmp_path / "bundle"
    project = tmp_path / "project"
    bundle.mkdir()
    (project / "logs").mkdir(parents=True)
    spec_path = bundle / "scenario.json"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    (project / "logs" / "app.log").write_text("target\n", encoding="utf-8")

    args = argparse.Namespace(
        spec=str(spec_path),
        scenario_command="run",
        platform="",
        base_dir=str(project),
        json=True,
    )

    assert scenario.cmd_scenario(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["input_lineage"][0]["original"] == str(
        (project / "logs" / "app.log").resolve()
    )
    assert Path(payload["manifest_path"]).is_relative_to(project / ".tracecite" / "runs")

