from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src/tracecite/runtime"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old[:140]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    tools_path = RUNTIME / "tools.py"
    acquisition_path = RUNTIME / "acquisition.py"
    tools_text = tools_path.read_text(encoding="utf-8")
    acquisition_text = tools_text.replace(
        '"""Small, deterministic tool surface intended for AI agents."""',
        '"""Canonical deterministic acquisition implementation for Evidence Runtime."""',
        1,
    )
    acquisition_path.write_text(acquisition_text, encoding="utf-8")

    tools_path.write_text(
        '''"""Backward-compatible ``runtime.tools`` surface over canonical acquisition.\n\nRuntime internals must depend on :mod:`tracecite.runtime.acquisition`; this\nmodule remains only for legacy callers and integrations while preserving the\nexisting Python surface.\n"""\n\nfrom __future__ import annotations\n\nfrom . import acquisition as _acquisition\nfrom .acquisition import *  # noqa: F401,F403\n\n\ndef __getattr__(name: str):\n    return getattr(_acquisition, name)\n\n\ndef __dir__() -> list[str]:\n    return sorted(set(globals()) | set(dir(_acquisition)))\n''',
        encoding="utf-8",
    )

    for path in sorted(RUNTIME.glob("*.py")):
        if path.name in {"tools.py", "acquisition.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        if "from . import tools as _tools" in text:
            text = text.replace(
                "from . import tools as _tools",
                "from . import acquisition as _acquisition",
            ).replace("_tools.", "_acquisition.")
        text = text.replace("from .tools import", "from .acquisition import")
        if text != original:
            path.write_text(text, encoding="utf-8")

    forbidden_runtime_imports: list[str] = []
    for path in sorted(RUNTIME.glob("*.py")):
        if path.name == "tools.py":
            continue
        text = path.read_text(encoding="utf-8")
        if (
            "from . import tools" in text
            or "from .tools import" in text
            or "tracecite.runtime.tools" in text
        ):
            forbidden_runtime_imports.append(path.name)
    if forbidden_runtime_imports:
        raise SystemExit(
            "Runtime internals still depend on compatibility tools module: "
            + ", ".join(forbidden_runtime_imports)
        )

    budget = ROOT / "tests/test_budget_cache.py"
    budget_text = budget.read_text(encoding="utf-8")
    if "from tracecite.runtime import acquisition\n" not in budget_text:
        budget_text = budget_text.replace(
            "from tracecite.runtime import tools\n",
            "from tracecite.runtime import acquisition\nfrom tracecite.runtime import tools\n",
            1,
        )
    budget_text = budget_text.replace(
        "original_search = tools.search_text",
        "original_search = acquisition.search_text",
    )
    budget_text = budget_text.replace(
        'monkeypatch.setattr(tools, "search_text", mutate_before_snapshot)',
        'monkeypatch.setattr(acquisition, "search_text", mutate_before_snapshot)',
    )
    budget_text = budget_text.replace(
        'monkeypatch.setattr(tools, "search_text", original_search)',
        'monkeypatch.setattr(acquisition, "search_text", original_search)',
    )
    budget_text = budget_text.replace(
        'monkeypatch.setattr(tools, "search_text", should_not_scan)',
        'monkeypatch.setattr(acquisition, "search_text", should_not_scan)',
    )
    budget.write_text(budget_text, encoding="utf-8")

    search_test = ROOT / "tests/test_runtime_search_engine.py"
    search_test.write_text(
        '''from __future__ import annotations\n\nimport re\nfrom pathlib import Path\n\nfrom tracecite.runtime import acquisition, search_engine, tools\nfrom tracecite.runtime.candidate_filter import CandidateFilterUnsupported\nfrom tracecite_core.segmenter import RawTextSegmenter\n\n\ndef test_literal_search_uses_candidate_first_fast_path(tmp_path: Path, monkeypatch) -> None:\n    source = tmp_path / "plain.log"\n    source.write_text("alpha\\nneedle one\\nbeta\\nneedle two\\n", encoding="utf-8")\n    original = search_engine.filter_literal_single_line\n    calls = 0\n\n    def wrapped(*args, **kwargs):\n        nonlocal calls\n        calls += 1\n        return original(*args, **kwargs)\n\n    monkeypatch.setattr(search_engine, "filter_literal_single_line", wrapped)\n    result = search_engine.search_text(\n        source,\n        pattern=re.escape("needle"),\n        regex=False,\n        output_path=tmp_path / "fast" / "evidence.log",\n        snapshot=False,\n        segmenter=RawTextSegmenter(mode="line"),\n    )\n\n    assert calls == 1\n    assert result.match_records == 2\n\n\ndef test_regex_search_bypasses_candidate_first(tmp_path: Path, monkeypatch) -> None:\n    source = tmp_path / "plain.log"\n    source.write_text("alpha\\nneedle one\\nneedle two\\n", encoding="utf-8")\n\n    def unexpected(*args, **kwargs):\n        raise AssertionError("regex search must not enter literal fast path")\n\n    monkeypatch.setattr(search_engine, "filter_literal_single_line", unexpected)\n    result = search_engine.search_text(\n        source,\n        pattern=r"needle\\s+(?:one|two)",\n        regex=True,\n        output_path=tmp_path / "legacy" / "evidence.log",\n        snapshot=False,\n        segmenter=RawTextSegmenter(mode="line"),\n    )\n\n    assert result.match_records == 2\n\n\ndef test_unsupported_fast_path_falls_back_to_legacy(tmp_path: Path, monkeypatch) -> None:\n    source = tmp_path / "plain.log"\n    source.write_text("alpha\\nneedle\\nbeta\\n", encoding="utf-8")\n\n    def unsupported(*args, **kwargs):\n        raise CandidateFilterUnsupported("test fallback")\n\n    monkeypatch.setattr(search_engine, "filter_literal_single_line", unsupported)\n    result = search_engine.search_text(\n        source,\n        pattern=re.escape("needle"),\n        regex=False,\n        output_path=tmp_path / "fallback" / "evidence.log",\n        snapshot=False,\n        segmenter=RawTextSegmenter(mode="line"),\n    )\n\n    assert result.match_records == 1\n\n\ndef test_runtime_acquisition_search_routes_through_search_engine(tmp_path: Path, monkeypatch) -> None:\n    source = tmp_path / "plain.log"\n    source.write_text("alpha\\nneedle\\n", encoding="utf-8")\n    original = acquisition.search_text\n    calls = 0\n\n    def wrapped(*args, **kwargs):\n        nonlocal calls\n        calls += 1\n        return original(*args, **kwargs)\n\n    monkeypatch.setattr(acquisition, "search_text", wrapped)\n    result = acquisition.search(source, "needle", snapshot=False, cache=False)\n\n    assert calls == 1\n    assert result["status"] == "ok"\n    assert result["coverage"]["match_records"] == 1\n\n\ndef test_tools_search_is_compatibility_alias() -> None:\n    assert tools.search is acquisition.search\n''',
        encoding="utf-8",
    )

    boundary_test = ROOT / "tests/test_runtime_acquisition_boundary.py"
    boundary_test.write_text(
        '''from pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[1]\nRUNTIME = ROOT / "src" / "tracecite" / "runtime"\n\n\ndef test_canonical_runtime_does_not_depend_on_compatibility_tools() -> None:\n    offenders: list[str] = []\n    for path in sorted(RUNTIME.glob("*.py")):\n        if path.name == "tools.py":\n            continue\n        text = path.read_text(encoding="utf-8")\n        if "from . import tools" in text or "from .tools import" in text or "tracecite.runtime.tools" in text:\n            offenders.append(path.name)\n    assert offenders == []\n\n\ndef test_tools_module_is_only_a_compatibility_surface() -> None:\n    text = (RUNTIME / "tools.py").read_text(encoding="utf-8")\n    assert "Backward-compatible ``runtime.tools`` surface" in text\n    assert "from .acquisition import *" in text\n    assert "def search(" not in text\n    assert "def expand(" not in text\n\n\ndef test_acquisition_module_owns_search_implementation() -> None:\n    text = (RUNTIME / "acquisition.py").read_text(encoding="utf-8")\n    assert "Canonical deterministic acquisition implementation" in text\n    assert "def search(" in text\n    assert "def probe(" in text\n    assert "def expand(" in text\n''',
        encoding="utf-8",
    )

    en = ROOT / "docs/architecture.md"
    en_text = en.read_text(encoding="utf-8")
    en_runtime = "Owns canonical evidence mechanics, including RetrievalSession, bounded routing/selection, novelty/repetition/Coverage/acquisition-end facts, identity/correlation safety, deterministic aggregation/traversal, and optional InvestigationState coordination.\n"
    en_extra = en_runtime + "\nCanonical local acquisition is implemented in `tracecite.runtime.acquisition`. `tracecite.runtime.tools` is a compatibility facade for legacy callers/integrations and is not an internal Runtime dependency.\n"
    if en_runtime not in en_text:
        raise SystemExit("architecture.md Runtime ownership paragraph not found")
    if "Canonical local acquisition is implemented in `tracecite.runtime.acquisition`" not in en_text:
        en_text = en_text.replace(en_runtime, en_extra, 1)
    en_marker = "| Candidate-first literal search fast path | Implemented | Parity-proven single-line literal subset; Runtime search dispatch uses deterministic legacy fallback and multiline local recovery remains internal |\n"
    en_row = "| Canonical acquisition implementation ownership | Implemented | `tracecite.runtime.acquisition` owns deterministic acquisition; `runtime.tools` is compatibility-only |\n"
    if en_marker not in en_text:
        raise SystemExit("architecture.md implementation marker not found")
    if en_row not in en_text:
        en_text = en_text.replace(en_marker, en_marker + en_row, 1)
    en.write_text(en_text, encoding="utf-8")

    zh = ROOT / "docs/architecture.zh-CN.md"
    zh_text = zh.read_text(encoding="utf-8")
    zh_runtime = "负责 canonical Evidence mechanics，包括 RetrievalSession、bounded routing/selection、novelty/repetition/Coverage/acquisition-end facts、identity/correlation safety、deterministic aggregate/traverse，以及可选 InvestigationState coordination。\n"
    zh_extra = zh_runtime + "\n本地 canonical acquisition 的唯一实现位于 `tracecite.runtime.acquisition`。`tracecite.runtime.tools` 仅保留为旧调用方/Integration 的兼容 facade，Runtime 内部不得再依赖它。\n"
    if zh_runtime not in zh_text:
        raise SystemExit("architecture.zh-CN.md Runtime ownership paragraph not found")
    if "本地 canonical acquisition 的唯一实现位于 `tracecite.runtime.acquisition`" not in zh_text:
        zh_text = zh_text.replace(zh_runtime, zh_extra, 1)
    zh_marker = "| Candidate-first literal search fast path | 已实现 | parity 已证明的单行 literal 子集；Runtime search dispatch 使用确定性 legacy fallback，multiline local recovery 仍保持 internal |\n"
    zh_row = "| Canonical acquisition 实现归属 | 已实现 | `tracecite.runtime.acquisition` 负责确定性 acquisition；`runtime.tools` 仅为 compatibility surface |\n"
    if zh_marker not in zh_text:
        raise SystemExit("architecture.zh-CN.md implementation marker not found")
    if zh_row not in zh_text:
        zh_text = zh_text.replace(zh_marker, zh_marker + zh_row, 1)
    zh.write_text(zh_text, encoding="utf-8")


if __name__ == "__main__":
    main()
