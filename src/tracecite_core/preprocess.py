"""预处理管道框架：内置 action + 公共插件 SDK 扩展。

约定：
- 内置 action 直接使用，spec 里配 ``{"action": "charset", ...}``
- 第三方包通过 ``PluginAPI.register_preprocessor`` 注册同一种 action
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


class PreprocessError(RuntimeError):
    """预处理管道错误。"""


def run_preprocess_pipeline(
    input_path: Path,
    steps: Sequence[Dict[str, Any]],
    *,
    temp_dir: Optional[Path] = None,
) -> Path:
    """按步骤依次执行预处理，返回最终文件路径。

    ``steps`` 中每项为 ``{action: 动作名, ...}``。
    无步骤时直接返回 input_path。
    """
    if not steps:
        return input_path
    import tempfile

    tmp = temp_dir or Path(tempfile.mkdtemp(prefix="tracecite_core_preproc_"))
    tmp.mkdir(parents=True, exist_ok=True)
    current = input_path
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            raise PreprocessError(f"preprocess 步骤 {idx} 必须是对象: {step!r}")
        out_path = tmp / f"step_{idx}_{current.name}"
        if "action" in step:
            _run_action(str(step["action"]), current, out_path, step)
        else:
            raise PreprocessError(f"preprocess 步骤 {idx} 需指定 action: {step}")
        current = out_path
    return current


# ---------------------------------------------------------------------------
# 内置 actions
# ---------------------------------------------------------------------------

_BUILTIN_ACTIONS = {}


def available_preprocessor_actions() -> list[str]:
    return sorted(_BUILTIN_ACTIONS)


def register_preprocessor_action(name: str, handler, *, replace: bool = False) -> None:
    """公开的预处理 action 注册 API；重复注册同一 handler 幂等。"""
    key = str(name).strip().lower()
    if not key:
        raise ValueError("preprocessor action 名不能为空")
    current = _BUILTIN_ACTIONS.get(key)
    if current is not None and current is not handler and not replace:
        raise ValueError(f"preprocessor action {key!r} 已注册")
    _BUILTIN_ACTIONS[key] = handler


def _register(name):
    def deco(fn):
        register_preprocessor_action(name, fn)
        return fn

    return deco


@_register("charset")
def _action_charset(input_path: Path, output_path: Path, params: Dict[str, Any]):
    from_enc = str(params.get("from", "utf-8"))
    to_enc = str(params.get("to", "utf-8"))
    errors = str(params.get("errors", "replace"))
    if from_enc.lower() == to_enc.lower():
        shutil.copy2(input_path, output_path)
        return
    with input_path.open(
        "r", encoding=from_enc, errors=errors
    ) as source, output_path.open(
        "w", encoding=to_enc, errors="replace"
    ) as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)


@_register("grep")
def _action_grep(input_path: Path, output_path: Path, params: Dict[str, Any]):
    pattern = str(params.get("pattern", ""))
    invert = bool(params.get("invert", False))
    if not pattern:
        raise PreprocessError("grep action 需要 pattern")
    pat = re.compile(pattern)
    encoding = str(params.get("encoding", "utf-8"))
    with input_path.open(
        "r", encoding=encoding, errors="replace"
    ) as source, output_path.open(
        "w", encoding=encoding, errors="replace"
    ) as output:
        for line in source:
            if bool(pat.search(line)) != invert:
                output.write(line)


def _run_action(name: str, input_path: Path, output_path: Path, step: Dict[str, Any]):
    fn = _BUILTIN_ACTIONS.get(name.strip().lower())
    if fn is None:
        known = ", ".join(sorted(_BUILTIN_ACTIONS))
        raise PreprocessError(f"未知 action {name!r}（可用: {known}；扩展请使用插件 SDK 注册）")
    params = {k: v for k, v in step.items() if k != "action"}
    fn(input_path, output_path, params)
