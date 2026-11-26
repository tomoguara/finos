"""The LangGraph wiring for the support agent, and its diagram text.

Importing this module loads nothing: LangGraph and the agents are imported
inside :func:`build_support_agent`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

SUPERVISOR_NODE = "classify_intent"
"""The entry node: the supervisor."""

SPECIALIST_NODES: tuple[str, ...] = ("policy_agent", "account_agent", "escalation_agent")
"""The specialist nodes, in the fixed order diagrams use."""


def build_support_agent() -> CompiledStateGraph:
    """Build and compile the support graph.

    Loads settings first, before anything that could make a traced call:
    ``finos.config.get_settings()`` is what applies the ``[langsmith]``
    tracing settings to the environment, and the ``langsmith`` client
    caches its environment lookups on first use. The same rule is why
    :func:`finos.llm.get_llm` loads settings before constructing a model.

    The graph registers ``classify_intent`` as the entry point, routes
    through ``route_by_intent`` to one of ``policy_agent``,
    ``account_agent``, or ``escalation_agent`` (an explicit path map), and
    each specialist terminates the graph. Nodes return only the keys they
    own, and LangGraph merges them into the state.

    Building makes no model call, opens no vector index, and makes no
    network request: nodes reach the model and the index only when invoked.
    Nothing is cached; each call returns a new compiled graph.

    Returns:
        The compiled LangGraph app. Every other handle has its own home:
        the retriever in :mod:`finos.vectorstore`, the model in
        :func:`finos.llm.get_llm`, the prompts in :mod:`finos.prompts`.
    """
    from finos.config import get_settings

    get_settings()

    # langgraph 0.2's checkpoint module triggers a langchain-core pending
    # deprecation warning on import. It isn't ours to fix, and it would print
    # on every `finos supervisor` command. Both `langchain` and
    # `langchain_core` re-enable their warnings when first imported, so
    # import them before suppressing.
    import langchain  # noqa: F401
    from langchain_core._api import suppress_langchain_deprecation_warning

    with suppress_langchain_deprecation_warning():
        from langgraph.graph import END, StateGraph

    from finos.agents import (
        account_agent,
        classify_intent,
        escalation_agent,
        policy_agent,
        route_by_intent,
    )
    from finos.state import SupportState

    graph = StateGraph(SupportState)
    graph.add_node(SUPERVISOR_NODE, classify_intent)
    graph.add_node("policy_agent", policy_agent)
    graph.add_node("account_agent", account_agent)
    graph.add_node("escalation_agent", escalation_agent)
    graph.set_entry_point(SUPERVISOR_NODE)
    graph.add_conditional_edges(
        SUPERVISOR_NODE, route_by_intent, {node: node for node in SPECIALIST_NODES}
    )
    for node in SPECIALIST_NODES:
        graph.add_edge(node, END)
    return graph.compile()


def render_plantuml(app: Any) -> str:
    """Render a compiled support graph as PlantUML state-diagram text.

    A start transition to the supervisor, a dashed transition from the
    supervisor to each specialist labeled with the intent that selects it,
    and a transition from each specialist to the end. The edges come from
    ``app.get_graph()``; the labels come from the same intent-to-node table
    ``route_by_intent`` uses, because LangGraph's edge data holds the path
    key, not the intent. The output order is fixed, so it is deterministic.
    """
    from finos.agents.supervisor import INTENT_TO_NODE

    drawable = app.get_graph()
    edges = {(edge.source, edge.target, bool(edge.conditional)) for edge in drawable.edges}
    node_to_intent = {node: intent for intent, node in INTENT_TO_NODE.items()}
    start, end = "__start__", "__end__"

    lines = ["@startuml"]
    if (start, SUPERVISOR_NODE, False) in edges:
        lines.append(f"[*] --> {SUPERVISOR_NODE}")
    for node in SPECIALIST_NODES:
        if (SUPERVISOR_NODE, node, True) in edges:
            lines.append(f"{SUPERVISOR_NODE} -[dashed]-> {node} : {node_to_intent[node]}")
    for node in SPECIALIST_NODES:
        if (node, end, False) in edges:
            lines.append(f"{node} --> [*]")
    lines.append("@enduml")
    return "\n".join(lines)


def render_mermaid(app: Any) -> str:
    """Render a compiled support graph as Mermaid text (LangGraph's own renderer)."""
    return app.get_graph().draw_mermaid()
