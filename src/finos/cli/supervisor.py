"""``finos supervisor``: run the whole system, show routing, print the wiring.

``ask`` builds the graph and runs a query through the supervisor and one
specialist. ``classify`` runs only the supervisor's model call and shows the
route. ``graph`` prints the wiring as PlantUML (default) or Mermaid without
calling a model. Top-level imports are ``typer`` and :mod:`finos.cli.shared`
only; LangGraph and the agents are imported inside command bodies.

Exit codes: 0 success; 1 a provider failure, or a specialist's environment
failure such as a missing corpus or records file (one plain-text stderr
line, also under ``--json``); 2 an empty ``--query`` or an unknown
``--format``.
"""

from typing import Annotated

import typer

from finos.cli.shared import (
    debug,
    emit_json,
    fail_runtime,
    fail_usage,
    observed,
    options,
    shared_options,
)

supervisor_app = typer.Typer(
    help="Run the whole support system, show routing, and print the graph.",
    no_args_is_help=True,
    rich_markup_mode=None,
)

QueryOption = Annotated[
    str, typer.Option("--query", "-q", help="The customer's message.")
]

FORMATS = ("plantuml", "mermaid")


def _require_query(query: str) -> None:
    if not query.strip():
        fail_usage("--query must not be empty")


def _fail(ctx: typer.Context, error: Exception):
    """Exit 1: name the provider unless the failure is a data file problem."""
    data_problem = isinstance(error, (FileNotFoundError, ValueError))
    fail_runtime(ctx, error, provider=not data_problem)


def _chat_model(ctx: typer.Context) -> None:
    from finos.config import get_settings

    settings = get_settings()
    provider = "ollama" if settings["llm"]["use_local_ollama_model"] else "openai"
    debug(ctx, f"chat model: {provider}/{settings[provider]['model']}")


@supervisor_app.command()
@shared_options
def ask(ctx: typer.Context, query: QueryOption = "") -> None:
    """Answer a query through the supervisor and one specialist.

    With --verbose, the trace line names this run's trace, where the raw
    supervisor reply is the ``normalize_intent`` run's input.
    """
    _require_query(query)
    with observed(ctx, "supervisor-ask"):
        try:
            from finos.agents.supervisor import route_by_intent
            from finos.graph import build_support_agent
            from finos.main import ask as run_graph

            app = build_support_agent()
            _chat_model(ctx)
            state = run_graph(app, query)
            trailer = None
            if state["intent"] == "account_status":
                from finos.accounts import resolve
                from finos.cli.account import account_trailer

                resolution = resolve(query)
                trailer = account_trailer(resolution.outcome, resolution.account_ids)
        except Exception as error:  # noqa: BLE001 - provider and data failures exit 1
            _fail(ctx, error)

        node = route_by_intent(state)
        debug(ctx, f"intent: {state['intent']}")
        debug(ctx, f"node: {node}")
        if state["intent"] == "policy":
            debug(ctx, "context sent to the model:\n" + (state["context"] or "(empty)"))
        elif state["intent"] == "account_status":
            debug(ctx, f"account resolution: {resolution.outcome} {', '.join(resolution.account_ids) or '(no IDs)'}")

        if options(ctx).json:
            emit_json(state)
            return
        typer.echo(state["response"])
        typer.echo()
        if state["intent"] == "policy":
            typer.echo(f"Sources: {', '.join(state['retrieved_sources']) or 'none'}")
        elif trailer:
            typer.echo(trailer)
        typer.echo(f"Intent: {state['intent']}")


@supervisor_app.command()
@shared_options
def classify(ctx: typer.Context, query: QueryOption = "") -> None:
    """Show which specialist a query routes to. Runs no specialist."""
    _require_query(query)
    with observed(ctx, "supervisor-classify"):
        try:
            from finos.agents import supervisor
            from finos.observability import root

            _chat_model(ctx)
            with root("supervisor_classify", inputs={"query": query}) as run:
                raw, intent = supervisor.classify_query(query)
                run.add_tags([f"intent:{intent}"])
        except Exception as error:  # noqa: BLE001 - provider failures exit 1
            _fail(ctx, error)

        node = supervisor.INTENT_TO_NODE[intent]
        debug(ctx, "raw supervisor reply:\n" + (raw if raw.strip() else "(empty)"))
        if options(ctx).json:
            emit_json({"intent": intent, "node": node})
            return
        typer.echo(f"{intent} -> {node}")


@supervisor_app.command()
@shared_options
def graph(
    ctx: typer.Context,
    diagram_format: Annotated[
        str,
        typer.Option(
            "--format", "-f", help="Diagram text to print: plantuml (default) or mermaid."
        ),
    ] = "plantuml",
) -> None:
    """Print the graph's wiring as diagram text. No model is called.

    --json doesn't apply: the output is always diagram text.
    """
    fmt = diagram_format.strip().lower()
    if fmt not in FORMATS:
        fail_usage(f"--format must be one of: {', '.join(FORMATS)} (got {diagram_format!r})")
    try:
        from finos.graph import build_support_agent, render_mermaid, render_plantuml

        app = build_support_agent()
    except Exception as error:  # noqa: BLE001 - e.g. a missing config.toml
        fail_runtime(ctx, error)
    typer.echo((render_plantuml if fmt == "plantuml" else render_mermaid)(app).rstrip("\n"))
