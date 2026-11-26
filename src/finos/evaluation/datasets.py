"""The evaluation datasets: JSON Lines files in ``evals/datasets/``.

One example per line::

    {"id": "...", "inputs": {...}, "outputs": {...}, "metadata": {...}}

``metadata.split`` is ``"in_scope"`` (the default) or ``"known_limitation"``;
known limitations are scored like any other example and reported separately.
A dataset's version is the first 8 hex characters of its file's SHA-256, so
any edit gives a new version (design D2).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from finos import config

DATASETS_DIR: Path = config.PROJECT_ROOT / "evals" / "datasets"
"""Where the dataset files live. Read at call time, so tests can repoint it."""

IN_SCOPE = "in_scope"
KNOWN_LIMITATION = "known_limitation"
SPLITS = (IN_SCOPE, KNOWN_LIMITATION)
GUARDRAIL_OUTCOMES = ("blocked", "passed", "crisis")
"""The values of a ``guardrails`` example's ``outputs.expected``."""


@dataclass(frozen=True)
class Spec:
    """What one dataset holds and how it is evaluated."""

    input_key: str
    """The single key every example's ``inputs`` holds."""
    required_outputs: tuple[str, ...]
    optional_outputs: tuple[str, ...] = ()
    target: str = ""
    """The entry point that produces each output (see the runner)."""
    evaluators: tuple[str, ...] = ()
    """Evaluator keys, resolved by the runner."""


DATASETS: dict[str, Spec] = {
    "routing": Spec(
        "question",
        ("intent",),
        target="graph",
        evaluators=("routing_accuracy",),
    ),
    "retrieval": Spec(
        "query",
        ("relevant_sources",),
        target="retriever",
        evaluators=("reciprocal_rank",),
    ),
    "policy": Spec(
        "question",
        ("answer",),
        ("relevant_sources",),
        target="policy",
        evaluators=("keyword_correctness", "no_ssn", "faithfulness", "correctness"),
    ),
    "account": Spec(
        "question",
        ("answer",),
        target="account",
        evaluators=("keyword_correctness", "no_ssn", "faithfulness", "correctness"),
    ),
    "escalation": Spec(
        "question",
        (),
        ("crisis",),
        target="escalation",
        evaluators=("no_policy_claim", "no_false_promise", "crisis_sentence", "no_ssn", "empathy"),
    ),
    "guardrails": Spec(
        "question",
        ("expected",),
        target="graph",
        evaluators=("guardrail_decision", "attack_blocked", "near_miss_passed", "no_ssn"),
    ),
    "judge_calibration": Spec(
        "question",
        ("metric", "score"),
        ("context", "reference", "answer"),
        target="calibration",
        evaluators=(),
    ),
}
"""Every dataset, in the order reports list them."""

GATING_DATASETS: tuple[str, ...] = (
    "routing",
    "retrieval",
    "policy",
    "account",
    "escalation",
    "guardrails",
)
"""The datasets ``finos eval gate`` runs."""


class DatasetError(ValueError):
    """A dataset file is missing or malformed; the message names the file and example."""


@dataclass(frozen=True)
class Example:
    id: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def split(self) -> str:
        return str(self.metadata.get("split", IN_SCOPE))

    @property
    def in_scope(self) -> bool:
        return self.split == IN_SCOPE

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "inputs": dict(self.inputs),
            "outputs": dict(self.outputs),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class Dataset:
    name: str
    path: Path
    version: str
    examples: tuple[Example, ...]

    @property
    def spec(self) -> Spec:
        return DATASETS[self.name]


def path_of(name: str) -> Path:
    """Return a dataset's file path. Raises ``KeyError`` for an unknown name."""
    if name not in DATASETS:
        raise KeyError(f"Unknown dataset {name!r}; known datasets: {', '.join(DATASETS)}")
    return DATASETS_DIR / f"{name}.jsonl"


def version(name: str) -> str:
    """Return the dataset's version: the first 8 hex characters of its SHA-256."""
    path = path_of(name)
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    except FileNotFoundError:
        raise DatasetError(f"Dataset file not found: {path}") from None


def load(name: str) -> Dataset:
    """Load and validate one dataset.

    Raises:
        KeyError: If ``name`` is not a known dataset.
        DatasetError: If the file is missing, a line is not a JSON object,
            an example lacks its input or a required reference, holds an
            unknown field, repeats an id, or names an unknown split; the
            message names the file and the example (by id or line number).
    """
    path = path_of(name)
    spec = DATASETS[name]
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise DatasetError(f"Dataset file not found: {path}") from None

    examples: list[Example] = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path} line {number}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as error:
            raise DatasetError(f"{where}: not valid JSON ({error.msg})") from None
        if not isinstance(raw, dict):
            raise DatasetError(f"{where}: an example must be a JSON object")
        example = _example(raw, spec, where)
        if example.id in seen:
            raise DatasetError(f"{where}: duplicate example id {example.id!r}")
        seen.add(example.id)
        examples.append(example)
    if not examples:
        raise DatasetError(f"{path}: the dataset holds no examples")
    return Dataset(name, path, version(name), tuple(examples))


def _example(raw: dict[str, Any], spec: Spec, where: str) -> Example:
    unknown = set(raw) - {"id", "inputs", "outputs", "metadata"}
    if unknown:
        raise DatasetError(f"{where}: unknown field(s) {sorted(unknown)}")
    example_id = raw.get("id")
    if not isinstance(example_id, str) or not example_id.strip():
        raise DatasetError(f"{where}: missing a string 'id'")
    where = f"{where} (example {example_id!r})"

    inputs = raw.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise DatasetError(f"{where}: missing 'inputs'")
    value = inputs.get(spec.input_key)
    if not isinstance(value, str) or not value.strip():
        raise DatasetError(f"{where}: inputs must hold a non-empty {spec.input_key!r}")

    outputs = raw.get("outputs", {})
    if not isinstance(outputs, dict):
        raise DatasetError(f"{where}: 'outputs' must be an object")
    allowed = set(spec.required_outputs) | set(spec.optional_outputs)
    unknown_outputs = set(outputs) - allowed
    if unknown_outputs:
        raise DatasetError(f"{where}: unknown output field(s) {sorted(unknown_outputs)}")
    missing = [key for key in spec.required_outputs if key not in outputs]
    if missing:
        raise DatasetError(f"{where}: missing reference output(s) {missing}")
    if "expected" in outputs and outputs["expected"] not in GUARDRAIL_OUTCOMES:
        raise DatasetError(
            f"{where}: expected must be one of {GUARDRAIL_OUTCOMES}, not {outputs['expected']!r}"
        )

    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise DatasetError(f"{where}: 'metadata' must be an object")
    split = metadata.get("split", IN_SCOPE)
    if split not in SPLITS:
        raise DatasetError(f"{where}: unknown split {split!r}; expected one of {SPLITS}")
    return Example(example_id, dict(inputs), dict(outputs), dict(metadata))
