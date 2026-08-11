# -*- coding: utf-8 -*-
"""文本来源：引擎的输入接缝。

本模块只解决通用的「文本从哪来」：本地文件、目录、压缩包、外部命令实时输出。
具体设备、产品或平台的采集适配由上层包提供。

核心约定 —— ``snapshot()`` 是唯一的归一化边界：

- **静态来源**（文件 / 目录 / 压缩包）：内容不再变化，``snapshot()`` 返回自身路径。
- **实时来源**（外部命令）：文件仍在写入，``snapshot()`` **必须**先冻结成不可变副本，
  后续分析一律基于副本，避免「边读边写」导致行号漂移、结论对不上。

实时采集命令可以是任意语言写的任意程序，只要它往 stdout 吐文本 —— 引擎不关心。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable


class SourceError(RuntimeError):
    """文本来源相关错误。"""


@runtime_checkable
class Source(Protocol):
    """所有文本来源必须实现的最小接口。"""

    @property
    def original(self) -> Path: ...

    def snapshot(self) -> Path: ...


@dataclass(frozen=True)
class SourceResolution:
    """source provider 的统一输出：不可变输入文件 + 可选来源对象。"""

    files: Tuple[Path, ...]
    source: Optional[Source] = None
    containers: Tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(Path(path).expanduser().resolve() for path in self.files)
        if not normalized:
            raise SourceError("source provider 没有返回任何文件")
        for path in normalized:
            if not path.is_file():
                raise SourceError(f"source provider 返回的文件不存在: {path}")
        object.__setattr__(self, "files", normalized)
        containers = tuple(
            Path(path).expanduser().resolve() for path in self.containers
        )
        for path in containers:
            if not path.is_file():
                raise SourceError(f"source provider 返回的容器不存在: {path}")
        object.__setattr__(self, "containers", containers)


SourceProvider = Callable[[Dict[str, Any], Optional[Path]], SourceResolution]
_SOURCE_PROVIDERS: Dict[str, SourceProvider] = {}


def register_source_provider(
    name: str,
    provider: SourceProvider,
    *,
    aliases: Sequence[str] = (),
    replace: bool = False,
) -> None:
    """注册声明式 source ``type``；冲突默认显式失败。"""
    keys = [str(name).strip().lower(), *(str(item).strip().lower() for item in aliases)]
    if not keys[0] or any(not key for key in keys):
        raise ValueError("source provider 名和 aliases 不能为空")
    for key in keys:
        current = _SOURCE_PROVIDERS.get(key)
        if current is not None and current is not provider and not replace:
            raise ValueError(f"source provider {key!r} 已注册")
    for key in keys:
        _SOURCE_PROVIDERS[key] = provider


def available_source_providers() -> List[str]:
    return sorted(_SOURCE_PROVIDERS)


def resolve_source_spec(
    spec: Dict[str, Any], *, base_dir: Optional[Path] = None
) -> SourceResolution:
    """通过公开 provider 注册表解析声明式来源。"""
    if not isinstance(spec, dict):
        raise SourceError("source 配置必须是对象")
    kind = str(spec.get("type") or "file").strip().lower()
    provider = _SOURCE_PROVIDERS.get(kind)
    if provider is None:
        known = ", ".join(available_source_providers()) or "(空)"
        raise SourceError(f"未知 source provider {kind!r}（可用: {known}）")
    try:
        result = provider(dict(spec), Path(base_dir) if base_dir is not None else None)
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError(f"source provider {kind!r} 执行失败: {exc}") from exc
    if not isinstance(result, SourceResolution):
        raise SourceError(
            f"source provider {kind!r} 必须返回 SourceResolution，"
            f"实际为 {type(result).__name__}"
        )
    return result


def _timestamp_suffix() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


@dataclass
class StaticFileSource:
    """静态文件：内容不再变化，快照即自身。"""

    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path).expanduser()
        if not self.path.exists():
            raise SourceError(f"文本来源不存在: {self.path}")
        if not self.path.is_file():
            raise SourceError(f"文本来源不是文件: {self.path}")

    @property
    def original(self) -> Path:
        return self.path

    def snapshot(self) -> Path:
        return self.path


@dataclass
class ArchiveSource:
    """压缩包来源：解包到临时目录后，按需挑选内部文件。

    支持 .zip / .tar / .tar.gz / .tgz。注意有些线上日志文件名叫 ``xxx.zip.txt``
    但其实是纯文本，这种由 ``is_archive()`` 判定为否，直接当静态文件处理。
    """

    path: Path
    extract_dir: Optional[Path] = None
    max_members: int = 10_000
    max_total_size: int = 2 * 1024 * 1024 * 1024
    max_member_size: int = 512 * 1024 * 1024
    max_compression_ratio: float = 1_000.0
    _members: List[Path] = field(default_factory=list, init=False)
    _target_dir: Optional[Path] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path).expanduser()
        if not self.path.exists():
            raise SourceError(f"压缩包不存在: {self.path}")
        for name, value in (
            ("max_members", self.max_members),
            ("max_total_size", self.max_total_size),
            ("max_member_size", self.max_member_size),
            ("max_compression_ratio", self.max_compression_ratio),
        ):
            if value <= 0:
                raise SourceError(f"{name} 必须大于 0")

    @staticmethod
    def is_archive(path: Path) -> bool:
        """按真实内容判定，不只看后缀 —— ``.zip.txt`` 这类命名会骗人。"""
        path = Path(path)
        if not path.is_file():
            return False
        try:
            if zipfile.is_zipfile(path):
                return True
            if tarfile.is_tarfile(path):
                return True
        except OSError:
            return False
        return False

    @property
    def original(self) -> Path:
        return self.path

    def extract(self) -> List[Path]:
        """解包并返回其中的所有普通文件路径。"""
        if self._members:
            return list(self._members)

        target = self.extract_dir or Path(tempfile.mkdtemp(prefix="tracecite_core_extract_"))
        target.mkdir(parents=True, exist_ok=True)
        self._target_dir = target
        target_root = target.resolve()
        extracted_members = 0
        extracted_size = 0
        extracted_paths: List[Path] = []

        def check_limits(name: str, size: int, compressed_size: Optional[int] = None) -> None:
            nonlocal extracted_members, extracted_size
            extracted_members += 1
            extracted_size += max(0, int(size))
            if extracted_members > self.max_members:
                raise SourceError(
                    f"压缩包成员过多: {extracted_members} > {self.max_members}"
                )
            if size > self.max_member_size:
                raise SourceError(
                    f"压缩包成员过大: {name}: {size} > {self.max_member_size}"
                )
            if extracted_size > self.max_total_size:
                raise SourceError(
                    f"压缩包解压总量过大: {extracted_size} > {self.max_total_size}"
                )
            if compressed_size is not None and size > 0:
                ratio = size / max(1, compressed_size)
                if ratio > self.max_compression_ratio:
                    raise SourceError(
                        f"压缩比异常: {name}: {ratio:.1f} > {self.max_compression_ratio:g}"
                    )

        try:
            if zipfile.is_zipfile(self.path):
                with zipfile.ZipFile(self.path) as zf:
                    safe_members = []
                    for member in zf.infolist():
                        dest = (target / member.filename).resolve()
                        mode = (member.external_attr >> 16) & 0o170000
                        if member.is_dir():
                            continue
                        if not dest.is_relative_to(target_root) or mode == 0o120000:
                            raise SourceError(
                                f"压缩包含不安全成员: {member.filename}"
                            )
                        check_limits(member.filename, member.file_size, member.compress_size)
                        safe_members.append((member, dest))
                    for member, dest in safe_members:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as source, dest.open("wb") as output:
                            shutil.copyfileobj(source, output)
                        extracted_paths.append(dest)
            elif tarfile.is_tarfile(self.path):
                with tarfile.open(self.path) as tf:
                    safe_members = []
                    for member in tf:
                        dest = (target / member.name).resolve()
                        if member.isdir():
                            continue
                        if (
                            not dest.is_relative_to(target_root)
                            or not member.isfile()
                            or member.issym()
                            or member.islnk()
                        ):
                            raise SourceError(
                                f"压缩包含不安全成员: {member.name}"
                            )
                        check_limits(member.name, member.size)
                        safe_members.append((member, dest))
                    archive_size = max(1, self.path.stat().st_size)
                    archive_ratio = extracted_size / archive_size
                    if archive_ratio > self.max_compression_ratio:
                        raise SourceError(
                            f"压缩包总体压缩比异常: {archive_ratio:.1f} > "
                            f"{self.max_compression_ratio:g}"
                        )
                    for member, dest in safe_members:
                        source = tf.extractfile(member)
                        if source is None:
                            continue
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with source, dest.open("wb") as output:
                            shutil.copyfileobj(source, output)
                        extracted_paths.append(dest)
            else:
                raise SourceError(f"不是可识别的压缩包: {self.path}")
        except Exception:
            for path in reversed(extracted_paths):
                path.unlink(missing_ok=True)
            if self.extract_dir is None:
                shutil.rmtree(target, ignore_errors=True)
                self._target_dir = None
            raise

        self._members = sorted(extracted_paths)
        return list(self._members)

    def snapshot(self) -> Path:
        members = self.extract()
        if not members:
            raise SourceError(f"压缩包内没有文件: {self.path}")
        return members[0]

    def cleanup(self) -> None:
        if self.extract_dir is None and self._target_dir is not None:
            shutil.rmtree(self._target_dir, ignore_errors=True)
        self._members.clear()
        self._target_dir = None


@dataclass
class LiveSource:
    """实时来源：跑一个外部命令，把 stdout 落盘，再冻结成快照。

    命令可以是任意语言的任意程序；Core 只负责启动、落盘、冻结，不理解命令语义。

    两种用法：

    - ``collect()``      按 duration 采集固定时长后返回（一次性）
    - ``start()`` / ``stop()``  长驻后台采集，随时 stop（配合 session 语义）
    """

    cmd: Sequence[str]
    output_path: Optional[Path] = None
    snapshot_dir: Optional[Path] = None
    duration: float = 30.0
    encoding: str = "utf-8"
    _proc: Optional[subprocess.Popen] = field(default=None, init=False, repr=False)
    _handle: Optional[Any] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.cmd:
            raise SourceError("LiveSource 需要一个非空命令")
        if self.output_path is None:
            base = Path(tempfile.mkdtemp(prefix="tracecite_core_live_"))
            self.output_path = base / f"live_{_timestamp_suffix()}.log"
        else:
            self.output_path = Path(self.output_path).expanduser()
            self.output_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def original(self) -> Path:
        return Path(self.output_path)

    def start(self) -> None:
        """启动采集进程，立即返回。"""
        if self._proc is not None:
            raise SourceError("采集已在运行中")
        self._handle = open(self.output_path, "w", encoding=self.encoding, errors="replace")
        try:
            self._proc = subprocess.Popen(
                list(self.cmd),
                stdout=self._handle,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            self._handle.close()
            self._handle = None
            raise SourceError(f"采集命令不存在: {self.cmd[0]}（{exc}）") from exc

    def stop(self, *, grace: float = 3.0) -> Path:
        """停止采集，返回落盘文件路径。"""
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=grace)
            self._proc = None
        if self._handle is not None:
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._handle.close()
            self._handle = None
        return Path(self.output_path)

    def collect(self) -> Path:
        """采集 ``duration`` 秒后停止，返回落盘文件路径。"""
        self.start()
        time.sleep(max(0.0, float(self.duration)))
        return self.stop()

    def snapshot(self) -> Path:
        """冻结当前内容为不可变副本。实时来源必须先冻结再分析。"""
        src = Path(self.output_path)
        if not src.exists():
            raise SourceError(f"采集文件不存在: {src}")
        target_dir = self.snapshot_dir or (src.parent / ".snapshots")
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / f"{src.stem}_{_timestamp_suffix()}.snapshot.log"
        shutil.copy2(src, dest)
        return dest


def resolve_paths(
    raw: str,
    *,
    base_dir: Optional[Path] = None,
    glob: str = "*",
    recursive: bool = False,
    extract_dir: Optional[Path] = None,
) -> List[Path]:
    """把一个路径字符串解析成实际待分析的文件列表。

    统一处理四种形态：单文件、目录（按 glob 挑选）、压缩包（解包后挑选）、
    以及路径本身带通配符。相对路径相对 ``base_dir`` 解析（通常是 spec 文件所在目录）。
    """
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute() and base_dir is not None:
        candidate = (Path(base_dir) / candidate).resolve()

    # 路径自带通配符
    if any(ch in str(candidate) for ch in "*?[") and not candidate.exists():
        parent = candidate.parent
        pattern = candidate.name
        return sorted(p for p in parent.glob(pattern) if p.is_file())

    if not candidate.exists():
        raise SourceError(f"路径不存在: {candidate}")

    if candidate.is_file():
        if ArchiveSource.is_archive(candidate):
            archive_dir = Path(extract_dir) / candidate.stem if extract_dir else None
            members = ArchiveSource(candidate, extract_dir=archive_dir).extract()
            return sorted(p for p in members if p.is_file())
        return [candidate]

    if candidate.is_dir():
        globber = candidate.rglob if recursive else candidate.glob
        files: List[Path] = []
        for item in sorted(globber(glob)):
            if not item.is_file():
                continue
            if ArchiveSource.is_archive(item):
                archive_dir = Path(extract_dir) / item.stem if extract_dir else None
                files.extend(ArchiveSource(item, extract_dir=archive_dir).extract())
            else:
                files.append(item)
        if not files:
            raise SourceError(f"目录下没有匹配 {glob!r} 的文件: {candidate}")
        return files

    raise SourceError(f"无法识别的路径类型: {candidate}")


def _file_source_provider(
    spec: Dict[str, Any], base_dir: Optional[Path]
) -> SourceResolution:
    raw_extract_dir = spec.get("extract_dir")
    extract_dir = Path(str(raw_extract_dir)).expanduser() if raw_extract_dir else None
    raw_path = str(spec.get("path", ""))
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute() and base_dir is not None:
        candidate = (Path(base_dir) / candidate).resolve()
    if candidate.is_file() and ArchiveSource.is_archive(candidate):
        archive_dir = extract_dir / candidate.stem if extract_dir else None
        source = ArchiveSource(candidate, extract_dir=archive_dir)
        members = source.extract()
        pattern = str(spec.get("glob", "*"))
        files = tuple(
            path for path in members if path.is_file() and path.match(pattern)
        )
        return SourceResolution(files, source=source, containers=(candidate,))

    paths = resolve_paths(
        raw_path,
        base_dir=base_dir,
        glob=str(spec.get("glob", "*")),
        recursive=bool(spec.get("recursive", False)),
        extract_dir=extract_dir,
    )
    containers: List[Path] = []
    if candidate.is_dir():
        globber = candidate.rglob if bool(spec.get("recursive", False)) else candidate.glob
        containers = [
            item
            for item in sorted(globber(str(spec.get("glob", "*"))))
            if item.is_file() and ArchiveSource.is_archive(item)
        ]
    elif any(ch in str(candidate) for ch in "*?[") and not candidate.exists():
        containers = [
            item
            for item in sorted(candidate.parent.glob(candidate.name))
            if item.is_file() and ArchiveSource.is_archive(item)
        ]
    return SourceResolution(tuple(paths), containers=tuple(containers))


def _live_source_provider(
    spec: Dict[str, Any], base_dir: Optional[Path]
) -> SourceResolution:
    cmd = spec.get("cmd")
    if not isinstance(cmd, (list, tuple)) or not cmd:
        raise SourceError("live 来源需要非空 cmd 数组")
    if any(not isinstance(item, str) or not item for item in cmd):
        raise SourceError("live 来源 cmd 的每一项都必须是非空字符串")
    snapshot_dir = (
        Path(str(spec["snapshot_dir"])).expanduser()
        if spec.get("snapshot_dir")
        else None
    )
    output_path = snapshot_dir.parent / "live_capture.log" if snapshot_dir else None
    source = LiveSource(
        list(cmd),
        output_path=output_path,
        snapshot_dir=snapshot_dir,
        duration=float(spec.get("duration", 30)),
        encoding=str(spec.get("encoding", "utf-8")),
    )
    source.collect()
    return SourceResolution(
        (source.snapshot(),), source=source, containers=(source.original,)
    )


register_source_provider(
    "file",
    _file_source_provider,
    aliases=("static", "path", "dir", "archive"),
)
register_source_provider("live", _live_source_provider, aliases=("command", "cmd"))


def build_source(spec: Dict[str, Any], *, base_dir: Optional[Path] = None) -> Source:
    """构造单个 ``Source``；多文件场景应使用 ``resolve_source_spec``。"""
    resolved = resolve_source_spec(spec, base_dir=base_dir)
    return resolved.source or StaticFileSource(resolved.files[0])
