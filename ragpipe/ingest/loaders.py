from io import BytesIO
from pathlib import Path, PurePosixPath

from pypdf import PdfReader


class DocumentLoadError(RuntimeError):
    pass


def load_bytes(
    content: bytes,
    name: str,
) -> str:
    """Extract text from document bytes using the document name as the format hint."""

    display_name = PurePosixPath(name).name or name

    try:
        if PurePosixPath(name).suffix.lower() == ".pdf":
            reader = PdfReader(BytesIO(content))

            return "\n\n".join(page.extract_text() or "" for page in reader.pages)

        return content.decode(
            "utf-8",
            errors="replace",
        )
    except Exception as error:
        raise DocumentLoadError(f"Could not read {display_name}: {error}") from error


def load_text(path: Path) -> str:
    """Read a local document and extract its text."""

    try:
        content = path.read_bytes()
    except Exception as error:
        raise DocumentLoadError(f"Could not read {path.name}: {error}") from error

    return load_bytes(
        content,
        path.name,
    )
