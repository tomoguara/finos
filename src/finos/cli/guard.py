"""``finos guard``: show how the input guardrails judge a query.

``check`` runs only the input guards (regex, then moderation, then the
injection classifier) and calls no agent. It prints one line per layer,
then the verdict and whether the query is a crisis::

    regex: blocked (competitor)
    moderation: skipped
    injection_classifier: skipped
    verdict: blocked
    crisis: no

A layer enabled in ``config.toml`` but without ``OPENAI_API_KEY`` shows
``off (no OPENAI_API_KEY)``.

Exit codes: 0 whatever the verdict; 2 an empty ``--query``; 1 settings
that can't be loaded.
"""

from typing import Annotated

import typer

from finos.cli.shared import emit_json, fail_runtime, fail_usage, options, shared_options

guard_app = typer.Typer(
    help="Show how the input guardrails judge a query.",
    no_args_is_help=True,
    rich_markup_mode=None,
)

NO_KEY_REASON = "no OPENAI_API_KEY"


@guard_app.command()
@shared_options
def check(
    ctx: typer.Context,
    query: Annotated[
        str, typer.Option("--query", "-q", help="The customer's message to check.")
    ] = "",
) -> None:
    """Run the input guards on a query, without calling any agent."""
    if not query.strip():
        fail_usage("--query must not be empty")
    try:
        from finos.guardrails.input import guard_input, guardrails_status

        off_without_key = guardrails_status()["off_without_key"]
        verdict = guard_input(query)
    except Exception as error:  # noqa: BLE001 - settings or setup failures exit 1
        fail_runtime(ctx, error)

    layers = []
    for decision in verdict.decisions:
        reason = decision.reason
        if decision.decision == "off" and decision.guard_type in off_without_key:
            reason = NO_KEY_REASON
        layers.append(
            {"layer": decision.guard_type, "decision": decision.decision, "category": reason}
        )
    if options(ctx).json:
        emit_json(
            {
                "layers": layers,
                "verdict": "blocked" if verdict.blocked else "passed",
                "crisis": verdict.crisis,
            }
        )
        return
    for layer in layers:
        suffix = f" ({layer['category']})" if layer["category"] else ""
        typer.echo(f"{layer['layer']}: {layer['decision']}{suffix}")
    typer.echo(f"verdict: {'blocked' if verdict.blocked else 'passed'}")
    typer.echo(f"crisis: {'yes' if verdict.crisis else 'no'}")
