from __future__ import annotations

import zipfile
import tarfile
from pathlib import Path

import pytest

from tracecite_core.source import ArchiveSource, SourceError


def test_archive_rejects_member_count_over_budget(tmp_path: Path) -> None:
    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("a.log", "a")
        handle.writestr("b.log", "b")

    with pytest.raises(SourceError, match="成员过多"):
        ArchiveSource(
            archive,
            extract_dir=tmp_path / "out",
            max_members=1,
        ).extract()


def test_archive_rejects_member_larger_than_budget(tmp_path: Path) -> None:
    archive = tmp_path / "large.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("large.log", "0123456789")

    with pytest.raises(SourceError, match="成员过大"):
        ArchiveSource(
            archive,
            extract_dir=tmp_path / "out",
            max_member_size=5,
        ).extract()


def test_archive_rejects_excessive_tar_compression_ratio(tmp_path: Path) -> None:
    source = tmp_path / "zeros.log"
    source.write_bytes(b"0" * 64_000)
    archive = tmp_path / "compressed.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source, arcname="zeros.log")

    with pytest.raises(SourceError, match="总体压缩比异常"):
        ArchiveSource(
            archive,
            extract_dir=tmp_path / "out",
            max_compression_ratio=2,
        ).extract()


def test_archive_returns_only_members_from_current_archive(tmp_path: Path) -> None:
    archive = tmp_path / "one.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("inside.log", "inside")
    output = tmp_path / "out"
    output.mkdir()
    preexisting = output / "unrelated.log"
    preexisting.write_text("keep", encoding="utf-8")

    members = ArchiveSource(archive, extract_dir=output).extract()

    assert members == [(output / "inside.log").resolve()]
    assert preexisting.read_text(encoding="utf-8") == "keep"


def test_archive_rejects_path_traversal_instead_of_silently_dropping_it(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../outside.log", "unsafe")

    with pytest.raises(SourceError, match="不安全成员"):
        ArchiveSource(archive, extract_dir=tmp_path / "out").extract()

    assert not (tmp_path / "outside.log").exists()
