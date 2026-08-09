# -*- coding: utf-8 -*-
"""通用文本过滤：快照定界 + scope + grep，供 Agent 分析（省 token）。"""

from __future__ import annotations

import random
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from .matcher import Matcher
from .state_file import state_lock
from .segmenter import RawTextSegmenter, Segmenter

_LAST_DURATION_RE = re.compile(
    r"^(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>s|sec|secs|m|min|mins|h|hr|hrs|hour|hours)?$",
    re.IGNORECASE,
)


class FilterError(Exception):
    """日志过滤失败。"""


def pattern_from_terms(terms: List[str]) -> str:
    """字面量 terms → 正则 pattern；去空、保序去重。"""
    seen = set()
    out: List[str] = []
    for term in terms:
        t = str(term).strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(re.escape(t))
    return "|".join(out)


def combine_patterns(*patterns: Optional[str]) -> str:
    """并联多个正则片段；空片段忽略，重复片段只保留一份。"""
    parts: List[str] = []
    for raw in patterns:
        text = (raw or "").strip()
        if text and text not in parts:
            parts.append(text)
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return "|".join(f"(?:{p})" for p in parts)


def merge_terms(*groups: Optional[List[str]]) -> List[str]:
    """多组 terms 按出现顺序合并去重。"""
    seen = set()
    out: List[str] = []
    for group in groups:
        if not group:
            continue
        for term in group:
            t = str(term).strip()
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(t)
    return out


# Preset 只注册名字，关键词全部不在代码里。
# 写入项目 `.tracecite/knowledge.<platform>.json`（grow term / preset add）后才生效。
DEFAULT_FILTER_PRESET_NAMES: Tuple[str, ...] = (
    "profile-leak",
    "apm-frame",
    "memory-leak",
    "user-behavior",
    "network-http",
    "user-action",
    "user-nav",
)

DEFAULT_FILTER_PRESET_SEEDS: Dict[str, List[str]] = {
    name: [] for name in DEFAULT_FILTER_PRESET_NAMES
}

DEFAULT_FILTER_PRESETS: Dict[str, Tuple[str, str]] = {
    name: ("", name) for name in DEFAULT_FILTER_PRESET_NAMES
}

# filtered 文件头部与正文的分隔行。头部里含 `# pattern: ...` 等元信息，
# 任何「在过滤结果里统计命中」的逻辑都必须先剥掉它，否则 pattern 自身
# 会被当成一次命中（0 命中的场景会被误判成断言满足）。
HEADER_TERMINATOR = "# ---"


def strip_filter_header(body: str) -> str:
    """剥掉 filtered 文件的元信息头部，只留正文。没有头部就原样返回。"""
    marker = HEADER_TERMINATOR + "\n"
    if marker in body:
        return body.split(marker, 1)[1]
    return body


# ---------------------------------------------------------------------------
# 未命中统计与模板折叠（纯附加信息，正文零污染）
# ---------------------------------------------------------------------------

# 未命中样本池上限：只保留前 N 条未命中记录，避免内存/输出膨胀
_UNMATCHED_POOL_MAX = 200
# 单条未命中样本截断长度
_UNMATCHED_SAMPLE_CHARS = 300
# 命中记录数达到该阈值才生成 .templates.jsonl（太少时折叠无意义）；<=0 关闭
# 折叠是「按需的分布概览」：默认关闭（0），agent 需要事件形状概览时显式
# 开启（--fold / scenario fold:true）。折叠绝不替代全量：正文 .filtered/ 始终
# 完整，命中侧 term_usage + 未命中侧 unmatched_summary 才是「环境无遗漏」的双侧覆盖。
DEFAULT_TEMPLATE_THRESHOLD = 10
# 模板折叠后的样本截断长度
_TEMPLATE_SAMPLE_CHARS = 300
# 模板 count 达到该阈值才输出 value_distribution（碎片模板不输出，控体积）
_VALUE_DIST_MIN_COUNT = 10

# 未命中记录里提取「有意义的 token」：>=4 位的字母数字/下划线，或 >=2 个中文字符
_UNMATCHED_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{4,}|[\u4e00-\u9fff]{2,}")

def _extract_record_tokens(text: str, *, header_re: Optional[re.Pattern] = None, token_re: Optional[re.Pattern] = None) -> List[str]:
    """从未命中记录提取业务正文 token，按记录去重（同一 token 一条记录只算一次）。"""
    seen = set()
    out: List[str] = []
    tok_re = token_re or _UNMATCHED_TOKEN_RE
    for line in text.splitlines():
        m = header_re.match(line) if header_re is not None else None
        body = line[m.end():] if m else line
        for tok in tok_re.findall(body):
            if tok in seen:
                continue
            seen.add(tok)
            out.append(tok)
    return out


def top_terms_in_text(
    path: Path,
    *,
    segmenter: Optional[Segmenter] = None,
    exclude: Sequence[str] = (),
    min_count: int = 3,
    limit: int = 20,
) -> List[Dict[str, object]]:
    """全量统计日志中的高频业务 token（按记录去重计数），供 ``grow`` 自成长发现候选。

    - 复用未命中统计的 header 剥离与 token 提取：只统计业务正文，时间戳/级别/线程名不污染
    - 排除 ``exclude``（已有词表词 / 已有 marker needle 等）
    - 返回 ``[{token, count}]`` 按 count 降序，纯统计不写盘

    用途：``grow suggest / auto`` 的候选源——从"环境里高频出现但词表还没覆盖"的
    token 里自动发现该 grow 的词，实现知识库自成长。
    """
    path = Path(path).expanduser()
    seg = segmenter or RawTextSegmenter()
    exclude_set = set(exclude)
    counter: Counter = Counter()
    for record in seg.segment_file(path):
        for tok in _extract_record_tokens(record.text, header_re=seg.header_strip_re, token_re=seg.token_re):
            if tok in exclude_set:
                continue
            counter[tok] += 1
    out: List[Dict[str, object]] = []
    for tok, count in counter.most_common(limit * 3):
        if count < min_count:
            break
        out.append({"token": tok, "count": count})
        if len(out) >= limit:
            break
    return out

# 模板归一化：先把时间戳 / IP / 十六进制 / 数字替换为占位符，再按空白切 token。
# 顺序不能乱：时间戳含数字，IP 含数字，HEX 可能被当成数字。
_TS_RE = re.compile(
    r"(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"|[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"|\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)"
)
_IP_RE = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")
_HEX_RE = re.compile(r"0x[0-9a-fA-F]+|[0-9a-fA-F]{8,}")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _hit_lines(record: "_LogRecord", term: str) -> List[int]:
    """命中词在记录块内的物理行号（绝对行号）。"""
    lines: List[int] = []
    for idx, line in enumerate(record.text.splitlines()):
        if term in line:
            lines.append(record.start_line + idx)
    return lines


def _build_unmatched_summary(
    *,
    unmatched_count: int,
    scoped_records: int,
    token_counter: Counter,
    pool: List[str],
) -> Optional[Dict[str, object]]:
    """未命中统计 + 分层抽样：高频 token 命中样本 + 随机样本。"""
    if scoped_records == 0:
        return None
    summary: Dict[str, object] = {
        "unmatched_records": unmatched_count,
        "scoped_records": scoped_records,
        "unmatched_ratio": round(unmatched_count / scoped_records, 4),
        "top_unmatched_tokens": [
            {"token": tok, "count": count}
            for tok, count in token_counter.most_common(10)
        ],
        "samples": {},
    }
    if not pool:
        return summary

    samples: Dict[str, List[str]] = {}
    if summary["top_unmatched_tokens"]:
        head = str(summary["top_unmatched_tokens"][0]["token"])  # type: ignore[index]
        high = [s for s in pool if head in s][:3]
        if high:
            samples["high_freq"] = high
    chosen_ids = {id(s) for row in samples.values() for s in row}
    rest = [s for s in pool if id(s) not in chosen_ids]
    if rest:
        rand = random.sample(rest, min(3, len(rest)))
        if rand:
            samples["random"] = rand
    summary["samples"] = samples  # type: ignore[assignment]
    return summary


def _normalize_for_template(text: str, *, normalizers: Optional[List[Tuple[re.Pattern, str]]] = None) -> str:
    """把记录文本归一化成模板 key。自定义 normalizers 优先于内置默认。"""
    t = text
    # 自定义 normalizers（segmenter 提供，格式特定规则）
    if normalizers:
        for pat, repl in normalizers:
            t = pat.sub(repl, t)
    t = _TS_RE.sub("<TS>", t)
    t = _IP_RE.sub("<IP>", t)
    t = _HEX_RE.sub("<HEX>", t)
    t = _NUM_RE.sub("<NUM>", t)
    return " ".join(t.split())


def _collect_value_distribution(text: str) -> Dict[str, Counter]:
    """收集模板占位符位置的真实值分布（供诊断：状态码/耗时不能被归一吞掉）。

    顺序必须是 IP → HEX → TS → NUM：IP 含数字、TS 含数字，先归一才能避免
    数值 token 被 NUM 提前抓走（如 callStatus=200 与 callCost=243 各自归位）。
    """
    out: Dict[str, Counter] = {
        "<IP>": Counter(),
        "<HEX>": Counter(),
        "<TS>": Counter(),
        "<NUM>": Counter(),
    }
    t = text
    for pat, tag in ((_IP_RE, "<IP>"), (_HEX_RE, "<HEX>"), (_TS_RE, "<TS>"), (_NUM_RE, "<NUM>")):
        if not t:
            break
        for match in pat.finditer(t):
            out[tag][match.group(0)] += 1
        t = pat.sub(tag, t)
    return {tag: c for tag, c in out.items() if c}


def _fold_templates(
    items: List[Dict[str, object]],
    *,
    normalizers: Optional[List[Tuple[re.Pattern, str]]] = None,
) -> List[Dict[str, object]]:
    """按归一化模板聚合命中记录，输出模板折叠视图（count 降序）。

    每个模板附带 ``value_distribution``：占位符位置（``<NUM>`` 等）的真实值 top5
    及计数 —— 状态码、耗时这类"数值即信号"的字段不会被归一吞掉（200 与 500
    在模板上合并，但值分布里能看到 200×957 / 500×1）。
    """
    groups: Dict[str, Dict[str, object]] = {}
    for item in items:
        text = str(item["text"])
        key = str(_normalize_for_template(text, normalizers=normalizers))
        group = groups.get(key)
        if group is None:
            group = {
                "template": key,
                "count": 0,
                "terms": set(),
                "sample": None,
                "first_seen": item.get("ts"),
                "values": {},
            }
            groups[key] = group
        group["count"] = int(group["count"]) + 1  # type: ignore[arg-type]
        term = item.get("term")
        if term:
            group["terms"].add(str(term))  # type: ignore[union-attr]
        sample = str(item["text"]).strip()[:_TEMPLATE_SAMPLE_CHARS]
        if group["sample"] is None:
            group["sample"] = sample
        elif term and term in str(item["text"]) and not group.get("has_term_sample"):
            # 优先换一条「包含命中词」的样本，让 Agent 一眼看出为什么被捞
            group["sample"] = sample
            group["has_term_sample"] = True
        for tag, counter in _collect_value_distribution(text).items():
            bucket = group["values"].setdefault(tag, Counter())  # type: ignore[union-attr,arg-type]
            for value, count in counter.items():
                bucket[value] += count  # type: ignore[index]

    entries: List[Dict[str, object]] = []
    for group in sorted(groups.values(), key=lambda g: -int(g["count"])):  # type: ignore[arg-type]
        terms = sorted(str(t) for t in group["terms"])  # type: ignore[union-attr]
        # 值分布只对高频模板输出（count 达到阈值）：碎片模板（count=1 等）输出空，
        # 否则值分布会把 JSONL 体积放大 2-3 倍，省 token 的目的落空
        count = int(group["count"])  # type: ignore[arg-type]
        if count >= _VALUE_DIST_MIN_COUNT:
            value_dist = {
                tag: [{"value": v, "count": c} for v, c in bucket.most_common(5)]
                for tag, bucket in group["values"].items()  # type: ignore[union-attr]
            }
        else:
            value_dist = {}
        entries.append(
            {
                "template": group["template"],
                "count": count,
                "matched_terms": terms,
                "sample": group["sample"],
                "first_seen": group["first_seen"],
                "value_distribution": value_dist,
            }
        )
    return entries


def template_stats(
    entries: List[Dict[str, object]], *, match_records: int
) -> Dict[str, object]:
    """折叠质量指标：碎片率/覆盖率 —— 帮助判断「折叠是否还有效」。

    碎片化时（url/接口名等字符串字段各异）模板数 ≈ 命中数、fold_ratio 很低，
    此时折叠视图既不能省 token 也不能看分布，应提示直接看原文或按字段收窄。
    """
    if not entries or match_records <= 0:
        return {
            "templates": 0,
            "folded_records": 0,
            "singleton_templates": 0,
            "fold_ratio": 0.0,
        }
    folded_records = sum(int(e["count"]) for e in entries if int(e["count"]) > 1)
    singletons = sum(1 for e in entries if int(e["count"]) == 1)
    return {
        "templates": len(entries),
        "folded_records": folded_records,
        "singleton_templates": singletons,
        "fold_ratio": round(folded_records / match_records, 4),
    }


@dataclass
class FilterResult:
    """过滤结果。"""

    original_source: Path
    original_total_lines_at_run: int
    output_path: Path
    tag: str
    pattern: str
    work_input: Path
    total_lines: int
    match_lines: int
    match_records: int = 0
    snapshot_path: Optional[Path] = None
    snapshot_lines: Optional[int] = None
    scope: Optional[str] = None
    time_from: Optional[str] = None
    time_to: Optional[str] = None
    records_path: Optional[Path] = None
    history_path: Optional[Path] = None
    engine: str = "regex"
    hits_path: Optional[Path] = None
    templates_path: Optional[Path] = None
    template_stats: Optional[Dict[str, object]] = None
    unmatched_summary: Optional[Dict[str, object]] = None
    term_usage: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "original_source": str(self.original_source),
            "original_total_lines_at_run": self.original_total_lines_at_run,
            "output_path": str(self.output_path),
            "tag": self.tag,
            "pattern": self.pattern,
            "work_input": str(self.work_input),
            "total_lines": self.total_lines,
            "match_lines": self.match_lines,
            "match_records": self.match_records,
            "snapshot_path": str(self.snapshot_path) if self.snapshot_path else None,
            "snapshot_lines": self.snapshot_lines,
            "scope": self.scope,
            "time_from": self.time_from,
            "time_to": self.time_to,
            "records_path": str(self.records_path) if self.records_path else None,
            "history_path": str(self.history_path) if self.history_path else None,
            "engine": self.engine,
            "hits_path": str(self.hits_path) if self.hits_path else None,
            "templates_path": str(self.templates_path) if self.templates_path else None,
            "template_stats": self.template_stats,
            "unmatched_summary": self.unmatched_summary,
            "term_usage": self.term_usage,
        }

    def metadata_header(self) -> str:
        lines = [
            "# tracecite log filter",
            f"# original_source: {self.original_source}",
            f"# original_total_lines_at_run: {self.original_total_lines_at_run}",
        ]
        if self.snapshot_path is not None:
            lines.append(f"# snapshot: {self.snapshot_path}")
            if self.snapshot_lines is not None:
                lines.append(f"# snapshot_lines: {self.snapshot_lines}")
        if self.scope:
            lines.append(f"# scope: {self.scope}")
            lines.append(f"# scoped_input_lines: {self.total_lines}")
        if self.time_from:
            lines.append(f"# time_from: {self.time_from}")
        if self.time_to:
            lines.append(f"# time_to: {self.time_to}")
        if self.history_path is not None:
            lines.append(f"# history: {self.history_path}")
        lines.extend(
            [
                f"# work_input: {self.work_input}",
                f"# tag: {self.tag}",
                f"# pattern: {self.pattern}",
                f"# engine: {self.engine}",
                f"# filtered_at: {datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}",
                f"# total_lines: {self.total_lines}",
                f"# match_records: {self.match_records}",
                f"# match_lines: {self.match_lines}",
                HEADER_TERMINATOR,
            ]
        )
        if self.hits_path is not None:
            lines.insert(-1, f"# hits: {self.hits_path}")
        if self.templates_path is not None:
            lines.insert(-1, f"# templates: {self.templates_path}")
        return "\n".join(lines) + "\n"


@dataclass
class _LogRecord:
    text: str
    start_line: int
    end_line: int
    # 分段器已解析出的时间戳；不完整日期由该分段器的时间策略补全。
    timestamp: Optional[datetime] = None
    fields: Dict[str, object] = field(default_factory=dict)


def _count_lines(path: Path, *, encoding: str = "utf-8") -> int:
    count = 0
    with path.open(encoding=encoding, errors="replace") as handle:
        for _ in handle:
            count += 1
    return count


def _format_scope_time(ts: datetime) -> str:
    return ts.isoformat(timespec="seconds")


def parse_last_duration(raw: str) -> timedelta:
    """解析 --last：60 / 60s / 1m / 5m / 1h。"""
    text = (raw or "").strip()
    match = _LAST_DURATION_RE.match(text)
    if not match:
        raise FilterError(
            f"非法 --last: {raw!r}（示例: 60s / 1m / 5m / 1h）"
        )
    value = float(match.group("value"))
    unit = (match.group("unit") or "s").lower()
    if unit in ("s", "sec", "secs"):
        return timedelta(seconds=value)
    if unit in ("m", "min", "mins"):
        return timedelta(minutes=value)
    if unit in ("h", "hr", "hrs", "hour", "hours"):
        return timedelta(hours=value)
    raise FilterError(f"非法 --last 单位: {raw!r}")


def reference_datetime(
    path: Path,
    *,
    segmenter: Optional[Segmenter] = None,
    encoding: str = "utf-8",
) -> datetime:
    """Use the first parsed record as the reference; mtime is the fallback."""
    path = Path(path).expanduser().resolve()
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    selected = segmenter or RawTextSegmenter()
    for record in selected.segment_file(path, encoding=encoding):
        ts = selected.record_timestamp(record, reference=mtime)
        if ts is not None:
            return ts
    return mtime


def parse_time_arg(
    raw: str,
    *,
    ref: datetime,
    segmenter: Optional[Segmenter] = None,
) -> datetime:
    """
    解析 --since / --until。
    Core 支持 HH:MM[:SS] / YYYY-MM-DD[ T]HH:MM[:SS]；其余由分段器解释。
    """
    text = (raw or "").strip()
    if not text:
        raise FilterError("时间参数不能为空")

    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass

    if segmenter is not None:
        parsed = segmenter.parse_time_argument(text, reference=ref)
        if parsed is not None:
            return parsed

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            return ref.replace(
                hour=parsed.hour,
                minute=parsed.minute,
                second=parsed.second if fmt == "%H:%M:%S" else 0,
                microsecond=0,
            )
        except ValueError:
            pass

    raise FilterError(
        f"非法时间: {raw!r}（Core 支持 18:42:00 / 2026-07-25T18:42:00；"
        "其他格式需由当前 segmenter 提供）"
    )


def record_timestamp(
    record: _LogRecord,
    *,
    ref: datetime,
    segmenter: Optional[Segmenter] = None,
) -> Optional[datetime]:
    """Resolve a timestamp through the selected format strategy."""
    selected = segmenter or RawTextSegmenter()
    return selected.record_timestamp(record, reference=ref)


def _find_last_timestamp(
    path: Path, *, ref: datetime, segmenter: Optional[Segmenter] = None, encoding: str = "utf-8"
) -> Optional[datetime]:
    last: Optional[datetime] = None
    for record in _iter_merged_records(path, segmenter=segmenter, encoding=encoding):
        ts = record_timestamp(record, ref=ref, segmenter=segmenter)
        if ts is not None:
            last = ts
    return last


def _resolve_time_window(
    work_input: Path,
    *,
    last: Optional[str],
    since: Optional[str],
    until: Optional[str],
    segmenter: Optional[Segmenter] = None,
    encoding: str = "utf-8",
) -> Tuple[Optional[datetime], Optional[datetime], Optional[str]]:
    """返回 (time_from, time_to, last_raw_for_scope)。"""
    if last is None and since is None and until is None:
        return None, None, None

    ref = reference_datetime(work_input, segmenter=segmenter, encoding=encoding)
    time_from: Optional[datetime] = None
    time_to: Optional[datetime] = None

    if last is not None:
        duration = parse_last_duration(last)
        last_ts = _find_last_timestamp(
            work_input, ref=ref, segmenter=segmenter, encoding=encoding
        )
        if last_ts is None:
            raise FilterError("无法从日志解析时间戳，不能使用 --last")
        time_from = last_ts - duration
        time_to = last_ts

    if since is not None:
        since_ts = parse_time_arg(since, ref=ref, segmenter=segmenter)
        time_from = since_ts if time_from is None else max(time_from, since_ts)
    if until is not None:
        until_ts = parse_time_arg(until, ref=ref, segmenter=segmenter)
        time_to = until_ts if time_to is None else min(time_to, until_ts)

    if time_from is not None and time_to is not None and time_from > time_to:
        raise FilterError(
            f"时间窗口无效: time_from={_format_scope_time(time_from)} > "
            f"time_to={_format_scope_time(time_to)}"
        )
    return time_from, time_to, last


def _record_in_time_window(
    record: _LogRecord,
    *,
    ref: datetime,
    time_from: Optional[datetime],
    time_to: Optional[datetime],
    segmenter: Optional[Segmenter] = None,
) -> bool:
    if time_from is None and time_to is None:
        return True
    ts = record_timestamp(record, ref=ref, segmenter=segmenter)
    if ts is None:
        # 无时间头的续行块：若整段无头，保守保留（通常合并后都有头）
        return True
    if time_from is not None and ts < time_from:
        return False
    if time_to is not None and ts > time_to:
        return False
    return True


def text_time_range(
    path: Path,
    *,
    segmenter: Optional[Segmenter] = None,
    encoding: str = "utf-8",
) -> Dict[str, object]:
    """统计日志文件的记录级时间范围与分钟分布。

    **不要用「首末物理行」判定时间范围**——线上日志包尾部可能有补打行
    （时间倒挂，实测首末行都是 21:41:21 而真实覆盖 13 分钟），
    必须以分钟分布为准。本函数一次性给出：

    - ``time_from / time_to``：记录时间戳的最早/最晚（含解析失败计数）
    - ``minute_distribution``：每分钟记录数（按记录数降序），用于判断真实覆盖
    """
    path = Path(path).expanduser().resolve()
    ref = reference_datetime(path, segmenter=segmenter, encoding=encoding)
    minutes: Counter = Counter()
    total_records = 0
    unparsed = 0
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None
    for record in _iter_merged_records(path, segmenter=segmenter, encoding=encoding):
        total_records += 1
        ts = record_timestamp(record, ref=ref, segmenter=segmenter)
        if ts is None:
            unparsed += 1
            continue
        if first_ts is None or ts < first_ts:
            first_ts = ts
        if last_ts is None or ts > last_ts:
            last_ts = ts
        minutes[ts.strftime("%Y-%m-%d %H:%M")] += 1
    return {
        "path": str(path),
        "total_lines": _count_lines(path, encoding=encoding),
        "total_records": total_records,
        "unparsed_records": unparsed,
        "time_from": _format_scope_time(first_ts) if first_ts else None,
        "time_to": _format_scope_time(last_ts) if last_ts else None,
        "minute_distribution": [
            {"minute": minute, "records": count} for minute, count in minutes.most_common()
        ],
    }


def _safe_tag(tag: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]", "_", tag.replace(" ", "_").replace("/", "_").replace(":", "_"))
    return cleaned[:64] or "filtered"


def _default_tag_from_pattern(pattern: str) -> str:
    tag = re.sub(r"\|", "_", pattern)
    tag = re.sub(r"[^0-9A-Za-z_-]", "", tag)
    return (tag[:32] or "filtered")


def _iter_merged_records(
    path: Path, *, segmenter: Optional[Segmenter] = None, encoding: str = "utf-8"
) -> Iterator[_LogRecord]:
    """按 stream 过滤逻辑合并物理行；只用于 filter 的离线二次筛选。

    分段规则由调用方注入；Core 默认按物理行处理，不含设备格式知识。
    """
    seg = segmenter or RawTextSegmenter()
    for record in seg.segment_file(path, encoding=encoding):
        yield _LogRecord(
            text=record.text,
            start_line=record.start_line,
            end_line=record.end_line,
            timestamp=record.timestamp,
            fields=dict(record.fields),
        )


def _resolve_scope_bounds(
    total_lines: int,
    *,
    tail_lines: Optional[int],
    line_from: Optional[int],
    line_to: Optional[int],
) -> Tuple[int, Optional[int]]:
    start = line_from or 1
    end = line_to
    if tail_lines is not None:
        tail_start = max(1, total_lines - tail_lines + 1)
        start = max(start, tail_start)
    return start, end


def _record_overlaps_scope(record: _LogRecord, start: int, end: Optional[int]) -> bool:
    if record.end_line < start:
        return False
    if end is not None and record.start_line > end:
        return False
    return True


def _build_scope_desc(
    *,
    tail_lines: Optional[int],
    line_from: Optional[int],
    line_to: Optional[int],
    pid: Optional[int],
    last: Optional[str] = None,
    time_from: Optional[datetime] = None,
    time_to: Optional[datetime] = None,
) -> Optional[str]:
    parts: List[str] = []
    if last is not None:
        parts.append(f"last={last}")
    if time_from is not None:
        parts.append(f"time_from={_format_scope_time(time_from)}")
    if time_to is not None:
        parts.append(f"time_to={_format_scope_time(time_to)}")
    if tail_lines is not None:
        parts.append(f"tail={tail_lines}")
    if line_from is not None or line_to is not None:
        parts.append(f"lines={line_from or 1}-{line_to or 'end'}")
    if pid is not None:
        parts.append(f"pid={pid}")
    return ",".join(parts) if parts else None


def _write_filter_history(
    filter_dir: Path,
    result: FilterResult,
) -> Path:
    history_path = filter_dir / "filter_history.jsonl"
    entry = {
        "filtered_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "original_source": str(result.original_source),
        "work_input": str(result.work_input),
        "tag": result.tag,
        "pattern": result.pattern,
        "snapshot": result.snapshot_path is not None,
        "snapshot_path": str(result.snapshot_path) if result.snapshot_path else None,
        "scope": result.scope,
        "time_from": result.time_from,
        "time_to": result.time_to,
        "output_path": str(result.output_path),
        "match_records": result.match_records,
        "match_lines": result.match_lines,
    }
    with state_lock(history_path):
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return history_path


def merge_filter_presets(
    overrides: Optional[Dict[str, Tuple[str, str]]] = None,
) -> Dict[str, Tuple[str, str]]:
    """内置名字表 + 覆盖；允许 pattern 为空（词尚未 grow）。"""
    merged = dict(DEFAULT_FILTER_PRESETS)
    if overrides:
        for name, item in overrides.items():
            pattern, tag = item
            if not name:
                continue
            merged[name] = (pattern or "", tag or name)
    return merged


def resolve_preset(
    preset: str,
    presets: Optional[Dict[str, Tuple[str, str]]] = None,
) -> Tuple[str, str]:
    """返回 (pattern, default_tag)。pattern 为空时提示先 grow term。"""
    table = presets if presets is not None else DEFAULT_FILTER_PRESETS
    if preset not in table:
        names = ", ".join(sorted(table)) or "(无)"
        raise FilterError(f"未知 preset: {preset}（可选: {names}）")
    pattern, tag = table[preset]
    if not (pattern or "").strip():
        raise FilterError(
            f"preset {preset!r} 尚无关键词。"
            "请由调用方提供 preset 词表，或显式传入 pattern。"
        )
    return pattern, tag


def filter_text(
    input_path: Path,
    *,
    pattern: str,
    tag: Optional[str] = None,
    output_path: Optional[Path] = None,
    snapshot: bool = False,
    pid: Optional[int] = None,
    tail_lines: Optional[int] = None,
    line_from: Optional[int] = None,
    line_to: Optional[int] = None,
    last: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    segmenter: Optional[Segmenter] = None,
    template_threshold: int = 0,
    encoding: str = "utf-8",
) -> FilterResult:
    """
    过滤运行日志。

    源文件可能仍在追加时，应设 snapshot=True，先复制到同级隐藏目录 .snapshots/ 再过滤。
    无命中时仍返回 result（match_records=0），便于 Agent 走放宽/兜底，不再抛错。

    ``segmenter`` 决定「一条记录」的边界；Core 默认按物理行处理。
    设备日志、线上日志等具体格式由应用层或插件显式注入。
    """
    original = Path(input_path).expanduser().resolve()
    if not original.is_file():
        raise FilterError(f"日志文件不存在: {original}")

    if not pattern:
        raise FilterError("必须指定 pattern（--grep 或 --preset）")
    if tail_lines is not None and tail_lines <= 0:
        raise FilterError("--tail-lines 必须大于 0")
    if line_from is not None and line_from <= 0:
        raise FilterError("--line-from 必须大于 0")
    if line_to is not None and line_to <= 0:
        raise FilterError("--line-to 必须大于 0")
    if line_from is not None and line_to is not None and line_from > line_to:
        raise FilterError("--line-from 不能大于 --line-to")

    resolved_tag = tag or _default_tag_from_pattern(pattern)
    safe_tag = _safe_tag(resolved_tag)
    src_dir = original.parent
    explicit_output = output_path is not None
    if output_path is not None:
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path: Optional[Path] = None
    snapshot_lines: Optional[int] = None
    work_input = original

    if snapshot:
        snapshot_root = output_path.parent if explicit_output and output_path else src_dir
        snap_dir = snapshot_root / ".snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        snapshot_path = snap_dir / f"{original.stem}_{stamp}.log"
        shutil.copy2(original, snapshot_path)
        work_input = snapshot_path
        snapshot_lines = _count_lines(snapshot_path, encoding=encoding)

    original_total = _count_lines(original, encoding=encoding)

    if output_path is None:
        filter_dir = src_dir / ".filtered"
        filter_dir.mkdir(parents=True, exist_ok=True)
        output_path = filter_dir / f"{safe_tag}_{original.name}"
        history_dir = filter_dir
    else:
        # 显式输出时，过滤历史跟随输出目录，避免回写输入目录。
        history_dir = output_path.parent / ".filtered"
        if output_path.parent.name == ".filtered":
            history_dir = output_path.parent

    try:
        matcher = Matcher(pattern)
    except re.error as exc:
        raise FilterError(f"非法正则: {exc}") from exc

    time_from, time_to, last_raw = _resolve_time_window(
        work_input,
        last=last,
        since=since,
        until=until,
        segmenter=segmenter,
        encoding=encoding,
    )
    ref = reference_datetime(work_input, segmenter=segmenter, encoding=encoding)
    scope = _build_scope_desc(
        tail_lines=tail_lines,
        line_from=line_from,
        line_to=line_to,
        pid=pid,
        last=last_raw,
        time_from=time_from,
        time_to=time_to,
    )

    records_path = Path(str(output_path) + ".records.jsonl")
    records_handle = records_path.open("w", encoding="utf-8")
    hits_candidate = Path(str(output_path) + ".hits.jsonl")
    hits_handle = hits_candidate.open("w", encoding="utf-8")
    match_records = 0
    match_lines = 0
    scoped_physical_lines = 0
    work_total_lines = snapshot_lines if snapshot_lines is not None else original_total
    scope_start, scope_end = _resolve_scope_bounds(
        work_total_lines,
        tail_lines=tail_lines,
        line_from=line_from,
        line_to=line_to,
    )

    pid_token = f"[{int(pid)}]" if pid is not None else None
    scoped_records = 0
    unmatched_count = 0
    token_counter: Counter = Counter()
    unmatched_pool: List[str] = []
    hit_record_count = 0
    term_usage: Dict[str, int] = {}
    template_items: List[Dict[str, object]] = []
    for record in _iter_merged_records(
        work_input, segmenter=segmenter, encoding=encoding
    ):
        if not _record_overlaps_scope(record, scope_start, scope_end):
            continue
        if not _record_in_time_window(
            record,
            ref=ref,
            time_from=time_from,
            time_to=time_to,
            segmenter=segmenter,
        ):
            continue
        scoped_physical_lines += record.end_line - record.start_line + 1
        if pid_token is not None:
            header = record.text.split("\n", 1)[0]
            if pid_token not in header and str(record.fields.get("pid") or "") != str(int(pid)):
                continue
        scoped_records += 1
        matched, term, terms_hit = matcher.match(record.text)
        if not matched:
            unmatched_count += 1
            if len(unmatched_pool) < _UNMATCHED_POOL_MAX:
                unmatched_pool.append(record.text[:_UNMATCHED_SAMPLE_CHARS])
            for tok in _extract_record_tokens(record.text, header_re=segmenter.header_strip_re if segmenter else None, token_re=segmenter.token_re if segmenter else None):
                token_counter[tok] += 1
            continue
        text = record.text if record.text.endswith("\n") else record.text + "\n"
        ts = record_timestamp(record, ref=ref, segmenter=segmenter)
        metadata = {
            "start_line": record.start_line,
            "end_line": record.end_line,
            "term": term,
            "terms": sorted(terms_hit),
            "timestamp": ts.isoformat(timespec="milliseconds") if ts is not None else None,
        }
        records_handle.write(
            json.dumps({"text": text, "metadata": metadata}, ensure_ascii=False) + "\n"
        )
        match_records += 1
        match_lines += text.count("\n")
        if term is not None:
            hit_row = {
                "start_line": record.start_line,
                "end_line": record.end_line,
                "term": term,
                "hit_lines": _hit_lines(record, term),
            }
            hits_handle.write(
                json.dumps(hit_row, ensure_ascii=False) + "\n"
            )
            hit_record_count += 1
            for tok in terms_hit:
                term_usage[tok] = term_usage.get(tok, 0) + 1
        if template_threshold > 0:
            template_items.append(
                {
                    "text": record.text,
                    "term": term,
                    "ts": _format_scope_time(ts) if ts is not None else None,
                }
            )

    records_handle.close()
    hits_handle.close()

    unmatched_summary = _build_unmatched_summary(
        unmatched_count=unmatched_count,
        scoped_records=scoped_records,
        token_counter=token_counter,
        pool=unmatched_pool,
    )

    result = FilterResult(
        original_source=original,
        original_total_lines_at_run=original_total,
        output_path=output_path,
        tag=resolved_tag,
        pattern=pattern,
        work_input=work_input,
        total_lines=scoped_physical_lines,
        match_lines=match_lines,
        match_records=match_records,
        snapshot_path=snapshot_path,
        snapshot_lines=snapshot_lines,
        scope=scope,
        time_from=_format_scope_time(time_from) if time_from else None,
        time_to=_format_scope_time(time_to) if time_to else None,
        records_path=records_path,
        engine=matcher.engine,
        unmatched_summary=unmatched_summary,
        term_usage=term_usage or None,
    )

    history_dir.mkdir(parents=True, exist_ok=True)
    result.history_path = _write_filter_history(history_dir, result)

    # 先写命中元数据与模板折叠（正文零污染，独立产物），再写正文头部引用它们
    if hit_record_count:
        result.hits_path = hits_candidate
    else:
        hits_candidate.unlink(missing_ok=True)
    if template_threshold > 0 and template_items and match_records >= template_threshold:
        entries = _fold_templates(template_items, normalizers=segmenter.template_normalizers if segmenter else None)
        if entries:
            templates_path = Path(str(output_path) + ".templates.jsonl")
            templates_path.write_text(
                "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                encoding="utf-8",
            )
            result.templates_path = templates_path
            result.template_stats = template_stats(entries, match_records=match_records)

    with output_path.open("w", encoding="utf-8") as output_handle:
        output_handle.write(result.metadata_header())
        with records_path.open("r", encoding="utf-8") as records_handle:
            for line in records_handle:
                row = json.loads(line)
                output_handle.write(str(row.get("text") or ""))

    return result


@dataclass
class MultiFilterResult:
    """多来源文本过滤结果。"""

    sources: List[Dict[str, object]]
    pattern: str
    tag: str
    merged_timeline_path: Optional[Path] = None
    match_records: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "sources": self.sources,
            "pattern": self.pattern,
            "tag": self.tag,
            "merged_timeline_path": (
                str(self.merged_timeline_path) if self.merged_timeline_path else None
            ),
            "match_records": self.match_records,
        }


def _source_label_from_path(path: Path) -> str:
    stem = path.stem
    # 通用文件名前缀剥离（pulled_/filtered_）
    for prefix in ("pulled_", "filtered_"):
        if stem.startswith(prefix):
            rest = stem[len(prefix) :]
            # filtered_tag_name → keep last chunk-ish
            if prefix == "filtered_":
                parts = rest.split("_", 1)
                rest = parts[1] if len(parts) > 1 else rest
            return rest.split("_20")[0] or stem
    return stem


def filter_texts(
    input_paths: List[Path],
    *,
    pattern: str,
    tag: Optional[str] = None,
    snapshot: bool = False,
    pid: Optional[int] = None,
    tail_lines: Optional[int] = None,
    line_from: Optional[int] = None,
    line_to: Optional[int] = None,
    last: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    merge_timeline: bool = False,
    source_labels: Optional[List[str]] = None,
    segmenter: Optional[object] = None,
    encoding: str = "utf-8",
    template_threshold: int = 0,
    output_dir: Optional[Path] = None,
) -> MultiFilterResult:
    """对多份日志跑同一 scope/pattern；可选合并时间线。"""
    if not input_paths:
        raise FilterError("至少需要一个日志路径")

    results: List[FilterResult] = []
    source_rows: List[Dict[str, object]] = []
    labels = source_labels or []
    resolved_output_dir = (
        Path(output_dir).expanduser().resolve() if output_dir is not None else None
    )
    if resolved_output_dir is not None:
        resolved_output_dir.mkdir(parents=True, exist_ok=True)

    def segmenter_for(index: int) -> Optional[Segmenter]:
        if isinstance(segmenter, Sequence) and not isinstance(segmenter, (str, bytes)):
            selected = segmenter[index] if index < len(segmenter) else None
            return selected if isinstance(selected, Segmenter) else None
        return segmenter if isinstance(segmenter, Segmenter) else None

    for idx, path in enumerate(input_paths):
        path = Path(path).expanduser()
        label = labels[idx] if idx < len(labels) and labels[idx] else _source_label_from_path(path)
        per_tag = f"{tag or 'multi'}_{_safe_tag(label)}"
        result = filter_text(
            path,
            pattern=pattern,
            tag=per_tag,
            output_path=(
                resolved_output_dir
                / f"{idx + 1:04d}_filtered_{_safe_tag(per_tag)}_{path.name}"
                if resolved_output_dir is not None
                else None
            ),
            snapshot=snapshot,
            pid=pid,
            tail_lines=tail_lines,
            line_from=line_from,
            line_to=line_to,
            last=last,
            since=since,
            until=until,
            segmenter=segmenter_for(idx),
            encoding=encoding,
            template_threshold=template_threshold,
        )
        results.append(result)
        row = result.to_dict()
        row["source"] = label
        source_rows.append(row)

    resolved_tag = tag or "multi"
    merged_path: Optional[Path] = None
    if merge_timeline and results:
        merge_labels = [
            str(row.get("source") or f"source{i}")
            for i, row in enumerate(source_rows)
        ]
        merged_path = _write_merged_timeline(
            results,
            labels=merge_labels,
            tag=resolved_tag,
            segmenters=[segmenter_for(index) for index in range(len(results))],
        )

    total_matches = sum(int(r.match_records) for r in results)
    return MultiFilterResult(
        sources=source_rows,
        pattern=pattern,
        tag=resolved_tag,
        merged_timeline_path=merged_path,
        match_records=total_matches,
    )


def _write_merged_timeline(
    results: List[FilterResult],
    *,
    labels: List[str],
    tag: str,
    segmenters: Optional[List[Optional[Segmenter]]] = None,
) -> Path:
    """按记录时间戳合并多个 filtered 正文，行前缀为来源标签。"""
    ref = datetime.now()
    entries: List[Tuple[datetime, int, str]] = []
    for idx, result in enumerate(results):
        label = labels[idx] if idx < len(labels) else f"source{idx}"
        body = strip_filter_header(
            result.output_path.read_text(encoding="utf-8", errors="replace")
        )
        # 用合并 record 迭代，保证多行块完整
        tmp = result.output_path.parent / f".merge_src_{idx}.tmp"
        try:
            tmp.write_text(body, encoding="utf-8")
            selected = segmenters[idx] if segmenters and idx < len(segmenters) else None
            for order, record in enumerate(
                _iter_merged_records(tmp, segmenter=selected)
            ):
                ts = record_timestamp(record, ref=ref, segmenter=selected) or datetime.min
                text = record.text if record.text.endswith("\n") else record.text + "\n"
                prefixed = "".join(
                    f"[{label}] {line}" if line else line
                    for line in text.splitlines(keepends=True)
                )
                entries.append((ts, order + idx * 1_000_000, prefixed))
        finally:
            tmp.unlink(missing_ok=True)

    entries.sort(key=lambda item: (item[0], item[1]))
    out_dir = results[0].output_path.parent
    out_path = out_dir / f"filtered_{_safe_tag(tag)}_merged_timeline.log"
    header = (
        f"# tracecite merged timeline\n"
        f"# sources: {', '.join(labels)}\n"
        f"# tag: {tag}\n"
        f"{HEADER_TERMINATOR}\n"
    )
    out_path.write_text(header + "".join(item[2] for item in entries), encoding="utf-8")
    return out_path
