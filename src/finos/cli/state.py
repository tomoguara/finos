"""``finos state``: inspect, validate, and convert ``SupportState`` values.

No command here loads settings, calls a model, or touches the network.
``validate``, ``serialize``, and ``deserialize`` read one state from
``--data`` or ``--file`` (``-`` is stdin), validate it against the contract,
and then report, re-print, or convert it. ``--file`` is always input; the
converters write to stdout, or to ``--output`` (see design D10).
"""

import json
import sys
from pathlib import Path
from typing import Annotated, Any, get_type_hints

import typer

from finos.cli.shared import (
    debug,
    emit_json,
    fail_usage,
    format_json,
    options,
    shared_options,
)
from finos.state import (
    FIELD_METADATA,
    PLANNED_FIELDS,
    SupportState,
    initial_state,
    validate_state,
)

state_app = typer.Typer(
    help="Inspect, validate, and convert SupportState values.",
    no_args_is_help=True,
    rich_markup_mode=None,
)

DataOption = Annotated[
    str | None, typer.Option("--data", "-d", help="The state as JSON text.")
]
FileOption = Annotated[
    str | None,
    typer.Option(
        "--file", "-f", help="Read the state (JSON) from this file; - for stdin."
    ),
]
OutputOption = Annotated[
    str | None,
    typer.Option(
        "--output",
        "-o",
        help="Write the result to this file instead of stdout; - for stdout. "
        "Missing parent directories are created.",
    ),
]
ForceOption = Annotated[
    bool, typer.Option("--force", help="Overwrite the --output file if it exists.")
]


def _type_name(annotation: Any) -> str:
    return annotation.__name__ if isinstance(annotation, type) and not getattr(
        annotation, "__args__", None
    ) else str(annotation)


def _table(rows: list[list[str]]) -> None:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        cells = [cell.ljust(width) for cell, width in zip(row, widths)]
        typer.echo("  ".join(cells).rstrip())


def _read_state(ctx: typer.Context, data: str | None, file: str | None) -> Any:
    """Read and parse one state from exactly one source, or exit 2."""
    if (data is None) == (file is None):
        fail_usage("provide exactly one of --data or --file")
    if data is not None:
        label = "--data"
        try:
            data.encode("utf-8")
        except UnicodeEncodeError:
            fail_usage("--data is not valid UTF-8")
        text = data
    else:
        assert file is not None
        if file == "-":
            label = "stdin"
            raw = sys.stdin.buffer.read()
        else:
            label = f"file '{file}'"
            try:
                with open(file, "rb") as handle:
                    raw = handle.read()
            except OSError as error:
                fail_usage(f"cannot read file '{file}': {error.strerror or error}")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            fail_usage(f"{label} is not valid UTF-8")
    debug(ctx, f"reading state from {label}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        fail_usage(f"{label} is not valid JSON: {error}")


def _read_valid_state(
    ctx: typer.Context, data: str | None, file: str | None
) -> dict[str, Any]:
    """Read a state for a converter; on invalid state, report on stderr, exit 1."""
    value = _read_state(ctx, data, file)
    errors = validate_state(value)
    if errors:
        for error in errors:
            typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1)
    return {name: value[name] for name in FIELD_METADATA}


def _check_output_options(output: str | None, force: bool) -> None:
    if force and output is None:
        fail_usage("--force requires --output")


def _write_output(
    ctx: typer.Context, text: str, output: str | None, force: bool
) -> None:
    """Send converter output to stdout or to ``--output``; exit 2 if unwritable.

    Called only after validation, so an invalid state never touches the file.
    Without ``--force`` the file is created exclusively, so an existing file
    is never overwritten.
    """
    if output is None or output == "-":
        typer.echo(text)
        return
    path = Path(output)
    if path.is_dir():
        fail_usage(f"cannot write '{output}': it is a directory")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        fail_usage(f"cannot write '{output}': {error.strerror or error}")
    try:
        with path.open("w" if force else "x", encoding="utf-8", newline="") as handle:
            handle.write(text + "\n")
    except FileExistsError:
        fail_usage(f"output file '{output}' already exists; use --force to overwrite")
    except OSError as error:
        fail_usage(f"cannot write '{output}': {error.strerror or error}")
    debug(ctx, f"wrote {path}")


def _known_sources(ctx: typer.Context) -> frozenset[str]:
    from finos import config

    directory = config.POLICY_DOCS_DIR
    if not directory.is_dir():
        fail_usage(f"policy documents directory not found: {directory}")
    names = frozenset(
        path.name
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )
    debug(ctx, f"{len(names)} known sources in {directory}")
    return names


@state_app.command()
@shared_options
def show(ctx: typer.Context) -> None:
    """Show each SupportState field with its type and description."""
    hints = get_type_hints(SupportState)
    fields = [
        {
            "name": name,
            "type": _type_name(hints[name]),
            "description": info["description"],
        }
        for name, info in FIELD_METADATA.items()
    ]
    if options(ctx).json:
        emit_json({"name": SupportState.__name__, "fields": fields})
        return
    typer.echo(SupportState.__name__)
    typer.echo()
    _table(
        [["Field", "Type", "Description"]]
        + [[f["name"], f["type"], f["description"]] for f in fields]
    )


@state_app.command()
@shared_options
def describe(ctx: typer.Context) -> None:
    """Show each field's initial value, writer, and readers."""
    fields = [{"name": name, **info} for name, info in FIELD_METADATA.items()]
    planned = [{"name": name, "note": note} for name, note in PLANNED_FIELDS.items()]
    if options(ctx).json:
        emit_json(
            {
                "name": SupportState.__name__,
                "fields": [
                    {k: f[k] for k in ("name", "initial", "written_by", "read_by")}
                    for f in fields
                ],
                "planned": planned,
            }
        )
        return
    _table(
        [["Field", "Initial value", "Written by", "Read by"]]
        + [[f["name"], f["initial"], f["written_by"], f["read_by"]] for f in fields]
    )
    typer.echo()
    for entry in planned:
        typer.echo(f"Planned: {entry['name']} - {entry['note']}")


@state_app.command()
@shared_options
def init(
    ctx: typer.Context,
    query: Annotated[
        str, typer.Option("--query", "-q", help="The customer's question.")
    ] = "",
) -> None:
    """Print a new state as JSON, with every other field at its initial value."""
    emit_json(initial_state(query))


@state_app.command()
@shared_options
def validate(
    ctx: typer.Context,
    data: DataOption = None,
    file: FileOption = None,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Also check sources against the policy documents and "
            "that only policy states carry retrieval fields.",
        ),
    ] = False,
) -> None:
    """Check a state against the contract. Exits 1 if it is invalid."""
    value = _read_state(ctx, data, file)
    known = _known_sources(ctx) if strict else frozenset()
    errors = validate_state(value, strict=strict, known_sources=known)
    shared = options(ctx)
    if shared.json:
        emit_json({"valid": not errors, "errors": errors})
    elif errors:
        typer.secho("invalid SupportState", fg="red", color=shared.color)
        for error in errors:
            typer.echo(f"  - {error}")
    else:
        typer.secho("valid SupportState", fg="green", color=shared.color)
    if errors:
        raise typer.Exit(1)


@state_app.command()
@shared_options
def serialize(
    ctx: typer.Context,
    data: DataOption = None,
    file: FileOption = None,
    compact: Annotated[
        bool, typer.Option("--compact", help="Print one line with no extra whitespace.")
    ] = False,
    sort_keys: Annotated[
        bool, typer.Option("--sort-keys", help="Order fields alphabetically.")
    ] = False,
    output: OutputOption = None,
    force: ForceOption = False,
) -> None:
    """Validate a state and print it as canonical JSON in contract order.

    The output is already JSON, so --json changes nothing here.
    """
    _check_output_options(output, force)
    state = _read_valid_state(ctx, data, file)
    text = format_json(state, compact=compact, sort_keys=sort_keys)
    _write_output(ctx, text, output, force)


@state_app.command()
@shared_options
def deserialize(
    ctx: typer.Context,
    data: DataOption = None,
    file: FileOption = None,
    output: OutputOption = None,
    force: ForceOption = False,
) -> None:
    """Validate a state and print it as a SupportState(...) expression."""
    _check_output_options(output, force)
    state = _read_valid_state(ctx, data, file)
    if options(ctx).json:
        text = format_json(state)
    else:
        arguments = ", ".join(f"{name}={value!r}" for name, value in state.items())
        text = f"{SupportState.__name__}({arguments})"
    _write_output(ctx, text, output, force)
