"""The ``policy`` module: deterministic allow, deny or require approval (DESIGNS No. 17, R3).

The engine named by ``policy.use`` answers at ``tool.before`` (governor step 3)
and at ``run.start``. Every engine combines ``policy.rules`` the same way
(:func:`harnessweaver.core.policy.decide_by_rules`, ADR-0025).
"""

from harnessweaver.modules.policy.cel_lite import CelLitePolicy

__all__ = ["CelLitePolicy"]
