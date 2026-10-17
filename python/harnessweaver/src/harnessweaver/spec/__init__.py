"""The spec system: ``harness.yaml``, profiles, layering, locks, bounds and levels.

See DESIGNS No. 11.
"""

from harnessweaver.spec.explain import ExplainRow, SpecChange, SpecDiff, render_diff, render_explain
from harnessweaver.spec.levels import REQUIREMENTS, LevelReport, assess
from harnessweaver.spec.loader import (
    ENV_VAR,
    POLICY_VARIABLES,
    VALIDATION_VARIABLES,
    EffectiveSpec,
    diff_specs,
    load_spec,
    spec_from_documents,
)
from harnessweaver.spec.merge import Bound, Layer, LayerKind, Lock, Provenance, merge_layers
from harnessweaver.spec.models import HarnessSpec, Level, ProfileSpec
from harnessweaver.spec.sources import BuiltinProfiles, ProfileDirectories, ProfileResolver

__all__ = [
    "ENV_VAR",
    "POLICY_VARIABLES",
    "REQUIREMENTS",
    "VALIDATION_VARIABLES",
    "Bound",
    "BuiltinProfiles",
    "EffectiveSpec",
    "ExplainRow",
    "HarnessSpec",
    "Layer",
    "LayerKind",
    "Level",
    "LevelReport",
    "Lock",
    "ProfileDirectories",
    "ProfileResolver",
    "ProfileSpec",
    "Provenance",
    "SpecChange",
    "SpecDiff",
    "assess",
    "diff_specs",
    "load_spec",
    "merge_layers",
    "render_diff",
    "render_explain",
    "spec_from_documents",
]
