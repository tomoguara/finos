"""``finos cost``: what queries cost, from the audit log (Hardening 4).

``report`` reads ``[cost] audit_log_path`` and prints, per intent and per
provider, the query count, total and mean cost, the guards' share, mean
tokens, p50/p95 latency, and the unpriced and blocked counts, under a header
naming the price date and today's budget status::

    prices as of 2026-11-20; budget: ok: $0.000482 of $1.000000 today (0%, 2026-11-20 UTC)
    queries: 3 (all entries but eval, live-test)
    intent           provider  queries  total cost   mean cost  guards  in tok  out tok  p50 ms  p95 ms  unpriced  blocked
    policy           openai          2   $0.000482   $0.000241     11%    1120      125    1950    2310         0        0

It calls no model and needs no key. Exit codes: 0 with or without records;
2 an invalid date; 1 settings that can't be loaded.
"""

import datetime
from typing import Annotated

import typer

from finos.cli.shared import (
    emit_json,
    fail_runtime,
    fail_usage,
    options,
    shared_options,
)

cost_app = typer.Typer(
    help="Report what queries cost, from the audit log.",
    no_args_is_help=True,
    rich_markup_mode=None,
)

COLUMNS = (
    ("intent", 15, "<"),
    ("provider", 8, "<"),
    ("queries", 7, ">"),
    ("total cost", 10, ">"),
    ("mean cost", 10, ">"),
    ("guards", 6, ">"),
    ("in tok", 6, ">"),
    ("out tok", 7, ">"),
    ("p50 ms", 6, ">"),
    ("p95 ms", 6, ">"),
    ("unpriced", 8, ">"),
    ("blocked", 7, ">"),
)


def _date(value: str | None, option: str) -> datetime.date | None:
    if value is None:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        fail_usage(f"{option} must be an ISO date such as 2026-11-20 (got {value!r})")


def _cells(row: dict) -> list[str]:
    from finos.cost import format_usd

    def number(value: float | None) -> str:
        return "-" if value is None else f"{value:.0f}"

    share = row["guard_share"]
    return [
        row["intent"],
        row["label"],
        str(row["queries"]),
        format_usd(row["total_cost_usd"]),
        format_usd(row["mean_cost_usd"]) if row["mean_cost_usd"] is not None else "-",
        "-" if share is None else f"{share:.0%}",
        number(row["mean_input_tokens"]),
        number(row["mean_output_tokens"]),
        number(row["latency_ms"]["p50"]),
        number(row["latency_ms"]["p95"]),
        str(row["unpriced"]),
        str(row["blocked"]),
    ]


def _line(cells: list[str]) -> str:
    return "  ".join(
        f"{cell:{align}{width}}" for cell, (_name, width, align) in zip(cells, COLUMNS, strict=True)
    ).rstrip()


@cost_app.command()
@shared_options
def report(
    ctx: typer.Context,
    since: Annotated[
        str | None, typer.Option("--since", help="First UTC day to include (YYYY-MM-DD).")
    ] = None,
    until: Annotated[
        str | None, typer.Option("--until", help="Last UTC day to include (YYYY-MM-DD).")
    ] = None,
    entry: Annotated[
        list[str] | None,
        typer.Option(
            "--entry",
            help="Only records from this entry point (repeatable). "
            "Default: every entry but eval and live-test.",
        ),
    ] = None,
) -> None:
    """Summarize cost and latency per intent and provider."""
    first = _date(since, "--since")
    last = _date(until, "--until")
    try:
        from finos import cost

        records, skipped = cost.read_records()
        rows = cost.summarize(records, since=first, until=last, entries=entry or None)
        as_of = cost.prices_as_of()
        budget = cost.daily_status()
    except Exception as error:
        fail_runtime(ctx, error)

    if skipped:
        typer.echo(f"cost: skipped {skipped} unreadable line(s) in the audit log", err=True)
    scope = (
        "entries: " + ", ".join(entry)
        if entry
        else "all entries but " + ", ".join(cost.DEFAULT_EXCLUDED_ENTRIES)
    )
    span = ""
    if first or last:
        span = f"; {first.isoformat() if first else 'start'} to {last.isoformat() if last else 'now'} UTC"
    total = sum(row["queries"] for row in rows)
    if options(ctx).json:
        emit_json(
            {
                "prices_as_of": as_of,
                "budget": {
                    "status": budget.status,
                    "total_usd": budget.total_usd,
                    "budget_usd": budget.budget_usd,
                    "share": budget.share,
                    "day": budget.day.isoformat(),
                },
                "since": first.isoformat() if first else None,
                "until": last.isoformat() if last else None,
                "entries": list(entry) if entry else None,
                "excluded_entries": [] if entry else list(cost.DEFAULT_EXCLUDED_ENTRIES),
                "queries": total,
                "skipped_lines": skipped,
                "rows": rows,
            }
        )
        return
    typer.echo(f"prices as of {as_of}; {budget.line()}")
    typer.echo(f"queries: {total} ({scope}{span})")
    if not rows:
        return
    typer.echo(_line([name for name, _width, _align in COLUMNS]))
    for row in rows:
        typer.echo(_line(_cells(row)))
