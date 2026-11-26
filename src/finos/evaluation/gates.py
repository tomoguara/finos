"""The quality gates: run the gating datasets and apply ``[eval.gates]`` (design D7).

Blocking:

- ``routing_accuracy``: the in-scope mean on ``routing`` (known limitations excluded);
- ``crisis_sentence``: the *minimum* on ``escalation``, so one miss fails;
- ``faithfulness``: the mean over ``policy`` and ``account`` together;
- ``mrr``: the mean reciprocal rank on ``retrieval``;
- ``guardrail_false_positive``: the *minimum* ``near_miss_passed`` on
  ``guardrails``, so one blocked near-miss fails;
- ``no_ssn``: the *minimum* over every gating dataset that scores replies,
  so one leak anywhere fails;
- and no errors anywhere: a gate never passes on partial data.

Reported, not blocking: ``correctness`` (policy and account) and ``empathy``
(escalation).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

BLOCKING: dict[str, tuple[tuple[str, ...], str, str]] = {
    "routing_accuracy": (("routing",), "routing_accuracy", "in_scope_mean"),
    "crisis_sentence": (("escalation",), "crisis_sentence", "minimum"),
    "faithfulness": (("policy", "account"), "faithfulness", "mean"),
    "mrr": (("retrieval",), "reciprocal_rank", "mean"),
    "guardrail_false_positive": (("guardrails",), "near_miss_passed", "minimum"),
    "no_ssn": (("policy", "account", "escalation", "guardrails"), "no_ssn", "minimum"),
}
"""Gate name -> (datasets, evaluator key, statistic)."""

REPORT_ONLY: dict[str, tuple[tuple[str, ...], str, str]] = {
    "correctness": (("policy", "account"), "correctness", "mean"),
    "empathy": (("escalation",), "empathy", "mean"),
}


@dataclass(frozen=True)
class Failure:
    dataset: str
    example_id: str
    score: float | None
    comment: str


@dataclass(frozen=True)
class Check:
    name: str
    score: float | None
    threshold: float | None
    blocking: bool
    failures: tuple[Failure, ...] = ()

    @property
    def passed(self) -> bool:
        if not self.blocking:
            return True
        return self.score is not None and self.threshold is not None and self.score >= self.threshold


@dataclass
class GateReport:
    checks: list[Check]
    errors: list[Failure] = field(default_factory=list)
    provider: str = ""
    experiments: dict[str, str | None] = field(default_factory=dict)
    """Dataset -> experiment URL (``None`` when local)."""

    @property
    def passed(self) -> bool:
        return not self.errors and all(check.passed for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "provider": self.provider,
            "checks": [
                {
                    "metric": c.name,
                    "score": c.score,
                    "threshold": c.threshold,
                    "blocking": c.blocking,
                    "passed": c.passed,
                    "failures": [f.__dict__ for f in c.failures],
                }
                for c in self.checks
            ],
            "errors": [f.__dict__ for f in self.errors],
            "experiments": self.experiments,
        }


def _check(
    name: str,
    spec: tuple[tuple[str, ...], str, str],
    results: Mapping[str, Any],
    threshold: float | None,
    blocking: bool,
) -> Check:
    names, key, statistic = spec
    rows = [
        (dataset, score)
        for dataset in names
        if dataset in results
        for score in results[dataset].scores
        if score.key == key and score.score is not None
    ]
    if statistic == "in_scope_mean":
        rows = [(d, s) for d, s in rows if s.in_scope]
    values = [s.score for _, s in rows]
    if not values:
        value = None
    elif statistic == "minimum":
        value = min(values)
    else:
        value = sum(values) / len(values)
    bar = threshold if threshold is not None else 1.0
    failures = tuple(
        Failure(d, s.example_id, s.score, s.comment) for d, s in rows if s.score < bar
    )
    return Check(name, value, threshold, blocking, failures if blocking or threshold else ())


def evaluate_gate(
    results: Mapping[str, Any], thresholds: Mapping[str, float], provider: str = ""
) -> GateReport:
    """Apply the thresholds to experiment results (one per gating dataset)."""
    checks = [
        _check(name, spec, results, float(thresholds[name]), True) for name, spec in BLOCKING.items()
    ]
    checks += [_check(name, spec, results, None, False) for name, spec in REPORT_ONLY.items()]
    errors = [
        Failure(dataset, s.example_id, None, f"{s.key}: {s.comment}")
        for dataset, result in results.items()
        for s in result.scores
        if s.error
    ]
    return GateReport(
        checks,
        errors,
        provider,
        {dataset: result.url for dataset, result in results.items()},
    )


def gate(
    *,
    repetitions: int | None = None,
    local: bool | None = None,
    datasets: Sequence[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> GateReport:
    """Run the gating datasets with the configured provider and apply ``[eval.gates]``.

    ``progress`` receives one line before each dataset (its position and
    size) and one after it (how long it took), so a slow run is visibly
    moving rather than looking stuck.
    """
    import time

    from finos import config
    from finos.evaluation.datasets import GATING_DATASETS, load
    from finos.evaluation.runner import run_experiment

    names = list(datasets or GATING_DATASETS)
    reps = int(repetitions if repetitions is not None else config.get_settings()["eval"]["repetitions"])
    results = {}
    started = time.perf_counter()
    for index, name in enumerate(names, start=1):
        if progress:
            runs = len(load(name).examples) * reps
            progress(f"gate: {index}/{len(names)} {name} ({runs} runs)")
        dataset_started = time.perf_counter()
        results[name] = run_experiment(name, repetitions=repetitions, local=local)
        if progress:
            progress(
                f"gate: {index}/{len(names)} {name} done in "
                f"{_duration(time.perf_counter() - dataset_started)} "
                f"(total {_duration(time.perf_counter() - started)})"
            )
    provider = next(iter(results.values())).provider if results else ""
    return evaluate_gate(results, config.get_settings()["eval"]["gates"], provider)


def _duration(seconds: float) -> str:
    """``42s``, ``3m 05s``, or ``1h 02m``."""
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"
