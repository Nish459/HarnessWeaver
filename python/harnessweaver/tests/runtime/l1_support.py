"""Helpers shared by the L1 module tests: specs with the core scripted model, org profiles."""

import json
from pathlib import Path
from typing import Any

import harnessweaver as hw
from harnessweaver.modules.models import ScriptedModel

__all__ = ["SUMMARY", "org_profile", "scripted", "scripted_model_of"]

SUMMARY = "hw_testkit:Summary"


def scripted(*replies: Any, **settings: Any) -> dict[str, Any]:
    return {"provider": "scripted", "replies": list(replies), **settings}


def org_profile(tmp_path: Path, **body: Any) -> str:
    directory = tmp_path / ".harness" / "profiles"
    directory.mkdir(parents=True, exist_ok=True)
    document = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Profile",
        "metadata": {"name": "acme-baseline", "version": "1.0.0"},
        **body,
    }
    (directory / "acme-baseline.yaml").write_text(json.dumps(document), encoding="ascii")
    return "org://acme-baseline"


def scripted_model_of(harness: hw.Harness) -> ScriptedModel:
    provider = harness._models.provider
    assert isinstance(provider, ScriptedModel)
    return provider
