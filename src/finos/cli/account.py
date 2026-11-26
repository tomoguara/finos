"""``finos account``: ask the account agent, and inspect the mock records.

``lookup`` and ``list`` read ``data/mock_accounts.json`` through
:mod:`finos.accounts` (standard library only). They never load settings or
call a model, so they need no ``.env`` and no provider. ``ask`` runs the
account agent, which calls the chat model only for a found account.

Exit codes: 0 success (every ``ask`` outcome, a found ``lookup``, ``list``);
1 a ``lookup`` that finds nothing (verdict on stdout), or a valid command
that could not complete: a missing or corrupt records file, or a provider
failure on ``ask`` (one plain-text stderr line, also under ``--json``);
2 unusable input: an empty ``--query`` or an ``--id`` that is not an
account ID.
"""

from typing import Annotated, Any

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

account_app = typer.Typer(
    help="Ask the account agent, and inspect the mock account records.",
    no_args_is_help=True,
    rich_markup_mode=None,
)

LIST_FIELDS = ("account_id", "status", "account_type", "holder_name")


def account_trailer(outcome: str, account_ids: tuple[str, ...]) -> str:
    """The `Account: …` line `account ask` and `supervisor ask` print last."""
    if outcome == "found":
        return f"Account: {account_ids[0]}"
    if outcome == "not_found":
        return f"Account: {account_ids[0]} (not found)"
    if outcome == "multiple_ids":
        return f"Account: {', '.join(account_ids)} (multiple)"
    return "Account: none"


def _money(value: Any, *, signed: bool = False) -> str:
    return f"{value:+,.2f}" if signed else f"{value:,.2f}"


def _records_path() -> str:
    from finos import config

    return str(config.MOCK_ACCOUNTS_PATH)


@account_app.command()
@shared_options
def ask(
    ctx: typer.Context,
    query: Annotated[
        str, typer.Option("--query", "-q", help="The customer's question.")
    ] = "",
) -> None:
    """Answer a question about one account, and show which account it used."""
    if not query.strip():
        fail_usage("--query must not be empty")

    from finos import accounts

    try:
        resolution = accounts.resolve(query)
    except (OSError, ValueError) as error:
        fail_runtime(ctx, error)
    debug(ctx, f"outcome: {resolution.outcome}")
    debug(ctx, f"account IDs: {', '.join(resolution.account_ids) or '(none)'}")

    with observed(ctx, "account-ask"):
        try:
            if resolution.outcome == "found":
                from finos.agents.account import render_record
                from finos.config import get_settings

                settings = get_settings()
                provider = "ollama" if settings["llm"]["use_local_ollama_model"] else "openai"
                debug(ctx, f"chat model: {provider}/{settings[provider]['model']}")
                debug(
                    ctx,
                    "record sent to the model:\n" + render_record(resolution.record, for_model=True),
                )
            from finos.agents.account import ask_account

            state = ask_account(query)
        except Exception as error:  # noqa: BLE001 - any provider failure exits 1
            fail_runtime(ctx, error, provider=resolution.outcome == "found")

        if options(ctx).json:
            emit_json(state)
            return
        typer.echo(state["response"])
        typer.echo()
        typer.echo(account_trailer(resolution.outcome, resolution.account_ids))


@account_app.command()
@shared_options
def lookup(
    ctx: typer.Context,
    account_id: Annotated[
        str,
        typer.Option("--id", "-i", help="The account ID, for example ACC-12345."),
    ] = "",
) -> None:
    """Show one account record. No model is called and no settings are loaded."""
    from finos import accounts

    normalized = accounts.normalize_account_id(account_id)
    if normalized is None:
        fail_usage(
            f"--id must be an account ID: ACC- followed by five digits, "
            f"for example ACC-12345 (got {account_id!r})"
        )
    debug(ctx, f"records file: {_records_path()}")
    try:
        record = accounts.lookup_account(normalized)
    except (OSError, ValueError) as error:
        fail_runtime(ctx, error)

    if record is None:
        if options(ctx).json:
            emit_json({"account_id": normalized, "found": False})
        else:
            typer.echo(f"No account found: {normalized}")
        raise typer.Exit(1)

    if options(ctx).json:
        emit_json(record)
        return
    status = record["status"]
    if record.get("freeze_reason"):
        status = f"{status} ({record['freeze_reason']})"
    waived = "waived" if record["monthly_fee_waived"] else "not waived"
    rows = [
        ("Account", record["account_id"]),
        ("Holder", record["holder_name"]),
        ("Type", record["account_type"]),
        ("Balance", _money(record["balance"])),
        ("Status", status),
        ("Monthly fee", f"{_money(record['monthly_fee'])} ({waived})"),
        ("Overdraft protection", "yes" if record["overdraft_protection"] else "no"),
        ("SSN last 4", record["ssn_last4"]),
    ]
    width = max(len(label) for label, _ in rows) + 1
    for label, value in rows:
        typer.echo(f"{label + ':':<{width}} {value}")
    transactions = record["recent_transactions"]
    typer.echo(f"Transactions ({len(transactions)}):")
    if not transactions:
        typer.echo("  (none)")
    amounts = [_money(t["amount"], signed=True) for t in transactions]
    amount_width = max((len(a) for a in amounts), default=0)
    for transaction, amount in zip(transactions, amounts):
        typer.echo(
            f"  {transaction['date']}  {amount:>{amount_width}}  {transaction['description']}"
        )


@account_app.command(name="list")
@shared_options
def list_accounts(ctx: typer.Context) -> None:
    """List the account IDs with status, type, and holder. No model is called."""
    from finos import accounts

    debug(ctx, f"records file: {_records_path()}")
    try:
        records = accounts.load_accounts()
    except (OSError, ValueError) as error:
        fail_runtime(ctx, error)

    rows = [
        {field: records[account_id].get(field, "") for field in LIST_FIELDS}
        for account_id in sorted(records)
    ]
    if options(ctx).json:
        emit_json(rows)
        return
    widths = {
        field: max((len(str(row[field])) for row in rows), default=0) for field in LIST_FIELDS
    }
    for row in rows:
        typer.echo(
            "  ".join(f"{str(row[field]):<{widths[field]}}" for field in LIST_FIELDS).rstrip()
        )
