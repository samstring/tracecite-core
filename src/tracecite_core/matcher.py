# -*- coding: utf-8 -*-
"""匹配引擎：纯字面量 OR 优先 Aho-Corasick（C 版可选 + 纯 Python 兜底），其余回落正则。

设计约束（与 log_filter 语义一致性绑定）：

- ``pattern_from_terms`` 产出的 pattern 是「每个词 re.escape 后 ``|`` 拼接」，
  属于**纯字面量 OR**：语义 = 行内出现任一字符串，与 ``re.search`` 逐字节等价，
  因此切换引擎**不改变匹配结果**，只是提速。
- 手写正则（--grep / combine_patterns 的 ``(?:...)`` 分组等）含正则元字符，
  ``is_pure_literal_or`` 判定失败后一律走 ``re`` 路径，行为完全不变。
- 引擎分四档，语义全部等价：
    ``aho-corasick``  pyahocorasick（C 扩展，最快，**可选依赖**）
    ``ac-python``    内置纯 Python Aho-Corasick（零依赖兜底，词表大时比逐词 in 快，
                      基准：200 词快约 3 倍、800 词快约 10 倍）
    ``literal``      纯字面量包含 ``t in text``（词表小时足够，CPython 内置 C 子串搜索）
    ``regex``        手写正则路径（含元字符时唯一选择，与改动前行为一致）
- 引擎降级是透明的：装不装 pyahocorasick 都不影响结果，只影响速度。
"""

from __future__ import annotations

from collections import deque
import re
from typing import Any, List, Optional, Set, Tuple

# 正则结构元字符：出现（且未转义）即判定为「非纯字面量」
_STRUCT_META = frozenset("()[]{}*+?^$")
# 未转义的 . 是通配符，同样拒绝
_DOT = "."


def _split_top_level(pattern: str) -> Optional[List[str]]:
    """按顶层 ``|`` 切分（括号内与转义 ``\\|`` 不切）；括号不匹配返回 None。"""
    parts: List[str] = []
    depth = 0
    buf: List[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "\\":
            buf.append(ch)
            if i + 1 < n:
                buf.append(pattern[i + 1])
                i += 2
            else:
                i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return None
        if ch == "|" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if depth != 0:
        return None
    parts.append("".join(buf))
    return parts


def _parse_literal_segment(part: str) -> Optional[str]:
    """解析单个纯字面量段（无顶层 ``|``）：转义标点 unescape，元字符/正则转义序列拒绝。"""
    chars: List[str] = []
    i = 0
    n = len(part)
    while i < n:
        ch = part[i]
        if ch == "\\":
            if i + 1 >= n:
                return None
            nxt = part[i + 1]
            if nxt.isalnum():
                # \d \w \s \b 等是正则转义序列，不是字面量
                return None
            chars.append(nxt)
            i += 2
            continue
        if ch in _STRUCT_META or ch == _DOT:
            return None
        chars.append(ch)
        i += 1
    return "".join(chars)


def is_pure_literal_or(pattern: str) -> Optional[List[str]]:
    """判定 pattern 是否为「纯字面量 OR」，是则返回字面量词列表，否则返回 None。

    支持 ``combine_patterns`` 产出的分组结构 ``(?:a|b)|(?:c|d)``：每个
    ``(?:...)`` 组内容必须是纯字面量 OR（无嵌套），顶层 ``|`` 连接的分支要么是
    这样的分组、要么是纯字面量段。判定失败（含元字符/嵌套/空分支/括号不匹配）
    一律回落正则，保证语义不变。

    词内转义管道 ``\\|`` 会被正确识别为字面量管道符（不会误切分支）。
    """
    if not pattern:
        return None
    parts = _split_top_level(pattern)
    if parts is None:
        return None
    terms: List[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            # 空分支（a| 或 |a）：正则语义含空串，不等价字面量
            return None
        if part.startswith("(?:") and part.endswith(")"):
            inner = part[3:-1]
            if "(" in inner or ")" in inner:
                # 嵌套分组，保守回落
                return None
            sub = is_pure_literal_or(inner)
            if sub is None:
                return None
            terms.extend(sub)
        else:
            term = _parse_literal_segment(part)
            if term is None:
                return None
            terms.append(term)
    return terms


def _build_automaton(terms: List[str]) -> Optional[Any]:
    """尝试构建 C 版 Aho-Corasick 自动机；pyahocorasick 未安装时返回 None。"""
    try:
        import ahocorasick  # type: ignore
    except ImportError:
        return None
    try:
        auto = ahocorasick.Automaton()
        for term in terms:
            auto.add_word(term, term)
        auto.make_automaton()
        return auto
    except Exception:  # noqa: BLE001 - 自动机构建失败不是致命错误，走纯 Python 兜底
        return None


class _PureAhoCorasick:
    """纯 Python Aho-Corasick（Trie + fail 指针），零依赖兜底档。

    ``scan(text)`` 返回 ``(first_hit, hits)``，与 C 版 ``iter`` 语义一致
    （first 为文本位置最早出现的词）。
    """

    __slots__ = ("_next", "_fail", "_out")

    def __init__(self, terms: List[str]):
        nxt: List[dict] = [{}]
        fail: List[int] = [0]
        out: List[List[str]] = [[]]
        for word in terms:
            state = 0
            for ch in word:
                ns = nxt[state].get(ch)
                if ns is None:
                    ns = len(nxt)
                    nxt[state][ch] = ns
                    nxt.append({})
                    fail.append(0)
                    out.append([])
                state = ns
            out[state].append(word)
        queue = deque(ns for ns in nxt[0].values())
        while queue:
            r = queue.popleft()
            for ch, u in nxt[r].items():
                queue.append(u)
                f = fail[r]
                while f and ch not in nxt[f]:
                    f = fail[f]
                fail[u] = nxt[f].get(ch, 0)
                out[u] += out[fail[u]]
        self._next = nxt
        self._fail = fail
        self._out = out

    def scan(self, text: str) -> Tuple[Optional[str], Set[str]]:
        first: Optional[str] = None
        hits: Set[str] = set()
        state = 0
        for ch in text:
            while state and ch not in self._next[state]:
                state = self._fail[state]
            state = self._next[state].get(ch, 0)
            for word in self._out[state]:
                if first is None:
                    first = word
                hits.add(word)
        return first, hits


class Matcher:
    """统一匹配入口：纯字面量 OR → C AC / 纯 Python AC / 字面量包含；其余 → 正则。

    ``match(text)`` 返回 ``(matched, term, terms_hit)``：

    - ``matched``   该记录是否命中。
    - ``term``      纯字面量路径下命中的**第一个**词（按文本位置序，供命中元数据）；
                    正则路径固定为 None。
    - ``terms_hit`` 纯字面量路径下命中的**全部**词（供 term_usage 统计）；
                    正则路径固定为空集。
    """

    def __init__(self, pattern: str):
        self.pattern = pattern
        self.terms = is_pure_literal_or(pattern)
        self.engine = "regex"
        self.regex: Optional[re.Pattern] = None
        self.automaton: Optional[Any] = None
        self.pure_ac: Optional[_PureAhoCorasick] = None
        if self.terms is not None:
            self.automaton = _build_automaton(self.terms)
            if self.automaton is not None:
                self.engine = "aho-corasick"
            else:
                try:
                    self.pure_ac = _PureAhoCorasick(self.terms)
                    self.engine = "ac-python"
                except Exception:  # noqa: BLE001 - 自动机构建失败不是致命错误
                    self.engine = "literal"
        else:
            self.regex = re.compile(pattern)

    def match(self, text: str) -> Tuple[bool, Optional[str], Set[str]]:
        if self.automaton is not None:
            first: Optional[str] = None
            hits: Set[str] = set()
            for _, term in self.automaton.iter(text):
                if first is None:
                    first = term
                hits.add(term)
            if not hits:
                return False, None, set()
            return True, first, hits
        if self.pure_ac is not None:
            first, hits = self.pure_ac.scan(text)
            if not hits:
                return False, None, set()
            return True, first, hits
        if self.terms is not None:
            hits = {t for t in self.terms if t in text}
            if not hits:
                return False, None, set()
            # 统一按文本位置序取第一个（与 AC 一致，不依赖词表顺序）
            first = min(hits, key=lambda t: text.index(t))
            return True, first, hits
        assert self.regex is not None
        return self.regex.search(text) is not None, None, set()
