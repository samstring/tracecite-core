"""L1 线索探测器：为陌生日志自动产出基于正则的 FormatSegmenter 配置。

与"固定候选链枚举"不同，本模块**不做格式预判**——它从采样行的**结构**
出发做通用归纳：

1. 把每行 token 化（数字 / 字母 / 符号 / 空白）；
2. 逐 token 位置统计形态分布，找"稳定前缀"（大多数行共享的开头结构）；
3. 在稳定结构里定位**时间戳段**（数字组 + 冒号/横线/斜杠/点等分隔符）；
4. 从时间戳段**归纳 strptime 格式**（不依赖预置格式表）；
5. 产出 ``FormatSegmenter`` dict + 行结构画像（``structure``），
   agent 可据此自由探索：接受、调整时间戳边界、或换 strptime。

设计约束（与 tracecite_core 其余部分一致）：
* 纯标准库，零第三方依赖。
* 采样有界（默认 1000 行），从不物化整个源。
* 保守优先：置信度 = 记录级覆盖率 x 位置权重 x 可解析验证，
  低于 0.6 一律回落 rawtext，不静默误切。
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
# 置信度门槛
# ---------------------------------------------------------------------------

HIGH_CONFIDENCE = 0.9
MEDIUM_CONFIDENCE = 0.6

_LEVEL_ALT = r"(?i:\b(?:TRACE|VERBOSE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERR(?:OR)?|CRIT(?:ICAL)?|FATAL)\b)"
_LEVEL_RE = re.compile(_LEVEL_ALT)

_NUM_RE = re.compile(r"^\d+$")
_ALPHA_RE = re.compile(r"^[A-Za-z]+$")


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


# ---------------------------------------------------------------------------
# 通用结构归纳（无候选枚举）
# ---------------------------------------------------------------------------

def _tokenize(line: str) -> List[str]:
    """拆成 token：数字 / 字母 / 符号串；空白保留为独立 token。

    下划线 ``_`` 单独成 token（文件名/标识符常见连接符，不并入数字或字母）。
    """
    return re.findall(r"\d+|[A-Za-z]+|[^\w\s]|_+|\s+", line)


def _token_shape(tok: str) -> str:
    """token 形态签名：4位数字->'N4'，字母->'A'，空白->' '，符号->字面。"""
    if _NUM_RE.match(tok):
        return f"N{len(tok)}"
    if _ALPHA_RE.match(tok):
        return "A"
    if tok.isspace():
        return " "
    return tok


def _line_signature(line: str) -> List[str]:
    return [_token_shape(t) for t in _tokenize(line)]


def _find_ts_span(tokens: List[str]) -> Optional[Tuple[int, int]]:
    """在 token 序列中定位时间戳子段 [start, end)。

    时间戳 = 数字组 + 时间分隔符（-./:T,，含空格）。启发式：找
    数字/分隔符连续段，段内须含冒号（HH:MM:SS）或 6 位紧凑数字；
    段首若是 ``\\d{6} [ \\d{6}``（HDFS 紧凑日期+时间）则只取这两个；
    时间戳后跟 "空格+数字"（pid/线程）在含冒号时截断。
    """
    ts_sep = set("-./:T,")
    candidates: List[Tuple[int, int]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.isdigit() or (tok in ts_sep and tok != "-"):
            j = i
            while j < len(tokens):
                t = tokens[j]
                if t.isdigit() or t in ts_sep:
                    j += 1
                elif t.isspace():
                    k = j + 1
                    if k < len(tokens) and (tokens[k].isdigit() or tokens[k] in ts_sep):
                        j += 1
                    else:
                        break
                else:
                    break
            while j > i and not tokens[j - 1].isdigit():
                j -= 1
            if j - i >= 2:
                candidates.append((i, j))
            i = max(j, i + 1)
        else:
            i += 1

    best = None
    best_score = -1
    for start, end in candidates:
        seg = tokens[start:end]
        has_colon = any(":" in t for t in seg)
        num_groups = sum(1 for t in seg if t.isdigit())
        score = num_groups * 2 + (1 if has_colon else 0)
        if any(len(t) == 6 and t.isdigit() for t in seg):
            score += 2
        # 时间戳通常在行首：靠前的段加权重（避免 IP/端口段 0:0:...:2181 反超）
        if start == 0:
            score += 4
        elif start <= 2:
            score += 2
        # 含冒号是时间戳的强信号：无冒号的段（如 IP 127.0.0.1）强压分
        if not has_colon:
            score -= 3
        if score > best_score:
            best_score = score
            best = (start, end)
    if best is None or best_score <= 0:
        return None

    start, end = best
    seg = tokens[start:end]
    # OpenStack 等：段内可能含文件名污染前缀 + 真正的 ISO 时间戳
    # （nova-api.log.1.2017-05-16_13:53:08 2017-05-16 00:00:00.008 25746）。
    # 若段首不是 ISO 开头，收缩到段内第一个完整 ISO 子段。
    joined = "".join(seg)
    iso_ms = re.findall(
        r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?", joined
    )
    if iso_ms and not re.match(r"^\d{4}-\d{2}-\d{2}[ T]", joined):
        chosen = iso_ms[-1]  # 取最后一个（通常是正文时间戳）
        idx = joined.rfind(chosen)
        consumed = 0
        for k in range(start, end):
            consumed += len(tokens[k])
            if consumed > idx:
                start = k
                break
        end = start
        consumed = 0
        for k in range(start, len(tokens)):
            consumed += len(tokens[k])
            if consumed >= len(chosen):
                end = k + 1
                break
    # HDFS 紧凑日期+时间：081109 203615 -> 只取这两个
    if len(seg) >= 3 and seg[0].isdigit() and len(seg[0]) == 6 \
            and seg[1].isspace() and seg[2].isdigit() and len(seg[2]) == 6:
        end = start + 3
    # pid/线程后缀截断（含冒号的时间格式）：03-17 16:13:38.811  1702 -> 截掉
    # 规则：尾部 [空格+数字] 组，若该数字组前一个非空格 token 是时间分隔符
    # （如 .811 的 '.'），则它是毫秒属时间戳，保留；否则是 pid/线程，截掉。
    if any(":" in t for t in tokens[start:end]):
        while end > start + 2 and tokens[end - 1].isdigit() and tokens[end - 2].isspace() \
                and tokens[end - 3].isdigit():
            prev = end - 2
            while prev > start and tokens[prev].isspace():
                prev -= 1
            if prev > start and tokens[prev] in (".", ",", "/", "-", ":"):
                break  # 数字组紧贴时间分隔符 -> 毫秒，保留
            end -= 2  # 去掉 "空格+数字"（pid/线程）
    # syslog 英文月前缀纳入（循环）：Jun 14 15:16:01；Apache：[Sun Dec 04 ...
    # 持续吞 "AAA " 前缀，直到遇到 '['（方括号包裹）或非字母 token。
    while start >= 2 and tokens[start - 2].isalpha() and len(tokens[start - 2]) == 3 \
            and tokens[start - 1].isspace():
        # 若前缀前还有 "[AAA "（方括号包裹），连同括号一并纳入
        if start >= 4 and tokens[start - 3] == "[" and tokens[start - 4].isalpha() \
                and len(tokens[start - 4]) == 3 and tokens[start - 5].isspace():
            start -= 5
            break
        start -= 2
    # Apache 方括号时间戳：[Sun Dec 04 04:47:44 2005] 尾部年份纳入。
    # 仅当 ts 段含英文月（syslog 形态）才补年份，避免误伤数字格式
    # （Android 的 " 1702  2395" 会被当成年份）。
    has_month = any(t.isalpha() and len(t) == 3 for t in tokens[start:end])
    if has_month and end < len(tokens) and tokens[end - 1].isdigit() and end + 1 < len(tokens) \
            and tokens[end].isspace() and tokens[end + 1].isdigit() and len(tokens[end + 1]) == 4:
        end += 2
    # apache 行中括号（10/Oct/2000:13:55:36 -0700）：ts 段起点可能是 '/'（如 index16），
    # 前面是 "Oct/"（tokens[15]='Oct' tokens[14]='/' tokens[13]='10'），
    # 把日期前缀 "dd/MMM/" 纳入（不含 '['，由 bracket 检测处理）。
    k = start
    while k >= 1 and tokens[k - 1].isspace():
        k -= 1  # 跳过空格（ts 段可能从 '/' 开始，前面有空格）
    # 模式:ts 段起点 tokens[k]=='/'，前面是 "10/Oct/"（数字/斜杠/英文月）
    if k >= 3 and tokens[k] == "/" and tokens[k - 1].isalpha() \
            and len(tokens[k - 1]) == 3 and tokens[k - 2] == "/" and tokens[k - 3].isdigit():
        k -= 3
        start = k
    # 若前面还有 '['（ts 段不含括号，start 指向括号后第一个 token）
    if start >= 1 and tokens[start - 1] == "[":
        pass  # bracket 检测在 report 层处理
    return start, end


def _guess_strptime(ts_tokens: List[str]) -> List[str]:
    """从时间戳 token 归纳 strptime 格式候选（无预置格式表）。

    用正则逐个匹配"形态"，生成格式串。覆盖：
    - 紧凑日期：yymmdd HHMMSS / YYYYMMDD-HH:MM:SS
    - 标准 ISO：YYYY-MM-DD[ T]HH:MM:SS[,.]fff
    - 无年份：MM-DD HH:MM:SS[,.]fff
    - 两位年：yy/MM/dd HH:MM:SS
    - syslog：MMM DD HH:MM:SS
    - 纯时间：HH:MM:SS[,.]fff
    """
    joined = "".join(ts_tokens)

    m = re.match(r"^(\d{6})[ T](\d{6})$", joined)
    if m:
        return ["%y%m%d %H%M%S", "%y%m%dT%H%M%S"]

    m = re.match(r"^(\d{8})-(\d{2}):(\d{2}):(\d{2})(?:[.,](\d+))?$", joined)
    if m:
        base = "%Y%m%d-%H:%M:%S"
        cands = [base]
        if m.group(5):
            cands.append(base + ".%f")
            cands.append(base + ",%f")
        return cands

    # HealthApp 紧凑日期+双冒号毫秒：20171223-22:15:29:606
    m = re.match(r"^(\d{8})-(\d{2}):(\d{2}):(\d{2}):(\d{3})$", joined)
    if m:
        return ["%Y%m%d-%H:%M:%S:%f"]

    m = re.match(
        r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:[.,](\d+))?(Z|[+-]\d{2}:?\d{2})?$",
        joined,
    )
    if m:
        base = "%Y-%m-%d %H:%M:%S"
        cands = [base]
        if m.group(7):
            cands.append(base + ".%f")
            cands.append(base + ",%f")
        if m.group(8):
            cands = [c + "%z" for c in cands]
        t_cands = [c.replace("%Y-%m-%d ", "%Y-%m-%dT", 1) for c in cands]
        return t_cands + cands

    m = re.match(r"^(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:[.,](\d+))?$", joined)
    if m:
        base = "%m-%d %H:%M:%S"
        cands = [base]
        if m.group(6):
            cands.append(base + ".%f")
            cands.append(base + ",%f")
        return cands

    m = re.match(r"^(\d{2})/(\d{2})/(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$", joined)
    if m:
        return ["%y/%m/%d %H:%M:%S", "%y/%m/%dT%H:%M:%S"]

    m = re.match(r"^(\d{2})/([A-Za-z]{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2})(?:\s([+-]\d{4}))?$", joined)
    if m:
        return ["%d/%b/%Y:%H:%M:%S %z", "%d/%b/%Y:%H:%M:%S"]

    m = re.match(r"^(?:[A-Za-z]{3}\s+)?([A-Za-z]{3})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})\s+(\d{4})$", joined)
    if m:
        return ["%a %b %d %H:%M:%S %Y", "%b %d %H:%M:%S %Y"]

    m = re.match(r"^([A-Za-z]{3})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})$", joined)
    if m:
        return ["%b %d %H:%M:%S"]

    m = re.match(r"^(\d{2}):(\d{2}):(\d{2})(?:[.,](\d+))?$", joined)
    if m:
        base = "%H:%M:%S"
        cands = [base]
        if m.group(4):
            cands.append(base + ".%f")
            cands.append(base + ",%f")
        return cands

    return []


def _build_start_re(
    ts_tokens: List[str], *, bracket: bool = False, prefix_tokens: Optional[List[str]] = None
) -> str:
    """从时间戳 token 构造 start 正则（(?P<ts>) 命名组）。

    数字 -> ``\\d+``，字母 -> ``[A-Za-z]+``，空白 -> ``\\s+``，符号字面保留。
    ``prefix_tokens`` 非空时，时间戳不在行首（行中形态），生成
    ``^(?P<prefix>...)(?P<ts>...)``。
    """
    body = "".join(
        r"\d+"
        if _NUM_RE.match(t) else
        (r"[A-Za-z]+" if _ALPHA_RE.match(t) else
         (r"\s+" if t.isspace() else re.escape(t)))
        for t in ts_tokens
    )
    if bracket:
        if prefix_tokens:
            # prefix 可能以 '[' 结尾（行中括号），去掉它——bracket 分支自己加 '['
            if prefix_tokens and prefix_tokens[-1] == "[":
                prefix_tokens = prefix_tokens[:-1]
            prefix = "".join(
                r"\d+"
                if _NUM_RE.match(t) else
                (r"[A-Za-z]+" if _ALPHA_RE.match(t) else
                 (r"\s+" if t.isspace() else re.escape(t)))
                for t in prefix_tokens
            )
            return r"^(?P<prefix>" + prefix + r")\[(?P<ts>" + body + r")\]"
        return r"^\[(?P<ts>" + body + r")\]"
    if prefix_tokens:
        prefix = "".join(
            r"\d+"
            if _NUM_RE.match(t) else
            (r"[A-Za-z]+" if _ALPHA_RE.match(t) else
             (r"\s+" if t.isspace() else re.escape(t)))
            for t in prefix_tokens
        )
        return r"^(?P<prefix>" + prefix + r")(?P<ts>" + body + r")"
    return r"^(?P<ts>" + body + r")"


def _record_coverage(lines: List[str], pattern: "re.Pattern[str]") -> float:
    """按"记录段"计算覆盖率，避免多行日志的 body 续行稀释行覆盖率。"""
    segments = 0
    with_start = 0
    has_open_segment = False
    for line in lines:
        if pattern.match(line):
            segments += 1
            with_start += 1
            has_open_segment = True
        elif not has_open_segment:
            segments += 1
            has_open_segment = True
    return with_start / segments if segments else 0.0


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


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def probe_format_config(
    input_path: Any,
    *,
    sample_lines: int = 1000,
    min_coverage: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """高置信时返回 FormatSegmenter dict，否则返回 None。"""
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
    """完整线索包：结构归纳结果 + 行画像，供 agent 自由决策。

    - detected / config / confidence / coverage / position
    - structure: 行结构画像（token 形态分布、时间戳段、strptime 候选）——agent 探索依据
    - level / json_like_fraction / issues / actions / samples
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
            "structure": {"tokens": [], "ts_span": None, "formats": [], "sample": None},
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
            "structure": {"tokens": [], "ts_span": None, "formats": [], "sample": None},
            "level": {"detected": False, "index": None, "token": None},
            "json_like_fraction": round(json_like, 3),
            "issues": [],
            "fallback": "jsonline",
            "actions": ["use_jsonline"],
            "samples": lines[:3],
        }

    # ---- 通用结构归纳：从首行定位时间戳段 ----
    first = lines[0]
    tokens = _tokenize(first)
    ts_span = _find_ts_span(tokens)
    if ts_span is None:
        return {
            "operation": "probe_format",
            "detected": False,
            "config": None,
            "confidence": 0.0,
            "coverage": 0.0,
            "position": None,
            "structure": {"tokens": tokens[:12], "ts_span": None, "formats": [], "sample": first[:200]},
            "level": {"detected": False, "index": None, "token": None},
            "json_like_fraction": round(json_like, 3),
            "issues": ["采样行中未找到可归纳的时间戳结构"],
            "fallback": "rawtext",
            "actions": ["increase_sample", "fallback_rawtext"],
            "samples": lines[:3],
        }

    ts_tokens = tokens[ts_span[0]:ts_span[1]]
    # 方括号包裹检测（apache 风格 [Sun Dec 04 04:47:44 2005]）
    bracket = (
        ts_span[0] >= 1
        and tokens[ts_span[0] - 1] == "["
        and ts_span[1] < len(tokens)
        and tokens[ts_span[1]] == "]"
    )
    formats = _guess_strptime(ts_tokens)
    if not formats:
        return {
            "operation": "probe_format",
            "detected": False,
            "config": None,
            "confidence": 0.0,
            "coverage": 0.0,
            "position": None,
            "structure": {
                "tokens": tokens[:12],
                "ts_span": ts_span,
                "ts_tokens": ts_tokens,
                "formats": [],
                "sample": first[:200],
            },
            "level": {"detected": False, "index": None, "token": None},
            "json_like_fraction": round(json_like, 3),
            "issues": ["已定位时间戳结构但无法归纳 strptime 格式"],
            "fallback": "rawtext",
            "actions": ["increase_sample", "fallback_rawtext"],
            "samples": lines[:3],
        }

    start_re = _build_start_re(
        ts_tokens,
        bracket=bracket,
        prefix_tokens=tokens[:ts_span[0]] if ts_span[0] > 0 else None,
    )
    pattern = re.compile(start_re)

    # ---- 覆盖率与可解析验证 ----
    coverage = _record_coverage(lines, pattern)
    parsed = 0
    matched_lines = 0
    for line in lines:
        m = pattern.match(line)
        if m:
            matched_lines += 1
            raw = m.group("ts")
            if _try_parse(raw, formats):
                parsed += 1
    total = len(lines)
    line_coverage = matched_lines / total if total else 0.0
    parse_validity = parsed / matched_lines if matched_lines else 0.0

    # 位置权重：行首=1.0（ts 段从 0 开始）；行中=0.8；方括号=0.95
    if bracket:
        weight = 0.95
    elif ts_span[0] == 0:
        weight = 1.0
    else:
        weight = 0.8
    confidence = coverage * weight * parse_validity

    bar = min_coverage if min_coverage is not None else 0.5
    level = _detect_level(lines, start_re)

    issues: List[str] = []
    if parse_validity < 0.8:
        issues.append(f"时间戳解析通过率 {round(parse_validity, 2)}（<0.8），形态存疑")
    if coverage < 0.5:
        issues.append(f"记录级覆盖率仅 {round(coverage, 2)}（<0.5），不足以信任")

    high = confidence >= HIGH_CONFIDENCE
    config: Optional[Dict[str, Any]] = None
    if high:
        start = start_re
        if level["detected"] and level["index"] <= 1:
            if level["index"] == 0:
                start += r"(?:\s+(?P<level>" + _LEVEL_ALT + r"))?"
            else:
                start += r"(?:\s+\S+)?(?:\s+(?P<level>" + _LEVEL_ALT + r"))?"
        config = {
            "start": start,
            "timestamp_formats": list(formats),
            "multiline": True,
            "flags": "",
        }

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
        "confidence": round(confidence, 3),
        "coverage": round(coverage, 3),
        "position": "structural",
        "structure": {
            "tokens": tokens[:12],
            "ts_span": ts_span,
            "ts_tokens": ts_tokens,
            "ts_raw": "".join(ts_tokens),
            "formats": formats,
            "line_coverage": round(line_coverage, 3),
            "sample": first[:200],
        },
        "level": level,
        "json_like_fraction": round(json_like, 3),
        "issues": issues,
        "fallback": "rawtext" if config is None else "format",
        "actions": actions,
        "samples": _first_matching(lines, pattern, 3),
    }


def _first_matching(lines: List[str], pattern: "re.Pattern[str]", n: int) -> List[str]:
    out: List[str] = []
    for line in lines:
        if pattern.match(line):
            out.append(line[:200])
            if len(out) >= n:
                break
    return out


def _try_parse(raw: str, formats: List[str]) -> bool:
    for fmt in formats:
        try:
            datetime.strptime(raw.strip(), fmt)
            return True
        except ValueError:
            continue
    return False
