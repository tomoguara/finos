"""The supervisor: intent classification and routing.

``classify_query`` makes the one model call and returns the raw reply with
the normalized intent; ``classify_intent`` is the graph node and writes only
``intent``; ``normalize_intent`` turns any reply into a vocabulary member;
``route_by_intent`` maps the intent to a specialist node. Importing this
module loads no settings and contacts no provider.

Traced runs (design D2): the model call is the ``supervisor_llm`` chain and
normalization is the ``normalize_intent`` parser step, whose output records
the intent and whether the fallback was used.
"""

from __future__ import annotations

import re

from finos.observability import step
from finos.state import Intent, SupportState

INTENT_TO_NODE: dict[str, str] = {
    "policy": "policy_agent",
    "account_status": "account_agent",
    "escalation": "escalation_agent",
}
"""Which specialist node handles each intent. Unknown intents go to policy."""

FALLBACK_INTENT: Intent = "policy"
"""The intent used when the model's reply names no vocabulary member."""

_MEMBER = re.compile(r"\b(policy|account_status|escalation)\b")


def normalize_intent(raw: str) -> Intent:
    """Convert the model's raw reply to an intent (design D3, rule R3).

    Trim and lowercase; read ``account status`` and ``account-status`` as
    ``account_status``; then the first vocabulary member that appears as a
    whole word wins. ``\\b`` treats ``_`` as a word character, so
    ``account_status`` matches whole and ``policy_agent`` doesn't match
    ``policy``. No member at all gives ``"policy"``.
    """
    return _normalize(raw)[0]


def _normalize(raw: str) -> tuple[Intent, bool]:
    """Return ``(intent, fallback)``: the intent, and whether no member appeared."""
    text = raw.strip().lower()
    text = text.replace("account status", "account_status").replace(
        "account-status", "account_status"
    )
    match = _MEMBER.search(text)
    if match:
        return match.group(1), False  # type: ignore[return-value]
    return FALLBACK_INTENT, True


@step(
    "normalize_intent",
    "parser",
    inputs=lambda raw: {"raw": raw},
    outputs=lambda result: {"intent": result[0], "fallback": result[1]},
)
def _traced_normalize(raw: str) -> tuple[Intent, bool]:
    return _normalize(raw)


def classify_query(query: str) -> tuple[str, Intent]:
    """Classify ``query`` with one model call; return ``(raw_reply, intent)``.

    The raw reply is for diagnostics (``finos supervisor classify -v``) and
    is never written to the state. Exceptions from the model call propagate;
    only an unrecognized reply falls back to ``"policy"``.
    """
    from langchain_core.prompts import ChatPromptTemplate

    from finos.agents.policy import _message_text
    from finos.llm import get_llm
    from finos.observability import chain_config
    from finos.prompts import SUPERVISOR_SYSTEM_PROMPT

    prompt = ChatPromptTemplate.from_messages(
        [("system", "{system}"), ("human", "{question}")]
    )
    chain = (prompt | get_llm()).with_config(**chain_config("supervisor_llm"))
    message = chain.invoke({"system": SUPERVISOR_SYSTEM_PROMPT, "question": query})
    raw = _message_text(message)
    intent, _fallback = _traced_normalize(raw)
    return raw, intent


def classify_intent(state: SupportState) -> dict:
    """Supervisor: classify customer intent and set ``state['intent']``.

    Reads:  ``state['query']``
    Writes: ``state['intent']``

    The model must emit only a category name from
    :data:`~finos.state.VALID_INTENTS`. Only a normalized vocabulary member
    is written to ``intent``: raw model output is normalized first by
    :func:`normalize_intent` (casing, whitespace, quotes, labels, and
    explanations), and unrecognized output becomes ``"policy"``, so raw model
    text never reaches the state. ``tests/test_supervisor.py`` checks this
    rule; the requirement is in ``specs/support-state/spec.md``. Emotional
    framing is not escalation: "I'm upset about the overdraft fee" is a
    policy question. Distress or danger is escalation.

    Args:
        state: The shared support state.

    Returns:
        Exactly ``{"intent": ...}``.
    """
    _raw, intent = classify_query(state["query"])
    return {"intent": intent}


def route_by_intent(state: SupportState) -> str:
    """Map ``state['intent']`` to a graph node name.

    Returns ``'policy_agent'``, ``'account_agent'``, or
    ``'escalation_agent'``, falling back to ``'policy_agent'`` if the intent
    is unrecognized. Makes no model call.

    Args:
        state: The shared support state.

    Returns:
        The name of the next graph node.
    """
    return INTENT_TO_NODE.get(state.get("intent", ""), INTENT_TO_NODE[FALLBACK_INTENT])
