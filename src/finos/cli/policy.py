"""``finos policy``: ask the policy agent, inspect retrieval, and manage the index.

Every command here loads settings, because it needs models. Top-level
imports are ``typer`` and :mod:`finos.cli.shared` only; the agent, the
index, and LangChain are imported inside each command body, so ``--help``
and importing the CLI stay light.

Exit codes: 0 success; 1 the command was valid but a model or embedding
provider could not be reached or used (one plain-text line on stderr, no
traceback, also under ``--json``); 2 unusable input such as an empty
``--query`` or ``--top-k`` below 1.
"""

from typing import Annotated, NoReturn

import typer

from finos.cli.shared import (
    debug,
    emit_json,
    fail_runtime,
    fail_usage,
    observed,
    one_line,
    options,
    shared_options,
)

policy_app = typer.Typer(
    help="Ask the policy agent, inspect retrieval, and manage the policy index.",
    no_args_is_help=True,
    rich_markup_mode=None,
)

QueryOption = Annotated[
    str, typer.Option("--query", "-q", help="The customer's question.")
]

PREVIEW_LENGTH = 200


def _require_query(query: str) -> str:
    if not query.strip():
        fail_usage("--query must not be empty")
    return query


def _fail_provider(ctx: typer.Context, error: Exception) -> NoReturn:
    """Report a provider failure as one plain-text stderr line and exit 1."""
    fail_runtime(ctx, error, provider=True)


def _ensure_index(ctx: typer.Context, *, rebuild: bool = False):
    from finos.vectorstore import ensure_index

    info = ensure_index(rebuild=rebuild)
    action = "rebuilt" if info.status == "built" else "reused"
    debug(
        ctx,
        f"index {action}: {info.chunks} chunks from {info.documents} documents "
        f"in collection {info.collection} ({info.provider}/{info.model})",
    )
    return info


@policy_app.command()
@shared_options
def ask(ctx: typer.Context, query: QueryOption = "") -> None:
    """Answer a question from the policy documents, with its sources."""
    _require_query(query)
    with observed(ctx, "policy-ask"):
        try:
            from finos.agents.policy import ask_policy
            from finos.config import get_settings

            settings = get_settings()
            provider = "ollama" if settings["llm"]["use_local_ollama_model"] else "openai"
            debug(ctx, f"chat model: {provider}/{settings[provider]['model']}")
            _ensure_index(ctx)
            state = ask_policy(query)
        except Exception as error:  # noqa: BLE001 - any provider failure exits 1
            _fail_provider(ctx, error)

        debug(ctx, "context sent to the model:\n" + (state["context"] or "(empty)"))
        if options(ctx).json:
            emit_json(state)
            return
        typer.echo(state["response"])
        typer.echo()
        sources = ", ".join(state["retrieved_sources"]) or "none"
        typer.echo(f"Sources: {sources}")


@policy_app.command()
@shared_options
def search(
    ctx: typer.Context,
    query: QueryOption = "",
    top_k: Annotated[
        int | None,
        typer.Option(
            "--top-k", "-k", help="How many chunks to return (default: [policy] top_k)."
        ),
    ] = None,
) -> None:
    """Show the ranked chunks retrieval returns, without generating an answer."""
    _require_query(query)
    if top_k is not None and top_k < 1:
        fail_usage("--top-k must be at least 1")
    with observed(ctx, "policy-search"):
        try:
            from finos import vectorstore
            from finos.observability import root

            _ensure_index(ctx)
            with root("policy_search", inputs={"query": query}):
                hits = vectorstore.traced_search(query, k=top_k)
        except Exception as error:  # noqa: BLE001 - any provider failure exits 1
            _fail_provider(ctx, error)

        if options(ctx).json:
            emit_json([hit.as_dict() for hit in hits])
            return
        for hit in hits:
            typer.echo(
                f"[{hit.rank}] Score: {hit.score:.2f}  Source: {hit.source} "
                f"(chunk {hit.chunk_index})"
            )
            preview = one_line(hit.text)
            if len(preview) > PREVIEW_LENGTH:
                preview = preview[:PREVIEW_LENGTH] + "..."
            typer.echo(f"    {preview}")


@policy_app.command()
@shared_options
def ingest(
    ctx: typer.Context,
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="Rebuild the index even if it is up to date.")
    ] = False,
) -> None:
    """Build the policy index if it is missing or stale, or report it is current."""
    try:
        info = _ensure_index(ctx, rebuild=rebuild)
    except Exception as error:  # noqa: BLE001 - any provider failure exits 1
        _fail_provider(ctx, error)

    if options(ctx).json:
        emit_json(info.as_dict())
        return
    label = "Built index" if info.status == "built" else "Index up to date"
    typer.echo(
        f"{label}: {info.chunks} chunks from {info.documents} documents "
        f"({info.provider}/{info.model})"
    )
