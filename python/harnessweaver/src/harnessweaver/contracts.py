"""The language-neutral contracts and their JSON Schemas (RULES R11, DESIGNS ADR-0005).

The Pydantic models are where contracts are written; the JSON Schemas generated
from them are checked in under ``contracts/schemas`` so other languages and
reviewers see the contract directly. A test fails if the two drift apart.

Regenerate with ``make schemas``; ``make schemas-check`` reports drift.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Final

from pydantic import TypeAdapter

from harnessweaver.core.decisions import Decision, DecisionRequest
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import ErrorInfo
from harnessweaver.core.guards import GuardResult
from harnessweaver.core.hooks import HookEvent
from harnessweaver.core.messages import ModelRequest, ModelResponse, ToolCall
from harnessweaver.core.outcomes import Outcome
from harnessweaver.core.retrieval import ContextItem
from harnessweaver.core.runs import ApprovalDecision, ApprovalRequest
from harnessweaver.core.tools import ToolInfo, ToolResult

__all__ = [
    "API_VERSION",
    "CONTRACTS",
    "json_schemas",
    "main",
    "render_schema",
    "stale_schemas",
    "write_schemas",
]

API_VERSION: Final = "harnessweaver/v1"
"""The contract version carried by specs and wire messages."""

_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"

CONTRACTS: Final[dict[str, Any]] = {
    "envelope": Envelope,
    "hook-event": HookEvent,
    "outcome": Outcome,
    "decision-request": DecisionRequest,
    "decision": Decision,
    "guard-result": GuardResult,
    "model-request": ModelRequest,
    "model-response": ModelResponse,
    "tool-call": ToolCall,
    "tool-info": ToolInfo,
    "tool-result": ToolResult,
    "context-item": ContextItem,
    "approval-request": ApprovalRequest,
    "approval-decision": ApprovalDecision,
    "error-info": ErrorInfo,
}
"""Every exported contract, by schema file name (without ``.schema.json``)."""


def json_schemas() -> dict[str, dict[str, Any]]:
    """Generate the JSON Schema (draft 2020-12) of every contract."""
    schemas: dict[str, dict[str, Any]] = {}
    for name, contract in CONTRACTS.items():
        generated = TypeAdapter(contract).json_schema()
        title = generated.pop("title", None) or name.replace("-", " ").title().replace(" ", "")
        schemas[name] = {
            "$schema": _DIALECT,
            "$id": f"urn:harnessweaver:v1:{name}",
            "title": title,
            **generated,
        }
    return schemas


def render_schema(schema: dict[str, Any]) -> str:
    """Serialize a schema exactly as it is checked in."""
    return json.dumps(schema, indent=2, ensure_ascii=True) + "\n"


def write_schemas(directory: Path) -> list[Path]:
    """Write every contract's schema to ``directory`` and remove stale schema files."""
    directory.mkdir(parents=True, exist_ok=True)
    schemas = json_schemas()
    written: list[Path] = []
    for name, schema in schemas.items():
        path = directory / f"{name}.schema.json"
        path.write_text(render_schema(schema), encoding="utf-8")
        written.append(path)
    for path in directory.glob("*.schema.json"):
        if path.name.removesuffix(".schema.json") not in schemas:
            path.unlink()
    return written


def stale_schemas(directory: Path) -> list[str]:
    """Return the schema files in ``directory`` that are missing, extra or out of date."""
    schemas = json_schemas()
    problems: list[str] = []
    for name, schema in schemas.items():
        path = directory / f"{name}.schema.json"
        if not path.exists():
            problems.append(f"{path.name} is missing")
        elif path.read_text(encoding="utf-8") != render_schema(schema):
            problems.append(f"{path.name} is out of date")
    for path in sorted(directory.glob("*.schema.json")):
        if path.name.removesuffix(".schema.json") not in schemas:
            problems.append(f"{path.name} is not a known contract")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Write the contract schemas, or with ``--check`` report drift (exit code 1)."""
    parser = argparse.ArgumentParser(prog="harnessweaver-contracts")
    parser.add_argument("directory", type=Path, help="usually contracts/schemas")
    parser.add_argument("--check", action="store_true", help="report drift instead of writing")
    args = parser.parse_args(argv)
    if args.check:
        problems = stale_schemas(args.directory)
        for problem in problems:
            print(problem)  # noqa: T201 - command-line output
        return 1 if problems else 0
    for path in write_schemas(args.directory):
        print(f"wrote {path}")  # noqa: T201 - command-line output
    return 0
