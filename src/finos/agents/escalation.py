"""The escalation agent: the empathetic handoff path.

A hybrid of a model call and a fixed text: the shared chat model writes 2-4
empathetic sentences (``ESCALATION_SYSTEM_PROMPT``), then code appends the
official ``SUPPORT_CONTACT`` block. Importing this module loads no settings
and contacts no provider.

Traced runs (design D2): the model call is the ``escalation_llm`` chain and
assembly is the ``escalation_assembly`` parser step, whose output records
whether the fallback message was used. :func:`ask_escalation` opens the
``escalation_query`` root.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from finos.observability import step
from finos.state import SupportState, initial_state


@dataclass(frozen=True)
class Escalation:
    """One escalation reply, with what the model actually returned."""

    response: str
    """The assembled reply: body, a blank line, then ``SUPPORT_CONTACT``."""
    raw_reply: str
    """The model's text before stripping and assembly."""
    used_fallback: bool
    """Whether ``ESCALATION_FALLBACK_MESSAGE`` replaced an empty reply."""


def escalation_agent(state: SupportState) -> dict:
    """Escalation specialist: generate an empathetic handoff response.

    Reads:  ``state['query']``
    Writes: ``state['response']``

    The response must NOT contain specific policy claims or dollar amounts.
    It acknowledges the customer's frustration, validates it, and offers a
    clear next step with support contact information. It never claims a
    transfer, case, or callback, and never promises an outcome or a timeline.
    These rules are enforced by the prompt only; ``tests/helpers.py`` measures
    them, and the guardrails layer (§9.3) is where code-level checks belong.

    The model is called once. Its reply is stripped (or replaced by
    ``ESCALATION_FALLBACK_MESSAGE`` if empty), then joined with a blank line
    to ``SUPPORT_CONTACT``, which is appended even if the model wrote its own
    contact line.

    Args:
        state: The shared support state.

    Returns:
        Exactly ``{"response": ...}``.
    """
    return {"response": escalate(state["query"]).response}


def escalate(query: str) -> Escalation:
    """Call the model once for ``query`` and assemble the reply.

    The CLI uses this directly so ``--verbose`` can show the raw reply and
    whether the fallback was used, without a second model call.
    """
    from langchain_core.prompts import ChatPromptTemplate

    from finos.agents.policy import _message_text
    from finos.llm import get_llm
    from finos.observability import chain_config
    from finos.prompts import ESCALATION_SYSTEM_PROMPT

    prompt = ChatPromptTemplate.from_messages(
        [("system", "{system}"), ("human", "{question}")]
    )
    chain = (prompt | get_llm()).with_config(**chain_config("escalation_llm"))
    message = chain.invoke({"system": ESCALATION_SYSTEM_PROMPT, "question": query})
    raw_reply = _message_text(message)
    response, used_fallback = _traced_assemble(raw_reply)
    return Escalation(response=response, raw_reply=raw_reply, used_fallback=used_fallback)


def assemble_response(raw_reply: str) -> tuple[str, bool]:
    """Return the final response for a model reply, and whether it fell back."""
    from finos.prompts import ESCALATION_FALLBACK_MESSAGE, SUPPORT_CONTACT

    body = raw_reply.strip()
    used_fallback = not body
    if used_fallback:
        body = ESCALATION_FALLBACK_MESSAGE
    return f"{body}\n\n{SUPPORT_CONTACT}", used_fallback


@step(
    "escalation_assembly",
    "parser",
    inputs=lambda raw_reply: {"raw": raw_reply},
    outputs=lambda result: {"used_fallback": result[1]},
)
def _traced_assemble(raw_reply: str) -> tuple[str, bool]:
    return assemble_response(raw_reply)


def ask_escalation(query: str, *, config: Mapping[str, Any] | None = None) -> SupportState:
    """Run the escalation agent without the graph and return the complete state.

    Builds :func:`~finos.state.initial_state` for ``query``, sets ``intent``
    to ``"escalation"`` (no supervisor runs here to do it), and merges in the
    agent's ``response``. The query is not validated; the CLI rejects empty
    queries. The run is traced under the ``escalation_query`` root;
    ``config`` may hold extra ``tags`` and ``metadata`` for it.
    """
    from finos.guardrails import guarded
    from finos.observability import root

    def answer(text: str) -> SupportState:
        state = initial_state(text)
        state["intent"] = "escalation"
        return SupportState(**{**state, **escalation_agent(state)})

    with root("escalation_query", config=config, inputs={"query": query}) as run:
        result, _verdict = guarded(query, answer, root_run=run)
        run.set_outputs(result)
    return result
