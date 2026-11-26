"""Tracing, masking, and per-step timings: the one module that imports ``langsmith``.

Every entry point that answers a query opens a :func:`root` run: ``ask``
opens ``support_query``, the standalone helpers open ``policy_query``,
``account_query``, and ``escalation_query``, and the CLI opens
``policy_search`` and ``supervisor_classify``. The decision steps inside the
agents are :func:`step` runs, and the four chains are named with
:func:`chain_config`. The run tree (design D2)::

    support_query
      support_graph
        classify_intent   -> supervisor_llm, normalize_intent
        policy_agent      -> policy_retrieval, policy_llm
        account_agent     -> account_resolution, account_llm (found only)
        escalation_agent  -> escalation_llm, escalation_assembly

The CLI and the live tests enter :func:`observe` around one command or test.
It holds an :class:`Observation`: the entry point, the trace ID once a root
records one, and the timing collector the ``--verbose`` lines read. The
collector works whether tracing is on or not.

Every root uploads through one masking client per process, whose
``hide_inputs`` and ``hide_outputs`` are :func:`mask`, so Social Security
data never leaves the machine.

Importing this module imports nothing from ``langsmith`` or LangChain; both
are imported inside the functions that need them. Tracing never changes a
result: a failure to build metadata, create the client, or upload a run is
swallowed, and the request runs untraced or unrecorded.
"""

from __future__ import annotations

import functools
import hashlib
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, TypeVar

from finos.config import tracing_status

__all__ = [
    "Observation",
    "REDACTED",
    "chain_config",
    "current_observation",
    "current_request",
    "masking_client",
    "mask",
    "observe",
    "record_call",
    "root",
    "root_metadata",
    "root_tags",
    "step",
    "tracing_status",
]

_F = TypeVar("_F", bound=Callable[..., Any])

REDACTED = "[REDACTED:ssn]"
"""What every masked Social Security value becomes."""

DEFAULT_ENTRY = "api"
"""The entry point of a root opened outside :func:`observe`: a library caller."""

NODE_NAMES: frozenset[str] = frozenset(
    {"classify_intent", "policy_agent", "account_agent", "escalation_agent"}
)
"""The graph nodes the timing collector reports one line for."""

GUARDS_UNIT = "guards"
"""The timing line for the input guards' span, when a guard made a model call."""

RETRIEVAL_STEP = "policy_retrieval"
"""The step whose time is reported as the policy route's retrieval time."""

ROLE_BY_RUN: dict[str, str] = {
    "supervisor_llm": "classify_intent",
    "policy_llm": "policy_agent",
    "account_llm": "account_agent",
    "escalation_llm": "escalation_agent",
    "injection_classifier_llm": "injection_classifier",
    "judge_faithfulness": "judge",
    "judge_correctness": "judge",
    "judge_empathy": "judge",
}
"""The role a chat call plays, from the nearest named run above it (cost attribution)."""


# --- Observation and the timing collector (design D7) -----------------------


@dataclass
class ModelCall:
    """One model call: when it ended, who made it, and its token usage if reported.

    ``chat`` calls come from the LangChain callback and are the ones the
    ``--verbose`` token counts add up. Other calls (moderation, the query
    embedding) are recorded with :func:`record_call` for cost only; an
    embedding's tokens are ``estimated``.
    """

    end: float
    input_tokens: int | None
    output_tokens: int | None
    model: str | None = None
    provider: str | None = None
    role: str = "unknown"
    cached_input_tokens: int | None = None
    estimated: bool = False
    chat: bool = True


@dataclass
class Span:
    """A named interval on the ``time.perf_counter`` clock."""

    name: str
    start: float
    end: float | None = None

    @property
    def ms(self) -> float:
        return ((self.end if self.end is not None else time.perf_counter()) - self.start) * 1000

    def contains(self, moment: float) -> bool:
        return self.start <= moment <= (self.end if self.end is not None else float("inf"))


@dataclass
class Unit:
    """One line of the timing report: a node, or a standalone root."""

    name: str
    ms: float
    retrieval_ms: float | None
    calls: list[ModelCall]

    @property
    def tokens(self) -> str | None:
        """``"in+out tokens"`` over chat calls, ``"n/a tokens"`` if one lacked usage, or ``None``."""
        chat = [c for c in self.calls if c.chat]
        if not chat:
            return None
        if any(c.input_tokens is None or c.output_tokens is None for c in chat):
            return "n/a tokens"
        prompt = sum(c.input_tokens or 0 for c in chat)
        completion = sum(c.output_tokens or 0 for c in chat)
        return f"{prompt}+{completion} tokens"

    def line(self) -> str:
        text = f"{self.name}: {self.ms:.0f} ms"
        if self.retrieval_ms is not None:
            text += f" (retrieval {self.retrieval_ms:.0f} ms)"
        if self.tokens:
            text += f", {self.tokens}"
        return text


@dataclass
class Observation:
    """What one command or test recorded: its entry, trace, and timings."""

    entry: str
    metadata: dict[str, Any] = field(default_factory=dict)
    """Extra root metadata, for example the live test's ``test_id``."""
    trace_id: str | None = None
    """The trace ID of the last root traced inside this observation."""
    started: float = field(default_factory=time.perf_counter)
    roots: list[Span] = field(default_factory=list)
    nodes: list[Span] = field(default_factory=list)
    steps: list[Span] = field(default_factory=list)
    calls: list[ModelCall] = field(default_factory=list)
    guard_decisions: list[Any] = field(default_factory=list)
    """Guardrail decisions (``finos.guardrails.GuardDecision``), for ``--verbose``."""
    guards: list[Span] = field(default_factory=list)
    """The input guards' spans, one per guarded request."""
    requests: list[Any] = field(default_factory=list)
    """Each finished root's cost (``finos.cost.FinishedQuery``), for the ``--verbose`` cost line."""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _open: dict[Any, Span] = field(default_factory=dict, repr=False)

    @property
    def total_seconds(self) -> float:
        """Seconds since :func:`observe` was entered."""
        return time.perf_counter() - self.started

    def units(self) -> list[Unit]:
        """The report's lines: one per node run, else one per standalone root.

        Steps and model calls are assigned to the node (or root) whose time
        span holds them; nodes run one after another, so the spans don't
        overlap.
        """
        guards = [g for g in self.guards if any(g.contains(c.end) for c in self.calls)]

        def in_guards(call: ModelCall) -> bool:
            return any(g.contains(call.end) for g in guards)

        spans = list(self.nodes) or list(self.roots)
        units = []
        for span in sorted(spans + guards, key=lambda s: s.start):
            if any(span is g for g in guards):
                calls = [c for c in self.calls if span.contains(c.end)]
                units.append(Unit(name=GUARDS_UNIT, ms=span.ms, retrieval_ms=None, calls=calls))
                continue
            retrieval = [
                s.ms for s in self.steps if s.name == RETRIEVAL_STEP and span.contains(s.start)
            ]
            calls = [c for c in self.calls if span.contains(c.end) and not in_guards(c)]
            units.append(
                Unit(
                    name=span.name,
                    ms=span.ms,
                    retrieval_ms=sum(retrieval) if retrieval else None,
                    calls=calls,
                )
            )
        return units

    def timing_lines(self) -> list[str]:
        """The ``--verbose`` timing lines, ending with the total."""
        lines = [unit.line() for unit in self.units()]
        lines.append(f"total: {self.total_seconds:.2f} s")
        return lines

    # Callback-side recording; LangGraph may call these from worker threads.

    def _node_started(self, run_id: Any, name: str) -> None:
        span = Span(name, time.perf_counter())
        with self._lock:
            self._open[run_id] = span
            self.nodes.append(span)

    def _run_ended(self, run_id: Any) -> None:
        with self._lock:
            span = self._open.pop(run_id, None)
        if span is not None:
            span.end = time.perf_counter()

    def _add_call(self, call: ModelCall) -> None:
        with self._lock:
            self.calls.append(call)


@dataclass
class Request:
    """What one root run collected: its calls and guard decisions (design D3).

    Every root is its own scope, so concurrent roots in one observation (an
    evaluation's threads) never mix their calls.
    """

    name: str
    calls: list[ModelCall] = field(default_factory=list)
    guard_decisions: list[Any] = field(default_factory=list)
    blocked: bool = False
    crisis: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _add_call(self, call: ModelCall) -> None:
        with self._lock:
            self.calls.append(call)


_observation: ContextVar[Observation | None] = ContextVar("finos_observation", default=None)
_request: ContextVar[Request | None] = ContextVar("finos_request", default=None)
_handler: ContextVar[Any] = ContextVar("finos_timing_handler", default=None)
_hook_lock = threading.Lock()
_hook_registered = False


def current_observation() -> Observation | None:
    """Return the :class:`Observation` entered by the nearest :func:`observe`."""
    return _observation.get()


def current_request() -> Request | None:
    """Return the :class:`Request` of the nearest enclosing :func:`root`."""
    return _request.get()


def _collect(call: ModelCall) -> None:
    """Add ``call`` to the active observation and the active request."""
    observation = _observation.get()
    if observation is not None:
        observation._add_call(call)
    request = _request.get()
    if request is not None:
        request._add_call(call)


def add_guard_decision(decision: Any) -> None:
    """Record a guard decision on the active observation and request."""
    observation = _observation.get()
    if observation is not None:
        observation.guard_decisions.append(decision)
    request = _request.get()
    if request is not None:
        request.guard_decisions.append(decision)


def note_verdict(*, blocked: bool, crisis: bool) -> None:
    """Record the input verdict on the active request, for its audit record."""
    request = _request.get()
    if request is not None:
        request.blocked = blocked
        request.crisis = crisis


@contextmanager
def guard_span() -> Iterator[None]:
    """Time the input guards, so their model calls get their own timing line."""
    observation = _observation.get()
    span = Span(GUARDS_UNIT, time.perf_counter())
    if observation is not None:
        observation.guards.append(span)
    try:
        yield
    finally:
        span.end = time.perf_counter()


def record_call(
    role: str,
    provider: str | None,
    model: str | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    *,
    estimated: bool = False,
) -> None:
    """Record a model call that fires no LangChain chat callback (for cost).

    Used for moderation and the query embedding. Never raises.
    """
    try:
        _collect(
            ModelCall(
                time.perf_counter(),
                input_tokens,
                output_tokens,
                model=model,
                provider=provider,
                role=role,
                estimated=estimated,
                chat=False,
            )
        )
    except Exception:  # noqa: BLE001 - recording must never fail a request
        pass


@contextmanager
def observe(entry: str, *, metadata: Mapping[str, Any] | None = None) -> Iterator[Observation]:
    """Observe one command or test under the entry point ``entry``.

    Roots opened inside carry ``entry:<entry>`` and ``metadata``, record the
    trace ID here, and LangChain runs started inside report their timings
    and tokens here. Outside an observation nothing is collected.
    """
    _register_timing_hook()
    observation = Observation(entry=entry, metadata=dict(metadata or {}))
    obs_token = _observation.set(observation)
    handler_token = _handler.set(_timing_handler_class()(observation))
    try:
        yield observation
    finally:
        _handler.reset(handler_token)
        _observation.reset(obs_token)


def _register_timing_hook() -> None:
    """Register the timing handler with LangChain once per process.

    Registered on first use rather than at import, so importing this module
    stays free of LangChain and ``langsmith``. The hook adds the handler to
    a run's callbacks only while :data:`_handler` is set, that is, inside
    :func:`observe`.
    """
    global _hook_registered
    if _hook_registered:
        return
    with _hook_lock:
        if _hook_registered:
            return
        from langchain_core.tracers.context import register_configure_hook

        register_configure_hook(_handler, True)
        _hook_registered = True


@functools.cache
def _timing_handler_class() -> type:
    """Build the callback handler class on first use, keeping LangChain out of import."""
    from langchain_core.callbacks import BaseCallbackHandler

    class TimingHandler(BaseCallbackHandler):
        """Node durations and model token usage, for the active Observation."""

        raise_error = False

        def __init__(self, observation: Observation) -> None:
            self.observation = observation
            self._lock = threading.Lock()
            self._runs: dict[Any, tuple[str | None, Any]] = {}
            self._pending: dict[Any, tuple[str | None, str | None, str]] = {}

        def _role(self, name: str | None, parent: Any) -> str:
            """The nearest named run (this one, then its parents) that names a role."""
            seen = 0
            while seen < 64:
                if name in ROLE_BY_RUN:
                    return ROLE_BY_RUN[name]
                if name in NODE_NAMES:
                    return name
                if parent is None:
                    return "unknown"
                with self._lock:
                    name, parent = self._runs.get(parent, (None, None))
                seen += 1
            return "unknown"

        def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, name=None, **kwargs):
            run_name = kwargs.get("name") or name
            with self._lock:
                self._runs[run_id] = (run_name, parent_run_id)
            if run_name in NODE_NAMES:
                self.observation._node_started(run_id, run_name)

        def on_chain_end(self, outputs, *, run_id, **kwargs):
            self.observation._run_ended(run_id)

        def on_chain_error(self, error, *, run_id, **kwargs):
            self.observation._run_ended(run_id)

        def on_chat_model_start(
            self, serialized, messages, *, run_id, parent_run_id=None, metadata=None, name=None, **kwargs
        ):
            metadata = metadata or {}
            role = self._role(kwargs.get("name") or name, parent_run_id)
            with self._lock:
                self._pending[run_id] = (
                    metadata.get("ls_model_name"),
                    metadata.get("ls_provider"),
                    role,
                )

        def on_llm_end(self, response, *, run_id, **kwargs):
            with self._lock:
                model, provider, role = self._pending.pop(run_id, (None, None, "unknown"))
            usage = None
            try:
                message = response.generations[0][0].message
                usage = getattr(message, "usage_metadata", None)
                model = model or (getattr(message, "response_metadata", None) or {}).get("model_name")
            except (AttributeError, IndexError, TypeError):
                usage = None
            details = (usage or {}).get("input_token_details") or {}
            _collect_from(
                self.observation,
                ModelCall(
                    time.perf_counter(),
                    usage.get("input_tokens") if usage else None,
                    usage.get("output_tokens") if usage else None,
                    model=model,
                    provider=provider,
                    role=role,
                    cached_input_tokens=details.get("cache_read"),
                ),
            )

        def on_llm_error(self, error, *, run_id, **kwargs):
            with self._lock:
                self._pending.pop(run_id, None)

    return TimingHandler


def _collect_from(observation: Observation, call: ModelCall) -> None:
    """Add a chat call to the handler's observation and the active request."""
    observation._add_call(call)
    request = _request.get()
    if request is not None:
        request._add_call(call)


# --- Masking (design D5) -----------------------------------------------------

_SSN_FIELD_JSON = re.compile(r'("ssn_last4"\s*:\s*)(?:"[^"]*"|\d+)')
_SSN_FIELD_REPR = re.compile(r"('ssn_last4'\s*:\s*)(?:'[^']*'|\d+)")
_FULL_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


@functools.cache
def _known_ssn_pattern() -> re.Pattern[str] | None:
    """Every ``ssn_last4`` in the account records, as a standalone number.

    Loaded once, on first use. A missing or invalid records file gives
    ``None``: field and pattern masking still apply, and nothing is raised.
    Tests call ``_known_ssn_pattern.cache_clear()``.
    """
    try:
        from finos.accounts import load_accounts

        values = sorted(
            {
                str(record["ssn_last4"])
                for record in load_accounts().values()
                if str(record.get("ssn_last4", "")).strip()
            },
            key=len,
            reverse=True,
        )
    except Exception:  # noqa: BLE001 - masking must never fail a request
        return None
    if not values:
        return None
    alternatives = "|".join(re.escape(value) for value in values)
    return re.compile(rf"(?<!\d)(?:{alternatives})(?!\d)")


def _mask_text(text: str) -> str:
    text = _SSN_FIELD_JSON.sub(rf'\g<1>"{REDACTED}"', text)
    text = _SSN_FIELD_REPR.sub(rf"\g<1>'{REDACTED}'", text)
    text = _FULL_SSN.sub(REDACTED, text)
    known = _known_ssn_pattern()
    if known is not None:
        text = known.sub(REDACTED, text)
    return text


def mask(payload: Any) -> Any:
    """Return ``payload`` with Social Security data replaced by ``[REDACTED:ssn]``.

    Walks dicts, lists, tuples, and pydantic models (messages and prompt
    values, as dumped), and on every string masks:

    1. the ``ssn_last4`` field's value, in JSON and in Python repr form (a
       dict key ``ssn_last4`` is masked directly);
    2. every ``ssn_last4`` value in the account records, as a standalone
       number (no adjacent digit);
    3. full SSNs, ``ddd-dd-dddd``.

    Amounts, years, and account IDs such as ``ACC-12345`` are left alone.
    Used as the upload client's ``hide_inputs`` and ``hide_outputs``.
    """
    if isinstance(payload, str):
        return _mask_text(payload)
    if isinstance(payload, Mapping):
        return {
            key: (REDACTED if key == "ssn_last4" else mask(value))
            for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [mask(item) for item in payload]
    dump = getattr(payload, "model_dump", None)
    if callable(dump) and not isinstance(payload, type):
        try:
            return mask(dump())
        except Exception:  # noqa: BLE001 - leave what can't be dumped as is
            return payload
    return payload


_client_lock = threading.Lock()
_client: Any = None


def masking_client() -> Any:
    """Return this process's upload client, which masks every run with :func:`mask`."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                from langsmith import Client

                _client = Client(hide_inputs=mask, hide_outputs=mask)
    return _client


# --- Tags and metadata (design D4) ------------------------------------------


def _provider(settings: Mapping[str, Any]) -> str:
    return "ollama" if settings["llm"]["use_local_ollama_model"] else "openai"


def _prompt_versions() -> dict[str, str]:
    from finos import prompts

    named = {
        "supervisor": prompts.SUPERVISOR_SYSTEM_PROMPT,
        "policy": prompts.POLICY_SYSTEM_PROMPT,
        "account": prompts.ACCOUNT_SYSTEM_PROMPT,
        "escalation": prompts.ESCALATION_SYSTEM_PROMPT,
        "judge_faithfulness": prompts.JUDGE_FAITHFULNESS_PROMPT,
        "judge_correctness": prompts.JUDGE_CORRECTNESS_PROMPT,
        "judge_empathy": prompts.JUDGE_EMPATHY_PROMPT,
    }
    return {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        for name, text in named.items()
    }


def _index_fingerprint() -> str:
    import json

    from finos import config

    try:
        marker = json.loads((config.CHROMA_DIR / "finos_index.json").read_text("utf-8"))
    except (OSError, ValueError):
        return "none"
    value = marker.get("fingerprint") if isinstance(marker, dict) else None
    return str(value) if value else "none"


def _finos_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("finos")
    except PackageNotFoundError:
        return "unknown"


def root_tags(entry: str | None = None) -> list[str]:
    """The vocabulary's root tags: ``entry:<point>`` and ``provider:<name>``."""
    from finos.config import get_settings

    if entry is None:
        observation = current_observation()
        entry = observation.entry if observation else DEFAULT_ENTRY
    return [f"entry:{entry}", f"provider:{_provider(get_settings())}"]


def root_metadata() -> dict[str, Any]:
    """Configuration metadata for a root run. No value comes from a query or record."""
    from finos.config import get_settings

    settings = get_settings()
    provider = _provider(settings)
    policy = settings["policy"]
    return {
        "provider": provider,
        "chat_model": str(settings[provider]["model"]),
        "embedding_model": str(settings[provider]["embedding_model"]),
        "temperature": settings["llm"]["temperature"],
        "chunk_size": policy["chunk_size"],
        "chunk_overlap": policy["chunk_overlap"],
        "top_k": policy["top_k"],
        "collection": str(policy["collection"]),
        "index_fingerprint": _index_fingerprint(),
        "prompt_versions": _prompt_versions(),
        "finos_version": _finos_version(),
    }


# --- Roots, steps, and chains (design D1-D3) --------------------------------


class Root:
    """The handle :func:`root` yields: add tags or outputs before the run ends."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.trace_id: str | None = None
        self._run: Any = None
        self._tags: list[str] = []
        self._outputs: dict[str, Any] | None = None

    @property
    def traced(self) -> bool:
        return self._run is not None

    def add_tags(self, tags: list[str]) -> None:
        """Add tags to the root run when it ends (the late ``intent:*`` tag)."""
        self._tags.extend(tags)

    def set_outputs(self, outputs: Mapping[str, Any]) -> None:
        """Record what the root run returns."""
        self._outputs = dict(outputs)


def _tracing_active() -> bool:
    """Whether a root opened now would be traced (by settings or a tracing context)."""
    from langsmith.utils import tracing_is_enabled

    try:
        return bool(tracing_is_enabled())
    except Exception:  # noqa: BLE001
        return False


@contextmanager
def root(
    name: str,
    *,
    config: Mapping[str, Any] | None = None,
    inputs: Mapping[str, Any] | None = None,
) -> Iterator[Root]:
    """Open the root run of one request, named after its entry point.

    The run carries :func:`root_tags` and :func:`root_metadata`, plus any
    ``tags`` and ``metadata`` in ``config`` and the active observation's
    metadata, and uploads through :func:`masking_client`. Its trace ID is
    recorded on the active :class:`Observation`. With tracing off, the body
    runs untraced, and only its duration is collected.

    Every root is also a cost scope (design D3): the calls and guard
    decisions made in its body are collected on its own :class:`Request`,
    and when it ends :func:`finos.cost.finish` prices them, writes the audit
    record, and adds the cost to the run's metadata. A root opened outside
    :func:`observe` (a library caller) observes itself under entry ``api``.

    Exceptions from the body propagate unchanged; failures of tracing and of
    cost recording never do.
    """
    if current_observation() is None:
        with observe(DEFAULT_ENTRY):
            with root(name, config=config, inputs=inputs) as handle:
                yield handle
        return

    handle = Root(name)
    observation = current_observation()
    span = Span(name, time.perf_counter())
    if observation is not None:
        observation.roots.append(span)

    stack = ExitStack()
    try:
        run = _open_root(stack, name, config=config, inputs=inputs, observation=observation)
    except Exception:  # noqa: BLE001 - tracing must never fail a request
        stack.close()
        stack = ExitStack()
        run = None
    if run is not None:
        handle._run = run
        handle.trace_id = str(run.trace_id)
        if observation is not None:
            observation.trace_id = handle.trace_id

    request = Request(name)
    error: str | None = None
    with stack:
        token = _request.set(request)
        try:
            yield handle
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            span.end = time.perf_counter()
            _request.reset(token)
            _finish(request, handle, span, observation, inputs, error)
        if run is not None:
            try:
                if handle._tags:
                    run.add_tags(handle._tags)
                run.end(outputs=handle._outputs or {})
            except Exception:  # noqa: BLE001
                pass


def _finish(
    request: Request,
    handle: Root,
    span: Span,
    observation: Observation | None,
    inputs: Mapping[str, Any] | None,
    error: str | None,
) -> None:
    """Hand the finished request to :mod:`finos.cost`; never raises."""
    try:
        from finos import cost

        cost.finish(
            request,
            handle,
            latency_ms=span.ms,
            observation=observation,
            inputs=inputs,
            error=error,
        )
    except Exception:  # noqa: BLE001 - cost must never fail a request
        pass


def _open_root(
    stack: ExitStack,
    name: str,
    *,
    config: Mapping[str, Any] | None,
    inputs: Mapping[str, Any] | None,
    observation: Observation | None,
) -> Any:
    """Enter the tracing context and the root run on ``stack``; return the run or ``None``.

    Settings load first, so ``config.toml`` (and the no-key auto-off) has
    decided the tracing variables before the SDK reads them.
    """
    from finos.config import get_settings

    get_settings()
    if not _tracing_active():
        return None
    from langsmith import run_helpers

    config = config or {}
    tags = root_tags(observation.entry if observation else None)
    tags += [tag for tag in config.get("tags", ()) if tag not in tags]
    metadata = root_metadata()
    if observation is not None:
        metadata.update(observation.metadata)
    metadata.update(config.get("metadata", {}) or {})

    project = tracing_status().project
    client = masking_client()
    stack.enter_context(
        run_helpers.tracing_context(client=client, project_name=project, enabled=True)
    )
    return stack.enter_context(
        run_helpers.trace(
            name,
            run_type="chain",
            inputs=dict(inputs or {}),
            tags=tags,
            metadata=metadata,
            client=client,
            project_name=project,
        )
    )


def _current_run() -> Any:
    """The run a step would nest under, without importing ``langsmith`` needlessly."""
    if "langsmith" not in sys.modules:
        return None
    from langsmith.run_helpers import get_current_run_tree

    try:
        return get_current_run_tree()
    except Exception:  # noqa: BLE001
        return None


def step(
    name: str,
    run_type: str,
    *,
    inputs: Callable[..., Mapping[str, Any]] | None = None,
    outputs: Callable[[Any], Any] | None = None,
) -> Callable[[_F], _F]:
    """Wrap a plain-Python step as a traced run named ``name``.

    ``inputs`` maps the call's arguments, and ``outputs`` the return value,
    to what the run records; the function's own return value never changes.
    The step is traced only beneath a traced run (a root, or a node of a
    traced graph), and its duration is collected in the active observation
    either way.
    """

    def decorate(func: _F) -> _F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            observation = current_observation()
            span = Span(name, time.perf_counter())
            if observation is not None:
                observation.steps.append(span)
            try:
                parent = _current_run()
                if parent is None:
                    return func(*args, **kwargs)
                return _traced_call(
                    name, run_type, func, args, kwargs, inputs=inputs, outputs=outputs
                )
            finally:
                span.end = time.perf_counter()

        return wrapper  # type: ignore[return-value]

    return decorate


def _traced_call(
    name: str,
    run_type: str,
    func: Callable[..., Any],
    args: tuple,
    kwargs: dict,
    *,
    inputs: Callable[..., Mapping[str, Any]] | None,
    outputs: Callable[[Any], Any] | None,
) -> Any:
    from langsmith import run_helpers

    stack = ExitStack()
    try:
        recorded = dict(inputs(*args, **kwargs)) if inputs else {"args": list(args), **kwargs}
        run = stack.enter_context(
            run_helpers.trace(name, run_type=run_type, inputs=recorded)  # type: ignore[arg-type]
        )
    except Exception:  # noqa: BLE001 - tracing must never fail a request
        stack.close()
        return func(*args, **kwargs)
    with stack:
        result = func(*args, **kwargs)
        try:
            shaped = outputs(result) if outputs else result
            run.end(outputs=shaped if isinstance(shaped, dict) else {"output": shaped})
        except Exception:  # noqa: BLE001
            pass
        return result


def chain_config(name: str) -> dict[str, Any]:
    """The ``with_config`` arguments that name a chain's run."""
    return {"run_name": name}
