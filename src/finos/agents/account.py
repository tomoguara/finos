"""The account agent: the mock-database lookup path.

Extraction and lookup live in :mod:`finos.accounts`; the prompt and the
fixed messages live in :mod:`finos.prompts`. Only a found account reaches
the chat model, so the other three outcomes need no settings, no provider,
and no key.

Traced runs (design D2): resolution is the ``account_resolution`` tool step,
which records only the outcome and the account IDs, never the record; the
model call is the ``account_llm`` chain. :func:`ask_account` opens the
``account_query`` root.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from finos.observability import step
from finos.state import SupportState, initial_state


def account_agent(state: SupportState) -> dict:
    """Account specialist: look up account data and format a response.

    Reads:  ``state['query']``
    Writes: ``state['response']``

    Does NOT write ``state['context']`` or ``state['retrieved_sources']``:
    there is no retrieval on this path, and those fields belong to the
    policy agent.

    The query resolves to one outcome (:func:`finos.accounts.resolve`):

    - ``no_id``: ``ACCOUNT_NO_ID_MESSAGE``, no model call
    - ``multiple_ids``: ``ACCOUNT_MULTIPLE_IDS_MESSAGE``, no model call
    - ``not_found``: ``ACCOUNT_NOT_FOUND_MESSAGE``, no model call
    - ``found``: one call to the shared chat model, with the full record as
      JSON in the system prompt and the question as the human message. Both
      are passed as values at invoke time, so braces in them are safe.

    Args:
        state: The shared support state.

    Returns:
        Exactly ``{"response": ...}``.
    """
    from finos.prompts import (
        ACCOUNT_MULTIPLE_IDS_MESSAGE,
        ACCOUNT_NO_ID_MESSAGE,
        ACCOUNT_NOT_FOUND_MESSAGE,
    )

    query = state["query"]
    resolution = _resolve(query)
    if resolution.outcome == "no_id":
        return {"response": ACCOUNT_NO_ID_MESSAGE}
    if resolution.outcome == "multiple_ids":
        return {"response": ACCOUNT_MULTIPLE_IDS_MESSAGE}
    if resolution.outcome == "not_found":
        return {"response": ACCOUNT_NOT_FOUND_MESSAGE}
    return {"response": _generate(resolution.record, query)}


@step(
    "account_resolution",
    "tool",
    inputs=lambda query: {"query": query},
    outputs=lambda resolution: {
        "outcome": resolution.outcome,
        "account_ids": list(resolution.account_ids),
    },
)
def _resolve(query: str):
    """Resolve the query; the trace sees the outcome and IDs, not the record."""
    from finos import accounts

    return accounts.resolve(query)


MODEL_HIDDEN_FIELDS: tuple[str, ...] = ("ssn_last4",)
"""Record fields the model never sees (Hardening 3, data minimization).

A model can't leak what it was never given; the prompt's SSN rule stays as
defense in depth.
"""


def render_record(record: dict, *, for_model: bool = False) -> str:
    """Render a record as JSON; ``for_model`` drops :data:`MODEL_HIDDEN_FIELDS`.

    ``account ask -v`` shows exactly what the model receives
    (``for_model=True``); ``account lookup`` shows the full local record.
    """
    if for_model:
        record = {key: value for key, value in record.items() if key not in MODEL_HIDDEN_FIELDS}
    return json.dumps(record, indent=2, ensure_ascii=False)


def _generate(record: dict, query: str) -> str:
    from langchain_core.prompts import ChatPromptTemplate

    from finos.agents.policy import _message_text
    from finos.llm import get_llm
    from finos.observability import chain_config
    from finos.prompts import ACCOUNT_SYSTEM_PROMPT

    prompt = ChatPromptTemplate.from_messages(
        [("system", ACCOUNT_SYSTEM_PROMPT), ("human", "{question}")]
    )
    chain = (prompt | get_llm()).with_config(**chain_config("account_llm"))
    message = chain.invoke(
        {"account": render_record(record, for_model=True), "question": query}
    )
    return _message_text(message)


def ask_account(query: str, *, config: Mapping[str, Any] | None = None) -> SupportState:
    """Run the account agent without the graph and return the complete state.

    Builds :func:`~finos.state.initial_state` for ``query``, sets ``intent``
    to ``"account_status"`` (no supervisor runs here to do it), and merges in
    the agent's ``response``. ``context`` and ``retrieved_sources`` stay
    empty, so the result passes strict validation for every outcome. The run
    is traced under the ``account_query`` root; ``config`` may hold extra
    ``tags`` and ``metadata`` for it.
    """
    from finos.guardrails import guarded
    from finos.observability import root

    def answer(text: str) -> SupportState:
        state = initial_state(text)
        state["intent"] = "account_status"
        return SupportState(**{**state, **account_agent(state)})

    with root("account_query", config=config, inputs={"query": query}) as run:
        result, _verdict = guarded(query, answer, root_run=run)
        run.set_outputs(result)
    return result
