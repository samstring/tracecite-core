from __future__ import annotations


def test_fast_jsonl_reuses_compiled_regex_matcher(monkeypatch) -> None:
    import tracecite.runtime.evidence_shell_fast_jsonl as fast

    fast._cached_matcher.cache_clear()
    real_matcher = fast.Matcher
    calls = 0

    def counted_matcher(pattern: str):
        nonlocal calls
        calls += 1
        return real_matcher(pattern)

    monkeypatch.setattr(fast, "Matcher", counted_matcher)
    stage = fast._Stage("regex", ("error.*timeout",))

    for _ in range(20):
        fast._matches({}, "error while waiting: timeout\n", stage)

    assert calls == 1
