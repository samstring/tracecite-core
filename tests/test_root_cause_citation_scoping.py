from __future__ import annotations

from tracecite.root_cause_benchmarking import _evidence_filenames, _line_refs


def test_path_line_citation_requires_an_evidence_basename() -> None:
    text = (
        "Evidence build-log.txt:84522 shows the observed state. "
        "The stack also mentions kubeletconfig.go:186 and pkg/worker.go:77."
    )

    assert _line_refs(text, ("build-log.txt",)) == {84522}


def test_evidence_path_prefix_is_accepted_but_unrelated_source_path_is_not() -> None:
    text = "/tmp/run/inputs/runtime.log:12 fact; src/runtime.go:12 implementation"

    assert _line_refs(text, ("runtime.log",)) == {12}


def test_explicit_line_syntax_remains_supported_without_a_filename() -> None:
    text = "Evidence #L12, L14, and line 19. Source helper.go:88 is only a code location."

    assert _line_refs(text, ("runtime.log",)) == {12, 14, 19}


def test_evidence_filenames_cover_remote_and_local_case_inputs() -> None:
    case = {
        "inputs": [{"filename": "build-log.txt"}, {"filename": "nested/runtime.log"}],
        "local_inputs": [{"path": "fixtures/state.jsonl"}],
    }

    assert _evidence_filenames(case) == ("build-log.txt", "runtime.log", "state.jsonl")
