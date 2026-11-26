"""The policy agent: the RAG path over the SecureBank policy documents.

Retrieval lives in :mod:`finos.vectorstore` and the prompt in
:mod:`finos.prompts`. Importing this module loads no settings, opens no
index, and contacts no provider; the index is opened on the first call.

Traced runs (design D2): retrieval is the ``policy_retrieval`` retriever step
and the model call is the ``policy_llm`` chain. :func:`ask_policy` opens the
``policy_query`` root.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from finos.state import SupportState, initial_state


def policy_agent(state: SupportState) -> dict:
    """RAG specialist: retrieve banking policy docs and generate a grounded answer.

    Reads:  ``state['query']``
    Writes: ``state['response']``, ``state['context']``,
    ``state['retrieved_sources']``

    This is the only node that writes ``context`` and ``retrieved_sources``,
    so the evaluation and observability layers can see what the agent saw.

    ``retrieved_sources`` holds bare filenames such as ``account_fees.md``,
    never a full or relative path as document loaders often report, because
    ``finos state validate --strict`` rejects anything else. The tests in
    ``tests/test_policy.py`` check this rule; the requirement is in
    ``specs/support-state/spec.md``.

    The top ``[policy] top_k`` chunks are formatted into ``context``, which
    fills the system prompt; the question alone is the human message. The
    shared chat model is called exactly once, even when nothing is
    retrieved. ``retrieved_sources`` lists distinct sources in rank order,
    most relevant first.

    Args:
        state: The shared support state.

    Returns:
        Exactly ``response``, ``context``, and ``retrieved_sources``. Never
        ``query`` or ``intent``.
    """
    from langchain_core.prompts import ChatPromptTemplate

    from finos.llm import get_llm
    from finos.observability import chain_config
    from finos.prompts import POLICY_SYSTEM_PROMPT
    from finos.vectorstore import distinct_sources, format_docs, traced_search

    query = state["query"]
    hits = traced_search(query)
    context = format_docs(hits)

    prompt = ChatPromptTemplate.from_messages(
        [("system", POLICY_SYSTEM_PROMPT), ("human", "{question}")]
    )
    chain = (prompt | get_llm()).with_config(**chain_config("policy_llm"))
    message = chain.invoke({"context": context, "question": query})

    return {
        "response": _message_text(message),
        "context": context,
        "retrieved_sources": distinct_sources(hits),
    }


def ask_policy(query: str, *, config: Mapping[str, Any] | None = None) -> SupportState:
    """Run the policy agent without the graph and return the complete state.

    Builds :func:`~finos.state.initial_state` for ``query``, sets ``intent``
    to ``"policy"`` (no supervisor runs here to do it), and merges in the
    agent's three keys. The run is traced under the ``policy_query`` root;
    ``config`` may hold extra ``tags`` and ``metadata`` for it.
    """
    from finos.guardrails import guarded
    from finos.observability import root

    def answer(text: str) -> SupportState:
        state = initial_state(text)
        state["intent"] = "policy"
        return SupportState(**{**state, **policy_agent(state)})

    with root("policy_query", config=config, inputs={"query": query}) as run:
        result, _verdict = guarded(query, answer, root_run=run)
        run.set_outputs(result)
    return result


def _message_text(message: Any) -> str:
    """Return a chat message's text, whether its content is a string or parts."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict) and part.get("type") == "text":
            parts.append(str(part.get("text", "")))
    return "".join(parts)
