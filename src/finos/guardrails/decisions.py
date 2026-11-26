"""Guard decisions, and recording them as traced runs (design D6)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

PASSED = "passed"
BLOCKED = "blocked"
REDACTED = "redacted"
REPLACED = "replaced"
APPENDED = "appended"
SKIPPED = "skipped"
OFF = "off"
ERROR = "error"

TAG_ORDER = (BLOCKED, REPLACED, REDACTED, APPENDED, ERROR)
"""Which decision names the root's ``guardrail:<decision>`` tag, strongest first."""


@dataclass(frozen=True)
class GuardDecision:
    guard_type: str
    decision: str
    reason: str = ""
    """The category, never the query or the matched text."""
    latency_ms: float = 0.0

    def line(self) -> str:
        return f"{self.guard_type} {self.decision}" + (f" ({self.reason})" if self.reason else "")


@dataclass
class InputVerdict:
    blocked: bool
    crisis: bool
    decisions: list[GuardDecision] = field(default_factory=list)


def record(guard_type: str, check: Callable[[], tuple[str, str]]) -> GuardDecision:
    """Run one guard as a ``guardrail_check`` run and record its decision.

    ``check`` returns ``(decision, reason)``. The run's inputs are the guard
    type only, and its outputs the decision, reason, and latency: never the
    query or the matched text. Only guards that actually run are recorded.
    """
    from finos.observability import add_guard_decision, step

    def run() -> GuardDecision:
        start = time.perf_counter()
        decision, reason = check()
        return GuardDecision(guard_type, decision, reason, (time.perf_counter() - start) * 1000)

    traced = step(
        "guardrail_check",
        "tool",
        inputs=lambda: {"guard_type": guard_type},
        outputs=lambda d: {"decision": d.decision, "reason": d.reason, "latency_ms": round(d.latency_ms, 1)},
    )(run)
    result = traced()
    add_guard_decision(result)
    return result


def strongest(decisions: list[GuardDecision], *, blocked: bool) -> str | None:
    """The root tag's decision: ``blocked`` only if the query was really blocked."""
    seen = {d.decision for d in decisions}
    if blocked:
        return BLOCKED
    for decision in TAG_ORDER[1:]:
        if decision in seen:
            return decision
    return None
