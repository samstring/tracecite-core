from __future__ import annotations

import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

from tracecite_core.immutable import is_stable_source
from tracecite_core.output_layout import OutputLayout, load_output_config, write_output_config
from tracecite_core.segment_store import (
    StoredSegment,
    append_segment,
    load_segments,
    unique_segment_path,
)
from tracecite_core.live_cut import (
    LiveCutError,
    cooperative_live_cut,
    cut_done_path,
    cut_request_path,
    rename_live_segment,
)
from tracecite_core.state_file import atomic_write_json, read_json


def _append_segment_worker(store_dir: str, index: int, barrier) -> None:
    barrier.wait()
    append_segment(
        Path(store_dir),
        StoredSegment(
            start=f"2026-08-18T10:{index:02d}:00",
            end=f"2026-08-18T10:{index:02d}:30",
            path=f"/tmp/sealed-{index}.log",
            bytes=index + 1,
            lines=index + 1,
        ),
    )


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


def test_output_layout_remains_available_from_its_secondary_module() -> None:
    from tracecite_core.output_layout import DEFAULT_OUTPUT_ROOT, OutputLayout as ModuleOutputLayout

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


def test_append_segment_serializes_cross_process_read_modify_write(tmp_path: Path) -> None:
    store = tmp_path / "device"
    context = multiprocessing.get_context("fork")
    count = 8
    barrier = context.Barrier(count)
    processes = [
        context.Process(target=_append_segment_worker, args=(str(store), index, barrier))
        for index in range(count)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
    for process in processes:
        if process.is_alive():
            process.terminate()
            process.join()

    assert all(process.exitcode == 0 for process in processes)
    rows = load_segments(store)
    assert len(rows) == count
    assert {row.path for row in rows} == {
        f"/tmp/sealed-{index}.log" for index in range(count)
    }


def test_unique_segment_path_can_atomically_reserve_names(tmp_path: Path) -> None:
    start = end = datetime(2026, 8, 18, 10, 0)

    def reserve() -> Path:
        return unique_segment_path(
            tmp_path,
            start,
            end,
            prefix="sealed",
            reserve=True,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(lambda _index: reserve(), range(8)))

    assert len({path.name for path in paths}) == 8
    assert all(path.is_file() and path.stat().st_size == 0 for path in paths)


def test_rename_live_segment(tmp_path: Path) -> None:
    live = tmp_path / "live.log"
    live.write_text("payload\n", encoding="utf-8")
    dest = tmp_path / "sealed.log"
    rename_live_segment(live, dest)
    assert dest.read_text(encoding="utf-8") == "payload\n"
    assert live.read_text(encoding="utf-8") == ""


def test_rename_live_segment_rejects_same_path_without_clearing_evidence(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live.log"
    live.write_text("payload\n", encoding="utf-8")

    with pytest.raises(LiveCutError):
        rename_live_segment(live, live)

    assert live.read_text(encoding="utf-8") == "payload\n"


def test_rename_live_segment_rejects_existing_destination(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live.log"
    live.write_text("payload\n", encoding="utf-8")
    dest = tmp_path / "sealed.log"
    dest.write_text("keep\n", encoding="utf-8")

    with pytest.raises(LiveCutError):
        rename_live_segment(live, dest)

    assert live.read_text(encoding="utf-8") == "payload\n"
    assert dest.read_text(encoding="utf-8") == "keep\n"


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


def test_cooperative_live_cut_correlates_done_response(tmp_path: Path) -> None:
    live = tmp_path / "live.log"
    live.write_text("x\n", encoding="utf-8")
    request = cut_request_path(live, request_suffix=".cut.request")
    done = cut_done_path(live, done_suffix=".cut.done")
    seen = []
    stop = threading.Event()

    def writer() -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not stop.is_set():
            if request.is_file():
                payload = read_json(request)
                seen.append(payload)
                atomic_write_json(done, {"request_id": payload["request_id"], "ok": True})
                return
            time.sleep(0.01)

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    try:
        result = cooperative_live_cut(
            live,
            request_suffix=".cut.request",
            done_suffix=".cut.done",
            request_payload={"op": "cut"},
            deserialize=lambda data: data,
            direct_cut=lambda: {"ok": False},
            timeout_sec=0.5,
            poll_sec=0.01,
        )
    finally:
        stop.set()
        writer_thread.join(timeout=2)

    assert result == {"request_id": seen[0]["request_id"], "ok": True}
    assert seen[0]["request_id"]


def test_cooperative_live_cut_serializes_concurrent_fallbacks(tmp_path: Path) -> None:
    live = tmp_path / "live.log"
    live.write_text("x\n", encoding="utf-8")
    active = 0
    maximum_active = 0
    counters_lock = threading.Lock()

    def direct_cut() -> dict:
        nonlocal active, maximum_active
        with counters_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.05)
        with counters_lock:
            active -= 1
        return {"ok": True}

    def request() -> dict:
        return cooperative_live_cut(
            live,
            request_suffix=".cut.request",
            done_suffix=".cut.done",
            request_payload={"op": "cut"},
            deserialize=lambda data: data,
            direct_cut=direct_cut,
            timeout_sec=0.5,
            poll_sec=0.01,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: request(), range(2)))

    assert results == [{"ok": True}, {"ok": True}]
    assert maximum_active == 1
