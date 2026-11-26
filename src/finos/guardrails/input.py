"""Input guards: the regex, then moderation, then the injection classifier (design D3).

The first block stops the chain. A crisis signal (the crisis pattern, or
moderation's self-harm categories) overrides every block: a customer in
crisis is always answered. The model layers fail open, and without an
OpenAI key they are off for the process.
"""

from __future__ import annotations

import os
from typing import Any

from finos.guardrails import checks
from finos.guardrails.decisions import (
    BLOCKED,
    ERROR,
    OFF,
    PASSED,
    SKIPPED,
    GuardDecision,
    InputVerdict,
    record,
)

MODERATION_MODEL = "omni-moderation-latest"
MODERATION_TIMEOUT_S = 5.0
CLASSIFIER_TIMEOUT_S = 10.0

BLOCKING_PREFIXES = ("violence", "illicit", "hate", "sexual/minors")
"""Moderation categories that block (with their sub-categories)."""

CRISIS_PREFIXES = ("self-harm", "self_harm")
"""Moderation categories that mark a crisis; they never block."""

LAYERS = ("regex", "moderation", "injection_classifier")


def guardrails_status() -> dict[str, Any]:
    """Which input layers run in this process, and which are off for lack of a key.

    Loads settings first (which reads ``.env``). The moderation check needs
    ``OPENAI_API_KEY``; the classifier needs it only with an OpenAI provider.
    """
    from finos.config import get_settings

    settings = get_settings()["guardrails"]
    has_key = bool(os.environ.get("OPENAI_API_KEY"))
    classifier_needs_key = settings["classifier_provider"] == "openai"
    no_key = []
    if settings["moderation"] and not has_key:
        no_key.append("moderation")
    if settings["injection_classifier"] and classifier_needs_key and not has_key:
        no_key.append("injection_classifier")
    return {
        "regex": bool(settings["input_regex"]),
        "moderation": bool(settings["moderation"]) and "moderation" not in no_key,
        "injection_classifier": bool(settings["injection_classifier"])
        and "injection_classifier" not in no_key,
        "off_without_key": no_key,
    }


def moderate(query: str) -> set[str]:
    """Return the moderation categories flagged for ``query``."""
    from openai import OpenAI

    response = OpenAI(timeout=MODERATION_TIMEOUT_S).moderations.create(
        model=MODERATION_MODEL, input=query
    )
    result = response.results[0]
    categories = result.categories.model_dump(by_alias=True)
    return {name for name, flagged in categories.items() if flagged}


def classify(query: str) -> str:
    """Return ``"injection"`` or ``"safe"`` (anything unreadable counts as safe, as ``unparsed``).

    The model runs in a worker thread so the timeout holds whatever the
    provider does. The worker runs in a copy of the caller's context, so the
    call stays in the request: its tokens reach the timing collector, and its
    run nests under the request's root and uploads through the masking
    client. A plain executor would lose all three.
    """
    from langchain_core.runnables.config import ContextThreadPoolExecutor

    from finos import llm
    from finos.agents.policy import _message_text
    from finos.observability import chain_config
    from finos.prompts import INJECTION_CLASSIFIER_PROMPT

    model = llm.get_classifier_llm().with_config(**chain_config("injection_classifier_llm"))
    with ContextThreadPoolExecutor(max_workers=1) as pool:
        message = pool.submit(
            model.invoke, [("system", INJECTION_CLASSIFIER_PROMPT), ("human", query)]
        ).result(timeout=CLASSIFIER_TIMEOUT_S)
    words = _message_text(message).strip().lower().split()
    first = words[0].strip(".!\"'") if words else ""
    if first in ("injection", "safe"):
        return first
    return "unparsed"


def _regex_check(query: str) -> tuple[str, str]:
    category = checks.input_category(query)
    return (BLOCKED, category) if category else (PASSED, "")


def guard_input(query: str) -> InputVerdict:
    """Run the enabled input layers in order and return the verdict.

    The layers run inside one guard span, so the classifier's call gets the
    ``guards:`` timing line, and the verdict is noted on the request for its
    audit record.
    """
    from finos.observability import guard_span, note_verdict

    with guard_span():
        verdict = _guard_input(query)
    note_verdict(blocked=verdict.blocked, crisis=verdict.crisis)
    return verdict


def _guard_input(query: str) -> InputVerdict:
    import finos.guardrails.input as this

    status = guardrails_status()
    crisis = checks.is_crisis(query)
    decisions: list[GuardDecision] = []
    blocked = False

    def skipped(layer: str) -> None:
        decisions.append(GuardDecision(layer, SKIPPED if status[layer] else OFF))

    # 1. regex
    if status["regex"]:
        decision = record("regex", lambda: _regex_check(query))
        decisions.append(decision)
        blocked = decision.decision == BLOCKED
    else:
        decisions.append(GuardDecision("regex", OFF))

    # 2. moderation
    if blocked or not status["moderation"]:
        skipped("moderation")
    else:
        found: dict[str, bool] = {}

        def moderation_check() -> tuple[str, str]:
            try:
                flagged = this.moderate(query)
            except Exception as error:  # noqa: BLE001 - fail open
                return ERROR, type(error).__name__
            from finos.observability import record_call

            record_call("moderation", "openai", MODERATION_MODEL)  # free; listed for the call count
            if any(name.startswith(CRISIS_PREFIXES) for name in flagged):
                found["crisis"] = True
            hits = sorted(name for name in flagged if name.startswith(BLOCKING_PREFIXES))
            if hits:
                return BLOCKED, hits[0]
            return PASSED, "self_harm" if found.get("crisis") else ""

        decision = record("moderation", moderation_check)
        decisions.append(decision)
        crisis = crisis or bool(found.get("crisis"))
        blocked = decision.decision == BLOCKED

    # 3. injection classifier
    if blocked or not status["injection_classifier"]:
        skipped("injection_classifier")
    else:

        def classifier_check() -> tuple[str, str]:
            try:
                label = this.classify(query)
            except Exception as error:  # noqa: BLE001 - fail open
                return ERROR, type(error).__name__
            if label == "injection":
                return BLOCKED, "injection"
            return PASSED, "unparsed" if label == "unparsed" else ""

        decision = record("injection_classifier", classifier_check)
        decisions.append(decision)
        blocked = decision.decision == BLOCKED

    return InputVerdict(blocked=blocked and not crisis, crisis=crisis, decisions=decisions)
