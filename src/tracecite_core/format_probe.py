"""L1 线索探测器：为陌生日志自动产出基于正则的 FormatSegmenter 配置。

与旧的"固定候选链枚举"不同，本模块**只采样、产出结构化线索，不下硬结论**：

* ``probe_format_config(path)`` → 高置信时返回 FormatSegmenter dict，否则 None；
* ``probe_format_report(path)`` → 完整线索包（detected/config/confidence/coverage/
  position/candidates/level/issues/actions/samples），agent 可据诊断逐轮决策。

时间戳按位置探测（行首为主、行内可选）：
* 行首：iso_tz / iso_space / compact_date / syslog / time_only
* 行内方括号：apache 风格 ``[10/Oct/2000:13:55:36 -0700]``（``(?P<prefix>...)(?P<ts>...)``）
* 行中：prefix + 空格 + ISO 时间戳

设计约束（与 tracecite_core 其余部分一致）：
* 纯标准库，零第三方依赖。
* 采样有界（默认 1000 行），从不物化整个源。
* 保守优先：置信度 = 覆盖率 x 位置权重 x 可解析验证，低于 0.6 一律回落 rawtext，
  不静默误切。
* 返回的 dict 只含 FormatSegmenter kwargs，可直接喂 ``build_segmenter``。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 时间戳形态候选（按位置分组）
# ---------------------------------------------------------------------------

# 行首形态：时间戳锚定在行首
_START_SHAPES: List[Dict[str, Any]] = [
    {
        "name": "iso_tz",
        "re": r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)",
        "formats": [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
        ],
    },
    {
        "name": "iso_space",
        "re": r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)",
        "formats": [
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ],
    },
    {
        "name": "compact_date",
        "re": r"^(?P<ts>\d{6}[ T]\d{6})",
        "formats": ["%y%m%d %H%M%S", "%y%m%dT%H%M%S"],
    },
    {
        "name": "bracketed",
        "re": r"^\[(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\]",
        "formats": [
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ],
    },
    {
        "name": "syslog",
        "re": r"^(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})",
        "formats": ["%b %d %H:%M:%S"],
    },
    {
        "name": "time_only",
        "re": r"^(?P<ts>\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)",
        "formats": ["%H:%M:%S.%f", "%H:%M:%S"],
    },
]

# 行内方括号时间戳（apache 风格）：时间戳在 ``[..]`` 内，prefix 为任意前置文本
_BRACKETED_MID = {
    "name": "bracketed_mid",
    "re": r"^(?P<prefix>.*?)\[(?P<ts>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2}(?:\s[+-]\d{4})?)\]",
    "formats": ["%d/%b/%Y:%H:%M:%S %z", "%d/%b/%Y:%H:%M:%S"],
}

# 行中时间戳：一个 prefix token + 空格 + ISO 时间戳
_MIDLINE = {
    "name": "midline",
    "re": r"^(?P<prefix>\S+\s+)(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)",
    "formats": [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ],
}

# 位置权重：行首最可信，方括号次之，行中最易误判。
# 注意：time_only 虽是行首，但纯时间易被普通数字行误匹配 —— 该风险由
# 覆盖率门槛（0.85）单独管理，位置权重只反映"时间戳在行中的位置可信度"。
_POSITION_WEIGHT = {
    "iso_tz": 1.0,
    "iso_space": 1.0,
    "compact_date": 1.0,
    "bracketed": 1.0,
    "syslog": 1.0,
    "time_only": 1.0,
    "bracketed_mid": 0.95,
    "midline": 0.8,
}

# 置信度门槛
HIGH_CONFIDENCE = 0.9
MEDIUM_CONFIDENCE = 0.6

_LEVEL_ALT = r"(?i:\b(?:TRACE|VERBOSE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERR(?:OR)?|CRIT(?:ICAL)?|FATAL)\b)"
_LEVEL_RE = re.compile(_LEVEL_ALT)


def _sample_lines(path: Path, *, sample_lines: int = 1000) -> List[str]:
    lines: List[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            lines.append(line.rstrip("\n"))
            if len(lines) >= sample_lines:
                break
    return lines


def _json_like_fraction(lines: List[str]) -> float:
    if not lines:
        return 0.0
    ok = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                json.loads(stripped)
                ok += 1
            except ValueError:
                pass
    return ok / len(lines)


def _try_parse(raw: str, formats: List[str]) -> bool:
    for fmt in formats:
        try:
            datetime.strptime(raw.strip(), fmt)
            return True
        except ValueError:
            continue
    return False


def _score_candidate(
    lines: List[str], cand: Dict[str, Any]
) -> Dict[str, Any]:
    """对单个形态候选评分：覆盖率 x 位置权重 x 可解析验证。"""
    pattern = re.compile(cand["re"])
    matched = 0
    parsed = 0
    samples: List[str] = []
    for line in lines:
        m = pattern.match(line)
        if m:
            matched += 1
            raw = m.group("ts")
            if _try_parse(raw, cand["formats"]):
                parsed += 1
            if len(samples) < 3:
                samples.append(line[:200])
    total = len(lines)
    coverage = matched / total if total else 0.0
    parse_validity = parsed / matched if matched else 0.0
    weight = _POSITION_WEIGHT.get(cand["name"], 1.0)
    return {
        "name": cand["name"],
        "re": cand["re"],
        "formats": list(cand["formats"]),
        "matched": matched,
        "coverage": round(coverage, 3),
        "parse_validity": round(parse_validity, 3),
        "confidence": round(coverage * weight * parse_validity, 3),
        "samples": samples,
    }


def _detect_level(lines: List[str], ts_re: str) -> Dict[str, Any]:
    """在时间戳之后的一致位置找级别词（≥3 条 found、同位置 ≥80% 才信）。"""
    pattern = re.compile(ts_re)
    found: List[Tuple[int, str]] = []
    for line in lines:
        m = pattern.match(line)
        if not m:
            continue
        rest = line[m.end():]
        for idx, token in enumerate(rest.split()[:3]):
            if _LEVEL_RE.match(token):
                found.append((idx, token))
                break
    if len(found) < 3:
        return {"detected": False, "index": None, "token": None}
    counter = Counter(idx for idx, _ in found)
    idx, count = counter.most_common(1)[0]
    if count / len(found) < 0.8:
        return {"detected": False, "index": None, "token": None}
    token = next(tok for i, tok in found if i == idx)
    return {"detected": True, "index": idx, "token": token}


def _build_config(best: Dict[str, Any], level: Dict[str, Any]) -> Dict[str, Any]:
    """把选中的形态组装成 FormatSegmenter dict（level 组为可选装饰，不改切分）。"""
    start = best["re"]
    if level["detected"] and level["index"] <= 1:
        if level["index"] == 0:
            start += r"(?:\s+(?P<level>" + _LEVEL_ALT + r"))?"
        else:
            start += r"(?:\s+\S+)?(?:\s+(?P<level>" + _LEVEL_ALT + r"))?"
    return {
        "start": start,
        "timestamp_formats": list(best["formats"]),
        "multiline": True,
        "flags": "",
    }


def probe_format_config(
    input_path: Any,
    *,
    sample_lines: int = 1000,
    min_coverage: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """高置信时返回 FormatSegmenter dict，否则返回 None。

    None 表示不应信任任何候选形态；调用方应回落到 rawtext / jsonline，
    或调用 ``probe_format_report`` 查看具体原因。
    """
    report = probe_format_report(
        input_path, sample_lines=sample_lines, min_coverage=min_coverage
    )
    return report.get("config")


def probe_format_report(
    input_path: Any,
    *,
    sample_lines: int = 1000,
    min_coverage: Optional[float] = None,
) -> Dict[str, Any]:
    """完整线索包：探测结果 + 诊断，供 agent 决策。

    - detected: config 是否可用
    - config: FormatSegmenter dict（可直接喂 build_segmenter），低置信时为 None
    - confidence / coverage / position: 选中最优形态的评分与时间戳位置
    - candidates: 前 3 候选各自评分（agent 可据置信度换策略）
    - level: 级别线索 {detected, index, token}
    - json_like_fraction: JSON 行占比（≥0.5 建议 jsonline）
    - issues: 为什么置信度没到 1 / 为什么回落
    - actions: agent 可选动作（accept / pick_candidate / increase_sample / fallback_rawtext / use_jsonline）
    - samples: 命中样本（诊断用）
    """
    path = Path(input_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"日志文件不存在或不是文件: {path}")
    lines = _sample_lines(path, sample_lines=sample_lines)
    if not lines:
        return {
            "operation": "probe_format",
            "detected": False,
            "config": None,
            "confidence": 0.0,
            "coverage": 0.0,
            "position": None,
            "candidates": [],
            "level": {"detected": False, "index": None, "token": None},
            "json_like_fraction": 0.0,
            "issues": ["empty_sample"],
            "fallback": "rawtext",
            "actions": ["fallback_rawtext"],
            "samples": [],
        }

    json_like = _json_like_fraction(lines)
    if json_like >= 0.5:
        return {
            "operation": "probe_format",
            "detected": True,
            "config": None,
            "confidence": 1.0,
            "coverage": round(json_like, 3),
            "position": "json",
            "candidates": [],
            "level": {"detected": False, "index": None, "token": None},
            "json_like_fraction": round(json_like, 3),
            "issues": [],
            "fallback": "jsonline",
            "actions": ["use_jsonline"],
            "samples": lines[:3],
        }

    # 覆盖门槛：date-bearing 形态 0.5，time_only 0.85（与旧实现一致）
    scores: List[Dict[str, Any]] = []
    for cand in _START_SHAPES:
        score = _score_candidate(lines, cand)
        bar = 0.85 if cand["name"] == "time_only" else 0.5
        if min_coverage is not None:
            bar = min_coverage
        if score["coverage"] >= bar:
            scores.append(score)
    for cand in (_BRACKETED_MID, _MIDLINE):
        score = _score_candidate(lines, cand)
        bar = 0.5 if min_coverage is None else min_coverage
        if score["coverage"] >= bar:
            scores.append(score)

    if not scores:
        return {
            "operation": "probe_format",
            "detected": False,
            "config": None,
            "confidence": 0.0,
            "coverage": 0.0,
            "position": None,
            "candidates": [],
            "level": {"detected": False, "index": None, "token": None},
            "json_like_fraction": round(json_like, 3),
            "issues": ["没有任何候选形态覆盖足够比例的采样行"],
            "fallback": "rawtext",
            "actions": ["increase_sample", "fallback_rawtext"],
            "samples": lines[:3],
        }

    ranked = sorted(scores, key=lambda s: -s["confidence"])
    best = ranked[0]
    level = _detect_level(lines, best["re"])

    issues: List[str] = []
    if best["parse_validity"] < 0.8:
        issues.append(
            f"时间戳解析通过率 {best['parse_validity']}（<0.8），形态存疑"
        )
    if best["coverage"] < 0.5:
        issues.append(f"最高覆盖率仅 {best['coverage']}（<0.5），不足以信任")

    high = best["confidence"] >= HIGH_CONFIDENCE
    config = _build_config(best, level) if high else None

    actions: List[str] = []
    if config is not None:
        actions.append("accept")
    else:
        actions.append("pick_candidate")
        actions.append("increase_sample")
        actions.append("fallback_rawtext")

    return {
        "operation": "probe_format",
        "detected": config is not None,
        "config": config,
        "confidence": best["confidence"],
        "coverage": best["coverage"],
        "position": best["name"],
        "candidates": [
            {
                "name": s["name"],
                "confidence": s["confidence"],
                "coverage": s["coverage"],
                "parse_validity": s["parse_validity"],
                "matched": s["matched"],
            }
            for s in ranked[:3]
        ],
        "level": level,
        "json_like_fraction": round(json_like, 3),
        "issues": issues,
        "fallback": "rawtext" if config is None else "format",
        "actions": actions,
        "samples": best["samples"],
    }
