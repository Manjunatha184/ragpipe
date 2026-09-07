from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import NoReturn

MAX_DOCUMENTS = 10_000
MAX_SIZE_BYTES = 10 * 1024 * 1024


def positive_bounded_integer(
    value: str,
    *,
    name: str,
    maximum: int,
) -> int:
    """Parse a positive integer with an explicit safety limit."""

    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{name} must be an integer") from error

    if not 1 <= parsed <= maximum:
        raise argparse.ArgumentTypeError(f"{name} must be between 1 and {maximum}")

    return parsed


def document_count(value: str) -> int:
    return positive_bounded_integer(
        value,
        name="documents",
        maximum=MAX_DOCUMENTS,
    )


def document_size(value: str) -> int:
    return positive_bounded_integer(
        value,
        name="size-bytes",
        maximum=MAX_SIZE_BYTES,
    )


def build_document(
    index: int,
    size_bytes: int,
    extension: str,
) -> bytes:
    """Build deterministic ASCII content with an exact byte size."""

    heading = (
        f"# Ragpipe benchmark document {index:05d}\n\n"
        if extension == "md"
        else f"Ragpipe benchmark document {index:05d}\n"
    )
    sentence = (
        f"Document {index:05d} exercises incremental scanning, "
        "chunking, embedding, and pgvector synchronization.\n"
    )
    seed = (heading + sentence).encode("ascii")
    repetitions = (size_bytes // len(seed)) + 1

    return (seed * repetitions)[:size_bytes]


def generate_corpus(
    output: Path,
    documents: int,
    size_bytes: int,
    extension: str,
) -> dict[str, int | str]:
    """Create a new benchmark corpus without overwriting existing data."""

    output = output.expanduser()

    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Output path already exists; refusing to overwrite it: {output}")

    output.mkdir(parents=True)

    width = max(5, len(str(documents)))

    for index in range(1, documents + 1):
        path = output / f"document-{index:0{width}d}.{extension}"
        path.write_bytes(
            build_document(
                index=index,
                size_bytes=size_bytes,
                extension=extension,
            )
        )

    return {
        "output": str(output.resolve()),
        "documents": documents,
        "size_bytes_per_document": size_bytes,
        "total_bytes": documents * size_bytes,
        "extension": extension,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a deterministic local corpus for Ragpipe load testing. "
            "The output path must not already exist."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New directory in which benchmark documents are created.",
    )
    parser.add_argument(
        "--documents",
        type=document_count,
        default=100,
        help=f"Number of documents to create (1-{MAX_DOCUMENTS}).",
    )
    parser.add_argument(
        "--size-bytes",
        type=document_size,
        default=4096,
        help=(f"Exact bytes per document (1-{MAX_SIZE_BYTES})."),
    )
    parser.add_argument(
        "--extension",
        choices=("txt", "md"),
        default="txt",
        help="Generated document extension.",
    )

    return parser


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()

    try:
        summary = generate_corpus(
            output=arguments.output,
            documents=arguments.documents,
            size_bytes=arguments.size_bytes,
            extension=arguments.extension,
        )
    except OSError as error:
        fail(f"Could not generate benchmark corpus: {error}")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
