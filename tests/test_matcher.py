# -*- coding: utf-8 -*-
"""matcher 引擎：纯字面量 OR 判定 + 与正则语义等价性锁死。"""

import re

import pytest

from tracecite_core.text_filter import pattern_from_terms
from tracecite_core.matcher import Matcher, is_pure_literal_or


class TestIsPureLiteralOr:
    def test_simple_or(self):
        assert is_pure_literal_or("a|b|c") == ["a", "b", "c"]

    def test_single_term(self):
        assert is_pure_literal_or("hello") == ["hello"]

    def test_escaped_dot_unescaped(self):
        # pattern_from_terms 产物：词内 . 被 re.escape 成 \.
        assert is_pure_literal_or(r"error\.code|timeout") == ["error.code", "timeout"]

    def test_bare_dot_is_regex_wildcard(self):
        # 手写正则的裸 . 是通配符，不可当字面量
        assert is_pure_literal_or("error.code|timeout") is None

    def test_struct_meta_rejected(self):
        for bad in ("a(b", "a)b", "a[b", "a^b", "a$b", "a*b", "a+b", "a?b"):
            assert is_pure_literal_or(bad) is None, bad

    def test_empty_branch_rejected(self):
        assert is_pure_literal_or("a|") is None
        assert is_pure_literal_or("|a") is None

    def test_trailing_backslash_rejected(self):
        assert is_pure_literal_or("a\\") is None

    def test_empty_pattern_rejected(self):
        assert is_pure_literal_or("") is None

    def test_pipe_inside_escaped_term_supported(self):
        # re.escape("a|b") = "a\|b"：顶层切分识别转义管道 → 词内管道作为字面量支持
        assert is_pure_literal_or(r"a\|b|c") == ["a|b", "c"]

    def test_numeric_escaped(self):
        assert is_pure_literal_or(r"1\.2\.3") == ["1.2.3"]

    def test_regex_escape_sequence_rejected(self):
        # \d \w \s \b 是正则转义序列，语义不是字面量 d/w/s/b —— 必须回落正则
        for bad in (r"errorCode=4\d\d", r"\w+", r"a\sb", r"foo\b"):
            assert is_pure_literal_or(bad) is None, bad

    def test_combine_patterns_grouping_supported(self):
        # combine_patterns 产物 (?:a|b)|(?:c|d)：纯分组 OR，应判定为字面量
        from tracecite_core.text_filter import combine_patterns

        p = combine_patterns("task_started|task_completed", r"request\ started|request\ failed")
        assert is_pure_literal_or(p) == [
            "task_started", "task_completed", "request started", "request failed",
        ]

    def test_escaped_pipe_inside_term(self):
        # re.escape("a|b") = a\|b：转义管道是字面量管道符，不切分支
        assert is_pure_literal_or(r"a\|b|c") == ["a|b", "c"]

    def test_nested_grouping_rejected(self):
        # (?:a(b)) 嵌套分组：保守回落正则
        assert is_pure_literal_or(r"(?:a(b)|c)") is None
        assert is_pure_literal_or(r"(?:a|(?:b))") is None

    def test_unbalanced_paren_rejected(self):
        assert is_pure_literal_or("(?:a|b") is None
        assert is_pure_literal_or("a|b)") is None


class TestMatcherSemantics:
    """核心正确性：纯字面量路径（AC/literal）与 re.search 输出逐字节一致。"""

    def _assert_equivalent(self, terms, texts):
        pattern = pattern_from_terms(terms)
        matcher = Matcher(pattern)
        assert matcher.engine in ("aho-corasick", "ac-python", "literal"), matcher.engine
        regex = re.compile(pattern)
        for text in texts:
            matched, term, hits = matcher.match(text)
            assert matched == (regex.search(text) is not None), (pattern, text)
            if matched:
                # 命中词必须是词表里真实出现在文本中的词
                assert term in terms, (term, text)
                assert term in text, (term, text)
                assert hits and all(h in terms for h in hits)

    def test_equivalent_on_device_log_lines(self):
        terms = ["alpha", "beta", "gamma", "action_beta", "error", "timeout", "404"]
        texts = [
            "Aug  8 14:10:00.000 app[1] <Notice>: alphabeta",
            "Aug  8 14:10:01.000 app[1] <Notice>: user action_beta id=1024",
            "Aug  8 14:10:02.000 app[1] <Error>: connect timeout to 192.0.2.1",
            "Aug  8 14:10:03.000 app[1] <Notice>: heartbeat ok",
            "Aug  8 14:10:04.000 app[1] <Error>: http 404 not found",
            "Aug  8 14:10:05.000 app[1] <Notice>: 页面加载完成",
        ]
        self._assert_equivalent(terms, texts)

    def test_equivalent_ascii_terms(self):
        terms = ["error", "Exception", "crash", "ANR", "GC"]
        texts = [
            "java.lang.Exception: boom",
            "android runtime GC freed",
            "ANR in com.example",
            "nothing here",
            "Exception in thread main",
        ]
        self._assert_equivalent(terms, texts)

    def test_overlapping_terms_hit_set(self):
        matcher = Matcher(pattern_from_terms(["alpha", "beta", "gamma"]))
        matched, term, hits = matcher.match("Aug  8 14:10:00 app[1]: alphabeta")
        assert matched is True
        assert term == "alpha"
        assert hits == {"alpha", "beta"}

    def test_first_hit_preserves_term_order(self):
        # literal 路径保词表序；AC 按文本位置序，二者对「首个出现词」应一致
        matcher = Matcher(pattern_from_terms(["beta", "alpha"]))
        _, term, _ = matcher.match("Aug  8 14:10:00 app[1]: alphabeta")
        assert term == "alpha"

    def test_no_hit(self):
        matcher = Matcher(pattern_from_terms(["alpha", "gamma"]))
        matched, term, hits = matcher.match("Aug  8 14:10:00 app[1]: heartbeat")
        assert (matched, term, hits) == (False, None, set())


class TestMatcherRegexFallback:
    def test_regex_engine_for_meta_pattern(self):
        matcher = Matcher(r"error.*timeout")
        assert matcher.engine == "regex"
        matched, term, hits = matcher.match("Aug  8 14:10:00 app[1]: error then timeout")
        assert matched is True
        assert term is None
        assert hits == set()

    def test_regex_fallback_equivalent(self):
        pattern = r"http\s+4\d\d|timeout"
        matcher = Matcher(pattern)
        assert matcher.engine == "regex"
        regex = re.compile(pattern)
        for text in (
            "Aug  8 14:10:00 app[1]: http 404 not found",
            "Aug  8 14:10:01 app[1]: request timeout",
            "Aug  8 14:10:02 app[1]: heartbeat",
        ):
            assert matcher.match(text)[0] == (regex.search(text) is not None), text

    def test_escape_sequence_not_mistaken_for_literal(self):
        """回归：正则转义序列不得被当字面量 —— errorCode=4\\d\\d 必须能命中 401。"""
        matcher = Matcher(r"errorCode=4\d\d")
        assert matcher.engine == "regex"
        assert matcher.match("Aug  8 14:10:00 app[1]: request failed errorCode=401")[0]
        assert not matcher.match("Aug  8 14:10:00 app[1]: request failed errorCode=4dd")[0]

    def test_invalid_regex_raises(self):
        with pytest.raises(re.error):
            Matcher("(unclosed")


class TestPureAhoCorasick:
    """纯 Python AC 兜底档：与 C 版/字面量路径语义一致。"""

    @staticmethod
    def _brute(terms, text):
        return {t for t in terms if t in text}

    def _scan(self, terms, text):
        from tracecite_core.matcher import _PureAhoCorasick

        first, hits = _PureAhoCorasick(terms).scan(text)
        return first, hits

    def test_prefix_and_overlap_words(self):
        # 经典用例：he / she / his / hers 存在前缀与重叠关系，考验 fail 指针
        terms = ["he", "she", "his", "hers"]
        for text in (
            "ushers",
            "she",
            "his",
            "he",
            "hers",
            "absent",
            "he said she said his hers",
        ):
            first, hits = self._scan(terms, text)
            expected = self._brute(terms, text)
            assert hits == expected, (text, hits, expected)
            if expected:
                # first 必须是文本位置最早出现的词
                first_pos = text.index(first)
                assert all(text.index(w) >= first_pos for w in expected), (text, first)

    def test_unicode_cjk_terms(self):
        terms = ["alpha", "beta", "gamma"]
        first, hits = self._scan(terms, "收到alphabeta通知")
        assert hits == {"alpha", "beta"}
        assert first == "alpha"

    def test_no_hit(self):
        first, hits = self._scan(["a", "bb"], "ccc ddd")
        assert (first, hits) == (None, set())

    def test_single_char_terms(self):
        first, hits = self._scan(["a", "bc"], "xbc")
        assert hits == {"bc"}
        assert first == "bc"


class TestAcPythonFallback:
    """pyahocorasick 缺失时自动回落 ac-python，且语义与 re 一致。"""

    def _matcher_without_c_lib(self, pattern):
        from unittest import mock
        import sys

        with mock.patch.dict(sys.modules, {"ahocorasick": None}):
            return Matcher(pattern)

    def test_engine_falls_back_to_ac_python(self):
        matcher = self._matcher_without_c_lib(pattern_from_terms(["login", "timeout"]))
        assert matcher.engine == "ac-python"

    def test_ac_python_equivalent_to_regex(self):
        matcher = self._matcher_without_c_lib(pattern_from_terms(["login", "timeout"]))
        regex = re.compile(pattern_from_terms(["login", "timeout"]))
        for text in (
            "Aug  8 14:10:00 app[1]: user login success",
            "Aug  8 14:10:01 app[1]: request timeout",
            "Aug  8 14:10:02 app[1]: heartbeat",
        ):
            assert matcher.match(text)[0] == (regex.search(text) is not None), text

    def test_first_hit_position_order(self):
        # 词表序 beta→alpha，文本位置序 alpha→beta；first 必须按位置序
        matcher = self._matcher_without_c_lib(pattern_from_terms(["beta", "alpha"]))
        _, term, hits = matcher.match("Aug  8 14:10:00 app[1]: alphabeta")
        assert term == "alpha"
        assert hits == {"alpha", "beta"}


class TestMatcherTermUsage:
    def test_term_counts_per_record(self):
        matcher = Matcher(pattern_from_terms(["error", "timeout", "heartbeat"]))
        counts = {}
        for line in (
            "Aug  8 14:10:00 app[1]: error timeout",
            "Aug  8 14:10:01 app[1]: timeout",
            "Aug  8 14:10:02 app[1]: heartbeat",
        ):
            _, _, hits = matcher.match(line)
            for t in hits:
                counts[t] = counts.get(t, 0) + 1
        assert counts == {"error": 1, "timeout": 2, "heartbeat": 1}
