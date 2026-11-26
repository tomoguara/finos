"""The shared invocation helper, ``ask``.

The command line lives in :mod:`finos.cli`; this module stays importable
without it, for tests and any future API.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from finos.state import SupportState, initial_state

GRAPH_RUN_NAME = "support_graph"
"""The name of LangGraph's run beneath the ``support_query`` root."""


def ask(app: Any, query: str, *, config: Mapping[str, Any] | None = None) -> SupportState:
    """Invoke the support agent graph with a customer query.

    The thin wrapper used by every entry point: the CLI, the tests, and any
    future API. It starts from :func:`~finos.state.initial_state`, with
    ``intent``, ``response``, and ``context`` empty and ``retrieved_sources``
    an empty list, and returns the final state.

    The query is not validated. Exceptions raised inside the graph (a
    provider failure, a missing corpus or records file) propagate; no
    partial state is returned. Only an unrecognized supervisor reply falls
    back, to ``policy``.

    The query passes the guardrails first (a blocked query never reaches
    the graph and returns the safe fallback), and the reply passes the
    output guards. The request is traced under the ``support_query`` root, with the graph
    run named ``support_graph``; once the graph returns, the root gets the
    ``intent:<intent>`` tag. Tracing never changes the returned state.

    Recorded extension point, not added: a keyword-only ``session_id`` for
    Phase 2 history, which would be backward compatible.

    Args:
        app: The compiled graph from :func:`finos.graph.build_support_agent`.
        query: The customer's question.
        config: Optional ``tags`` and ``metadata`` for the trace's root run.

    Returns:
        The final ``SupportState``.
    """
    from finos.guardrails import guarded
    from finos.observability import root

    def run_graph(text: str) -> SupportState:
        return SupportState(
            **app.invoke(initial_state(text), config={"run_name": GRAPH_RUN_NAME})
        )

    with root("support_query", config=config, inputs={"query": query}) as run:
        result, verdict = guarded(query, run_graph, root_run=run)
        if not verdict.blocked:
            run.add_tags([f"intent:{result['intent']}"])
        run.set_outputs(result)
    return result
