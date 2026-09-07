from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_benchmark_corpus.py"


def run_generator(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def test_generates_deterministic_exact_size_corpus(
    tmp_path: Path,
) -> None:
    output = tmp_path / "benchmark-docs"

    result = run_generator(
        "--output",
        str(output),
        "--documents",
        "3",
        "--size-bytes",
        "128",
        "--extension",
        "md",
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "output": str(output.resolve()),
        "documents": 3,
        "size_bytes_per_document": 128,
        "total_bytes": 384,
        "extension": "md",
    }

    paths = sorted(output.iterdir())
    assert [path.name for path in paths] == [
        "document-00001.md",
        "document-00002.md",
        "document-00003.md",
    ]
    assert [path.stat().st_size for path in paths] == [128, 128, 128]
    assert paths[0].read_bytes().startswith(b"# Ragpipe benchmark document 00001")


def test_refuses_to_overwrite_existing_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("do not replace", encoding="utf-8")

    result = run_generator(
        "--output",
        str(output),
    )

    assert result.returncode != 0
    assert "refusing to overwrite" in result.stderr
    assert marker.read_text(encoding="utf-8") == "do not replace"


def test_rejects_unsafe_generation_limits(
    tmp_path: Path,
) -> None:
    result = run_generator(
        "--output",
        str(tmp_path / "benchmark-docs"),
        "--documents",
        "10001",
    )

    assert result.returncode == 2
    assert "documents must be between 1 and 10000" in result.stderr
    assert not (tmp_path / "benchmark-docs").exists()
