from pathlib import Path

from tracecite_core.preprocess import run_preprocess_pipeline


def test_builtin_preprocessors_stream_without_path_bulk_reads(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.log"
    source.write_bytes("保留 target\n丢弃 other\n".encode("gbk"))

    def reject_bulk_read(*args, **kwargs):
        raise AssertionError("preprocessor 不应使用 Path.read_text/read_bytes 整体读入")

    monkeypatch.setattr(Path, "read_text", reject_bulk_read)
    monkeypatch.setattr(Path, "read_bytes", reject_bulk_read)
    result = run_preprocess_pipeline(
        source,
        [
            {"action": "charset", "from": "gbk", "to": "utf-8"},
            {"action": "grep", "pattern": "target", "encoding": "utf-8"},
        ],
        temp_dir=tmp_path / "processed",
    )

    with result.open(encoding="utf-8") as handle:
        assert handle.read() == "保留 target\n"
