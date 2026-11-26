"""The root ``finos`` app and its module registrations.

To add a module, create ``finos/cli/<module>.py`` with a ``typer.Typer``
group (``no_args_is_help=True``) whose commands use
:func:`~finos.cli.shared.shared_options`, then register it below with one
``app.add_typer`` line. Keep heavy imports inside command bodies.
"""

from importlib.metadata import version as package_version
from typing import Annotated

import typer

from finos.cli.account import account_app
from finos.cli.cost import cost_app
from finos.cli.escalation import escalation_app
from finos.cli.eval import eval_app
from finos.cli.guard import guard_app
from finos.cli.policy import policy_app
from finos.cli.shared import JsonOption, NoColorOption, VerboseOption
from finos.cli.state import state_app
from finos.cli.supervisor import supervisor_app

app = typer.Typer(
    name="finos",
    help="SecureBank multi-agent support system.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
    rich_markup_mode=None,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"finos {package_version('finos')}")
        raise typer.Exit()


@app.callback()
def root(
    shared_json: JsonOption = False,
    shared_verbose: VerboseOption = False,
    shared_no_color: NoColorOption = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Print the installed version and exit.",
            callback=_print_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """SecureBank multi-agent support system."""


app.add_typer(state_app, name="state")
app.add_typer(policy_app, name="policy")
app.add_typer(account_app, name="account")
app.add_typer(escalation_app, name="escalation")
app.add_typer(supervisor_app, name="supervisor")
app.add_typer(eval_app, name="eval")
app.add_typer(guard_app, name="guard")
app.add_typer(cost_app, name="cost")


def main() -> None:
    """Run the ``finos`` command line."""
    app(prog_name="finos")
