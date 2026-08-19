from __future__ import annotations

from pathlib import Path

from tracecite_core.immutable import is_stable_source
from tracecite_core.output_layout import OutputLayout, load_output_config, write_output_config
from tracecite_core.segment_store import StoredSegment, append_segment, load_segments, unique_segment_path
from tracecite_core.live_cut import cooperative_live_cut, rename_live_segment


def test_is_stable_source() -> None:
    archive = Path("/tmp/log/.archive/device/sealed_20260101-20260102.log")
    assert is_stable_source(archive) is True
    assert is_stable_source(Path("/tmp/log/ios_live_phone.log")) is False


def test_output_layout_loads_defaults(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "output.json"
    monkeypatch.setattr(
        "tracecite_core.output_layout.USER_OUTPUT_CONFIG_PATH",
        config_path,
    )
    layout = OutputLayout.load(defaults={"output_root": "~/Documents/TraceCite", "plugins": {}})
    assert layout.output_root == (Path.home() / "Documents" / "TraceCite").resolve()


def test_output_layout_is_public_from_tracecite_root() -> None:
    import tracecite
    from tracecite import DEFAULT_OUTPUT_ROOT, OutputLayout, load_output_config, write_output_config
    from tracecite.output_layout import OutputLayout as ModuleOutputLayout

    assert tracecite.OutputLayout is OutputLayout
    assert ModuleOutputLayout is OutputLayout
    assert DEFAULT_OUTPUT_ROOT == "~/Documents/TraceCite"
    assert callable(load_output_config)
    assert callable(write_output_config)


def test_segment_store_roundtrip(tmp_path: Path) -> None:
    store = tmp_path / "device"
    segment = StoredSegment(
        start="2026-08-18T10:00:00",
        end="2026-08-18T10:01:00",
        path=str(tmp_path / "sealed.log"),
        bytes=12,
        lines=2,
    )
    append_segment(store, segment)
    rows = load_segments(store)
    assert len(rows) == 1
    assert rows[0].path == segment.path


def test_rename_live_segment(tmp_path: Path) -> None:
    live = tmp_path / "live.log"
    live.write_text("payload\n", encoding="utf-8")
    dest = tmp_path / "sealed.log"
    rename_live_segment(live, dest)
    assert dest.read_text(encoding="utf-8") == "payload\n"
    assert live.read_text(encoding="utf-8") == ""


def test_cooperative_live_cut_fallback(tmp_path: Path) -> None:
    live = tmp_path / "live.log"
    live.write_text("x\n", encoding="utf-8")

    result = cooperative_live_cut(
        live,
        request_suffix=".cut.request",
        done_suffix=".cut.done",
        request_payload={"op": "cut"},
        deserialize=lambda data: data,
        direct_cut=lambda: {"sealed": str(tmp_path / "out.log")},
        timeout_sec=0.2,
        poll_sec=0.02,
    )
    assert result["sealed"].endswith("out.log")
