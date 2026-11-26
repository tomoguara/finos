"""Checks for policy claims and false promises in agent replies (Step 4).

The detectors live in :mod:`finos.evaluation.detectors` since Hardening 2,
where the evaluation evaluators use them; this module re-exports them so the
live tests keep their imports.
"""

from finos.evaluation.detectors import (  # noqa: F401
    FALSE_PROMISE_PATTERNS,
    POLICY_CLAIM_PATTERNS,
    explain,
    has_false_promise,
    has_policy_claim,
)
