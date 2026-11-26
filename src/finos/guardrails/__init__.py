"""Guardrails: code-level checks on every query and every reply (Hardening 3).

- :mod:`finos.guardrails.checks` — pure checks with no I/O: the input regex
  categories, the crisis pattern, and the output checks
- :mod:`finos.guardrails.input` — the input layers (regex, moderation,
  injection classifier), failing open
- :mod:`finos.guardrails.output` — the output checks and their fixed
  replacements, failing closed

Importing this package loads no settings and imports neither LangChain,
``openai``, nor ``langsmith``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from finos.guardrails.decisions import GuardDecision, InputVerdict

__all__ = ["GuardDecision", "InputVerdict", "blocked_state", "guarded"]


def blocked_state(query: str) -> dict[str, Any]:
    """The state a blocked query returns: the fallback, intent ``policy``, nothing retrieved."""
    from finos.prompts import GUARDRAIL_FALLBACK_MESSAGE
    from finos.state import SupportState, initial_state

    state = initial_state(query)
    state["intent"] = "policy"
    state["response"] = GUARDRAIL_FALLBACK_MESSAGE
    return SupportState(**state)


def guarded(
    query: str, run: Callable[[str], Any], *, root_run: Any = None
) -> tuple[Any, InputVerdict]:
    """Answer ``query`` through the guardrails (design D2).

    Runs the input guards; a blocked query returns :func:`blocked_state`
    without calling ``run``. Otherwise ``run(query)`` answers, and its
    ``response`` passes the output guards. When anything but ``passed``
    happened, ``root_run`` (the request's root handle) gets the
    ``guardrail:<decision>`` tag.
    """
    from finos.guardrails.decisions import strongest
    from finos.guardrails.input import guard_input
    from finos.guardrails.output import guard_output

    verdict = guard_input(query)
    if verdict.blocked:
        state = blocked_state(query)
        decisions = list(verdict.decisions)
    else:
        state = run(query)
        text, out = guard_output(
            state["response"], query=query, intent=state["intent"], crisis=verdict.crisis
        )
        state["response"] = text
        decisions = list(verdict.decisions) + out
    tag = strongest(decisions, blocked=verdict.blocked)
    if tag and root_run is not None:
        root_run.add_tags([f"guardrail:{tag}"])
    return state, verdict
