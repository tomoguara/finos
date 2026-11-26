"""``finos escalation``: ask the escalation agent, and show its fixed texts.

``ask`` runs the escalation agent through the guardrails: one model call,
then the official ``SUPPORT_CONTACT`` block appended by code, then the
output checks. ``--verbose`` still shows the raw model reply. Unlike ``policy ask`` and
``account ask`` it prints no trailer line, because the contact block
already ends the reply (design D5).

``contact`` prints the fixed texts from :mod:`finos.prompts` without
loading settings, importing LangChain, or calling a model.

Exit codes: 0 success; 1 a provider failure on ``ask`` (one plain-text
stderr line, also under ``--json``); 2 an empty ``--query``.
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

escalation_app = typer.Typer(
    help="Ask the escalation agent, and show the fixed support texts.",
    no_args_is_help=True,
    rich_markup_mode=None,
)


@escalation_app.command()
@shared_options
def ask(
    ctx: typer.Context,
    query: Annotated[
        str, typer.Option("--query", "-q", help="The customer's message.")
    ] = "",
) -> None:
    """Reply to a complaint or a request for a person, with the support contact."""
    if not query.strip():
        fail_usage("--query must not be empty")
    with observed(ctx, "escalation-ask"):
        try:
            from finos.agents.escalation import Escalation, escalate
            from finos.config import get_settings
            from finos.guardrails import guarded
            from finos.observability import root
            from finos.state import initial_state

            settings = get_settings()
            provider = "ollama" if settings["llm"]["use_local_ollama_model"] else "openai"
            debug(ctx, f"chat model: {provider}/{settings[provider]['model']}")
            results: list[Escalation] = []

            def answer(text: str) -> dict:
                results.append(escalate(text))
                state = initial_state(text)
                state["intent"] = "escalation"
                state["response"] = results[0].response
                return state

            with root("escalation_query", inputs={"query": query}) as run:
                state, _ = guarded(query, answer, root_run=run)
                run.set_outputs(state)
        except Exception as error:  # noqa: BLE001 - any provider failure exits 1
            fail_runtime(ctx, error, provider=True)

        if results:
            raw = results[0].raw_reply
            debug(ctx, "raw model reply:\n" + (raw if raw.strip() else "(empty)"))
            debug(ctx, f"fallback used: {'yes' if results[0].used_fallback else 'no'}")
        else:
            debug(ctx, "raw model reply: (none: the query was blocked)")
        if options(ctx).json:
            emit_json(state)
            return
        typer.echo(state["response"])


@escalation_app.command()
@shared_options
def contact(ctx: typer.Context) -> None:
    """Show the official support contact. No model is called."""
    from finos.prompts import CRISIS_SUPPORT_MESSAGE, SUPPORT_CONTACT

    if options(ctx).json:
        emit_json(
            {"support_contact": SUPPORT_CONTACT, "crisis_support": CRISIS_SUPPORT_MESSAGE}
        )
        return
    typer.echo(SUPPORT_CONTACT)
