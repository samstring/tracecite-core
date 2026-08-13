from __future__ import annotations

import json
from pathlib import Path

import pytest
import re

from tracecite_core.matcher import PatternComponent, coerce_pattern_components
from tracecite_core.text_filter import FilterError, filter_text
from tracecite.runtime.runtime import ScenarioProfile, ScenarioRuntime
from tracecite.runtime.scenario import resolve_pattern_details, run_scenario


def test_filter_records_all_matching_components_deterministically(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("fatal checkout\ncheckout only\nother\n", encoding="utf-8")
    result = filter_text(
        source,
        pattern="(?:fatal)|(?:checkout)",
        pattern_components=[
            {"id": "preset:fault", "kind": "preset", "pattern": "fatal"},
            {"id": "grep", "kind": "grep", "pattern": "checkout"},
        ],
        output_path=tmp_path / "filtered.log",
    )

    rows = [
        json.loads(line)
        for line in result.records_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["metadata"]["matched_by"] for row in rows] == [
        ["preset:fault", "grep"],
        ["grep"],
    ]
    hits = [
        json.loads(line)
        for line in result.hits_path.read_text(encoding="utf-8").splitlines()
    ]
    assert hits[0]["matched_by"] == ["preset:fault", "grep"]
    assert result.matched_by_counts == {"grep": 2, "preset:fault": 1}


def test_scenario_resolver_is_one_effective_component(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("fatal\ncheckout\nscenario-only\n", encoding="utf-8")
    profile = ScenarioProfile(filter_presets={"fault": ("fatal", "fault")})

    def resolver(preset, scenario, start_dir, base_pattern, platform):
        return f"(?:{base_pattern})|(?:scenario-only)"

    runtime = ScenarioRuntime(
        load_profile=lambda start_dir, platform: profile,
        resolve_scenario_pattern=resolver,
    )
    details = resolve_pattern_details(
        {
            "filter": {
                "preset": "fault",
                "grep": "checkout",
                "scenario": "checkout-case",
            }
        },
        profile=profile,
        runtime=runtime,
    )
    assert details["pattern"] == "(?:(?:fatal)|(?:checkout))|(?:scenario-only)"
    by_id = {item["id"]: item for item in details["components"]}
    assert by_id["preset:fault"]["effective"] is False
    assert by_id["grep"]["effective"] is False
    assert by_id["scenario:checkout-case"]["effective"] is True

    spec = {
        "schema_version": 2,
        "name": "provenance",
        "source": {"type": "file", "path": str(source)},
        "parse": {"segmenter": "rawtext"},
        "filter": {
            "preset": "fault",
            "grep": "checkout",
            "scenario": "checkout-case",
        },
        "output": {"run_dir": str(tmp_path / "runs")},
    }
    summary = run_scenario(spec, base_dir=tmp_path, runtime=runtime)
    rows = [
        json.loads(line)
        for line in Path(summary["results"][0]["records_path"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert all(row["metadata"]["matched_by"] == ["scenario:checkout-case"] for row in rows)
    manifest = json.loads(Path(summary["manifest_path"]).read_text(encoding="utf-8"))
    provenance = manifest["parameters"]["filter"]
    assert provenance["match_mode"] == "or"
    assert provenance["preset"]["name"] == "fault"
    assert provenance["preset"]["version"] == "unknown"
    assert provenance["components"][-1]["id"] == "scenario:checkout-case"


def test_preset_metadata_keeps_explicit_version_source_and_hash(tmp_path: Path) -> None:
    profile = ScenarioProfile(
        filter_presets={
            "fault": {
                "pattern": "fatal",
                "tag": "fault",
                "version": "2026.08",
                "source": "knowledge.json",
                "sha256": "abc123",
            }
        }
    )
    details = resolve_pattern_details(
        {"filter": {"preset": "fault"}}, profile=profile
    )
    assert details["preset"] == {
        "name": "fault",
        "tag": "fault",
        "version": "2026.08",
        "source": "knowledge.json",
        "sha256": "abc123",
    }


def test_component_metadata_and_ids_are_bounded_and_json_safe() -> None:
    with pytest.raises(ValueError, match="id 必须匹配"):
        coerce_pattern_components([{"id": "bad id", "pattern": "x"}])
    with pytest.raises(ValueError, match="id 必须匹配"):
        coerce_pattern_components([{"id": "a" * 97, "pattern": "x"}])
    with pytest.raises(ValueError, match="JSON-safe"):
        coerce_pattern_components([{"id": "grep", "pattern": "x", "object": object()}])
    with pytest.raises(ValueError, match="嵌套"):
        coerce_pattern_components(
            [{"id": "grep", "pattern": "x", "nested": {"a": {"b": {"c": {"d": 1}}}}}]
        )

    component = PatternComponent(
        "grep",
        "x",
        kind="grep",
        metadata={"id": "evil", "pattern": "evil", "effective": False, "kind": "evil", "note": "ok"},
    )
    payload = component.to_dict()
    assert payload["id"] == "grep"
    assert payload["pattern"] == "x"
    assert payload["effective"] is True
    assert payload["kind"] == "grep"
    assert payload["note"] == "ok"


def test_mismatch_uses_explicit_reserved_pattern_fallback(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("fatal\n", encoding="utf-8")
    result = filter_text(
        source,
        pattern="fatal",
        pattern_components=[{"id": "grep", "kind": "grep", "pattern": "checkout"}],
        output_path=tmp_path / "filtered.log",
    )
    assert result.matched_by_fallback is True
    assert result.matched_by_counts == {"pattern": 1}
    fallback = next(item for item in result.pattern_components or [] if item["id"] == "pattern")
    assert fallback["reserved"] is True
    assert fallback["fallback"] is True
    assert fallback["pattern_ref"] == "final"
    row = json.loads(result.records_path.read_text(encoding="utf-8"))
    assert row["metadata"]["matched_by"] == ["pattern"]


def test_unsafe_long_component_names_use_safe_ids_and_bounded_metadata() -> None:
    preset_name = "异常 preset/name " + ("x" * 320)
    profile = ScenarioProfile(
        filter_presets={
            preset_name: {
                "pattern": "fatal",
                "tag": "tag/" + ("t" * 320),
                "version": "v" * 400,
                "source": "source/" + ("s" * 400),
                "sha256": "h" * 400,
            }
        }
    )
    details = resolve_pattern_details(
        {"filter": {"preset": preset_name}}, profile=profile
    )
    component = details["components"][0]
    assert component["id"].startswith("preset:")
    assert len(component["id"]) <= 96
    assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}", component["id"])
    assert details["preset"]["name_truncated"] is True
    assert len(details["preset"]["name"]) == 256
    assert details["preset"]["version_truncated"] is True
    assert len(details["preset"]["source"]) == 256
    assert details["preset"]["sha256_truncated"] is True

    scenario_name = "场景/" + ("y" * 320)
    runtime = ScenarioRuntime(
        load_profile=lambda start_dir, platform: profile,
        resolve_scenario_pattern=lambda preset, scenario, start_dir, base, platform: base,
    )
    scenario_details = resolve_pattern_details(
        {
            "filter": {
                "preset": preset_name,
                "scenario": scenario_name,
            }
        },
        profile=profile,
        runtime=runtime,
    )
    scenario_component = scenario_details["components"][-1]
    assert scenario_component["id"].startswith("scenario:")
    assert len(scenario_component["id"]) <= 96
    assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}", scenario_component["id"])
    assert scenario_details["scenario"]["name_truncated"] is True
    assert len(scenario_details["scenario"]["name"]) == 256
