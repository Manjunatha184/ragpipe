from pathlib import Path

from ragpipe.ingest.loaders import load_text


def test_weird_encoding_is_replaced_not_crashed(tmp_path: Path) -> None:
    path = tmp_path / "legacy.txt"
    path.write_bytes(b"hello\xffworld")
    assert load_text(path) == "hello\ufffdworld"
