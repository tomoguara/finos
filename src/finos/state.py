"""The shared state contract that flows through the support graph.

Every agent, the graph, and the evaluation layers read and write
:class:`SupportState`. Nothing else in the package defines state fields.

Alongside the contract this module holds everything else about it: the
per-field metadata, the planned fields, an initial-state builder, and an
opt-in validator. It imports only from :mod:`typing`.
"""

from typing import Literal, TypedDict, get_args

Intent = Literal["policy", "account_status", "escalation"]
"""The three intents the supervisor may route to.

Use this alias for values that have already been normalized. The
``SupportState["intent"]`` field is a plain ``str`` because its initial
value is ``""``, which is not an intent. The supervisor normalizes model
output before writing it, so the field only ever holds ``""`` or a member
of :data:`VALID_INTENTS`.
"""

VALID_INTENTS: frozenset[str] = frozenset(get_args(Intent))
"""The intent vocabulary as a runtime collection.

Exactly ``{"policy", "account_status", "escalation"}``. The empty initial
intent is deliberately not a member.
"""


class SupportState(TypedDict):
    """State passed between the supervisor and the specialist agents.

    The contract has exactly these five fields. The core build does not add
    others; in particular the Phase 2 ``history`` field is out of scope.

    Field ownership matrix:

    =================== ==================== ==================== ==========================================
    Field               Initial value        Written by           Read by
    =================== ==================== ==================== ==========================================
    ``query``           customer's question  (graph input)        all agents
    ``intent``          ``""``               ``classify_intent``  ``route_by_intent``, evaluation
    ``response``        ``""``               the specialist agent caller, evaluation, guardrails
    ``context``         ``""``               ``policy_agent`` only evaluation, cost tracking
    ``retrieved_sources`` ``[]``             ``policy_agent`` only evaluation, observability
    =================== ==================== ==================== ==========================================

    ``context`` and ``retrieved_sources`` belong to the policy agent only.
    The account and escalation agents leave them at their initial values, so
    the evaluation and observability layers can tell what a retrieval-backed
    answer actually saw.

    Ownership is a documented convention: each node returns only its own
    keys, and each agent's tests check that. The core build deliberately has
    no runtime validation layer enforcing it. :func:`validate_state` is
    opt-in: the CLI calls it, and evaluation code may, but the graph never
    does.

    Attributes:
        query: The original customer question.
        intent: One of :data:`VALID_INTENTS`, or ``""`` before the
            supervisor has classified the query.
        response: The final answer text.
        context: Retrieved policy context, or ``""`` outside the policy path.
        retrieved_sources: Filenames of the retrieved policy documents, or
            ``[]`` outside the policy path.
    """

    query: str
    intent: str
    response: str
    context: str
    retrieved_sources: list[str]


class FieldInfo(TypedDict):
    """Display metadata for one contract field.

    ``initial`` is display text, not a value. ``written_by`` and ``read_by``
    use the same words as the ownership matrix on :class:`SupportState`.
    """

    description: str
    initial: str
    written_by: str
    read_by: str


FIELD_METADATA: dict[str, FieldInfo] = {
    "query": {
        "description": "The original customer question.",
        "initial": "customer's question",
        "written_by": "(graph input)",
        "read_by": "all agents",
    },
    "intent": {
        "description": "The routed intent, or empty before classification.",
        "initial": '""',
        "written_by": "classify_intent",
        "read_by": "route_by_intent, evaluation",
    },
    "response": {
        "description": "The final answer text.",
        "initial": '""',
        "written_by": "the specialist agent",
        "read_by": "caller, evaluation, guardrails",
    },
    "context": {
        "description": "Retrieved policy context, or empty outside the policy path.",
        "initial": '""',
        "written_by": "policy_agent only",
        "read_by": "evaluation, cost tracking",
    },
    "retrieved_sources": {
        "description": "Filenames of the retrieved policy documents.",
        "initial": "[]",
        "written_by": "policy_agent only",
        "read_by": "evaluation, observability",
    },
}
"""Metadata for each :class:`SupportState` field, in contract order."""

PLANNED_FIELDS: dict[str, str] = {
    "history": "Phase 2: prior conversation turns. Not part of the core contract.",
}
"""Fields planned for later phases. They are not in the contract."""


def initial_state(query: str = "") -> SupportState:
    """Build a new state with every field at its documented initial value.

    Each call returns a new ``retrieved_sources`` list.

    Args:
        query: The customer's question.

    Returns:
        A fresh ``SupportState``.
    """
    return SupportState(
        query=query, intent="", response="", context="", retrieved_sources=[]
    )


def _quoted(values) -> str:
    return ", ".join(f'"{value}"' for value in values)


def validate_state(
    value: object,
    *,
    strict: bool = False,
    known_sources: frozenset[str] = frozenset(),
) -> list[str]:
    """Return every way ``value`` breaks the contract, or ``[]`` if none.

    The base checks require a dict with exactly the five fields, the
    contract's types, and an ``intent`` that is ``""`` or in
    :data:`VALID_INTENTS`. With ``strict``, each ``retrieved_sources`` entry
    must be in ``known_sources`` (exact membership, no path handling), and
    ``context`` and ``retrieved_sources`` must be empty unless ``intent`` is
    ``"policy"``. Strict checks only look at fields that passed the base
    checks. This function reads no files and no settings.

    Args:
        value: The candidate state, usually parsed JSON.
        strict: Whether to add the source and ownership checks.
        known_sources: The policy document names strict mode accepts.

    Returns:
        Error messages, in contract field order, then unknown fields.
    """
    if not isinstance(value, dict):
        return [f"state must be a JSON object (got {type(value).__name__})"]

    errors: list[str] = []
    passed: set[str] = set()
    for name in FIELD_METADATA:
        if name not in value:
            errors.append(f"missing field '{name}'")
            continue
        field = value[name]
        if name == "retrieved_sources":
            if not isinstance(field, list) or not all(
                isinstance(item, str) for item in field
            ):
                errors.append(f"field '{name}' must be a list of strings")
                continue
        elif not isinstance(field, str):
            errors.append(f"field '{name}' must be a string")
            continue
        if name == "intent" and field and field not in VALID_INTENTS:
            errors.append(
                f"field 'intent' must be one of: {_quoted(get_args(Intent))} "
                f'(got "{field}")'
            )
            continue
        passed.add(name)

    for name in value:
        if name not in FIELD_METADATA:
            errors.append(f"unknown field '{name}'")

    if strict:
        if "retrieved_sources" in passed:
            for source in value["retrieved_sources"]:
                if source not in known_sources:
                    errors.append(
                        f"field 'retrieved_sources' has unknown source '{source}'"
                    )
        if "intent" in passed and value["intent"] != "policy":
            for name in ("context", "retrieved_sources"):
                if name in passed and value[name]:
                    errors.append(
                        f"field '{name}' must be empty unless intent is \"policy\""
                    )
    return errors
