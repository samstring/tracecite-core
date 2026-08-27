# -*- coding: utf-8 -*-
"""Live 文件协作切段：lock + rename + 可选 request/done 握手。"""

from __future__ import annotations

import os
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TextIO, TypeVar
from uuid import uuid4

from .state_file import atomic_write_json, read_json, state_lock

T = TypeVar("T")


class LiveCutError(RuntimeError):
    pass


def cut_request_path(live_path: Path, *, request_suffix: str) -> Path:
    path = live_path.expanduser().resolve()
    return path.with_name(f"{path.name}{request_suffix}")


def cut_done_path(live_path: Path, *, done_suffix: str) -> Path:
    path = live_path.expanduser().resolve()
    return path.with_name(f"{path.name}{done_suffix}")


def _protocol_lock_path(live_path: Path) -> Path:
    """Return a lock key dedicated to the request/done protocol.

    The writer's live-file lock is intentionally separate: a writer may need
    to acquire it while handling a request, so holding that lock while polling
    for ``done`` would deadlock the handshake.
    """
    path = live_path.expanduser().resolve()
    return path.with_name(f"{path.name}.cut.protocol")


def _move_live_no_replace(path: Path, dest: Path) -> None:
    """Move ``path`` to ``dest`` without ever replacing an existing path."""
    try:
        # Both paths are normally in the same output directory.  Hard-linking
        # and unlinking is atomic with respect to destination creation and
        # avoids rename(2)'s replace-if-present behavior.
        os.link(path, dest)
    except FileExistsError as exc:
        raise LiveCutError(f"目标文件已存在: {dest}") from exc
    except OSError:
        # Keep the operation usable on filesystems without hard-link support;
        # O_EXCL still gives the fallback no-replace destination guarantee.
        try:
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise LiveCutError(f"目标文件已存在: {dest}") from exc
        copied = False
        try:
            with os.fdopen(fd, "wb") as output, path.open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            copied = True
        finally:
            if not copied:
                dest.unlink(missing_ok=True)
        os.unlink(path)
        return
    os.unlink(path)


def rename_live_segment(
    live_path: Path,
    destination: Path,
    *,
    open_fp: Optional[TextIO] = None,
    acquire_lock: bool = True,
) -> Optional[TextIO]:
    """在 lock 下 rename live 文件到 destination，并重建空 live。"""
    path = live_path.expanduser().resolve()
    dest = Path(destination).expanduser().resolve()
    lock_ctx = state_lock(path) if acquire_lock else nullcontext()
    with lock_ctx:
        if path == dest:
            raise LiveCutError("live 文件与目标文件不能相同")
        if os.path.lexists(dest):
            raise LiveCutError(f"目标文件已存在: {dest}")
        if open_fp is not None:
            open_fp.flush()
        if not path.is_file():
            raise LiveCutError(f"live 文件不存在: {path}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        _move_live_no_replace(path, dest)
        new_fp: Optional[TextIO] = None
        if open_fp is not None:
            open_fp.close()
            new_fp = path.open("w", encoding="utf-8")
        else:
            path.write_text("", encoding="utf-8")
        return new_fp


def cooperative_live_cut(
    live_path: Path,
    *,
    request_suffix: str,
    done_suffix: str,
    request_payload: Dict[str, Any],
    deserialize: Callable[[Dict[str, Any]], T],
    direct_cut: Callable[[], T],
    timeout_sec: float = 30.0,
    poll_sec: float = 0.05,
) -> T:
    """向 live writer 发切段请求；超时则 direct_cut。"""
    path = live_path.expanduser().resolve()
    done_path = cut_done_path(path, done_suffix=done_suffix)
    req_path = cut_request_path(path, request_suffix=request_suffix)
    request_id = uuid4().hex
    payload_to_send = dict(request_payload)
    payload_to_send["request_id"] = request_id

    # Serialize the complete request/done lifecycle for one live path.  This
    # prevents two callers from deleting or consuming each other's fixed-path
    # response while keeping the lock independent from the writer's live lock.
    with state_lock(_protocol_lock_path(path)):
        done_path.unlink(missing_ok=True)
        atomic_write_json(req_path, payload_to_send)
        deadline = time.monotonic() + max(0.5, float(timeout_sec))
        while time.monotonic() < deadline:
            if done_path.is_file():
                try:
                    payload = read_json(done_path)
                except ValueError as exc:
                    raise LiveCutError(f"切段完成文件不可读: {done_path}: {exc}") from exc
                response_id = payload.get("request_id")
                if response_id is not None and str(response_id) != request_id:
                    time.sleep(max(0.01, float(poll_sec)))
                    continue
                done_path.unlink(missing_ok=True)
                req_path.unlink(missing_ok=True)
                return deserialize(payload)
            time.sleep(max(0.01, float(poll_sec)))
        req_path.unlink(missing_ok=True)
        return direct_cut()
