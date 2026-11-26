"""``finos eval``: push the evaluation datasets, run experiments, and apply the gates.

``push`` uploads the repository datasets to LangSmith with their versions.
``run`` evaluates one dataset under one variant, locally or as a LangSmith
experiment. ``gate`` runs the gating datasets and applies ``[eval.gates]``.
``compare`` prints two saved ``run --json`` results before and after (the
before/after method); it calls no model.
Top-level imports are ``typer`` and :mod:`finos.cli.shared` only; the
evaluation package, LangChain, and ``langsmith`` load inside the commands.

Exit codes: 0 success (``run`` exits 0 whatever its scores; ``gate`` exits 0
when it passes); 1 a gate that failed, or a valid command that could not
complete: no LangSmith key for ``push``, LangSmith unreachable, a dataset
version mismatch, a missing dataset file, or a provider failure (one
plain-text stderr line, also under ``--json``); 2 unusable input: an
unknown dataset, a malformed ``--set``, ``--repetitions`` below 1, or a
``compare`` file that is missing, unreadable, or of another dataset.
"""

from typing import Annotated, Any, Optional

import typer

from finos.cli.shared import (
    emit_json,
    fail_runtime,
    fail_usage,
    observed,
    options,
    shared_options,
)

eval_app = typer.Typer(
    help="Push the evaluation datasets, run experiments, and apply the quality gates.",
    no_args_is_help=True,
    rich_markup_mode=None,
)

SetOption = Annotated[
    Optional[list[str]],
    typer.Option(
        "--set",
        help="Override one setting for this run, as section.key=value (repeatable).",
    ),
]
RepetitionsOption = Annotated[
    Optional[int],
    typer.Option("--repetitions", "-r", help="Runs per example (default: [eval] repetitions)."),
]
LocalOption = Annotated[
    bool,
    typer.Option("--local", help="Run without LangSmith (the default when no key is set)."),
]


def _known_datasets() -> list[str]:
    from finos.evaluation.datasets import DATASETS

    return list(DATASETS)


def _require_dataset(name: str, *, allow_empty: bool = False) -> str | None:
    if not name and allow_empty:
        return None
    if name not in _known_datasets():
        fail_usage(f"--dataset must be one of: {', '.join(_known_datasets())} (got {name!r})")
    return name


def _require_repetitions(repetitions: int | None) -> None:
    if repetitions is not None and repetitions < 1:
        fail_usage("--repetitions must be at least 1")


def _parse_overrides(values: list[str] | None) -> list[str]:
    from finos.evaluation.runner import OverrideError, parse_override

    for value in values or []:
        try:
            parse_override(value)
        except OverrideError as error:
            fail_usage(str(error))
    return list(values or [])


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f} ms"


@eval_app.command()
@shared_options
def push(
    ctx: typer.Context,
    dataset: Annotated[
        str, typer.Option("--dataset", "-d", help="One dataset to push (default: all).")
    ] = "",
) -> None:
    """Upload the evaluation datasets to LangSmith, with their versions."""
    chosen = _require_dataset(dataset, allow_empty=True)
    try:
        from finos.evaluation.runner import push as push_dataset

        names = [chosen] if chosen else _known_datasets()
        results = [push_dataset(name) for name in names]
    except Exception as error:
        fail_runtime(ctx, error)

    if options(ctx).json:
        emit_json([r.__dict__ for r in results])
        return
    for r in results:
        state = "uploaded" if r.uploaded else "up to date"
        typer.echo(f"{r.dataset}: {r.examples} examples, version {r.version}, {state}")


@eval_app.command()
@shared_options
def run(
    ctx: typer.Context,
    dataset: Annotated[str, typer.Option("--dataset", "-d", help="The dataset to evaluate.")] = "",
    overrides: SetOption = None,
    repetitions: RepetitionsOption = None,
    local: LocalOption = False,
) -> None:
    """Evaluate one dataset under one variant and report its metrics.

    `--dataset judge_calibration` checks the judge against hand-scored items.
    """
    _require_dataset(dataset)
    _require_repetitions(repetitions)
    parsed = _parse_overrides(overrides)
    with observed(ctx, "eval"):
        if dataset == "judge_calibration":
            _run_calibration(ctx, parsed)
            return
        try:
            from finos.evaluation.runner import OverrideError, run_experiment

            result = run_experiment(
                dataset, overrides=parsed, repetitions=repetitions, local=True if local else None
            )
        except OverrideError as error:
            fail_usage(str(error))
        except Exception as error:
            fail_runtime(ctx, error)

        if options(ctx).json:
            emit_json(result.as_dict())
            return
        _print_result(result)


def _run_calibration(ctx: typer.Context, overrides: list[str]) -> None:
    try:
        from finos.evaluation.judge import CALIBRATION_TOLERANCE, calibrate
        from finos.evaluation.runner import OverrideError, variant

        with variant(overrides):
            result = calibrate()
    except OverrideError as error:
        fail_usage(str(error))
    except Exception as error:
        fail_runtime(ctx, error, provider=True)

    if options(ctx).json:
        emit_json(
            {
                "passed": result.passed,
                "tolerance": CALIBRATION_TOLERANCE,
                "items": [{**item.__dict__, "ok": item.ok} for item in result.items],
            }
        )
        return
    for item in result.items:
        mark = "ok" if item.ok else "FAIL"
        typer.echo(
            f"{mark:<4} {item.id} ({item.metric}): label {item.label:.2f}, "
            f"judge {_fmt(item.score)} - {item.reason}"
        )
    typer.echo(
        f"calibration: {'passed' if result.passed else 'FAILED'} "
        f"(tolerance {CALIBRATION_TOLERANCE})"
    )


def _print_result(result: Any) -> None:
    where = "local" if result.local else "LangSmith"
    typer.echo(f"experiment: {result.experiment} ({where})")
    typer.echo(
        f"dataset: {result.dataset} (version {result.dataset_version}), "
        f"{result.outputs} outputs, {result.repetitions} repetitions"
    )
    typer.echo(f"model: {result.provider}/{result.chat_model}")
    if result.judged:
        note = "  (self-judged: the judge is the chat model)" if result.self_judged else ""
        typer.echo(f"judge: {result.judge_provider}/{result.judge_model}{note}")
    metrics = result.metrics
    width = max((len(key) for key in metrics), default=0)
    for key, metric in metrics.items():
        text = f"{key:<{width}}  {_fmt(metric.mean)}"
        if metric.in_scope_mean != metric.mean:
            text += f"  (in scope {_fmt(metric.in_scope_mean)}, all rows {_fmt(metric.mean)})"
        text += f"  [{metric.scored} scored, {metric.errors} errors]"
        typer.echo(text)
    typer.echo(f"errors: {len(result.errors)}")
    for error in result.errors:
        typer.echo(f"  - {error.example_id} #{error.repetition} {error.key}: {error.comment}")
    typer.echo(f"latency: p50 {_ms(result.p50_ms)}, p95 {_ms(result.p95_ms)}")
    typer.echo(_cost_line(result.cost_summary()))
    if result.judged:
        typer.echo(_judge_line(result))
    if result.url:
        typer.echo(f"url: {result.url}")


def _usd(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.6f}"


def _cost_line(summary: dict) -> str:
    """``cost: mean $0.000241, p50 ..., p95 ..., total ... per output (guards 11%; ...)``."""
    usd = summary["usd"]
    share = summary["guard_share"]
    guards = "-" if share is None else f"{share:.0%}"
    return (
        f"cost: mean {_usd(usd['mean'])}, p50 {_usd(usd['p50'])}, p95 {_usd(usd['p95'])}, "
        f"total {_usd(usd['total'])} per output (guards {guards}; "
        f"{summary['unknown_outputs']} unknown; prices as of {summary['prices_as_of']})"
    )


def _judge_line(result: Any) -> str:
    """``judge: 10 calls, 3630+170 tokens, $0.000647`` (unknown counts read ``n/a``)."""
    if result.judge_input_tokens is None or result.judge_output_tokens is None:
        tokens = "n/a tokens"
    else:
        tokens = f"{result.judge_input_tokens}+{result.judge_output_tokens} tokens"
    return f"judge: {result.judge_calls} calls, {tokens}, {_usd(result.judge_cost_usd)}"


@eval_app.command()
@shared_options
def compare(
    ctx: typer.Context,
    before: Annotated[str, typer.Argument(help="A saved `finos eval run --json` result: the baseline.")],
    after: Annotated[str, typer.Argument(help="A saved `finos eval run --json` result: the variant.")],
) -> None:
    """Print two saved results of one dataset before and after: metrics, gates, cost, latency."""
    first = _load_result(before)
    second = _load_result(after)
    if (first["dataset"], first["dataset_version"]) != (second["dataset"], second["dataset_version"]):
        fail_usage(
            f"{before} holds {first['dataset']} version {first['dataset_version']}, "
            f"{after} holds {second['dataset']} version {second['dataset_version']}: "
            "compare results of the same dataset version"
        )
    try:
        from finos.config import get_settings

        thresholds = dict(get_settings()["eval"]["gates"])
    except Exception as error:
        fail_runtime(ctx, error)
    comparison = _compare(first, second, thresholds)
    if options(ctx).json:
        emit_json(comparison)
        return
    _print_comparison(comparison)


def _load_result(path: str) -> dict:
    import json
    from pathlib import Path

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        fail_usage(f"cannot read {path}: {type(error).__name__}")
    required = ("dataset", "dataset_version", "metrics", "latency_ms")
    if not isinstance(data, dict) or any(key not in data for key in required):
        fail_usage(f"{path} is not a `finos eval run --json` result")
    return data


def _change(before: float | None, after: float | None) -> float | None:
    return None if before is None or after is None else after - before


def _relative(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or before == 0:
        return None
    return (after - before) / before


def _compare(first: dict, second: dict, thresholds: dict) -> dict:
    from finos.evaluation.gates import BLOCKING

    keys = list(dict.fromkeys([*first["metrics"], *second["metrics"]]))
    metrics = []
    for key in keys:
        a = (first["metrics"].get(key) or {}).get("mean")
        b = (second["metrics"].get(key) or {}).get("mean")
        metrics.append({"key": key, "before": a, "after": b, "change": _change(a, b)})
    gates = []
    for name, (datasets, key, statistic) in BLOCKING.items():
        if first["dataset"] not in datasets or name not in thresholds:
            continue
        a = (first["metrics"].get(key) or {}).get(statistic)
        b = (second["metrics"].get(key) or {}).get(statistic)
        threshold = float(thresholds[name])
        gates.append(
            {
                "name": name,
                "threshold": threshold,
                "before": a,
                "after": b,
                "before_passed": a is not None and a >= threshold,
                "after_passed": b is not None and b >= threshold,
            }
        )

    def cost_of(result: dict, stat: str) -> float | None:
        return ((result.get("cost") or {}).get("usd") or {}).get(stat)

    cost = {
        stat: {
            "before": cost_of(first, stat),
            "after": cost_of(second, stat),
            "change": _relative(cost_of(first, stat), cost_of(second, stat)),
        }
        for stat in ("mean", "p50", "p95", "total")
    }
    latency = {
        stat: {
            "before": first["latency_ms"].get(stat),
            "after": second["latency_ms"].get(stat),
            "change": _relative(first["latency_ms"].get(stat), second["latency_ms"].get(stat)),
        }
        for stat in ("p50", "p95")
    }
    return {
        "dataset": first["dataset"],
        "dataset_version": first["dataset_version"],
        "before": {"variant": first.get("variant"), "experiment": first.get("experiment")},
        "after": {"variant": second.get("variant"), "experiment": second.get("experiment")},
        "metrics": metrics,
        "gates": gates,
        "errors": {"before": len(first.get("errors", [])), "after": len(second.get("errors", []))},
        "cost_usd_per_output": cost,
        "latency_ms": latency,
    }


def _signed(value: float | None, *, percent: bool = False) -> str:
    if value is None:
        return "-"
    return f"{value:+.0%}" if percent else f"{value:+.3f}"


def _print_comparison(comparison: dict) -> None:
    typer.echo(f"dataset: {comparison['dataset']} (version {comparison['dataset_version']})")
    typer.echo(
        f"before: {comparison['before']['variant']}  after: {comparison['after']['variant']}"
    )
    rows = comparison["metrics"]
    width = max([len("metric")] + [len(row["key"]) for row in rows])
    typer.echo(f"{'metric':<{width}}  {'before':>7}  {'after':>7}  {'change':>7}")
    for row in rows:
        typer.echo(
            f"{row['key']:<{width}}  {_fmt(row['before']):>7}  {_fmt(row['after']):>7}  "
            f"{_signed(row['change']):>7}"
        )
    def verdict(ok: bool) -> str:
        return "pass" if ok else "FAIL"

    for gate in comparison["gates"]:
        typer.echo(
            f"gate {gate['name']} >= {gate['threshold']}: "
            f"{verdict(gate['before_passed'])} -> {verdict(gate['after_passed'])}"
        )
    errors = comparison["errors"]
    typer.echo(f"errors: {errors['before']} -> {errors['after']}")
    cost = comparison["cost_usd_per_output"]
    for stat in ("mean", "p95"):
        item = cost[stat]
        typer.echo(
            f"cost per output ({stat}): {_usd(item['before'])} -> {_usd(item['after'])} "
            f"({_signed(item['change'], percent=True)})"
        )
    for stat in ("p50", "p95"):
        item = comparison["latency_ms"][stat]
        typer.echo(
            f"latency {stat}: {_ms(item['before'])} -> {_ms(item['after'])} "
            f"({_signed(item['change'], percent=True)})"
        )


@eval_app.command()
@shared_options
def gate(
    ctx: typer.Context,
    repetitions: RepetitionsOption = None,
    local: LocalOption = False,
) -> None:
    """Run the gating datasets and apply the [eval.gates] thresholds.

    Progress (each dataset, its size, and how long it took) goes to stderr.
    """
    _require_repetitions(repetitions)
    with observed(ctx, "eval"):
        try:
            from finos.evaluation.gates import gate as run_gate

            report = run_gate(
                repetitions=repetitions,
                local=True if local else None,
                progress=lambda line: typer.echo(line, err=True),
            )
        except Exception as error:
            fail_runtime(ctx, error)

        if options(ctx).json:
            emit_json(report.as_dict())
        else:
            _print_gate(report)
    if not report.passed:
        raise typer.Exit(1)


def _print_gate(report: Any) -> None:
    width = max(len(check.name) for check in report.checks)
    for check in report.checks:
        if check.blocking:
            verdict = "pass" if check.passed else "FAIL"
            typer.echo(f"{check.name:<{width}}  {_fmt(check.score)}  >= {check.threshold}  {verdict}")
            if not check.passed:
                for failure in check.failures:
                    typer.echo(
                        f"  - {failure.dataset}/{failure.example_id}: "
                        f"{_fmt(failure.score)} {failure.comment}"
                    )
        else:
            typer.echo(f"{check.name:<{width}}  {_fmt(check.score)}  (report only)")
    typer.echo(f"errors: {len(report.errors)}")
    for failure in report.errors:
        typer.echo(f"  - {failure.dataset}/{failure.example_id}: {failure.comment}")
    for dataset, url in report.experiments.items():
        if url:
            typer.echo(f"{dataset}: {url}")
    typer.echo(f"gate: {'passed' if report.passed else 'FAILED'} ({report.provider})")
