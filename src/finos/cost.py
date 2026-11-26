"""What a query costs: prices, per-call and per-query cost (Hardening 4).

A call is priced from the tokens it reported and ``[cost.prices]``:

- a call to the local (Ollama) provider costs $0, whatever its model;
- moderation costs $0 (it is free);
- an OpenAI model with no price entry, or a chat call with no reported
  usage, costs ``None`` ("unpriced"), never 0, and so does its query.

Importing this module imports nothing beyond the standard library and
``finos.config``: the light ``finos cost`` command uses it.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "GUARD_ROLES",
    "FinishedQuery",
    "QueryCost",
    "append_record",
    "audit_log_path",
    "capture",
    "cost_line",
    "daily_status",
    "finish",
    "format_usd",
    "price_call",
    "price_for",
    "query_cost",
    "read_records",
    "summarize",
]

LOCAL_PROVIDER = "ollama"
"""Calls to this provider cost nothing in API money."""

FREE_ROLES: frozenset[str] = frozenset({"moderation"})
"""Calls in these roles are free, whatever reports usage."""

GUARD_ROLES: frozenset[str] = frozenset({"moderation", "injection_classifier"})
"""Calls in these roles form a query's guard subtotal."""

STORED_DECIMALS = 8
"""Costs are stored (audit log, metadata) to 8 decimals: one classifier call is ~$0.000026."""

PRINTED_DECIMALS = 6
"""Costs are printed to 6 decimals."""

_SNAPSHOT = re.compile(r"-\d{4}(?:-\d{2}-\d{2})?$")
"""A dated model snapshot suffix, such as ``-2024-07-18``."""


def _settings() -> Mapping[str, Any]:
    from finos.config import get_settings

    return get_settings()["cost"]


def prices() -> Mapping[str, Mapping[str, float]]:
    """The configured price table, ``{model: {input_per_1m, ...}}``."""
    return _settings().get("prices", {}) or {}


def prices_as_of() -> str:
    """The configured ``[cost] prices_as_of`` date, as ``YYYY-MM-DD``."""
    return str(_settings()["prices_as_of"])


def price_for(model: str | None, table: Mapping[str, Mapping[str, float]]) -> Mapping[str, float] | None:
    """The price entry for ``model``, or ``None``.

    An exact name wins; otherwise a dated snapshot (``gpt-4o-mini-2024-07-18``)
    uses its base model's entry (``gpt-4o-mini``). Nothing else is guessed.
    """
    if not model:
        return None
    if model in table:
        return table[model]
    base = _SNAPSHOT.sub("", model)
    if base != model and base in table:
        return table[base]
    return None


_warned_lock = threading.Lock()
_warned: set[str] = set()


def _warn_unpriced(model: str) -> None:
    """One stderr line per unpriced model per process."""
    with _warned_lock:
        if model in _warned:
            return
        _warned.add(model)
    print(
        f'cost: no price for {model}; add [cost.prices."{model}"] to config.toml',
        file=sys.stderr,
    )


def price_call(call: Any, table: Mapping[str, Mapping[str, float]] | None = None) -> float | None:
    """The USD cost of one call, or ``None`` when it cannot be known.

    ``call`` needs ``provider``, ``model``, ``role``, ``input_tokens``,
    ``output_tokens``, and ``cached_input_tokens`` attributes
    (:class:`finos.observability.ModelCall`).
    """
    if call.provider == LOCAL_PROVIDER or call.role in FREE_ROLES:
        return 0.0
    table = prices() if table is None else table
    entry = price_for(call.model, table)
    if entry is None:
        if call.provider == "openai":
            _warn_unpriced(call.model or "an unnamed model")
        return None
    if call.input_tokens is None or call.output_tokens is None:
        return None
    cached = min(int(call.cached_input_tokens or 0), int(call.input_tokens))
    input_price = float(entry["input_per_1m"])
    cached_price = float(entry.get("cached_input_per_1m", input_price))
    output_price = float(entry.get("output_per_1m", 0.0))
    usd = (
        (call.input_tokens - cached) * input_price
        + cached * cached_price
        + call.output_tokens * output_price
    ) / 1_000_000
    return round(usd, STORED_DECIMALS)


def _sum(values: Iterable[float | None]) -> float | None:
    total = 0.0
    for value in values:
        if value is None:
            return None
        total += value
    return round(total, STORED_DECIMALS)


@dataclass
class PricedCall:
    """One call and its cost, as the audit record lists it."""

    role: str
    provider: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    estimated: bool = False
    latency_ms: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "estimated": self.estimated,
        }


@dataclass
class QueryCost:
    """What one query (one root run) cost."""

    calls: list[PricedCall] = field(default_factory=list)

    @property
    def cost_usd(self) -> float | None:
        """The sum over every call, or ``None`` if any call is unknown."""
        return _sum(c.cost_usd for c in self.calls)

    @property
    def guard_cost_usd(self) -> float | None:
        """The sum over the guard calls (moderation, the injection classifier)."""
        return _sum(c.cost_usd for c in self.calls if c.role in GUARD_ROLES)

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens or 0 for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens or 0 for c in self.calls)

    @property
    def unpriced(self) -> list[str]:
        """The models whose calls have no known cost, sorted."""
        return sorted({c.model or "unknown" for c in self.calls if c.cost_usd is None})

    @property
    def priced(self) -> bool:
        return self.cost_usd is not None


def query_cost(calls: Iterable[Any], table: Mapping[str, Mapping[str, float]] | None = None) -> QueryCost:
    """Price every call of one query."""
    table = prices() if table is None else table
    return QueryCost(
        [
            PricedCall(
                role=c.role,
                provider=c.provider,
                model=c.model,
                input_tokens=c.input_tokens,
                output_tokens=c.output_tokens,
                cost_usd=price_call(c, table),
                estimated=bool(getattr(c, "estimated", False)),
            )
            for c in calls
        ]
    )


def format_usd(value: float | None) -> str:
    """``$0.000241``, or ``unpriced`` for ``None``."""
    return "unpriced" if value is None else f"${value:.{PRINTED_DECIMALS}f}"


# --- Finishing a query: the audit record, the alert, the metadata (design D3-D7) ---

ALERT_PER_QUERY = "per_query"
INFO = "INFO"
WARNING = "WARNING"
ERROR_LEVEL = "ERROR"


@dataclass
class FinishedQuery:
    """One finished root: its cost and its audit record."""

    root: str
    cost: QueryCost
    record: dict[str, Any]


_captures: ContextVar[list[FinishedQuery] | None] = ContextVar("finos_cost_capture", default=None)


@contextmanager
def capture() -> Iterator[list[FinishedQuery]]:
    """Collect every root that finishes inside the body (an evaluation output's cost)."""
    collected: list[FinishedQuery] = []
    token = _captures.set(collected)
    try:
        yield collected
    finally:
        _captures.reset(token)


def _intent(handle: Any) -> str | None:
    outputs = getattr(handle, "_outputs", None) or {}
    intent = outputs.get("intent") if isinstance(outputs, Mapping) else None
    if intent:
        return str(intent)
    for tag in getattr(handle, "_tags", []):
        if tag.startswith("intent:"):
            return tag.split(":", 1)[1]
    return None


def _guard(request: Any) -> dict[str, Any]:
    from finos.guardrails.decisions import strongest

    decisions = list(getattr(request, "guard_decisions", []))
    outcome = strongest(decisions, blocked=bool(getattr(request, "blocked", False)))
    if outcome is None:
        outcome = "passed" if decisions else None
    return {
        "outcome": outcome,
        "layers": [
            {"type": d.guard_type, "decision": d.decision, "reason": d.reason} for d in decisions
        ],
    }


def _length(mapping: Any, key: str) -> int | None:
    value = mapping.get(key) if isinstance(mapping, Mapping) else None
    return len(value) if isinstance(value, str) else None


def build_record(
    request: Any,
    handle: Any,
    query: QueryCost,
    *,
    latency_ms: float,
    entry: str,
    inputs: Mapping[str, Any] | None,
    error: str | None,
    config: Mapping[str, Any],
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """The audit record of one root (cost-tracking spec): no query or reply text."""
    now = now or datetime.datetime.now(datetime.UTC)
    return {
        "ts": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "level": ERROR_LEVEL if error else INFO,
        "root": getattr(request, "name", None),
        "trace_id": getattr(handle, "trace_id", None),
        "entry": entry,
        "provider": config.get("provider"),
        "chat_model": config.get("chat_model"),
        "intent": _intent(handle),
        "guard": _guard(request),
        "crisis": bool(getattr(request, "crisis", False)),
        "calls": [c.as_dict() for c in query.calls],
        "input_tokens": query.input_tokens,
        "output_tokens": query.output_tokens,
        "cost_usd": query.cost_usd,
        "guard_cost_usd": query.guard_cost_usd,
        "unpriced": query.unpriced,
        "latency_ms": round(latency_ms, 1),
        "config": dict(config),
        "query_chars": _length(inputs, "query"),
        "response_chars": _length(getattr(handle, "_outputs", None), "response"),
        "alerts": [],
        "error": error,
    }


def _alert(record: dict[str, Any], handle: Any, threshold: float) -> None:
    """The per-query alert: a stderr line, a WARNING record, and the ``cost:alert`` tag."""
    value = record["cost_usd"]
    if value is None or value <= threshold:
        return
    record["alerts"].append(ALERT_PER_QUERY)
    if record["level"] == INFO:
        record["level"] = WARNING
    try:
        handle.add_tags(["cost:alert"])
    except Exception:  # noqa: BLE001
        pass
    print(
        f"cost: query {format_usd(value)} above the {format_usd(float(threshold))} alert",
        file=sys.stderr,
    )


def _add_metadata(handle: Any, query: QueryCost) -> None:
    run = getattr(handle, "_run", None)
    if run is None:
        return
    try:
        run.add_metadata(
            {
                "cost_usd": query.cost_usd,
                "guard_cost_usd": query.guard_cost_usd,
                "input_tokens": query.input_tokens,
                "output_tokens": query.output_tokens,
            }
        )
    except Exception:  # noqa: BLE001 - tracing never fails a request
        pass


def finish(
    request: Any,
    handle: Any,
    *,
    latency_ms: float,
    observation: Any = None,
    inputs: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> FinishedQuery:
    """Price a finished root, alert, add its cost to the trace, and write its record."""
    from finos.observability import DEFAULT_ENTRY, root_metadata

    settings = _settings()
    query = query_cost(request.calls)
    try:
        config = root_metadata()
    except Exception:  # noqa: BLE001
        config = {}
    record = build_record(
        request,
        handle,
        query,
        latency_ms=latency_ms,
        entry=getattr(observation, "entry", None) or DEFAULT_ENTRY,
        inputs=inputs,
        error=error,
        config=config,
    )
    _alert(record, handle, float(settings["per_query_alert_usd"]))
    _add_metadata(handle, query)
    if settings["audit_log"]:
        append_record(record)
    finished = FinishedQuery(request.name, query, record)
    if observation is not None:
        observation.requests.append(finished)
    collected = _captures.get()
    if collected is not None:
        collected.append(finished)
    return finished


# --- The audit log (design D6) ----------------------------------------------------

_write_lock = threading.Lock()
_write_failed = False


def audit_log_path() -> Path:
    """``[cost] audit_log_path``, relative paths taken from the repository root."""
    from finos.config import PROJECT_ROOT

    path = Path(str(_settings()["audit_log_path"])).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def append_record(record: Mapping[str, Any], path: Path | None = None) -> bool:
    """Append one record as one line; ``False`` (and one stderr line per process) on failure."""
    global _write_failed
    try:
        target = path or audit_log_path()
        line = json.dumps(record, separators=(",", ":"), sort_keys=True, default=str) + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(line)
        return True
    except Exception as error:  # noqa: BLE001 - fail open (C6)
        with _write_lock:
            first = not _write_failed
            _write_failed = True
        if first:
            print(f"audit: not written ({type(error).__name__})", file=sys.stderr)
        return False


def read_records(path: Path | None = None) -> tuple[list[dict[str, Any]], int]:
    """Every parseable record in the log, and the number of lines skipped."""
    target = path or audit_log_path()
    records: list[dict[str, Any]] = []
    skipped = 0
    try:
        handle = target.open(encoding="utf-8")
    except FileNotFoundError:
        return records, 0
    with handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if isinstance(record, dict):
                records.append(record)
            else:
                skipped += 1
    return records, skipped


def record_date(record: Mapping[str, Any]) -> datetime.date | None:
    """The UTC date of a record's ``ts``, or ``None``."""
    try:
        return datetime.date.fromisoformat(str(record["ts"])[:10])
    except (KeyError, ValueError):
        return None


# --- The daily budget (design D7) ----------------------------------------------------

BUDGET_OK = "ok"
BUDGET_WARNING = "warning"
BUDGET_ALERT = "alert"
BUDGET_WARNING_SHARE = 0.8


@dataclass(frozen=True)
class BudgetStatus:
    status: str
    total_usd: float
    budget_usd: float
    day: datetime.date

    @property
    def share(self) -> float:
        return self.total_usd / self.budget_usd if self.budget_usd else 0.0

    def line(self) -> str:
        label = {BUDGET_OK: "ok", BUDGET_WARNING: "warning", BUDGET_ALERT: "alert"}[self.status]
        return (
            f"budget: {label}: {format_usd(self.total_usd)} of {format_usd(self.budget_usd)} "
            f"today ({self.share:.0%}, {self.day.isoformat()} UTC)"
        )


def budget_status(total: float, budget: float, day: datetime.date) -> BudgetStatus:
    share = total / budget if budget else 0.0
    if share > 1.0:
        status = BUDGET_ALERT
    elif share >= BUDGET_WARNING_SHARE:
        status = BUDGET_WARNING
    else:
        status = BUDGET_OK
    return BudgetStatus(status, round(total, STORED_DECIMALS), budget, day)


def daily_status(today: datetime.date | None = None, path: Path | None = None) -> BudgetStatus:
    """Today's (UTC) known audited cost against ``[cost] daily_budget_usd``."""
    day = today or datetime.datetime.now(datetime.UTC).date()
    records, _skipped = read_records(path)
    total = sum(
        float(r["cost_usd"])
        for r in records
        if record_date(r) == day and isinstance(r.get("cost_usd"), (int, float))
    )
    return budget_status(total, float(_settings()["daily_budget_usd"]), day)


# --- The --verbose cost line (design D9) ---------------------------------------------


def cost_line(finished: Iterable[FinishedQuery], as_of: str | None = None) -> str | None:
    """``cost: $0.000241 (1123+124 tokens, 5 calls; guards $0.000026; prices as of ...)``.

    Sums every root the command opened (one today). ``None`` when nothing was
    recorded. An unknown cost reads ``cost: unpriced (<model> has no price; ...)``.
    """
    queries = [f.cost for f in finished]
    if not queries:
        return None
    calls = [c for q in queries for c in q.calls]
    combined = QueryCost(calls)
    as_of = as_of or prices_as_of()
    noun = "call" if len(calls) == 1 else "calls"
    tokens = f"{combined.input_tokens}+{combined.output_tokens} tokens, {len(calls)} {noun}"
    date = f"prices as of {as_of}"
    if combined.cost_usd is None:
        names = ", ".join(combined.unpriced)
        verb = "has" if len(combined.unpriced) == 1 else "have"
        return f"cost: unpriced ({names} {verb} no price; {tokens}; {date})"
    return (
        f"cost: {format_usd(combined.cost_usd)} ({tokens}; "
        f"guards {format_usd(combined.guard_cost_usd)}; {date})"
    )


# --- The report (cost-cli spec; design D9) -------------------------------------------

DEFAULT_EXCLUDED_ENTRIES: tuple[str, ...] = ("eval", "live-test")
"""Entries ``finos cost report`` leaves out unless ``--entry`` names them."""


def _filtered(
    records: Iterable[Mapping[str, Any]],
    *,
    since: datetime.date | None,
    until: datetime.date | None,
    entries: Iterable[str] | None,
) -> list[Mapping[str, Any]]:
    wanted = set(entries) if entries else None
    kept = []
    for record in records:
        day = record_date(record)
        if since and (day is None or day < since):
            continue
        if until and (day is None or day > until):
            continue
        entry = record.get("entry")
        if wanted is not None:
            if entry not in wanted:
                continue
        elif entry in DEFAULT_EXCLUDED_ENTRIES:
            continue
        kept.append(record)
    return kept


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def summarize(
    records: Iterable[Mapping[str, Any]],
    *,
    since: datetime.date | None = None,
    until: datetime.date | None = None,
    entries: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Per ``(intent, provider)`` rows: counts, cost, guard share, tokens, and latency.

    A record with an unknown (``null``) cost is counted as unpriced and left
    out of the cost totals and means, but still counted in tokens and latency.
    """
    from finos.stats import mean, percentile

    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for record in _filtered(records, since=since, until=until, entries=entries):
        key = (str(record.get("intent") or "none"), str(record.get("provider") or "unknown"))
        groups.setdefault(key, []).append(record)
    rows = []
    for (intent, provider), group in sorted(groups.items()):
        costs = [c for c in (_number(r.get("cost_usd")) for r in group) if c is not None]
        guard = [
            _number(r.get("guard_cost_usd")) or 0.0
            for r in group
            if _number(r.get("cost_usd")) is not None
        ]
        latencies = [x for x in (_number(r.get("latency_ms")) for r in group) if x is not None]
        total = round(sum(costs), STORED_DECIMALS)
        rows.append(
            {
                "intent": intent,
                "provider": provider,
                "label": "local" if provider == LOCAL_PROVIDER else provider,
                "queries": len(group),
                "total_cost_usd": total,
                "mean_cost_usd": round(mean(costs), STORED_DECIMALS) if costs else None,
                "guard_share": (sum(guard) / total) if total > 0 else None,
                "mean_input_tokens": mean([_number(r.get("input_tokens")) or 0.0 for r in group]),
                "mean_output_tokens": mean([_number(r.get("output_tokens")) or 0.0 for r in group]),
                "latency_ms": {"p50": percentile(latencies, 0.50), "p95": percentile(latencies, 0.95)},
                "unpriced": len(group) - len(costs),
                "blocked": sum(1 for r in group if (r.get("guard") or {}).get("outcome") == "blocked"),
            }
        )
    return rows
