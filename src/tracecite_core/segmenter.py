"""文本记录分段器 — 通用默认。

core 保留：
- Segmenter 基类（header_strip_re / token_re / template_normalizers 属性）
- FormatSegmenter（声明式：一条 start 正则+时间格式接入任意格式）
- JsonLineSegmenter（JSON 行，自动提取时间/级别/消息字段）
- RawTextSegmenter（按行 / 段落 / 窗口）
- RegexSegmenter（按分隔正则）

Application-specific formats are injected by upper layers through the public API.
"""

from __future__ import annotations

import json as _json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from .records import Record
# ---------------------------------------------------------------------------
# 基类
# ---------------------------------------------------------------------------

class Segmenter:
    """分段器基类。

    可选属性（子类覆盖，text_filter 自动读取）：
    - header_strip_re: header 剥离正则（token 统计防污染）
    - token_re: 业务 token 提取正则（grow 自成长用）
    - template_normalizers: 模板折叠自定义归一化规则
    """

    name = "base"

    @property
    def header_strip_re(self) -> Optional[re.Pattern]:
        return None

    @property
    def token_re(self) -> Optional[re.Pattern]:
        return None

    @property
    def template_normalizers(self) -> Optional[List[Tuple[re.Pattern, str]]]:
        return None

    def segment_lines(self, lines: Iterator[Tuple[int, str]]) -> Iterator[Record]:
        raise NotImplementedError

    def record_timestamp(
        self,
        record: Record,
        *,
        reference: datetime,
    ) -> Optional[datetime]:
        """Return a record timestamp using this format's own rules.

        Core only trusts timestamps already produced by the segmenter. Formats
        with incomplete dates (for example a year-less text header) override
        this method in the application/plugin layer.
        """
        return record.timestamp

    def parse_time_argument(
        self,
        raw: str,
        *,
        reference: datetime,
    ) -> Optional[datetime]:
        """Parse a format-specific ``--since``/``--until`` value.

        Returning ``None`` means the format does not recognise the value. The
        generic ISO and clock forms remain owned by the Core filter engine.
        """
        return None

    def segment_file(self, path: Path, *, encoding: str = "utf-8") -> Iterator[Record]:
        with path.open("r", encoding=encoding, errors="replace") as fh:
            yield from self.segment_lines((i + 1, line) for i, line in enumerate(fh))


# ---------------------------------------------------------------------------
# RawTextSegmenter — 无格式文本
# ---------------------------------------------------------------------------

class RawTextSegmenter(Segmenter):
    """按行 / 段落 / 固定窗口切分。"""

    name = "rawtext"

    def __init__(self, mode: str = "line", window: int = 50) -> None:
        if mode not in ("line", "paragraph", "window"):
            raise ValueError(f"不支持的 rawtext mode: {mode!r}")
        self.mode = mode
        self.window = max(1, int(window))

    def segment_lines(self, lines: Iterator[Tuple[int, str]]) -> Iterator[Record]:
        pending: List[Tuple[int, str]] = []
        for line_number, line in lines:
            if self.mode == "line":
                yield Record(text=line, start_line=line_number, end_line=line_number)
            elif self.mode == "paragraph":
                if not line.strip():
                    if pending:
                        yield self._build(pending)
                        pending = []
                else:
                    pending.append((line_number, line))
            else:
                pending.append((line_number, line))
                if len(pending) >= self.window:
                    yield self._build(pending)
                    pending = []
        if pending:
            yield self._build(pending)

    @staticmethod
    def _build(pending: List[Tuple[int, str]]) -> Record:
        return Record(
            text="".join(line for _, line in pending),
            start_line=pending[0][0],
            end_line=pending[-1][0],
        )


# ---------------------------------------------------------------------------
# RegexSegmenter — 按分隔正则
# ---------------------------------------------------------------------------

class RegexSegmenter(Segmenter):
    """按自定义正则切分记录（每匹配一次正则 = 新记录开始）。"""

    name = "regex"

    def __init__(self, separator: str, flags: str = "") -> None:
        re_flags = 0
        if "i" in (flags or "").lower():
            re_flags |= re.IGNORECASE
        self.pattern = re.compile(separator, re_flags)

    def segment_lines(self, lines: Iterator[Tuple[int, str]]) -> Iterator[Record]:
        pending: List[Tuple[int, str]] = []
        for line_number, line in lines:
            if self.pattern.match(line):
                if pending:
                    yield self._build(pending)
                    pending = []
            pending.append((line_number, line))
        if pending:
            yield self._build(pending)

    _build = RawTextSegmenter._build


# ---------------------------------------------------------------------------
# JsonLineSegmenter — JSON 行
# ---------------------------------------------------------------------------

_JSON_TIME_KEYS = ("ts", "time", "timestamp", "@timestamp", "datetime", "eventTime")
_JSON_LEVEL_KEYS = ("level", "lvl", "severity")
_JSON_MSG_KEYS = ("msg", "message", "content", "text")


class JsonLineSegmenter(Segmenter):
    """每行一个 JSON 对象，自动提取时间/级别/消息字段。"""

    name = "jsonline"

    def __init__(self, time_field=None, level_field=None, msg_field=None):
        self._time_field = time_field
        self._level_field = level_field
        self._msg_field = msg_field

    def segment_lines(self, lines: Iterator[Tuple[int, str]]) -> Iterator[Record]:
        for line_number, line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = _json.loads(stripped)
            except _json.JSONDecodeError as exc:
                yield Record(
                    text=line,
                    start_line=line_number,
                    end_line=line_number,
                    fields={"parse_error": str(exc), "raw_fallback": True},
                )
                continue
            if not isinstance(obj, dict):
                yield Record(
                    text=line,
                    start_line=line_number,
                    end_line=line_number,
                    fields={
                        "parse_error": f"JSON 顶层必须是对象，实际为 {type(obj).__name__}",
                        "raw_fallback": True,
                    },
                )
                continue
            fields: Dict[str, Any] = {}
            ts = None
            tf = self._time_field
            if tf:
                ts = obj.get(tf)
            else:
                for k in _JSON_TIME_KEYS:
                    if k in obj:
                        ts = obj.get(k)
                        break
            if ts is not None:
                if isinstance(ts, (int, float)):
                    if ts > 1e11:
                        ts = datetime.utcfromtimestamp(ts / 1000)
                    else:
                        ts = datetime.utcfromtimestamp(ts)
                elif isinstance(ts, str):
                    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                        try:
                            ts = datetime.strptime(ts, fmt)
                            break
                        except ValueError:
                            continue
            level_keys = (self._level_field,) if self._level_field else _JSON_LEVEL_KEYS
            for k in level_keys:
                if k in obj:
                    fields["level"] = obj[k]
                    break
            message_keys = (self._msg_field,) if self._msg_field else _JSON_MSG_KEYS
            for k in message_keys:
                if k in obj:
                    fields["msg"] = str(obj[k])[:200]
                    break
            yield Record(
                text=line, start_line=line_number, end_line=line_number,
                timestamp=ts if isinstance(ts, datetime) else None,
                fields=fields,
            )


# ---------------------------------------------------------------------------
# FormatSegmenter — 声明式格式（核心能力）
# ---------------------------------------------------------------------------

def _brace_unclosed(text: str) -> bool:
    braces = {"{": "}", "[": "]", "(": ")"}
    stack: List[str] = []
    for ch in text:
        if ch in braces:
            stack.append(braces[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
    return len(stack) > 0


class FormatSegmenter(Segmenter):
    """声明式格式：一条 ``start`` 正则 + ``timestamp_formats`` 接入任意文本格式。

    完整字段：
    - start (必填): 记录起始行正则，支持命名组 ``(?P<ts>...)``
    - timestamp_formats: strptime 格式列表，默认 ISO 8601
    - multiline: True=非 start 行合并到上一条（默认）
    - continuation: 续行规则 {"kind": "unclosed_start", "max_lines": 100}
    - header_strip: 剥离 header 正则（token 统计用）
    - token_re: 业务 token 提取正则（grow 自成长用）
    - template_normalizers: 模板折叠自定义归一化
    """

    name = "format"

    def __init__(
        self,
        *,
        start: str,
        timestamp_formats: Optional[List[str]] = None,
        multiline: bool = True,
        flags: str = "",
        continuation: Optional[Dict[str, Any]] = None,
        header_strip: Optional[str] = None,
        token_re: Optional[str] = None,
        template_normalizers: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        if not start:
            raise ValueError("FormatSegmenter 需要 start 正则")
        re_flags = 0
        if "i" in (flags or "").lower():
            re_flags |= re.IGNORECASE
        self.pattern = re.compile(start, re_flags)
        self.ts_formats = tuple(
            timestamp_formats or ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S")
        )
        self.multiline = multiline
        self.continuation = continuation or {}
        self._header_strip_re = re.compile(header_strip) if header_strip else None
        self._token_re = re.compile(token_re) if token_re else None
        self._template_normalizers: Optional[List[Tuple[re.Pattern, str]]] = None
        if template_normalizers:
            self._template_normalizers = [
                (re.compile(r["pattern"]), r["replacement"]) for r in template_normalizers
            ]
        self._continu_max_lines = int(self.continuation.get("max_lines", 100))

    @property
    def header_strip_re(self) -> Optional[re.Pattern]:
        return self._header_strip_re

    @property
    def token_re(self) -> Optional[re.Pattern]:
        return self._token_re

    @property
    def template_normalizers(self) -> Optional[List[Tuple[re.Pattern, str]]]:
        return self._template_normalizers

    def segment_lines(self, lines: Iterator[Tuple[int, str]]) -> Iterator[Record]:
        pending: List[Tuple[int, str]] = []
        cont_kind = (self.continuation or {}).get("kind", "")
        cont_max = int((self.continuation or {}).get("max_lines", 100))
        for line_number, line in lines:
            match = self.pattern.match(line)
            if match:
                if pending:
                    merged = "".join(item for _, item in pending)
                    if cont_kind == "unclosed_start" and _brace_unclosed(merged) and len(pending) < cont_max:
                        pending.append((line_number, line))
                        continue
                    yield self._build(pending, pending[0][1])
                    pending = []
            elif not self.multiline:
                if pending:
                    yield self._build(pending, pending[0][1])
                    pending = []
            pending.append((line_number, line))
        if pending:
            yield self._build(pending, pending[0][1])

    def _build(self, pending: List[Tuple[int, str]], first: str) -> Record:
        text = "".join(line for _, line in pending)
        ts = None
        m = self.pattern.match(first)
        if m:
            raw = m.group("ts") if "ts" in (m.groupdict() or {}) else m.group()
            for fmt in self.ts_formats:
                try:
                    ts = datetime.strptime(raw.strip(), fmt)
                    break
                except ValueError:
                    continue
        fields: Dict[str, Any] = {}
        if m:
            for k, v in (m.groupdict() or {}).items():
                if k != "ts" and v is not None:
                    fields[k] = v
        return Record(
            text=text,
            start_line=pending[0][0],
            end_line=pending[-1][0],
            timestamp=ts,
            fields=fields,
        )


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

_BUILDERS: Dict[str, Any] = {
    "rawtext": RawTextSegmenter,
    "text": RawTextSegmenter,
    "regex": RegexSegmenter,
    "jsonline": JsonLineSegmenter,
    "json": JsonLineSegmenter,
    "jsonl": JsonLineSegmenter,
    "format": FormatSegmenter,
}

_PRESET_FORMATS: Dict[str, Dict[str, Any]] = {}
# Application log presets are registered by upper layers.

_DETECTORS: Dict[str, Tuple[int, Callable[..., Optional[str]]]] = {}


def register_segmenter(
    name: str,
    factory: Any,
    *,
    aliases: Tuple[str, ...] = (),
    replace: bool = False,
) -> None:
    """公开的 segmenter 注册 API；重复注册同一 factory 幂等。"""
    names = (name, *aliases)
    for raw in names:
        key = str(raw).strip().lower()
        if not key:
            raise ValueError("segmenter 名不能为空")
        current = _BUILDERS.get(key)
        if current is not None and current is not factory and not replace:
            raise ValueError(f"segmenter {key!r} 已注册")
        if key in _PRESET_FORMATS and not replace:
            raise ValueError(f"名称 {key!r} 已被 format 注册")
        if replace:
            _PRESET_FORMATS.pop(key, None)
        _BUILDERS[key] = factory


def register_format(
    name: str,
    definition: Dict[str, Any],
    *,
    replace: bool = False,
) -> None:
    """注册命名声明式格式；定义会复制保存，避免调用方后续修改。"""
    key = str(name).strip().lower()
    if not key:
        raise ValueError("format 名不能为空")
    if key in _PRESET_FORMATS and _PRESET_FORMATS[key] != definition and not replace:
        raise ValueError(f"format {key!r} 已注册")
    if key in _BUILDERS and not replace:
        raise ValueError(f"名称 {key!r} 已被 segmenter 注册")
    if replace:
        _BUILDERS.pop(key, None)
    _PRESET_FORMATS[key] = dict(definition)


def register_segmenter_detector(
    name: str,
    detector: Callable[..., Optional[str]],
    *,
    priority: int = 0,
    replace: bool = False,
) -> None:
    """注册格式嗅探器。返回 ``None`` 表示不认识，按优先级继续尝试。"""
    key = str(name).strip().lower()
    current = _DETECTORS.get(key)
    if current is not None and current[1] is not detector and not replace:
        raise ValueError(f"segmenter detector {key!r} 已注册")
    _DETECTORS[key] = (int(priority), detector)


def available_segmenters() -> List[str]:
    return sorted(set(_BUILDERS) | set(_PRESET_FORMATS))


def _detect_core_segmenter(path: Path, *, sample_lines: int = 200) -> str:
    json_lines = 0
    sampled = 0
    with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
        for sampled, line in enumerate(handle, start=1):
            if sampled > sample_lines:
                break
            stripped = line.lstrip()
            if stripped.startswith("{") and stripped.rstrip().endswith("}"):
                try:
                    _json.loads(stripped)
                    json_lines += 1
                except ValueError:
                    pass
    if sampled and json_lines >= max(1, sampled // 2):
        return "jsonline"
    return "rawtext"


def detect_segmenter_kind(
    path: Path, *, sample_lines: int = 200
) -> Union[str, Dict[str, Any]]:
    """通过公开 detector 链嗅探格式，最后回落 core 默认实现。

    返回 ``str``（内置/插件格式名）或 ``FormatSegmenter`` 定义 dict
    （L1 线索探测器高置信时对陌生日志自动推断出的声明式配置，
    可直接喂 build_segmenter）。
    """
    for _name, (_priority, detector) in sorted(
        _DETECTORS.items(), key=lambda item: item[1][0], reverse=True
    ):
        detected = detector(Path(path), sample_lines=sample_lines)
        if detected and str(detected) != "rawtext":
            # 明确的格式识别（插件名 / jsonline 等）：立即返回。
            # "rawtext" 是兜底信号（上层 detector 可能用它表示"只认得它是文本"），
            # 不中断探测链，继续尝试 L1 线索探测——若推断出时间戳格式更优。
            return str(detected)
    core = _detect_core_segmenter(Path(path), sample_lines=sample_lines)
    if core != "rawtext":
        # 内置链明确识别（jsonline 等）：优先，不触发探测。
        return core
    # 内置链只能兜底 rawtext → L1 线索探测器高置信分支。
    # 惰性导入：format_probe 是本模块新增的探测能力，避免模块加载循环。
    from .format_probe import probe_format_config

    inferred = probe_format_config(Path(path), sample_lines=sample_lines)
    if inferred:
        return inferred
    return "rawtext"


def build_segmenter(kind: Any = "rawtext", **options: Any) -> Segmenter:
    """按名字或声明式 format 定义构造分段器。

    - ``build_segmenter({"start": "...", ...})``：内联声明式
    - ``build_segmenter("rawtext")``：内置常用格式
    - ``build_segmenter("jsonline")``：JSON 行
    - 设备/业务格式名由上层插件注册后可用
    """
    if isinstance(kind, dict):
        return FormatSegmenter(**kind)
    key = (kind or "rawtext").strip().lower()
    definition = _PRESET_FORMATS.get(key)
    if definition is not None:
        merged = dict(definition)
        merged.update(options)
        return FormatSegmenter(**merged)
    cls = _BUILDERS.get(key)
    if cls is None:
        available = ", ".join(available_segmenters())
        raise ValueError(f"不支持的 segmenter: {kind!r}（可选: {available}，或传 format 定义 dict）")
    return cls(**options)
