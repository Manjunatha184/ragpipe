from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def load_generator() -> ModuleType:
    script = Path(__file__).parents[1] / "scripts" / "generate_enterprise_demo.py"
    spec = importlib.util.spec_from_file_location("generate_enterprise_demo", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_enterprise_corpus_and_daily_update(tmp_path: Path) -> None:
    generator = load_generator()
    source = tmp_path / "enterprise_docs"

    initial = generator.initialize(source, 100)
    assert initial["documents"] == 100
    assert len(list(source.rglob("*.md"))) == 100

    updated = generator.apply_daily_changes(source)
    assert updated == {
        "action": "daily_changes_applied",
        "output": str(source.resolve()),
        "new_documents": 25,
        "changed_documents": 20,
        "metadata_changed_documents": 10,
        "deleted_documents": 5,
        "expected_total_documents": 120,
    }
    assert len(list(source.rglob("*.md"))) == 120
