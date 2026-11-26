"""Judge evaluators: faithfulness, correctness, and empathy, scored by a judge model.

The judge is ``finos.llm.get_judge_llm()`` (``[eval] judge_provider`` and
``judge_model``), never the chat model's settings (design D5). It replies
with a score from 0.0 to 1.0 and a one-line reason, through structured
output where the provider supports it, else as a JSON object in its reply.

A reply that holds no readable score, or a call that fails twice, raises
:class:`JudgeError`. The runner records it as an error for that example;
nothing here ever substitutes a default score.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

Result = dict[str, Any]

CALIBRATION_TOLERANCE = 0.25
"""How far from its hand-set label a calibration score may be."""

ATTEMPTS = 2
"""A judge call is tried once more after a failure, then it is an error."""


class JudgeError(RuntimeError):
    """The judge gave no usable score; the message holds the reason."""


@dataclass(frozen=True)
class Verdict:
    score: float
    reason: str


@dataclass
class Usage:
    """Judge calls and tokens, for an experiment's cost record.

    Once one call reports no usage, the token totals are unknown (``None``)
    rather than an undercount (cost-tracking: unknown, never zero).
    """

    calls: int = 0
    _input: int = 0
    _output: int = 0
    _unknown: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def input_tokens(self) -> int | None:
        return None if self._unknown else self._input

    @property
    def output_tokens(self) -> int | None:
        return None if self._unknown else self._output

    def add(self, message: Any) -> None:
        usage = getattr(message, "usage_metadata", None) or {}
        with self._lock:
            self.calls += 1
            if usage.get("input_tokens") is None or usage.get("output_tokens") is None:
                self._unknown = True
                return
            self._input += int(usage["input_tokens"])
            self._output += int(usage["output_tokens"])

    def reset(self) -> None:
        with self._lock:
            self.calls = self._input = self._output = 0
            self._unknown = False


usage = Usage()
"""Judge usage since the last ``usage.reset()``; the runner resets it per experiment."""


# --- Asking the judge -----------------------------------------------------------


def _schema() -> type:
    from pydantic import BaseModel, Field

    class JudgeScore(BaseModel):
        """A judge's score and its one-line reason."""

        score: float = Field(ge=0.0, le=1.0, description="The score, from 0.0 to 1.0")
        reason: str = Field(description="A one-line reason")

    return JudgeScore


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_reply(text: str) -> Verdict:
    """Read a score and reason from a judge's text reply; raise :class:`JudgeError` if none."""
    match = _JSON_OBJECT.search(text or "")
    if not match:
        raise JudgeError(f"the judge's reply holds no score: {text.strip()[:200]!r}")
    try:
        data = json.loads(match.group(0))
        score = float(data["score"])
    except (ValueError, KeyError, TypeError):
        raise JudgeError(f"the judge's reply holds no readable score: {text.strip()[:200]!r}") from None
    if not 0.0 <= score <= 1.0:
        raise JudgeError(f"the judge's score {score} is outside 0.0 to 1.0")
    return Verdict(score, str(data.get("reason", "")).strip())


def ask(system: str, human: str, *, run_name: str) -> Verdict:
    """Ask the judge once (retrying once on failure) and return its verdict."""
    from finos import llm

    model = llm.get_judge_llm()
    messages = [("system", system), ("human", human)]
    last_error: Exception | None = None
    for _attempt in range(ATTEMPTS):
        try:
            return _structured(model, messages, run_name) or _plain(model, messages, run_name)
        except JudgeError as error:
            last_error = error
        except Exception as error:  # noqa: BLE001 - provider errors become judge errors
            last_error = JudgeError(f"the judge call failed: {type(error).__name__}: {error}")
    assert last_error is not None
    raise last_error


def _structured(model: Any, messages: list, run_name: str) -> Verdict | None:
    """Structured output, or ``None`` when the model doesn't support it."""
    from finos.observability import chain_config

    try:
        bound = model.with_structured_output(_schema(), include_raw=True)
    except (RuntimeError, AttributeError, TypeError, ValueError):  # incl. not implemented
        return None
    reply = bound.with_config(**chain_config(run_name)).invoke(messages)
    raw = reply.get("raw") if isinstance(reply, Mapping) else None
    if raw is not None:
        usage.add(raw)
    parsed = reply.get("parsed") if isinstance(reply, Mapping) else None
    if parsed is None:
        text = getattr(raw, "content", "") if raw is not None else ""
        return parse_reply(text if isinstance(text, str) else json.dumps(text))
    return Verdict(float(parsed.score), str(parsed.reason).strip())


def _plain(model: Any, messages: list, run_name: str) -> Verdict:
    from finos.agents.policy import _message_text
    from finos.observability import chain_config

    message = model.with_config(**chain_config(run_name)).invoke(messages)
    usage.add(message)
    return parse_reply(_message_text(message))


# --- The three judged scores ------------------------------------------------------


def score_faithfulness(question: str, material: str, answer: str) -> Verdict:
    from finos.prompts import JUDGE_FAITHFULNESS_PROMPT

    human = f"Material the agent was given:\n{material or '(none)'}\n\nQuestion:\n{question}\n\nAnswer:\n{answer}"
    return ask(JUDGE_FAITHFULNESS_PROMPT, human, run_name="judge_faithfulness")


def score_correctness(question: str, reference: str, answer: str) -> Verdict:
    from finos.prompts import JUDGE_CORRECTNESS_PROMPT

    human = f"Question:\n{question}\n\nReference answer:\n{reference}\n\nAnswer to grade:\n{answer}"
    return ask(JUDGE_CORRECTNESS_PROMPT, human, run_name="judge_correctness")


def score_empathy(message: str, reply: str) -> Verdict:
    from finos.prompts import JUDGE_EMPATHY_PROMPT

    human = f"Customer's message:\n{message}\n\nReply:\n{reply}"
    return ask(JUDGE_EMPATHY_PROMPT, human, run_name="judge_empathy")


# --- Judge evaluators (the runner's ``(run, example)`` signature) ----------------


def _question(example: Mapping[str, Any]) -> str:
    return str(example["inputs"].get("question", ""))


def _response(run: Mapping[str, Any]) -> str:
    return str((run.get("outputs") or {}).get("response", ""))


def _verdict(key: str, verdict: Verdict) -> Result:
    return {"key": key, "score": verdict.score, "comment": verdict.reason}


def material_for(run: Mapping[str, Any], example: Mapping[str, Any]) -> str | None:
    """What the agent saw: the retrieved context, or the account record.

    Policy runs carry their ``context`` in the state. The account record is
    not in the state, so it is looked up in-process for the question
    (design D3). An account question that resolves to no record (a fixed
    message) returns ``None``: there is nothing to be faithful to.
    """
    outputs = run.get("outputs") or {}
    if outputs.get("intent") == "account_status":
        from finos.accounts import resolve
        from finos.agents.account import render_record

        resolution = resolve(_question(example))
        if resolution.record is None:
            return None
        return render_record(resolution.record)
    return str(outputs.get("context", ""))


def faithfulness(run: Mapping[str, Any], example: Mapping[str, Any]) -> Result | None:
    """Every claim grounded in what the agent saw; ``None`` for a fixed account message."""
    material = material_for(run, example)
    if material is None:
        return None
    return _verdict("faithfulness", score_faithfulness(_question(example), material, _response(run)))


def correctness(run: Mapping[str, Any], example: Mapping[str, Any]) -> Result:
    """Agreement with the reference answer."""
    reference = str(example["outputs"].get("answer", ""))
    return _verdict("correctness", score_correctness(_question(example), reference, _response(run)))


def empathy(run: Mapping[str, Any], example: Mapping[str, Any]) -> Result:
    """The escalation prompt's four empathy criteria."""
    return _verdict("empathy", score_empathy(_question(example), _response(run)))


JUDGE_EVALUATORS = {
    "faithfulness": faithfulness,
    "correctness": correctness,
    "empathy": empathy,
}
"""Judge evaluators by key, as the dataset registry names them."""


# --- Self-judging and calibration --------------------------------------------------


def self_judged() -> bool:
    """Whether the judge is the same provider and model as the chat model."""
    from finos.llm import chat_identity, judge_identity

    return judge_identity() == chat_identity()


@dataclass(frozen=True)
class CalibrationItem:
    id: str
    metric: str
    label: float
    score: float | None
    reason: str

    @property
    def ok(self) -> bool:
        return self.score is not None and abs(self.score - self.label) <= CALIBRATION_TOLERANCE


@dataclass(frozen=True)
class Calibration:
    items: tuple[CalibrationItem, ...]

    @property
    def passed(self) -> bool:
        return bool(self.items) and all(item.ok for item in self.items)

    @property
    def failures(self) -> list[CalibrationItem]:
        return [item for item in self.items if not item.ok]


def calibrate() -> Calibration:
    """Score every calibration item; pass only if each is within the tolerance.

    A judge error on an item fails that item, with the error as its reason.
    """
    from finos.evaluation.datasets import load

    items = []
    for example in load("judge_calibration").examples:
        outputs = example.outputs
        question = example.inputs["question"]
        try:
            if outputs["metric"] == "faithfulness":
                verdict = score_faithfulness(question, outputs.get("context", ""), outputs["answer"])
            elif outputs["metric"] == "correctness":
                verdict = score_correctness(question, outputs.get("reference", ""), outputs["answer"])
            else:
                verdict = score_empathy(question, outputs["answer"])
            score, reason = verdict.score, verdict.reason
        except JudgeError as error:
            score, reason = None, f"error: {error}"
        items.append(
            CalibrationItem(example.id, outputs["metric"], float(outputs["score"]), score, reason)
        )
    return Calibration(tuple(items))
