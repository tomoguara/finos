"""Run experiments: variants, the local runner, and the LangSmith runner.

Variants (design D6) apply ``section.key=value`` overrides to a temporary
copy of ``config.toml``, in this process only, with a policy index of their
own under ``data/chroma-eval/``. The committed ``config.toml`` and the
shipped ``data/chroma/`` index are never touched.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import tomllib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from finos import config
from finos.stats import percentile

VARIANTS_DIR: Path = config.PROJECT_ROOT / "data" / "chroma-eval"
"""Parent of each variant's own policy index. Git-ignored and safe to delete."""

BASELINE = "baseline"


class OverrideError(ValueError):
    """An override is malformed or names a setting the configuration doesn't have."""


# --- Variants -------------------------------------------------------------------


@dataclass(frozen=True)
class Override:
    section: str
    key: str
    value: Any
    text: str
    """The override as given, for names and metadata."""


def parse_override(text: str) -> Override:
    """Parse ``section.key=value``; the value is read as TOML, else as a string.

    ``policy.chunk_size=100`` sets an integer, ``ollama.model=qwen3:8b`` a
    string, and ``eval.gates.mrr=0.9`` a key in a nested table.
    """
    name, sep, raw = text.partition("=")
    name, raw = name.strip(), raw.strip()
    if not sep or "." not in name or not raw:
        raise OverrideError(f"overrides take the form section.key=value (got {text!r})")
    section, _, key = name.rpartition(".")
    if not section or not key:
        raise OverrideError(f"overrides take the form section.key=value (got {text!r})")
    try:
        value = tomllib.loads(f"v = {raw}")["v"]
    except tomllib.TOMLDecodeError:
        value = raw
    return Override(section, key, value, f"{name}={raw}")


def variant_name(overrides: Sequence[Override]) -> str:
    """``baseline``, or the overrides joined with commas."""
    return ",".join(o.text for o in overrides) or BASELINE


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(str(value))


def _apply(text: str, override: Override) -> str:
    """Replace one ``key = value`` line inside ``[section]`` of a TOML text."""
    lines = text.splitlines(keepends=True)
    header = re.compile(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$")
    assignment = re.compile(rf"^(\s*{re.escape(override.key)}\s*=\s*)([^#\n]*?)(\s*(#.*)?)$")
    current = None
    section_header: int | None = None
    for index, line in enumerate(lines):
        match = header.match(line.rstrip("\n"))
        if match:
            current = match.group(1).strip()
            if current == override.section:
                section_header = index
            continue
        if current == override.section:
            found = assignment.match(line.rstrip("\n"))
            if found:
                newline = "\n" if line.endswith("\n") else ""
                lines[index] = (
                    found.group(1) + _toml_value(override.value) + found.group(3) + newline
                )
                return "".join(lines)
    if section_header is not None and (override.section, override.key) in config.OPTIONAL_SETTINGS:
        # An optional setting the file leaves unset: add it under its header.
        lines.insert(section_header + 1, f"{override.key} = {_toml_value(override.value)}\n")
        return "".join(lines)
    raise OverrideError(
        f"unknown setting [{override.section}] {override.key} in {config.CONFIG_PATH}"
    )


def _clear_caches() -> None:
    from finos import llm, vectorstore

    for function in (
        config.get_settings,
        llm.get_llm,
        llm.get_judge_llm,
        llm.get_classifier_llm,
        llm.get_embeddings,
        vectorstore.get_store,
    ):
        clear = getattr(function, "cache_clear", None)
        if clear is not None:
            clear()


@dataclass(frozen=True)
class Variant:
    name: str
    overrides: tuple[Override, ...]
    config_path: Path
    chroma_dir: Path


@contextmanager
def variant(overrides: Sequence[str | Override] = ()) -> Iterator[Variant]:
    """Run the body with ``overrides`` applied, then restore everything.

    With no overrides this is the shipped configuration and index, unchanged.
    Otherwise the body sees a temporary configuration and a policy index of
    its own, ``VARIANTS_DIR/<fingerprint8>/``.

    Raises:
        OverrideError: If an override is malformed or names an unknown
            setting; nothing is changed.
    """
    parsed = tuple(o if isinstance(o, Override) else parse_override(o) for o in overrides)
    if not parsed:
        yield Variant(BASELINE, (), config.CONFIG_PATH, config.CHROMA_DIR)
        return

    text = config.CONFIG_PATH.read_text(encoding="utf-8")
    for override in parsed:
        text = _apply(text, override)
    fingerprint = hashlib.sha256(
        "\n".join(sorted(o.text for o in parsed)).encode("utf-8")
    ).hexdigest()[:8]

    saved = (config.CONFIG_PATH, config.CHROMA_DIR)
    with tempfile.TemporaryDirectory(prefix="finos-variant-") as directory:
        path = Path(directory) / "config.toml"
        path.write_text(text, encoding="utf-8")
        config.CONFIG_PATH = path
        config.CHROMA_DIR = VARIANTS_DIR / fingerprint
        _clear_caches()
        try:
            config.get_settings()  # validate the variant before running anything
            yield Variant(variant_name(parsed), parsed, path, config.CHROMA_DIR)
        finally:
            config.CONFIG_PATH, config.CHROMA_DIR = saved
            _clear_caches()


# --- Targets: the entry points each dataset runs through (design D3) -------------


def _graph_target(run_config: dict[str, Any]):
    from finos.graph import build_support_agent
    from finos.main import ask

    app = build_support_agent()
    return lambda inputs: dict(ask(app, inputs["question"], config=run_config))


def _retriever_target(run_config: dict[str, Any]):
    from finos import vectorstore
    from finos.observability import root

    def target(inputs: dict[str, Any]) -> dict[str, Any]:
        # The same root as ``finos policy search``, so the query embedding is
        # a priced call of this output (and audited) like any other query.
        with root("policy_search", config=run_config, inputs={"query": inputs["query"]}):
            return {"sources": [hit.source for hit in vectorstore.search(inputs["query"])]}

    return target


def _costed(target: Any, costs: list[Any]) -> Any:
    """Wrap ``target`` so each successful output's cost is appended to ``costs``.

    The cost is every root that finished inside the call (design D8), so it
    holds only that output's calls even when outputs run in threads; the
    judge runs outside the target and is never part of it.
    """
    from finos import cost

    def run(inputs: dict[str, Any]) -> dict[str, Any]:
        with cost.capture() as finished:
            output = target(inputs)
        costs.append(cost.QueryCost([call for query in finished for call in query.cost.calls]))
        return output

    return run


def _helper_target(name: str):
    def factory(run_config: dict[str, Any]):
        from finos import agents

        helper = getattr(agents, name)
        return lambda inputs: dict(helper(inputs["question"], config=run_config))

    return factory


TARGETS = {
    "graph": _graph_target,
    "retriever": _retriever_target,
    "policy": _helper_target("ask_policy"),
    "account": _helper_target("ask_account"),
    "escalation": _helper_target("ask_escalation"),
}
"""Target factories by name: ``factory(run_config) -> target(inputs) -> outputs``."""


def evaluators_for(name: str, *, judged: bool = True) -> dict[str, Any]:
    """The evaluator functions a dataset is scored with, by key."""
    from finos.evaluation.datasets import DATASETS
    from finos.evaluation.evaluators import CODE_EVALUATORS
    from finos.evaluation.judge import JUDGE_EVALUATORS

    chosen = {}
    for key in DATASETS[name].evaluators:
        if key in CODE_EVALUATORS:
            chosen[key] = CODE_EVALUATORS[key]
        elif judged:
            chosen[key] = JUDGE_EVALUATORS[key]
    return chosen


# --- Results (design D7) -------------------------------------------------------


@dataclass(frozen=True)
class Score:
    example_id: str
    repetition: int
    key: str
    score: float | None
    comment: str
    in_scope: bool

    @property
    def error(self) -> bool:
        return self.score is None


@dataclass(frozen=True)
class Metric:
    key: str
    mean: float | None
    """Over all scored outputs."""
    in_scope_mean: float | None
    """Over outputs of in-scope examples (known limitations excluded)."""
    minimum: float | None
    scored: int
    errors: int


@dataclass
class ExperimentResult:
    dataset: str
    dataset_version: str
    variant: str
    overrides: list[str]
    provider: str
    chat_model: str
    judge_provider: str
    judge_model: str
    self_judged: bool
    judged: bool
    repetitions: int
    local: bool
    outputs: int
    scores: list[Score]
    latencies_ms: list[float]
    judge_calls: int = 0
    judge_input_tokens: int | None = 0
    judge_output_tokens: int | None = 0
    experiment: str = ""
    url: str | None = None
    costs: list[Any] = field(default_factory=list)
    """Each successful output's ``finos.cost.QueryCost``."""
    judge_cost_usd: float | None = None
    prices_as_of: str | None = None

    # --- Cost (evaluation delta) ---

    @property
    def output_costs(self) -> list[float | None]:
        return [c.cost_usd for c in self.costs]

    @property
    def known_costs(self) -> list[float]:
        return [c for c in self.output_costs if c is not None]

    @property
    def unknown_cost_outputs(self) -> int:
        return sum(1 for c in self.output_costs if c is None)

    def cost_summary(self) -> dict[str, Any]:
        """Per-output cost and tokens: mean, p50, p95, total; the guard share; unknowns."""
        from finos.stats import mean

        known = self.known_costs
        guard = [c.guard_cost_usd or 0.0 for c in self.costs if c.cost_usd is not None]
        total = round(sum(known), 8)
        inputs = [float(c.input_tokens) for c in self.costs]
        outputs = [float(c.output_tokens) for c in self.costs]

        def stats(values: list[float]) -> dict[str, float | None]:
            return {
                "mean": mean(values),
                "p50": percentile(values, 0.50),
                "p95": percentile(values, 0.95),
                "total": round(sum(values), 8) if values else 0.0,
            }

        return {
            "prices_as_of": self.prices_as_of,
            "outputs": len(self.costs),
            "unknown_outputs": self.unknown_cost_outputs,
            "usd": stats(known),
            "guard_share": (sum(guard) / total) if total > 0 else None,
            "input_tokens": stats(inputs),
            "output_tokens": stats(outputs),
        }

    @property
    def errors(self) -> list[Score]:
        return [score for score in self.scores if score.error]

    @property
    def metrics(self) -> dict[str, Metric]:
        keys = list(dict.fromkeys(s.key for s in self.scores if s.key != "target"))
        summary = {}
        for key in keys:
            rows = [s for s in self.scores if s.key == key]
            values = [s.score for s in rows if s.score is not None]
            in_scope = [s.score for s in rows if s.score is not None and s.in_scope]
            summary[key] = Metric(
                key,
                sum(values) / len(values) if values else None,
                sum(in_scope) / len(in_scope) if in_scope else None,
                min(values) if values else None,
                len(values),
                sum(1 for s in rows if s.error),
            )
        return summary

    @property
    def p50_ms(self) -> float | None:
        return percentile(self.latencies_ms, 0.50)

    @property
    def p95_ms(self) -> float | None:
        return percentile(self.latencies_ms, 0.95)

    def as_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "dataset": self.dataset,
            "dataset_version": self.dataset_version,
            "variant": self.variant,
            "overrides": self.overrides,
            "provider": self.provider,
            "chat_model": self.chat_model,
            "judge": {
                "provider": self.judge_provider,
                "model": self.judge_model,
                "used": self.judged,
                "self_judged": self.self_judged,
                "calls": self.judge_calls,
                "input_tokens": self.judge_input_tokens,
                "output_tokens": self.judge_output_tokens,
                "cost_usd": self.judge_cost_usd,
            },
            "repetitions": self.repetitions,
            "local": self.local,
            "outputs": self.outputs,
            "metrics": {
                key: {
                    "mean": m.mean,
                    "in_scope_mean": m.in_scope_mean,
                    "minimum": m.minimum,
                    "scored": m.scored,
                    "errors": m.errors,
                }
                for key, m in self.metrics.items()
            },
            "errors": [
                {"example": s.example_id, "repetition": s.repetition, "key": s.key, "reason": s.comment}
                for s in self.errors
            ],
            "latency_ms": {"p50": self.p50_ms, "p95": self.p95_ms},
            "cost": self.cost_summary(),
            "url": self.url,
        }


# --- The local runner (design D4) -------------------------------------------------


def _score(
    function: Any, key: str, run: dict[str, Any], example: Any, repetition: int
) -> Score | None:
    try:
        result = function(run, example.as_dict())
    except Exception as error:  # noqa: BLE001 - an evaluator failure is an error row
        return Score(example.id, repetition, key, None, f"error: {error}", example.in_scope)
    if result is None:
        return None
    return Score(
        example.id,
        repetition,
        result["key"],
        float(result["score"]),
        str(result.get("comment", "")),
        example.in_scope,
    )


def run_local(
    examples: Sequence[Any],
    target: Any,
    evaluators: dict[str, Any],
    repetitions: int,
    costs: list[Any] | None = None,
) -> tuple[int, list[Score], list[float]]:
    """Run every example ``repetitions`` times with tracing off; score each output.

    A target that raises is recorded as one ``target`` error for that output,
    with its exception type; the run continues with the next example.
    """
    import time

    from langsmith import tracing_context

    if costs is not None:
        target = _costed(target, costs)
    outputs = 0
    scores: list[Score] = []
    latencies: list[float] = []
    with tracing_context(enabled=False):
        for repetition in range(1, repetitions + 1):
            for example in examples:
                start = time.perf_counter()
                try:
                    output = target(dict(example.inputs))
                except Exception as error:  # noqa: BLE001 - recorded, run continues
                    latencies.append((time.perf_counter() - start) * 1000)
                    scores.append(
                        Score(
                            example.id,
                            repetition,
                            "target",
                            None,
                            f"error: {type(error).__name__}: {error}",
                            example.in_scope,
                        )
                    )
                    continue
                latencies.append((time.perf_counter() - start) * 1000)
                outputs += 1
                run = {"outputs": output}
                for key, function in evaluators.items():
                    score = _score(function, key, run, example, repetition)
                    if score is not None:
                        scores.append(score)
    return outputs, scores, latencies


# --- Running an experiment ------------------------------------------------------------


def langsmith_key_set() -> bool:
    """Whether a LangSmith API key is set, in the environment or in ``.env``.

    Loads settings first: that is what reads ``.env``, so a key kept only
    there is seen even when nothing else has loaded settings yet.
    """
    import os

    config.get_settings()
    return any(os.environ.get(name) for name in config.API_KEY_VARS)


def experiment_name(dataset: str, provider: str, variant_label: str) -> str:
    return f"eval-{dataset}-{provider}-{variant_label}"


def run_experiment(
    dataset: str,
    *,
    overrides: Sequence[str] = (),
    repetitions: int | None = None,
    local: bool | None = None,
    judged: bool = True,
) -> ExperimentResult:
    """Run one dataset under one variant and return its result.

    ``local`` defaults to true when no LangSmith key is set. ``judged=False``
    skips the judge evaluators (the deterministic tier).

    Raises:
        KeyError: Unknown dataset, or an invalid setting in the variant.
        OverrideError: A malformed override or an unknown setting.
        DatasetError: A missing or malformed dataset file.
        RuntimeError: LangSmith could not be reached (LangSmith runs only).
    """
    from finos import llm
    from finos.evaluation import judge
    from finos.evaluation.datasets import DATASETS, load
    from finos.observability import current_observation, observe

    spec = DATASETS[dataset]
    if spec.target not in TARGETS:
        raise KeyError(f"Dataset {dataset!r} is not run as an experiment")

    with variant(overrides) as active:
        settings = config.get_settings()
        loaded = load(dataset)
        reps = int(repetitions if repetitions is not None else settings["eval"]["repetitions"])
        if reps < 1:
            raise ValueError("repetitions must be at least 1")
        is_local = (not langsmith_key_set()) if local is None else bool(local)
        provider, chat_model = llm.chat_identity()
        judge_provider, judge_model = llm.judge_identity()
        evaluators = evaluators_for(dataset, judged=judged)
        uses_judge = any(key in judge.JUDGE_EVALUATORS for key in evaluators)
        name = experiment_name(dataset, provider, active.name)
        run_config = {
            "tags": [f"exp:{active.name}", f"eval-{dataset}"],
            "metadata": {"dataset_version": loaded.version, "experiment": name},
        }
        judge.usage.reset()
        costs: list[Any] = []

        observation = None if current_observation() is not None else observe("eval")
        with observation if observation is not None else _nullcontext():
            if is_local:
                target = TARGETS[spec.target](run_config)
                outputs, scores, latencies = run_local(
                    loaded.examples, target, evaluators, reps, costs
                )
                url = None
            else:
                outputs, scores, latencies, url = run_langsmith(
                    loaded, spec.target, run_config, evaluators, reps, name, active, provider, costs
                )
        judge_cost, as_of = _judge_cost(judge_provider, judge_model)
        _report_budget()

        return ExperimentResult(
            dataset=dataset,
            dataset_version=loaded.version,
            variant=active.name,
            overrides=[o.text for o in active.overrides],
            provider=provider,
            chat_model=chat_model,
            judge_provider=judge_provider,
            judge_model=judge_model,
            self_judged=uses_judge and judge.self_judged(),
            judged=uses_judge,
            repetitions=reps,
            local=is_local,
            outputs=outputs,
            scores=scores,
            latencies_ms=latencies,
            judge_calls=judge.usage.calls,
            judge_input_tokens=judge.usage.input_tokens,
            judge_output_tokens=judge.usage.output_tokens,
            experiment=name,
            url=url,
            costs=costs,
            judge_cost_usd=judge_cost,
            prices_as_of=as_of,
        )


@contextmanager
def _nullcontext() -> Iterator[None]:
    yield None


def _judge_cost(provider: str, model: str) -> tuple[float | None, str | None]:
    """Price the experiment's judge usage; ``(None, ...)`` when unknown. Never raises."""
    from types import SimpleNamespace

    from finos import cost
    from finos.evaluation import judge

    try:
        as_of = cost.prices_as_of()
        if judge.usage.calls == 0:
            return 0.0, as_of
        call = SimpleNamespace(
            role="judge",
            provider=provider,
            model=model,
            input_tokens=judge.usage.input_tokens,
            output_tokens=judge.usage.output_tokens,
            cached_input_tokens=None,
        )
        return cost.price_call(call), as_of
    except Exception:  # noqa: BLE001 - cost never fails an experiment
        return None, None


def _report_budget() -> None:
    """After an experiment, warn on stderr when today's audited cost nears the budget."""
    import sys

    from finos import cost

    try:
        status = cost.daily_status()
    except Exception:  # noqa: BLE001 - cost never fails an experiment
        return
    if status.status != cost.BUDGET_OK:
        print(status.line(), file=sys.stderr)


# --- LangSmith: datasets and experiments (design D2, D4, D8) -----------------------

NOT_SCORED = "not scored"
"""The comment of an adapted evaluator result that has no score for this example."""


class VersionMismatch(RuntimeError):
    """LangSmith holds a different version of a dataset than the repository."""


def dataset_name(name: str) -> str:
    """The LangSmith dataset a repository dataset is pushed to."""
    return f"finos-{name}"


def _remote_version(client: Any, name: str) -> str | None:
    """The version LangSmith holds for a dataset, ``None`` if absent, ``"mixed"`` if inconsistent."""
    if not client.has_dataset(dataset_name=dataset_name(name)):
        return None
    versions = {
        str((example.metadata or {}).get("dataset_version"))
        for example in client.list_examples(dataset_name=dataset_name(name))
    }
    if len(versions) != 1:
        return "mixed" if versions else None
    return versions.pop()


def _connection_error(error: Exception) -> RuntimeError:
    return RuntimeError(f"LangSmith could not be reached: {type(error).__name__}: {error}")


@dataclass(frozen=True)
class PushResult:
    dataset: str
    examples: int
    version: str
    uploaded: bool
    """False when LangSmith already held this version."""


def push(name: str) -> PushResult:
    """Upload a dataset to LangSmith as ``finos-<name>``, unless it holds this version.

    Each example carries its id, split, and the dataset version in its
    metadata. A changed dataset replaces the old examples.

    Raises:
        RuntimeError: If no LangSmith key is set, or LangSmith can't be reached.
    """
    from finos.evaluation.datasets import load
    from finos.observability import masking_client

    if not langsmith_key_set():
        raise RuntimeError("A LangSmith key is required: set LANGSMITH_API_KEY or LANGCHAIN_API_KEY")
    loaded = load(name)
    client = masking_client()
    try:
        remote = _remote_version(client, name)
        if remote == loaded.version:
            return PushResult(name, len(loaded.examples), loaded.version, False)
        if remote is None and not client.has_dataset(dataset_name=dataset_name(name)):
            client.create_dataset(
                dataset_name(name),
                description=f"finos evaluation dataset {name!r} (evals/datasets/{name}.jsonl)",
                metadata={"source": f"evals/datasets/{name}.jsonl"},
            )
        else:
            old = [example.id for example in client.list_examples(dataset_name=dataset_name(name))]
            if old:
                client.delete_examples(old)
        client.create_examples(
            dataset_name=dataset_name(name),
            examples=[
                {
                    "inputs": example.inputs,
                    "outputs": example.outputs,
                    "metadata": {
                        **example.metadata,
                        "example_id": example.id,
                        "split": example.split,
                        "dataset_version": loaded.version,
                    },
                }
                for example in loaded.examples
            ],
        )
    except Exception as error:  # noqa: BLE001 - one clear failure, no partial claim
        raise _connection_error(error) from error
    return PushResult(name, len(loaded.examples), loaded.version, True)


def _adapt(key: str, function: Any):
    """Wrap a plain-dict evaluator for ``langsmith.evaluate``."""

    def evaluator(run: Any, example: Any) -> dict[str, Any]:
        metadata = dict(example.metadata or {})
        plain_example = {
            "inputs": dict(example.inputs or {}),
            "outputs": dict(example.outputs or {}),
            "metadata": metadata,
        }
        try:
            result = function({"outputs": dict(run.outputs or {})}, plain_example)
        except Exception as error:  # noqa: BLE001 - an error row, never a default score
            return {"key": key, "score": None, "comment": f"error: {error}"}
        if result is None:
            return {"key": key, "score": None, "comment": NOT_SCORED}
        return {"key": result["key"], "score": result["score"], "comment": result.get("comment", "")}

    evaluator.__name__ = key
    return evaluator


def _git_sha() -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=config.PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return out.stdout.strip()[:8] or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def run_langsmith(
    loaded: Any,
    target_name: str,
    run_config: dict[str, Any],
    evaluators: dict[str, Any],
    repetitions: int,
    name: str,
    active: Variant,
    provider: str,
    costs: list[Any] | None = None,
) -> tuple[int, list[Score], list[float], str | None]:
    """Run an experiment with ``langsmith.evaluate`` through the masking client.

    The masking client is passed explicitly: ``evaluate`` traces through its
    own client, and every run beneath its target inherits it, so without
    this the experiment would upload unmasked (explore probes 1 and 2).

    Raises:
        VersionMismatch: LangSmith holds a different version of the dataset.
        RuntimeError: LangSmith could not be reached.
    """
    import time

    from langsmith import evaluate

    from finos import llm
    from finos.observability import masking_client

    client = masking_client()
    try:
        remote = _remote_version(client, loaded.name)
    except Exception as error:  # noqa: BLE001
        raise _connection_error(error) from error
    if remote != loaded.version:
        raise VersionMismatch(
            f"LangSmith holds version {remote or 'none'} of {dataset_name(loaded.name)}, "
            f"the repository has {loaded.version}; run `finos eval push --dataset {loaded.name}`"
        )

    target = TARGETS[target_name](run_config)
    if costs is not None:
        target = _costed(target, costs)
    latencies: list[float] = []

    def timed_target(inputs: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            return target(inputs)
        finally:
            latencies.append((time.perf_counter() - start) * 1000)

    judge_provider, judge_model = llm.judge_identity()
    metadata = {
        "dataset_version": loaded.version,
        "repetitions": repetitions,
        "variant": active.name,
        "overrides": [o.text for o in active.overrides],
        "provider": provider,
        "judge_provider": judge_provider,
        "judge_model": judge_model,
        "git_sha": _git_sha(),
    }
    try:
        results = evaluate(
            timed_target,
            data=dataset_name(loaded.name),
            evaluators=[_adapt(key, function) for key, function in evaluators.items()],
            client=client,
            num_repetitions=repetitions,
            experiment_prefix=name,
            metadata=metadata,
            max_concurrency=1 if provider == "ollama" else 4,
            blocking=True,
        )
        rows = list(results)
    except VersionMismatch:
        raise
    except Exception as error:  # noqa: BLE001 - no partial experiment is reported
        raise _connection_error(error) from error

    outputs = 0
    scores: list[Score] = []
    seen: dict[str, int] = {}
    for row in rows:
        example = row["example"]
        meta = dict(example.metadata or {})
        example_id = str(meta.get("example_id", example.id))
        in_scope = meta.get("split", "in_scope") == "in_scope"
        seen[example_id] = seen.get(example_id, 0) + 1
        repetition = seen[example_id]
        run = row["run"]
        if getattr(run, "error", None):
            scores.append(Score(example_id, repetition, "target", None, f"error: {run.error}", in_scope))
            continue
        outputs += 1
        for result in row["evaluation_results"]["results"]:
            if result.comment == NOT_SCORED:
                continue
            score = None if result.score is None else float(result.score)
            scores.append(Score(example_id, repetition, result.key, score, result.comment or "", in_scope))
    url = getattr(results, "url", None)
    return outputs, scores, latencies, url
