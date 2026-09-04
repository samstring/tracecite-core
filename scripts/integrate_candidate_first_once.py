from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    tools = ROOT / "src/tracecite/runtime/tools.py"
    replace_once(
        tools,
        "from tracecite_core.text_filter import FilterError, filter_text, text_time_range\n",
        "from tracecite_core.text_filter import FilterError, text_time_range\n\nfrom .search_engine import search_text\n",
    )
    replace_once(
        tools,
        """        result = filter_text(\n            source,\n            pattern=pattern,\n            output_path=resolved_output,\n            snapshot=snapshot,\n            segmenter=build_segmenter(kind),\n            last=last,\n            since=since,\n            until=until,\n            template_threshold=10 if fold else 0,\n            max_line_chars=max_line_chars,\n        )\n""",
        """        result = search_text(\n            source,\n            pattern=pattern,\n            regex=regex,\n            output_path=resolved_output,\n            snapshot=snapshot,\n            segmenter=build_segmenter(kind),\n            last=last,\n            since=since,\n            until=until,\n            fold=fold,\n            max_line_chars=max_line_chars,\n        )\n""",
    )

    (ROOT / "src/tracecite/runtime/search_engine.py").write_text(
        '''from __future__ import annotations

"""Mechanical search dispatch for the canonical Runtime.

The fast path is deliberately conservative: exact literal searches over
single-line segmenters use the parity-tested candidate-first filter. Any
request outside that proven subset falls back to the legacy Core filter with
unchanged semantics. Multiline local-record recovery remains internal until its
artifact/result parity is proven at this boundary.
"""

from pathlib import Path
from typing import Optional

from tracecite_core.segmenter import Segmenter
from tracecite_core.text_filter import FilterResult, filter_text

from .candidate_filter import CandidateFilterUnsupported, filter_literal_single_line


def search_text(
    source: Path,
    *,
    pattern: str,
    regex: bool,
    output_path: Path,
    snapshot: bool,
    segmenter: Segmenter,
    last: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    fold: bool = False,
    max_line_chars: Optional[int] = None,
) -> FilterResult:
    """Execute one search with a correctness-preserving candidate-first fast path."""

    template_threshold = 10 if fold else 0
    if not regex:
        try:
            return filter_literal_single_line(
                source,
                pattern=pattern,
                output_path=output_path,
                snapshot=snapshot,
                segmenter=segmenter,
                last=last,
                since=since,
                until=until,
                template_threshold=template_threshold,
                max_line_chars=max_line_chars,
            )
        except CandidateFilterUnsupported:
            pass

    return filter_text(
        source,
        pattern=pattern,
        output_path=output_path,
        snapshot=snapshot,
        segmenter=segmenter,
        last=last,
        since=since,
        until=until,
        template_threshold=template_threshold,
        max_line_chars=max_line_chars,
    )


__all__ = ["search_text"]
''',
        encoding="utf-8",
    )

    (ROOT / "tests/test_runtime_search_engine.py").write_text(
        '''from __future__ import annotations

import re
from pathlib import Path

from tracecite.runtime import search_engine, tools
from tracecite.runtime.candidate_filter import CandidateFilterUnsupported
from tracecite_core.segmenter import RawTextSegmenter


def test_literal_search_uses_candidate_first_fast_path(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "plain.log"
    source.write_text("alpha\\nneedle one\\nbeta\\nneedle two\\n", encoding="utf-8")
    original = search_engine.filter_literal_single_line
    calls = 0

    def wrapped(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(search_engine, "filter_literal_single_line", wrapped)
    result = search_engine.search_text(
        source,
        pattern=re.escape("needle"),
        regex=False,
        output_path=tmp_path / "fast" / "evidence.log",
        snapshot=False,
        segmenter=RawTextSegmenter(mode="line"),
    )

    assert calls == 1
    assert result.match_records == 2


def test_regex_search_bypasses_candidate_first(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "plain.log"
    source.write_text("alpha\\nneedle one\\nneedle two\\n", encoding="utf-8")

    def unexpected(*args, **kwargs):
        raise AssertionError("regex search must not enter literal fast path")

    monkeypatch.setattr(search_engine, "filter_literal_single_line", unexpected)
    result = search_engine.search_text(
        source,
        pattern=r"needle\\s+(?:one|two)",
        regex=True,
        output_path=tmp_path / "legacy" / "evidence.log",
        snapshot=False,
        segmenter=RawTextSegmenter(mode="line"),
    )

    assert result.match_records == 2


def test_unsupported_fast_path_falls_back_to_legacy(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "plain.log"
    source.write_text("alpha\\nneedle\\nbeta\\n", encoding="utf-8")

    def unsupported(*args, **kwargs):
        raise CandidateFilterUnsupported("test fallback")

    monkeypatch.setattr(search_engine, "filter_literal_single_line", unsupported)
    result = search_engine.search_text(
        source,
        pattern=re.escape("needle"),
        regex=False,
        output_path=tmp_path / "fallback" / "evidence.log",
        snapshot=False,
        segmenter=RawTextSegmenter(mode="line"),
    )

    assert result.match_records == 1


def test_runtime_tools_search_routes_through_search_engine(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "plain.log"
    source.write_text("alpha\\nneedle\\n", encoding="utf-8")
    original = tools.search_text
    calls = 0

    def wrapped(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(tools, "search_text", wrapped)
    result = tools.search(source, "needle", snapshot=False, cache=False)

    assert calls == 1
    assert result["status"] == "ok"
    assert result["coverage"]["match_records"] == 1
''',
        encoding="utf-8",
    )

    en = ROOT / "docs/architecture.md"
    en_marker = "| Evidence Ledger + Context Engine / cross-turn delta | Implemented | `tracecite.integrations` |\n"
    en_row = "| Candidate-first literal search fast path | Implemented | Parity-proven single-line literal subset; Runtime search dispatch uses deterministic legacy fallback and multiline local recovery remains internal |\n"
    en_text = en.read_text(encoding="utf-8")
    if en_marker not in en_text:
        raise SystemExit("architecture.md status marker not found")
    if en_row not in en_text:
        en.write_text(en_text.replace(en_marker, en_row + en_marker, 1), encoding="utf-8")

    zh = ROOT / "docs/architecture.zh-CN.md"
    zh_marker = "| Evidence Ledger + Context Engine / cross-turn delta | 已实现 | `tracecite.integrations` |\n"
    zh_row = "| Candidate-first literal search fast path | 已实现 | parity 已证明的单行 literal 子集；Runtime search dispatch 使用确定性 legacy fallback，multiline local recovery 仍保持 internal |\n"
    zh_text = zh.read_text(encoding="utf-8")
    if zh_marker not in zh_text:
        raise SystemExit("architecture.zh-CN.md status marker not found")
    if zh_row not in zh_text:
        zh.write_text(zh_text.replace(zh_marker, zh_row + zh_marker, 1), encoding="utf-8")

    neutral = ROOT / "tests/test_pi_tracecite_runtime_neutral.py"
    neutral_text = neutral.read_text(encoding="utf-8")
    neutral.write_text(
        neutral_text.replace(
            "\n# candidate-first integration trigger; removed from process significance after this commit.\n",
            "\n",
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
