from pathlib import Path

from pypdf import PdfReader


class DocumentLoadError(RuntimeError):
    pass


def load_text(path: Path) -> str:
    try:
        if path.suffix.lower() == ".pdf":
            reader = PdfReader(path)
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        raise DocumentLoadError(f"Could not read {path.name}: {exc}") from exc
