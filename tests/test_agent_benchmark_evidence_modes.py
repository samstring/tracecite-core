from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


BENCH_DIR = Path(__file__).resolve().parents[1] / "benchmarks" / "agent-investigation"
RUNNER = BENCH_DIR / "run_host.py"
GMI_HOST = BENCH_DIR / "gmi_host.py"
RAW_HOST_V2 = BENCH_DIR / "gmi_raw_host_v2.py"
SCALE_HOST = BENCH_DIR / "gmi_scale_host.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("tracecite_benchmark_run_host", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_gmi_host():
    sys.path.insert(0, str(BENCH_DIR))
    try:
        spec = importlib.util.spec_from_file_location("tracecite_benchmark_gmi_host", GMI_HOST)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(BENCH_DIR))


def _load_raw_host_v2():
    sys.path.insert(0, str(BENCH_DIR))
    try:
        spec = importlib.util.spec_from_file_location("tracecite_benchmark_gmi_raw_host_v2", RAW_HOST_V2)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(BENCH_DIR))


def _load_scale_host():
    sys.path.insert(0, str(BENCH_DIR))
    try:
        spec = importlib.util.spec_from_file_location("tracecite_benchmark_gmi_scale_host", SCALE_HOST)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(BENCH_DIR))


def _restore_raw_host_globals(module) -> None:
    module.base.BenchmarkToolRuntime = module.InspectFirstRuntime.__mro__[1]
    module.base._post_chat = module._ORIGINAL_POST_CHAT
    module.common._tools_for_mode = module._ORIGINAL_TOOLS_FOR_MODE


def _restore_scale_host_globals(module) -> None:
    module.base.BenchmarkToolRuntime = module.ScaleRuntime.__mro__[1]
    module.base._post_chat = module._ORIGINAL_POST_CHAT
    module.common._tools_for_mode = module._ORIGINAL_TOOLS_FOR_MODE


def test_agent_benchmark_exposes_six_comparable_modes() -> None:
    runner = _load_runner()
    assert runner.MODES == (
        "shell_rg",
        "free_shell",
        "tracecite",
        "tracecite_context",
        "tracecite_intelligence",
        "tracecite_investigate",
    )
    assert runner.STATEFUL_MODES == frozenset(
        {"tracecite_context", "tracecite_intelligence", "tracecite_investigate"}
    )


def test_complete_inspection_blocks_redundant_searches() -> None:
    module = _load_raw_host_v2()
    try:
        runtime = object.__new__(module.InspectFirstRuntime)
        runtime._fully_inspected = {"evidence.txt": (37, 37)}

        output = runtime._tracecite_search(
            {"file": "evidence.txt", "query": "different synonym", "regex": False}
        )

        assert output.startswith("NO_NEW_EVIDENCE:")
        assert "37/37 evidence records returned" in output
        assert "reason from them" in output
    finally:
        _restore_raw_host_globals(module)


def test_complete_coverage_marker_is_detected() -> None:
    module = _load_raw_host_v2()
    try:
        match = module._COVERAGE_RE.search(
            "@COV evidence_available=37 evidence_returned=37 "
            "evidence_truncated=False match_lines=37"
        )
        assert match is not None
        assert match.groups() == ("37", "37", "False")
    finally:
        _restore_raw_host_globals(module)


def test_scale_host_uses_inspect_get_then_search_tools(tmp_path: Path) -> None:
    module = _load_scale_host()
    try:
        evidence = tmp_path / "evidence.log"
        evidence.write_text("one\ntwo\n", encoding="utf-8")
        runtime = module.ScaleRuntime(
            mode="tracecite",
            input_root=tmp_path,
            scratch=tmp_path,
            context_id="",
        )
        names = [item["name"] for item in module._tools_for_mode("tracecite", runtime.files)]
        assert names == ["tracecite_inspect", "tracecite_get", "tracecite_search"]
    finally:
        _restore_scale_host_globals(module)


def test_scale_inspect_surfaces_generic_incident_window_and_line_refs(tmp_path: Path) -> None:
    module = _load_scale_host()
    try:
        evidence = tmp_path / "evidence.log"
        evidence.write_text(
            "normal start\n"
            "request begins\n"
            "worker IOException: checksum mismatch while reading payload\n"
            "reporting affected resource\n"
            "retry from replica\n"
            "normal end\n",
            encoding="utf-8",
        )
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        runtime = module.ScaleRuntime(
            mode="tracecite",
            input_root=tmp_path,
            scratch=scratch,
            context_id="",
        )
        runtime._survey = lambda path: '{"status":"ok","coverage":{"lines_scanned":6},"data":{"levels":[{"level":"ERROR","count":1}],"top_templates":[]}}'

        output = runtime._tracecite_inspect({"file": "evidence.log"})

        assert output.startswith("@TCI 1 inspect status=ok")
        assert "incident_signal_lines=1" in output
        assert "#L3\tworker IOException: checksum mismatch while reading payload" in output
        assert "#L4\treporting affected resource" in output
        assert "source_scan_complete=True" in output
    finally:
        _restore_scale_host_globals(module)


def test_scale_get_recovers_known_line_window(tmp_path: Path) -> None:
    module = _load_scale_host()
    try:
        evidence = tmp_path / "evidence.log"
        evidence.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        runtime = module.ScaleRuntime(
            mode="tracecite",
            input_root=tmp_path,
            scratch=scratch,
            context_id="",
        )
        runtime._inspected_files.add("evidence.log")

        output = runtime._tracecite_get({"file": "evidence.log", "line": 3, "radius": 1})

        assert "#L2\ttwo" in output
        assert "#L3\tthree" in output
        assert "#L4\tfour" in output
        assert "#L1\tone" not in output
    finally:
        _restore_scale_host_globals(module)


def test_scale_numeric_search_is_routed_to_get(tmp_path: Path) -> None:
    module = _load_scale_host()
    try:
        evidence = tmp_path / "evidence.log"
        evidence.write_text("one\ntwo\n", encoding="utf-8")
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        runtime = module.ScaleRuntime(
            mode="tracecite",
            input_root=tmp_path,
            scratch=scratch,
            context_id="",
        )
        runtime._inspected_files.add("evidence.log")

        output = runtime._tracecite_search_scale(
            {"file": "evidence.log", "query": "1404", "regex": False}
        )

        assert output.startswith("USE_GET:")
        assert "tracecite_get" in output
    finally:
        _restore_scale_host_globals(module)


def test_scale_search_has_no_benchmark_specific_caps(tmp_path: Path) -> None:
    module = _load_scale_host()
    try:
        evidence = tmp_path / "evidence.log"
        evidence.write_text("one\ntwo\n", encoding="utf-8")
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        runtime = module.ScaleRuntime(
            mode="tracecite",
            input_root=tmp_path,
            scratch=scratch,
            context_id="",
        )
        runtime._inspected_files.add("evidence.log")
        captured: dict[str, object] = {}

        class SearchCaptured(RuntimeError):
            pass

        def fake_search(path, query, **kwargs):
            captured["path"] = path
            captured["query"] = query
            captured.update(kwargs)
            raise SearchCaptured

        module.tracecite_search = fake_search
        try:
            runtime._tracecite_search_scale(
                {"file": "evidence.log", "query": "one", "regex": False}
            )
        except SearchCaptured:
            pass
        else:
            raise AssertionError("scale search did not invoke canonical tracecite_search")

        assert captured["path"] == evidence
        assert captured["query"] == "one"
        assert captured["snapshot"] is False
        assert captured["max_evidence"] is None
        assert captured["max_line_chars"] is None
        assert captured["cache"] is True
    finally:
        _restore_scale_host_globals(module)


def test_gmi_output_limit_marks_final_as_incomplete() -> None:
    module = _load_gmi_host()
    assert module._incomplete_final(
        visible="partial answer",
        usage={"output_tokens": 1600},
        finish_reason=None,
        max_output_tokens=1600,
    )
    assert module._incomplete_final(
        visible="",
        usage={"output_tokens": 900},
        finish_reason="length",
        max_output_tokens=1600,
    )
    assert not module._incomplete_final(
        visible="complete answer",
        usage={"output_tokens": 900},
        finish_reason="stop",
        max_output_tokens=1600,
    )
