from __future__ import annotations

from tracecite_core.matcher import Matcher


def test_single_literal_query_uses_c_substring_engine() -> None:
    matcher = Matcher("needle")
    assert matcher.engine == "literal"
    assert matcher.match("prefix needle suffix") == (True, "needle", {"needle"})
    assert matcher.match("prefix suffix") == (False, None, set())
