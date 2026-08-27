"""统一分析运行实体与 manifest。"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .immutable import is_stable_source

RUN_SCHEMA_VERSION = 2


class RunIntegrityError(RuntimeError):
    """运行输入或产物缺失、不可读或被执行期外部修改。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _path_sha256(path: Path) -> Optional[str]:
    """Hash a file or a directory tree deterministically."""
    if not path.exists():
        return None
    digest = hashlib.sha256()
    try:
        if path.is_file():
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        elif path.is_dir():
            for child in sorted(item for item in path.rglob("*") if item.is_file()):
                digest.update(child.relative_to(path).as_posix().encode("utf-8"))
                digest.update(b"\0")
                with child.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
                digest.update(b"\0")
        else:
            return None
    except OSError:
        return None
    return digest.hexdigest()


def _path_size(path: Path) -> Optional[int]:
    try:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    except OSError:
        return None
    return None


def verify_manifest(path: Path) -> Dict[str, Any]:
    """校验已完成 manifest 登记的全部输入与产物。"""
    manifest = Path(path).expanduser().resolve()
    if not manifest.is_file():
        raise RunIntegrityError(f"manifest 不存在: {manifest}")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunIntegrityError(f"manifest 不可读: {manifest}: {exc}") from exc
    if payload.get("schema_version") != RUN_SCHEMA_VERSION:
        raise RunIntegrityError(
            f"manifest schema 不匹配: {payload.get('schema_version')} != {RUN_SCHEMA_VERSION}"
        )
    checked = 0
    for section in ("inputs", "artifacts"):
        rows = payload.get(section) or []
        if not isinstance(rows, list):
            raise RunIntegrityError(f"manifest.{section} 必须是数组")
        for row in rows:
            if not isinstance(row, dict):
                raise RunIntegrityError(f"manifest.{section} 含非法条目")
            item = RunFile(
                role=str(row.get("role") or "unknown"),
                path=str(row.get("path") or ""),
                size=row.get("size"),
                sha256=row.get("sha256"),
                metadata=dict(row.get("metadata") or {}),
            )
            item.verify()
            checked += 1
    return {
        "valid": True,
        "manifest_path": str(manifest),
        "run_id": payload.get("run_id"),
        "status": payload.get("status"),
        "verdict": payload.get("verdict"),
        "checked_files": checked,
    }


@dataclass(frozen=True)
class RunFile:
    role: str
    path: str
    size: Optional[int] = None
    sha256: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_path(
        cls, role: str, path: Path, *, metadata: Optional[Dict[str, Any]] = None
    ) -> "RunFile":
        resolved = Path(path).expanduser().resolve()
        item_metadata = dict(metadata or {})
        if resolved.is_dir():
            item_metadata.setdefault("path_type", "directory")
        return cls(
            role=role,
            path=str(resolved),
            size=_path_size(resolved),
            sha256=_path_sha256(resolved),
            metadata=item_metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"role": self.role, "path": self.path}
        if self.size is not None:
            out["size"] = self.size
        if self.sha256 is not None:
            out["sha256"] = self.sha256
        if self.metadata:
            out["metadata"] = self.metadata
        return out

    def verify(self) -> None:
        path = Path(self.path)
        if not path.exists() or not (path.is_file() or path.is_dir()):
            raise RunIntegrityError(f"运行文件不存在: {self.role}: {path}")
        actual_size = _path_size(path)
        actual_sha = _path_sha256(path)
        if self.size is None or self.sha256 is None:
            raise RunIntegrityError(f"运行文件缺少完整性信息: {self.role}: {path}")
        if actual_size != self.size or actual_sha != self.sha256:
            raise RunIntegrityError(f"运行文件在登记后发生变化: {self.role}: {path}")


@dataclass(frozen=True)
class RunWorkspace:
    """一次分析运行的不可变工作区。"""

    root: Path
    run_id: str

    @classmethod
    def create(cls, run_root: Path, run_id: str) -> "RunWorkspace":
        workspace = cls(Path(run_root).expanduser().resolve() / run_id, run_id)
        for path in (
            workspace.inputs_dir,
            workspace.evidence_dir,
            workspace.reports_dir,
            workspace.actions_dir,
            workspace.temp_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return workspace

    @property
    def inputs_dir(self) -> Path:
        return self.root / "inputs"

    @property
    def evidence_dir(self) -> Path:
        return self.root / "evidence"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def actions_dir(self) -> Path:
        return self.root / "actions"

    @property
    def temp_dir(self) -> Path:
        return self.root / "temp"

    @property
    def preprocess_dir(self) -> Path:
        path = self.inputs_dir / "preprocessed"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def freeze_input(self, source: Path, *, index: int) -> Path:
        original = Path(source).expanduser().resolve()
        if not original.is_file():
            raise RunIntegrityError(f"无法冻结输入文件: {original}")
        destination = self.inputs_dir / f"{index + 1:04d}_{original.name}"
        if destination.exists():
            raise RunIntegrityError(f"运行输入目标已存在: {destination}")
        # 快照语义：源可能是持续追加写入的日志（采集场景）。copy 完成后，
        # destination 是复制期间源的一致视图，本身即合法快照；源是否继续增长
        # 不影响快照合法性。故只校验快照自身可读、完整（copy2 失败会抛 OSError），
        # 不再与不断变化的源比较 sha——那在并发写入下必然不一致，属误报。
        shutil.copy2(original, destination)
        if _path_sha256(destination) is None:
            raise RunIntegrityError(f"冻结输入校验失败: {original}")
        return destination

    def prepare_input(
        self,
        source: Path,
        *,
        index: int,
        copy: Optional[bool] = None,
    ) -> Tuple[Path, bool]:
        """返回 (工作路径, 是否 copy 冻结)。稳定源默认直接引用。"""
        resolved = Path(source).expanduser().resolve()
        should_copy = copy if copy is not None else not is_stable_source(resolved)
        if should_copy:
            return self.freeze_input(resolved, index=index), True
        if not resolved.is_file():
            raise RunIntegrityError(f"无法读取输入文件: {resolved}")
        return resolved, False

    def write_spec(self, canonical_json: str) -> Path:
        path = self.inputs_dir / "scenario.json"
        path.write_text(canonical_json + "\n", encoding="utf-8")
        return path

    def freeze_context(self, source: Path, *, name: str) -> Path:
        original = Path(source).expanduser().resolve()
        if not original.is_file():
            raise RunIntegrityError(f"无法冻结运行上下文: {original}")
        context_dir = self.inputs_dir / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        suffix = "".join(original.suffixes)
        destination = context_dir / f"{name}{suffix}"
        if destination.exists():
            raise RunIntegrityError(f"运行上下文目标已存在: {destination}")
        # 与 freeze_input 相同的快照语义：只校验快照自身完整性，
        # 避免源在复制/hash 期间被并发写入导致的误报。
        shutil.copy2(original, destination)
        if _path_sha256(destination) is None:
            raise RunIntegrityError(f"冻结运行上下文校验失败: {original}")
        return destination

    def cleanup_temp(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)


@dataclass
class AnalysisRun:
    name: str
    kind: str = "scenario"
    platform: Optional[str] = None
    run_id: str = field(
        default_factory=lambda: datetime.now().strftime("%Y%m%dT%H%M%S")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    status: str = "running"
    verdict: str = "pending"
    started_at: str = field(default_factory=_now_iso)
    finished_at: Optional[str] = None
    inputs: List[RunFile] = field(default_factory=list)
    artifacts: List[RunFile] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    assertions: Dict[str, Any] = field(default_factory=dict)
    delivery: Dict[str, Any] = field(default_factory=dict)
    retention: Dict[str, Any] = field(default_factory=lambda: {"pinned": False})
    error: Optional[str] = None
    manifest_path: Optional[str] = None

    def add_input(
        self,
        path: Path,
        *,
        role: str = "source_snapshot",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        item = RunFile.from_path(role, path, metadata=metadata)
        if item.sha256 is None:
            raise RunIntegrityError(f"无法登记运行输入: {path}")
        self.inputs.append(item)

    def add_artifact(
        self,
        path: Path,
        *,
        role: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        resolved = str(Path(path).expanduser().resolve())
        if any(item.path == resolved and item.role == role for item in self.artifacts):
            return
        item = RunFile.from_path(role, Path(resolved), metadata=metadata)
        if item.sha256 is None:
            raise RunIntegrityError(f"无法登记运行产物: {path}")
        self.artifacts.append(item)

    def finish(
        self,
        *,
        status: str,
        verdict: Optional[str] = None,
        metrics: Optional[Dict[str, Any]] = None,
        assertions: Optional[Dict[str, Any]] = None,
        delivery: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        self.status = status
        if verdict is not None:
            self.verdict = verdict
        self.finished_at = _now_iso()
        if metrics:
            self.metrics.update(metrics)
        if assertions:
            self.assertions = dict(assertions)
        if delivery is not None:
            self.delivery = dict(delivery)
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": self.run_id,
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "verdict": self.verdict,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "inputs": [item.to_dict() for item in self.inputs],
            "artifacts": [item.to_dict() for item in self.artifacts],
            "parameters": self.parameters,
            "metrics": self.metrics,
            "assertions": self.assertions,
            "delivery": self.delivery,
            "retention": self.retention,
        }
        if self.platform:
            out["platform"] = self.platform
        if self.error:
            out["error"] = self.error
        if self.manifest_path:
            out["manifest_path"] = self.manifest_path
        return out

    def verify_files(self) -> None:
        for item in (*self.inputs, *self.artifacts):
            item.verify()
            original_path = item.metadata.get("original_path")
            original_sha = item.metadata.get("original_sha256")
            if original_path and original_sha:
                current = _path_sha256(Path(str(original_path)))
                if current != original_sha:
                    raise RunIntegrityError(
                        f"运行期间原始输入发生变化: {original_path}"
                    )

    def workspace(self, run_root: Path) -> RunWorkspace:
        return RunWorkspace.create(run_root, self.run_id)

    def write_manifest(self, run_root: Path) -> Path:
        run_dir = Path(run_root).expanduser().resolve() / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "manifest.json"
        self.manifest_path = str(path)
        tmp = run_dir / ".manifest.json.tmp"
        tmp.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
        return path
