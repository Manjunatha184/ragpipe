from __future__ import annotations

import argparse
import json
import random
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

DEPARTMENTS = ("hr", "finance", "engineering", "security", "legal")
REGIONS = ("global", "americas", "emea", "apac")
CLASSIFICATIONS = ("internal", "confidential", "restricted")
DOCUMENT_TYPES = ("policy", "procedure", "runbook", "standard", "guide")
TOPICS = {
    "hr": ("annual leave", "employee onboarding", "performance reviews", "workplace conduct"),
    "finance": ("expense reimbursement", "invoice approval", "financial close", "procurement"),
    "engineering": (
        "service deployment",
        "incident response",
        "database recovery",
        "release management",
    ),
    "security": (
        "access control",
        "credential rotation",
        "data classification",
        "security incidents",
    ),
    "legal": ("records retention", "vendor contracts", "privacy requests", "regulatory compliance"),
}
OWNERS = {
    "hr": "people-operations",
    "finance": "financial-controls",
    "engineering": "platform-engineering",
    "security": "information-security",
    "legal": "legal-compliance",
}
MANIFEST_NAME = ".ragpipe-metadata.json"
SCENARIO_NAME = ".enterprise-demo-scenario.json"


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def document_path(index: int) -> PurePosixPath:
    department = DEPARTMENTS[(index - 1) % len(DEPARTMENTS)]
    return PurePosixPath(department) / f"document-{index:05d}.md"


def document_metadata(index: int, version: int = 1) -> dict[str, Any]:
    department = DEPARTMENTS[(index - 1) % len(DEPARTMENTS)]
    return {
        "department": department,
        "classification": CLASSIFICATIONS[(index - 1) % len(CLASSIFICATIONS)],
        "region": REGIONS[(index - 1) % len(REGIONS)],
        "document_type": DOCUMENT_TYPES[(index - 1) % len(DOCUMENT_TYPES)],
        "owner": OWNERS[department],
        "version": version,
    }


def document_text(index: int, version: int = 1) -> str:
    metadata = document_metadata(index, version)
    department = str(metadata["department"])
    topic = TOPICS[department][(index - 1) % len(TOPICS[department])]
    document_id = f"ENT-{index:05d}"
    effective_date = f"2026-{((index - 1) % 12) + 1:02d}-01"
    return f"""# {topic.title()}

Document ID: {document_id}
Department: {department.title()}
Owner: {metadata["owner"]}
Region: {metadata["region"]}
Classification: {metadata["classification"]}
Version: {version}
Effective date: {effective_date}

## Purpose

This controlled enterprise document defines the {topic} requirements for the
{department} department. Employees and approved contractors must follow this
guidance when performing related business activities.

## Required process

1. Confirm that the request has a named owner and a documented business reason.
2. Obtain approval from the responsible department before taking action.
3. Record the decision, supporting evidence, and completion timestamp.
4. Escalate exceptions to {metadata["owner"]} within one business day.

## Controls

Evidence must be retained according to the records-retention schedule. Restricted
information must only be shared with authorized personnel. Quarterly control
reviews must identify overdue actions and unresolved exceptions.

## Operational guidance

For document {document_id}, the primary operational topic is {topic}. The owning
team is {metadata["owner"]}. Questions should be routed through the department's
standard support channel and include the document ID, region, and current version.
"""


def write_document(root: Path, index: int, version: int = 1) -> str:
    relative = document_path(index)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document_text(index, version), encoding="utf-8")
    return relative.as_posix()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def initialize(output: Path, documents: int) -> dict[str, Any]:
    if not 100 <= documents <= 10_000:
        raise ValueError("documents must be between 100 and 10000")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing path: {output}")

    output.mkdir(parents=True)
    manifest: dict[str, dict[str, Any]] = {}
    for index in range(1, documents + 1):
        relative = write_document(output, index)
        manifest[relative] = document_metadata(index)

    write_json(output / MANIFEST_NAME, manifest)
    scenario = build_scenario(documents)
    write_json(output.parent / f"{output.name}{SCENARIO_NAME}", scenario)
    write_json(output.parent / f"{output.name}-queries.json", build_queries())
    return {
        "action": "initialized",
        "output": str(output.resolve()),
        "documents": documents,
        "departments": len(DEPARTMENTS),
        "metadata_manifest": MANIFEST_NAME,
        "scenario_file": f"{output.name}{SCENARIO_NAME}",
        "queries_file": f"{output.name}-queries.json",
    }


def build_scenario(documents: int) -> dict[str, list[int]]:
    indexes = list(range(1, documents + 1))
    random.Random(20260908).shuffle(indexes)
    return {
        "deleted": sorted(indexes[:5]),
        "content_changed": sorted(indexes[5:25]),
        "metadata_changed": sorted(indexes[25:35]),
        "added": list(range(documents + 1, documents + 26)),
    }


def build_queries() -> list[dict[str, Any]]:
    return [
        {
            "query": "How are employee expense reimbursements approved?",
            "metadata": {"department": "finance"},
        },
        {
            "query": "What is the process for responding to a security incident?",
            "metadata": {"department": "security"},
        },
        {
            "query": "Who handles employee onboarding requirements?",
            "metadata": {"department": "hr"},
        },
        {
            "query": "How should a production service deployment be documented?",
            "metadata": {"department": "engineering"},
        },
        {
            "query": "What evidence is required for regulatory compliance?",
            "metadata": {"department": "legal"},
        },
    ]


def apply_daily_changes(root: Path) -> dict[str, Any]:
    manifest_path = root / MANIFEST_NAME
    scenario_path = root.parent / f"{root.name}{SCENARIO_NAME}"
    if not root.is_dir() or not manifest_path.is_file() or not scenario_path.is_file():
        raise FileNotFoundError("enterprise corpus or its scenario file is missing")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    first_added = document_path(scenario["added"][0]).as_posix()
    if first_added in manifest:
        raise RuntimeError("daily changes were already applied")

    for index in scenario["deleted"]:
        relative = document_path(index).as_posix()
        (root / relative).unlink()
        del manifest[relative]

    for index in scenario["content_changed"]:
        relative = write_document(root, index, version=2)
        manifest[relative] = document_metadata(index, version=2)

    for index in scenario["metadata_changed"]:
        relative = document_path(index).as_posix()
        updated = dict(manifest[relative])
        updated["classification"] = "restricted"
        updated["review_required"] = True
        manifest[relative] = updated

    for index in scenario["added"]:
        relative = write_document(root, index)
        manifest[relative] = document_metadata(index)

    write_json(manifest_path, manifest)
    return {
        "action": "daily_changes_applied",
        "output": str(root.resolve()),
        "new_documents": len(scenario["added"]),
        "changed_documents": len(scenario["content_changed"]),
        "metadata_changed_documents": len(scenario["metadata_changed"]),
        "deleted_documents": len(scenario["deleted"]),
        "expected_total_documents": len(manifest),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and update a deterministic enterprise Ragpipe demo corpus."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize_parser = subparsers.add_parser("init", help="Create a new enterprise corpus.")
    initialize_parser.add_argument("--output", type=Path, required=True)
    initialize_parser.add_argument("--documents", type=int, default=1000)
    update_parser = subparsers.add_parser(
        "daily-update", help="Apply one deterministic daily change set."
    )
    update_parser.add_argument("--source", type=Path, required=True)
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    try:
        if arguments.command == "init":
            result = initialize(arguments.output.expanduser(), arguments.documents)
        else:
            result = apply_daily_changes(arguments.source.expanduser())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        fail(f"Enterprise demo failed: {error}")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
