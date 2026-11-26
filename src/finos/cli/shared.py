"""Options and output helpers shared by every CLI module.

``--json/-j``, ``--verbose/-v``, and ``--no-color`` work both before the
module name and after the command. Each option's callback records ``True``
on the root context's ``obj``, and options only ever turn on, so a flag set
in either position (or both) counts once. The root callback declares the
options directly; commands get them from :func:`shared_options` and read
them with :func:`options`.

``-j``, ``-v``, and ``-V`` are reserved across all modules.

Exit codes: 0 success, 1 input understood but rejected on its merits,
2 unusable invocation or input (reported on stderr as plain text).

Commands that call a model run inside :func:`observed`, which reports
tracing on stderr when they succeed (:func:`report_tracing`).
"""

import functools
import inspect
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, Any, Callable, NoReturn, TypeVar

import typer

_F = TypeVar("_F", bound=Callable[..., Any])


def _record(key: str) -> Callable[[typer.Context, bool], bool]:
    def callback(ctx: typer.Context, value: bool) -> bool:
        if value:
            root = ctx.find_root()
            if root.obj is None:
                root.obj = {}
            root.obj[key] = True
        return value

    return callback


JsonOption = Annotated[
    bool,
    typer.Option(
        "--json", "-j", help="Print machine-readable JSON.", callback=_record("json")
    ),
]
VerboseOption = Annotated[
    bool,
    typer.Option(
        "--verbose",
        "-v",
        help="Write diagnostic detail to stderr.",
        callback=_record("verbose"),
    ),
]
NoColorOption = Annotated[
    bool,
    typer.Option(
        "--no-color",
        help="Disable colored output (also set by NO_COLOR).",
        callback=_record("no_color"),
    ),
]

_SHARED_PARAMETERS: dict[str, Any] = {
    "shared_json": JsonOption,
    "shared_verbose": VerboseOption,
    "shared_no_color": NoColorOption,
}


def shared_options(func: _F) -> _F:
    """Add the shared options to a command.

    The options are appended to the function's signature for Typer to read,
    and removed again before the function is called. The command takes
    ``ctx: typer.Context`` and reads them with :func:`options`.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        for name in _SHARED_PARAMETERS:
            kwargs.pop(name, None)
        return func(*args, **kwargs)

    signature = inspect.signature(func)
    extra = [
        inspect.Parameter(
            name, inspect.Parameter.KEYWORD_ONLY, default=False, annotation=annotation
        )
        for name, annotation in _SHARED_PARAMETERS.items()
    ]
    wrapper.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=[*signature.parameters.values(), *extra]
    )
    wrapper.__annotations__ = {**func.__annotations__, **_SHARED_PARAMETERS}
    return wrapper  # type: ignore[return-value]


@dataclass(frozen=True)
class SharedOptions:
    """The shared options in effect for this invocation."""

    json: bool
    verbose: bool
    no_color: bool

    @property
    def color(self) -> bool | None:
        """``False`` to strip color; ``None`` lets Click check for a terminal."""
        if self.no_color or os.environ.get("NO_COLOR"):
            return False
        return None


def options(ctx: typer.Context) -> SharedOptions:
    """Return the shared options set in either position."""
    obj = ctx.find_root().obj or {}
    return SharedOptions(
        json=bool(obj.get("json")),
        verbose=bool(obj.get("verbose")),
        no_color=bool(obj.get("no_color")),
    )


def format_json(data: Any, *, compact: bool = False, sort_keys: bool = False) -> str:
    """Format ``data`` as JSON, keeping non-ASCII text as is."""
    if compact:
        return json.dumps(
            data, ensure_ascii=False, separators=(",", ":"), sort_keys=sort_keys
        )
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=sort_keys)


def emit_json(data: Any, *, compact: bool = False, sort_keys: bool = False) -> None:
    """Print ``data`` as JSON on stdout, keeping non-ASCII text as is."""
    typer.echo(format_json(data, compact=compact, sort_keys=sort_keys))


def fail_usage(message: str) -> NoReturn:
    """Report unusable invocation or input on stderr and exit 2."""
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(2)


def debug(ctx: typer.Context, message: str) -> None:
    """Write a diagnostic line to stderr when ``--verbose`` is set."""
    if options(ctx).verbose:
        typer.echo(f"debug: {message}", err=True)


NO_KEY_LINE = "tracing: off (no LANGSMITH_API_KEY or LANGCHAIN_API_KEY set)"
"""Written once by a model-calling command when tracing is on but no key is set."""

GUARDRAILS_NO_KEY_LINE = "guardrails: {layers} off (no OPENAI_API_KEY)"
"""Written once by a model-calling command when model-based guards are enabled without a key."""

_QUIET_DECISIONS = ("passed", "skipped", "off")


@contextmanager
def observed(ctx: typer.Context, entry: str) -> Iterator[Any]:
    """Run a model-calling command under ``observe(entry)``, then report tracing.

    The report runs only when the body completes, after its stdout; a
    command that fails keeps its single ``Error:`` line on stderr.
    """
    from finos.observability import observe

    with observe(entry) as observation:
        yield observation
        report_tracing(ctx)


def report_tracing(ctx: typer.Context) -> None:
    """Write what a model-calling command reports about tracing, on stderr.

    - With tracing on in ``config.toml`` but no API key: :data:`NO_KEY_LINE`,
      verbose or not. It is the only tracing line without ``--verbose``.
    - With model-based guardrails enabled but no ``OPENAI_API_KEY``:
      :data:`GUARDRAILS_NO_KEY_LINE`, verbose or not.
    - With ``--verbose``: ``guardrail: <decision>`` for each guard that did
      anything but pass (``regex blocked (investment_advice)``).
    - With ``--verbose``: ``trace: <id> (project <p>)``, or ``trace: none
      (tracing off)``; below a 1.0 sampling rate the line says the trace may
      not be recorded. Then one timing line per node or standalone step
      (and ``guards:`` when an input guard made a model call), the total,
      and the cost line (``cost: $0.000241 (...)``, or ``cost: unpriced``).

    Never raises: settings that can't be loaded report nothing.
    """
    try:
        from finos.config import NO_API_KEY, tracing_status
        from finos.observability import current_observation

        status = tracing_status()
    except Exception:  # noqa: BLE001 - the command's own result stands
        return
    if status.off_reason == NO_API_KEY:
        typer.echo(NO_KEY_LINE, err=True)
    report_guardrails_key()
    if not options(ctx).verbose:
        return
    observation = current_observation()
    if observation is not None:
        for decision in observation.guard_decisions:
            if decision.decision not in _QUIET_DECISIONS:
                debug(ctx, f"guardrail: {decision.line()}")
    trace_id = observation.trace_id if observation else None
    if trace_id is None:
        debug(ctx, "trace: none (tracing off)")
    elif status.sampling_rate < 1.0:
        debug(
            ctx,
            f"trace: {trace_id} (project {status.project}, "
            f"sampling {status.sampling_rate:g}: may not be recorded)",
        )
    else:
        debug(ctx, f"trace: {trace_id} (project {status.project})")
    if observation is not None:
        for line in observation.timing_lines():
            debug(ctx, line)
        try:
            from finos.cost import cost_line

            line = cost_line(observation.requests)
        except Exception:  # noqa: BLE001 - the command's own result stands
            line = None
        if line:
            debug(ctx, line)


def report_guardrails_key() -> None:
    """Write :data:`GUARDRAILS_NO_KEY_LINE` when enabled model layers lack a key.

    Never raises: settings that can't be loaded report nothing.
    """
    try:
        from finos.guardrails.input import guardrails_status

        off = guardrails_status()["off_without_key"]
    except Exception:  # noqa: BLE001 - the command's own result stands
        return
    if off:
        typer.echo(GUARDRAILS_NO_KEY_LINE.format(layers=" and ".join(off)), err=True)


def one_line(text: Any) -> str:
    """Collapse whitespace, including newlines, into single spaces."""
    return " ".join(str(text).split())


def provider_summary() -> str:
    """Name the configured provider and models, for error messages.

    Returns ``""`` if settings can't be loaded; the caller's own error is
    reported instead.
    """
    try:
        from finos.config import get_settings

        settings = get_settings()
    except Exception:  # noqa: BLE001 - the original error is reported instead
        return ""
    if settings["llm"]["use_local_ollama_model"]:
        ollama = settings["ollama"]
        return (
            f"ollama at {ollama['base_url']}, chat model {ollama['model']}, "
            f"embedding model {ollama['embedding_model']}"
        )
    openai = settings["openai"]
    return f"openai, chat model {openai['model']}, embedding model {openai['embedding_model']}"


def fail_runtime(ctx: typer.Context, error: Exception, *, provider: bool = False) -> NoReturn:
    """Report a valid command that could not complete, on one stderr line; exit 1.

    Used for provider failures (``provider=True`` appends the configured
    provider and models) and environment failures such as a missing data
    file. No traceback, even under ``--json``; ``--verbose`` adds the
    exception type.
    """
    debug(ctx, f"{type(error).__module__}.{type(error).__name__}")
    message = one_line(error) or type(error).__name__
    summary = provider_summary() if provider else ""
    if summary:
        message = f"{message} ({summary})"
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(1)
