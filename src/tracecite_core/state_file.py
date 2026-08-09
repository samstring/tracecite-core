"""进程状态文件：原子写入、互斥操作与 PID 身份核验。"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator


def read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"状态文件损坏或不可读: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"状态文件顶层必须是对象: {path}")
    return value


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


@contextmanager
def state_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def process_command_contains(pid: int, marker: str) -> bool:
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # ps 不可用（如沙箱/权限受限）时无法核验命令行。
        # 保守按"确认存活"处理：配合 _pid_alive(os.kill) 时按存活判定，
        # 避免误判旧采集进程已死 → start 覆盖状态却不杀旧进程 → 多写者叠加。
        return True
    return proc.returncode == 0 and marker in (proc.stdout or "")
