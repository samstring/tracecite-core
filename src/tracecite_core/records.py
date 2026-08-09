# -*- coding: utf-8 -*-
"""与平台无关的最小文本单元 Record。

引擎内部只认识 Record，不认识 syslog / logcat / JSON / 任何具体格式。
「一条数据」由 Segmenter 决定边界，引擎不参与判断。

与 ``log_filter._LogRecord`` 的关系：
``_LogRecord`` 是 filter 内部的历史结构（text/start_line/end_line），
``Record`` 是对外接缝的通用结构，额外携带 timestamp 与 fields。
两者通过 ``Record.as_log_record_tuple()`` 无损互转，避免重复实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Tuple


@dataclass
class Record:
    """一条逻辑记录（可能由多个物理行合并而成）。

    Attributes:
        text: 记录原文，含换行；多行块已合并。
        start_line: 起始物理行号（1-based，闭区间）。
        end_line: 结束物理行号（1-based，闭区间）。
        timestamp: 解析出的时间；解析不出为 None（不报错，交给上层判断）。
        fields: 分段器附加的结构化字段，如 pid / level / tag / subsystem。
    """

    text: str
    start_line: int
    end_line: int
    timestamp: Optional[datetime] = None
    fields: Dict[str, Any] = field(default_factory=dict)

    @property
    def line_count(self) -> int:
        """物理行数。"""
        return self.end_line - self.start_line + 1

    def as_log_record_tuple(self) -> Tuple[str, int, int]:
        """转成 log_filter._LogRecord 的三元组，保证与历史结构无损互转。"""
        return (self.text, self.start_line, self.end_line)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "fields": dict(self.fields),
        }


def estimate_tokens(text: str) -> int:
    """粗估 token 数：按 3 字符 ≈ 1 token。

    只用于给 Agent 一个「这坨证据会吃掉多少上下文」的量级参考，
    不追求精确，也不依赖任何分词库。
    """
    return max(0, len(text) // 3)
