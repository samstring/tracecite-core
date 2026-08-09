"""统一分析事件模型。

事件正文留在原始/过滤日志中，模型只保存结构化字段与可复核定位；``text`` 仅供
本次进程内断言匹配，默认不序列化，避免复制大段日志。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Union


@dataclass(frozen=True)
class EventRef:
    source_path: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"source_path": self.source_path}
        if self.start_line is not None:
            out["start_line"] = self.start_line
        if self.end_line is not None:
            out["end_line"] = self.end_line
        return out


@dataclass
class AnalysisEvent:
    timestamp: Optional[str]
    category: str
    name: str
    source: str
    label: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    raw_ref: Optional[EventRef] = None
    parent_event_ids: List[str] = field(default_factory=list)
    transformations: List[str] = field(default_factory=list)
    event_id: str = ""
    text: Optional[str] = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.event_id:
            identity = "|".join(
                [
                    self.timestamp or "",
                    self.category,
                    self.name,
                    self.source,
                    self.raw_ref.source_path if self.raw_ref else "",
                    str(self.raw_ref.start_line if self.raw_ref else ""),
                ]
            )
            self.event_id = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]

    def to_dict(self, *, include_text: bool = False) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "category": self.category,
            "name": self.name,
            "source": self.source,
        }
        if self.label:
            out["label"] = self.label
        if self.attributes:
            out["attributes"] = self.attributes
        if self.raw_ref is not None:
            out["raw_ref"] = self.raw_ref.to_dict()
        if self.parent_event_ids:
            out["parent_event_ids"] = list(self.parent_event_ids)
        if self.transformations:
            out["transformations"] = list(self.transformations)
        if include_text and self.text is not None:
            out["text"] = self.text
        return out

    def searchable_text(self) -> str:
        # attributes 可能含 filter pattern、配置名等控制面元数据；把它们混入
        # 全文匹配会让断言被自己的规则污染。属性只能通过 DSL attributes 显式匹配。
        return "\n".join([self.category, self.name, self.label or "", self.text or ""])


class EventTransformError(RuntimeError):
    """事件转换器配置或执行失败。"""


@dataclass(frozen=True)
class EventTransformContext:
    scenario: str = ""
    platform: str = ""
    source_path: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


EventTransformer = Callable[
    [AnalysisEvent, Mapping[str, Any], EventTransformContext],
    Optional[Union[AnalysisEvent, Iterable[AnalysisEvent]]],
]
_EVENT_TRANSFORMERS: Dict[str, EventTransformer] = {}


def register_event_transformer(
    name: str, transformer: EventTransformer, *, replace: bool = False
) -> None:
    """注册事件转换器；一个输入事件可产出零个、一个或多个统一事件。"""
    key = str(name).strip().lower()
    if not key:
        raise ValueError("event transformer 名不能为空")
    current = _EVENT_TRANSFORMERS.get(key)
    if current is not None and current is not transformer and not replace:
        raise ValueError(f"event transformer {key!r} 已注册")
    _EVENT_TRANSFORMERS[key] = transformer


def available_event_transformers() -> List[str]:
    return sorted(_EVENT_TRANSFORMERS)


def apply_event_transformers(
    events: Iterable[AnalysisEvent],
    steps: Sequence[Union[Mapping[str, Any], str]],
    *,
    context: Optional[EventTransformContext] = None,
) -> List[AnalysisEvent]:
    """按声明顺序执行转换管道。转换器签名为 ``(event, params, context)``。"""
    current = list(events)
    resolved_context = context or EventTransformContext()
    for index, raw_step in enumerate(steps):
        if isinstance(raw_step, str):
            name = raw_step
            params: Dict[str, Any] = {}
        elif isinstance(raw_step, Mapping):
            name = str(raw_step.get("type") or "")
            params = {str(key): value for key, value in raw_step.items() if key != "type"}
        else:
            raise EventTransformError(f"events.transforms[{index}] 必须是字符串或对象")
        key = name.strip().lower()
        transformer = _EVENT_TRANSFORMERS.get(key)
        if transformer is None:
            known = ", ".join(available_event_transformers()) or "(空)"
            raise EventTransformError(f"未知 event transformer {key!r}（可用: {known}）")

        transformed: List[AnalysisEvent] = []
        for event in current:
            try:
                result = transformer(event, params, resolved_context)
            except Exception as exc:
                raise EventTransformError(
                    f"event transformer {key!r} 处理 {event.event_id} 失败: {exc}"
                ) from exc
            if result is None:
                continue
            produced = [result] if isinstance(result, AnalysisEvent) else list(result)
            if any(not isinstance(item, AnalysisEvent) for item in produced):
                raise EventTransformError(
                    f"event transformer {key!r} 必须返回 AnalysisEvent、事件迭代或 None"
                )
            for item in produced:
                if item.raw_ref is None:
                    item.raw_ref = event.raw_ref
                if event.event_id not in item.parent_event_ids:
                    item.parent_event_ids.append(event.event_id)
                if key not in item.transformations:
                    item.transformations.append(key)
                transformed.append(item)
        current = transformed
    return current


def parse_event_datetime(value: Optional[str]) -> Optional[datetime]:
    """解析统一事件时间；无年份日志固定使用 2000 年，便于计算同窗时差。"""
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%b %d %H:%M:%S.%f",
        "%b %d %H:%M:%S",
        "%m-%d %H:%M:%S.%f",
    ):
        try:
            parsed = datetime.strptime(raw, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=2000)
            return parsed
        except ValueError:
            continue
    return None


def events_from_filter_result(result: Any) -> List[AnalysisEvent]:
    """把 ``FilterResult`` 的命中记录转换为统一事件。"""
    records_path = getattr(result, "records_path", None)

    def iter_rows() -> Iterable[tuple[str, Mapping[str, Any]]]:
        if records_path and Path(records_path).is_file():
            with Path(records_path).open("r", encoding="utf-8") as handle:
                for line in handle:
                    payload = json.loads(line)
                    yield str(payload.get("text") or ""), payload.get("metadata") or {}
            return
        chunks = list(getattr(result, "matched_content", ()) or ())
        metadata = list(getattr(result, "matched_record_metadata", ()) or ())
        for index, chunk in enumerate(chunks):
            yield chunk, metadata[index] if index < len(metadata) else {}
    source_path = str(getattr(result, "original_source", ""))
    pattern = str(getattr(result, "pattern", ""))
    out: List[AnalysisEvent] = []
    for index, (chunk, meta) in enumerate(iter_rows()):
        term = meta.get("term")
        first_line = next((line.strip() for line in chunk.splitlines() if line.strip()), "")
        out.append(
            AnalysisEvent(
                timestamp=meta.get("timestamp"),
                category="log_match",
                name=str(term or "pattern_match"),
                label=first_line[:240] or None,
                source="filter",
                attributes={
                    "term": term,
                    "terms": list(meta.get("terms") or []),
                    "pattern": pattern,
                    "record_index": index,
                },
                raw_ref=EventRef(
                    source_path=source_path,
                    start_line=meta.get("start_line"),
                    end_line=meta.get("end_line"),
                ),
                text=chunk,
            )
        )
    return out


def write_events_jsonl(path: Path, events: Iterable[AnalysisEvent]) -> Path:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    return resolved
