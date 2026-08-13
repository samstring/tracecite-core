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
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple, Union

# 正则结构元字符：出现（且未转义）即判定为「非纯字面量」
_STRUCT_META = frozenset("()[]{}*+?^$")
# 未转义的 . 是通配符，同样拒绝
_DOT = "."
_COMPONENT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,95}$")
_MAX_COMPONENT_ID_CHARS = 96
_MAX_COMPONENT_METADATA_DEPTH = 3
_MAX_COMPONENT_METADATA_ITEMS = 32
_MAX_COMPONENT_METADATA_STRING_CHARS = 1024
_MAX_PATTERN_COMPONENTS = 64
_COMPONENT_RESERVED_KEYS = frozenset({"id", "pattern", "effective", "kind"})


@dataclass(frozen=True)
class PatternComponent:
    """One bounded, independently matchable filter component.

    ``component_id`` is the stable provenance identity exposed in hit metadata.
    ``effective=False`` keeps an input component in provenance while preventing
    it from being reported as the matcher when a resolver replaced the final
    expression (for example, a domain scenario resolver).
    """

    component_id: str
    pattern: str
    kind: Optional[str] = None
    effective: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.component_id

    def to_dict(self) -> Dict[str, Any]:
        component = _validate_component(self, index=0)
        out: Dict[str, Any] = {
            "id": component.component_id,
            "pattern": component.pattern,
            "effective": bool(component.effective),
        }
        if component.kind:
            out["kind"] = component.kind
        if component.metadata:
            metadata = _bounded_component_metadata(component.metadata)
            for key, value in metadata.items():
                # Provenance extensions cannot replace the stable identity or
                # matcher fields supplied by Core.
                if key not in _COMPONENT_RESERVED_KEYS:
                    out[key] = value
        return out


def _bounded_json_value(value: Any, *, depth: int = 0) -> Any:
    """Validate and copy JSON-safe bounded extension metadata."""
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value) > _MAX_COMPONENT_METADATA_STRING_CHARS:
            raise ValueError("pattern component metadata 字符串超过 1024 字符")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("pattern component metadata 浮点值必须有限")
        return value
    if depth >= _MAX_COMPONENT_METADATA_DEPTH:
        raise ValueError("pattern component metadata 嵌套超过 3 层")
    if isinstance(value, Mapping):
        if len(value) > _MAX_COMPONENT_METADATA_ITEMS:
            raise ValueError("pattern component metadata 对象字段超过 32 个")
        copied: Dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item)):
            if not isinstance(key, str):
                raise ValueError("pattern component metadata 对象键必须是字符串")
            copied[key] = _bounded_json_value(value[key], depth=depth + 1)
        return copied
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_COMPONENT_METADATA_ITEMS:
            raise ValueError("pattern component metadata 数组元素超过 32 个")
        return [_bounded_json_value(item, depth=depth + 1) for item in value]
    raise ValueError(
        "pattern component metadata 只能包含 JSON-safe 的 null/bool/number/string/array/object"
    )


def _bounded_component_metadata(metadata: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(metadata, Mapping):
        raise ValueError("pattern component metadata 必须是对象")
    if len(metadata) > _MAX_COMPONENT_METADATA_ITEMS:
        raise ValueError("pattern component metadata 字段超过 32 个")
    copied: Dict[str, Any] = {}
    for key, value in metadata.items():
        if not isinstance(key, str):
            raise ValueError("pattern component metadata 对象键必须是字符串")
        copied[key] = _bounded_json_value(value)
    return copied


def _validate_component(component: PatternComponent, *, index: int) -> PatternComponent:
    component_id = str(component.component_id).strip()
    if not component_id:
        raise ValueError(f"pattern_components[{index}] 缺少非空 id")
    if len(component_id) > _MAX_COMPONENT_ID_CHARS or not _COMPONENT_ID_RE.fullmatch(component_id):
        raise ValueError(
            f"pattern_components[{index}] id 必须匹配 [A-Za-z][A-Za-z0-9_.:-]{{0,95}}"
        )
    if not isinstance(component.pattern, str) or not component.pattern:
        raise ValueError(f"pattern_components[{index}] 缺少非空 pattern")
    kind: Optional[str] = None
    if component.kind is not None:
        kind = str(component.kind).strip()
        if kind and not _COMPONENT_ID_RE.fullmatch(kind):
            raise ValueError(f"pattern_components[{index}] kind 格式无效")
    metadata = _bounded_component_metadata(component.metadata)
    return PatternComponent(
        component_id=component_id,
        pattern=component.pattern,
        kind=kind,
        effective=bool(component.effective),
        metadata=metadata,
    )


def coerce_pattern_components(
    components: Optional[Iterable[Union[PatternComponent, Mapping[str, Any]]]],
) -> List[PatternComponent]:
    """Normalize public mapping/dataclass component declarations.

    The normalizer deliberately accepts only small scalar metadata and leaves
    unknown values untouched for Runtime-owned provenance fields.  Callers are
    responsible for bounding any values they put in ``metadata``.
    """

    if components is None:
        return []
    out: List[PatternComponent] = []
    seen: Set[str] = set()
    for index, raw in enumerate(components):
        if index >= _MAX_PATTERN_COMPONENTS:
            raise ValueError("pattern_components 元素超过 64 个")
        if isinstance(raw, PatternComponent):
            component = raw
        elif isinstance(raw, Mapping):
            component_id = str(raw.get("id") or raw.get("component_id") or "").strip()
            pattern = str(raw.get("pattern") or "")
            kind = str(raw.get("kind") or "").strip() or None
            effective = bool(raw.get("effective", True))
            metadata = {
                key: value
                for key, value in raw.items()
                if key not in {"id", "component_id", "pattern", "kind", "effective"}
            }
            component = PatternComponent(
                component_id=component_id,
                pattern=pattern,
                kind=kind,
                effective=effective,
                metadata=metadata,
            )
        else:
            raise TypeError(f"pattern_components[{index}] 必须是 PatternComponent 或对象")
        component = _validate_component(component, index=index)
        if component.component_id in seen:
            raise ValueError(f"pattern_components 含重复 id: {component.component_id}")
        seen.add(component.component_id)
        out.append(component)
    return out


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
        self._component_cache: Dict[str, "Matcher"] = {}
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

    def match_with_components(
        self,
        text: str,
        components: Optional[Iterable[Union[PatternComponent, Mapping[str, Any]]]] = None,
    ) -> Tuple[bool, Optional[str], Set[str], List[str]]:
        """Match text and return deterministic component provenance.

        The final ``pattern`` remains the compatibility source of truth.  When
        component declarations are supplied, each effective component is
        evaluated independently; this is equivalent to the OR combination used
        by ``combine_patterns`` while preserving regex/literal semantics.  A
        fallback ``pattern`` identity is emitted only for malformed or
        resolver-specific expressions that cannot be attributed to a declared
        component.
        """

        matched, term, terms_hit = self.match(text)
        if not matched:
            return False, term, terms_hit, []
        normalized = coerce_pattern_components(components)
        if not normalized:
            return True, term, terms_hit, ["pattern"]

        matched_by: List[str] = []
        for component in normalized:
            if not component.effective:
                continue
            try:
                component_matcher = self._component_cache.get(component.pattern)
                if component_matcher is None:
                    component_matcher = Matcher(component.pattern)
                    self._component_cache[component.pattern] = component_matcher
                component_hit = component_matcher.match(text)[0]
            except re.error:
                # The final matcher was already compiled successfully.  A
                # component's independent compilation failure is provenance
                # only; do not change the historical final-match result.
                component_hit = False
            if component_hit:
                matched_by.append(component.component_id)
        if not matched_by:
            matched_by = ["pattern"]
        return True, term, terms_hit, matched_by

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
