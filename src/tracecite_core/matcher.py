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

try:  # CPython's parser is stdlib-only and avoids importing deprecated sre_parse.
    from re import _constants as _RE_CONSTANTS  # type: ignore[attr-defined]
    from re import _parser as _RE_PARSER  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - compatibility with older Python implementations
    import sre_parse as _RE_PARSER  # type: ignore[no-redef]

    _RE_CONSTANTS = _RE_PARSER  # type: ignore[assignment]

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
# CPython's substring search runs in C and is materially faster than the pure
# Python Aho-Corasick fallback for small term sets. Keep AC for larger sets.
_LITERAL_ENGINE_MAX_TERMS = 8

# Regexes can be supplied by an Agent or a Scenario resolver.  ``re`` has no
# timeout API, so reject a small, explicit class of structures which are known
# to trigger super-linear backtracking.  This is a conservative guardrail,
# not a proof that every accepted expression is linear-time.
_MAX_PATTERN_CHARS = 4096
_MAX_REGEX_NODES = 4096
_MAX_REGEX_GROUPS = 128
_MAX_REGEX_REPEATS = 128
_MAX_REGEX_BRANCHES = 128
_MAX_REGEX_DEPTH = 64
_MAX_REGEX_REPEAT_COUNT = 100_000
_RE_MAXREPEAT = getattr(_RE_CONSTANTS, "MAXREPEAT", 2**32)

_REPEAT_OP_NAMES = frozenset({"MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"})
_VARIABLE_REPEAT_OP_NAMES = frozenset({"MAX_REPEAT", "MIN_REPEAT"})
_GROUP_WRAPPER_OP_NAMES = frozenset({"SUBPATTERN", "ATOMIC_GROUP"})
_ASSERT_OP_NAMES = frozenset({"ASSERT", "ASSERT_NOT"})
_GROUPREF_OP_NAMES = frozenset(
    {
        "GROUPREF",
        "GROUPREF_IGNORE",
        "GROUPREF_UNI_IGNORE",
        "GROUPREF_LOC_IGNORE",
        "GROUPREF_EXISTS",
    }
)


def _regex_op_name(op: Any) -> str:
    """Return a parser opcode name across supported Python versions."""
    return str(op)


def _regex_sequence_data(sequence: Any) -> Any:
    """Get the token list from ``re._parser.SubPattern`` or a plain list."""
    return getattr(sequence, "data", sequence)


def _atom_overlap(left: Tuple[Any, ...], right: Tuple[Any, ...]) -> bool:
    """Conservatively compare two possible first-character summaries."""
    left_kind, left_value = left[0], left[1] if len(left) > 1 else None
    right_kind, right_value = right[0], right[1] if len(right) > 1 else None
    if left_kind == "any" or right_kind == "any":
        return True
    if left_kind == "literal" and right_kind == "literal":
        return left_value == right_value
    if left_kind == "literal" and right_kind == "range":
        return right_value[0] <= left_value <= right_value[1]
    if left_kind == "range" and right_kind == "literal":
        return left_value[0] <= right_value <= left_value[1]
    if left_kind == "range" and right_kind == "range":
        return max(left_value[0], right_value[0]) <= min(left_value[1], right_value[1])
    # Unicode categories and parser extensions are deliberately treated as
    # potentially overlapping; this is a rejection-only safety heuristic.
    return left_kind == "category" or right_kind == "category"


def _regex_shape(
    sequence: Any, *, depth: int = 0, limit: int = 64
) -> Tuple[bool, List[Tuple[Any, ...]], bool]:
    """Return ``(nullable, deterministic_prefix, prefix_is_complete)``."""
    if depth > _MAX_REGEX_DEPTH:
        raise re.error(f"regex pattern nesting exceeds {_MAX_REGEX_DEPTH} levels")
    nullable = True
    prefix: List[Tuple[Any, ...]] = []
    complete = True
    for op, arg in _regex_sequence_data(sequence):
        token_nullable, token_prefix, token_complete = _regex_token_shape(
            op, arg, depth=depth + 1, limit=limit
        )
        prefix.extend(token_prefix)
        if len(prefix) >= limit:
            return nullable, prefix[:limit], False
        if not token_complete:
            return nullable, prefix, False
        if not token_nullable:
            return False, prefix, complete
    return nullable, prefix, complete


def _regex_token_shape(
    op: Any, arg: Any, *, depth: int, limit: int
) -> Tuple[bool, List[Tuple[Any, ...]], bool]:
    name = _regex_op_name(op)
    if name == "LITERAL":
        return False, [("literal", int(arg))], True
    if name in {"NOT_LITERAL", "ANY", "ANY_ALL"}:
        return False, [("any",)], True
    if name == "IN":
        atoms: List[Tuple[Any, ...]] = []
        for item_op, item_arg in _regex_sequence_data(arg):
            item_name = _regex_op_name(item_op)
            if item_name == "LITERAL":
                atoms.append(("literal", int(item_arg)))
            elif item_name == "RANGE":
                start, end = item_arg
                atoms.append(("range", (int(start), int(end))))
            elif item_name == "CATEGORY":
                atoms.append(("category", str(item_arg)))
            else:
                atoms.append(("any",))
        return False, [atoms[0] if len(atoms) == 1 else ("any",)], True
    if name in _GROUP_WRAPPER_OP_NAMES:
        child = arg[-1] if name == "SUBPATTERN" else arg
        return _regex_shape(child, depth=depth, limit=limit)
    if name in _ASSERT_OP_NAMES or name in {"AT", "SUCCESS", "FAILURE"}:
        return True, [], True
    if name == "BRANCH":
        shapes = [_regex_shape(branch, depth=depth, limit=limit) for branch in arg[1]]
        return any(item[0] for item in shapes), [], False
    if name in _REPEAT_OP_NAMES:
        min_count, max_count, child = arg
        child_nullable, child_prefix, child_complete = _regex_shape(
            child, depth=depth, limit=limit
        )
        nullable = min_count == 0 or child_nullable
        if min_count == max_count and child_complete and min_count <= limit:
            return nullable, child_prefix * min_count, True
        return nullable, child_prefix[:limit], False
    if name == "GROUPREF_EXISTS":
        yes = _regex_shape(arg[1], depth=depth, limit=limit)
        no = _regex_shape(arg[2], depth=depth, limit=limit) if arg[2] is not None else (True, [], True)
        return yes[0] or no[0], [], False
    return False, [("any",)], False


def _alternatives_overlap(branches: Any) -> bool:
    """Detect empty or prefix-ambiguous alternatives in a repeated branch."""
    shapes = [_regex_shape(branch) for branch in branches]
    for index, (nullable, left_prefix, left_complete) in enumerate(shapes):
        if nullable:
            return True
        for right_nullable, right_prefix, right_complete in shapes[index + 1 :]:
            if right_nullable:
                return True
            overlap = all(
                _atom_overlap(left, right)
                for left, right in zip(left_prefix, right_prefix)
            )
            if not overlap:
                continue
            if len(left_prefix) == len(right_prefix) and left_complete and right_complete:
                return True
            if len(left_prefix) < len(right_prefix) and left_complete:
                return True
            if len(right_prefix) < len(left_prefix) and right_complete:
                return True
    return False


def _validate_regex_safety(pattern: str) -> None:
    """Reject known high-risk shapes before compiling a user regex.

    ``re`` deliberately has no execution timeout.  This gate therefore blocks
    nested variable repetitions, backreferences inside a variable repetition,
    and prefix-ambiguous alternatives in repeated regions.  It also bounds
    parser structure.  Accepted patterns are not claimed to be provably
    linear-time.
    """
    try:
        parsed = _RE_PARSER.parse(pattern, 0)
    except re.error:
        raise
    except RecursionError as exc:
        raise re.error(f"regex pattern nesting exceeds {_MAX_REGEX_DEPTH} levels") from exc

    node_count = 0
    groups = 0
    repeats = 0
    branches = 0

    def walk(sequence: Any, *, variable_repeat_depth: int, depth: int) -> None:
        nonlocal node_count, groups, repeats, branches
        if depth > _MAX_REGEX_DEPTH:
            raise re.error(f"regex pattern nesting exceeds {_MAX_REGEX_DEPTH} levels")
        for op, arg in _regex_sequence_data(sequence):
            node_count += 1
            if node_count > _MAX_REGEX_NODES:
                raise re.error(f"regex pattern structure exceeds {_MAX_REGEX_NODES} nodes")
            name = _regex_op_name(op)
            if name in _GROUP_WRAPPER_OP_NAMES:
                if name == "SUBPATTERN" and arg[0]:
                    groups += 1
                    if groups > _MAX_REGEX_GROUPS:
                        raise re.error(f"regex pattern contains more than {_MAX_REGEX_GROUPS} groups")
                child = arg[-1] if name == "SUBPATTERN" else arg
                walk(child, variable_repeat_depth=variable_repeat_depth, depth=depth + 1)
                continue
            if name in _REPEAT_OP_NAMES:
                repeats += 1
                if repeats > _MAX_REGEX_REPEATS:
                    raise re.error(f"regex pattern contains more than {_MAX_REGEX_REPEATS} repeats")
                min_count, max_count, child = arg
                if max_count != _RE_MAXREPEAT and max_count > _MAX_REGEX_REPEAT_COUNT:
                    raise re.error(
                        f"regex repeat upper bound exceeds {_MAX_REGEX_REPEAT_COUNT}"
                    )
                variable = name in _VARIABLE_REPEAT_OP_NAMES and max_count != min_count
                if variable and variable_repeat_depth:
                    raise re.error("regex pattern contains nested variable repetitions")
                if variable and _sequence_has_overlapping_branch(child):
                    raise re.error(
                        "regex pattern contains overlapping alternation inside repetition"
                    )
                walk(
                    child,
                    # A single optional group cannot repeatedly repartition
                    # its child's input.  Only a repeat that may execute more
                    # than once creates the dangerous enclosing context.
                    variable_repeat_depth=variable_repeat_depth
                    + int(variable and max_count != 1),
                    depth=depth + 1,
                )
                continue
            if name == "BRANCH":
                branches += max(0, len(arg[1]) - 1)
                if branches > _MAX_REGEX_BRANCHES:
                    raise re.error(
                        f"regex pattern contains more than {_MAX_REGEX_BRANCHES} alternations"
                    )
                for branch in arg[1]:
                    walk(branch, variable_repeat_depth=variable_repeat_depth, depth=depth + 1)
                continue
            if name in _GROUPREF_OP_NAMES and variable_repeat_depth:
                raise re.error("regex pattern contains a backreference inside repetition")
            if name in _ASSERT_OP_NAMES:
                walk(arg[1], variable_repeat_depth=variable_repeat_depth, depth=depth + 1)
                continue
            if name == "GROUPREF_EXISTS":
                walk(arg[1], variable_repeat_depth=variable_repeat_depth, depth=depth + 1)
                if arg[2] is not None:
                    walk(arg[2], variable_repeat_depth=variable_repeat_depth, depth=depth + 1)
                continue
            if name == "IN":
                walk(arg, variable_repeat_depth=variable_repeat_depth, depth=depth + 1)

    def _sequence_has_overlapping_branch(sequence: Any) -> bool:
        # Defined as a nested helper so branch analysis uses the same parser
        # representation while keeping all safety policy in this function.
        for op, arg in _regex_sequence_data(sequence):
            name = _regex_op_name(op)
            if name == "BRANCH" and _alternatives_overlap(arg[1]):
                return True
            if name in _GROUP_WRAPPER_OP_NAMES:
                child = arg[-1] if name == "SUBPATTERN" else arg
                if _sequence_has_overlapping_branch(child):
                    return True
            elif name in _REPEAT_OP_NAMES:
                if _sequence_has_overlapping_branch(arg[2]):
                    return True
            elif name in _ASSERT_OP_NAMES:
                if _sequence_has_overlapping_branch(arg[1]):
                    return True
            elif name == "GROUPREF_EXISTS":
                if _sequence_has_overlapping_branch(arg[1]):
                    return True
                if arg[2] is not None and _sequence_has_overlapping_branch(arg[2]):
                    return True
        return False

    try:
        walk(parsed, variable_repeat_depth=0, depth=0)
    except RecursionError as exc:
        raise re.error(f"regex pattern nesting exceeds {_MAX_REGEX_DEPTH} levels") from exc


def _compile_safe_regex(pattern: str, flags: int = 0) -> re.Pattern[str]:
    """Compile a user-supplied regex after applying Core's resource gate."""
    if len(pattern) > _MAX_PATTERN_CHARS:
        raise re.error(f"regex pattern exceeds {_MAX_PATTERN_CHARS} characters")
    _validate_regex_safety(pattern)
    return re.compile(pattern, flags)


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
        if len(pattern) > _MAX_PATTERN_CHARS:
            raise re.error(f"regex pattern exceeds {_MAX_PATTERN_CHARS} characters")
        self.pattern = pattern
        self.terms = is_pure_literal_or(pattern)
        self.engine = "regex"
        self.regex: Optional[re.Pattern] = None
        self.automaton: Optional[Any] = None
        self.pure_ac: Optional[_PureAhoCorasick] = None
        self._component_cache: Dict[str, "Matcher"] = {}
        if self.terms is not None:
            if len(self.terms) <= _LITERAL_ENGINE_MAX_TERMS:
                self.engine = "literal"
            else:
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
            self.regex = _compile_safe_regex(pattern)

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
            if len(self.terms) == 1:
                term = self.terms[0]
                if term not in text:
                    return False, None, set()
                return True, term, {term}
            hits = {t for t in self.terms if t in text}
            if not hits:
                return False, None, set()
            # 统一按文本位置序取第一个（与 AC 一致，不依赖词表顺序）
            first = min(hits, key=lambda t: text.index(t))
            return True, first, hits
        assert self.regex is not None
        return self.regex.search(text) is not None, None, set()
