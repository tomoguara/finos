"""Tests for the CLI framework (Step 1b): entry points and shared options.

Shared-option behavior is exercised through a small test-only module, so
these tests don't depend on what any real command prints.
"""

from __future__ import annotations

import re
import subprocess
import sys
from importlib.metadata import version
from typing import Annotated

import pytest
import typer
from typer.testing import CliRunner

from finos.cli.main import app, root
from finos.cli.shared import debug, emit_json, options, shared_options

ANSI = "\x1b["

probe_app = typer.Typer(no_args_is_help=True, rich_markup_mode=None)


@probe_app.command()
@shared_options
def echo(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", "-n")] = "probe",
) -> None:
    """Print a colored name, or JSON with the options in effect."""
    shared = options(ctx)
    debug(ctx, "probe diagnostics")
    if shared.json:
        emit_json({"name": name})
    else:
        typer.secho(name, fg="green", color=shared.color)


@probe_app.command()
def plain() -> None:
    """A command without the shared options."""


def _test_app() -> typer.Typer:
    """A root app with the real root callback plus the probe module."""
    test_app = typer.Typer(no_args_is_help=True, rich_markup_mode=None)
    test_app.callback()(root)
    test_app.add_typer(probe_app, name="probe")
    return test_app


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.delenv("NO_COLOR", raising=False)
    return CliRunner()


def invoke(runner: CliRunner, args: list[str], **kwargs):
    return runner.invoke(_test_app(), args, prog_name="finos", **kwargs)


# --- Shared options ---------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["--json", "probe", "echo"],
        ["probe", "echo", "--json"],
        ["-j", "probe", "echo", "-j"],
    ],
)
def test_json_flag_in_any_position(runner: CliRunner, args: list[str]):
    result = invoke(runner, args)
    assert result.exit_code == 0, result.output
    assert result.stdout.strip().startswith("{")
    assert '"name": "probe"' in result.stdout


def test_flag_positions_give_identical_output(runner: CliRunner):
    before = invoke(runner, ["--json", "probe", "echo"])
    after = invoke(runner, ["probe", "echo", "--json"])
    both = invoke(runner, ["--json", "probe", "echo", "--json"])
    assert before.stdout == after.stdout == both.stdout


def test_commands_own_options_work_alongside(runner: CliRunner):
    result = invoke(runner, ["-v", "probe", "echo", "--name", "x", "-j"])
    assert result.exit_code == 0, result.output
    assert '"name": "x"' in result.stdout
    assert "probe diagnostics" in result.stderr


def test_shared_options_listed_in_command_help(runner: CliRunner):
    result = invoke(runner, ["probe", "echo", "--help"])
    assert result.exit_code == 0
    for flag in ("--json", "-j", "--verbose", "-v", "--no-color", "--name"):
        assert flag in result.stdout


def test_shared_options_listed_in_root_help(runner: CliRunner):
    result = runner.invoke(app, ["--help"], prog_name="finos")
    assert result.exit_code == 0
    for flag in ("--json", "--verbose", "--no-color", "--version"):
        assert flag in result.stdout
    assert "state" in result.stdout


def test_json_flag_takes_no_value(runner: CliRunner):
    result = invoke(runner, ["probe", "echo", "--json", '{"query":"test"}'])
    assert result.exit_code == 2
    assert result.stdout == ""


# --- Color ------------------------------------------------------------------


def test_color_is_emitted_on_a_terminal(runner: CliRunner):
    result = invoke(runner, ["probe", "echo"], color=True)
    assert ANSI in result.stdout


@pytest.mark.parametrize(
    "args", [["--no-color", "probe", "echo"], ["probe", "echo", "--no-color"]]
)
def test_no_color_flag_strips_color(runner: CliRunner, args: list[str]):
    result = invoke(runner, args, color=True)
    assert result.exit_code == 0
    assert ANSI not in result.stdout
    assert "probe" in result.stdout


def test_no_color_environment_variable_strips_color(runner: CliRunner):
    result = invoke(runner, ["probe", "echo"], color=True, env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    assert ANSI not in result.stdout


def test_empty_no_color_variable_is_ignored(runner: CliRunner):
    result = invoke(runner, ["probe", "echo"], color=True, env={"NO_COLOR": ""})
    assert ANSI in result.stdout


def test_color_is_stripped_when_not_a_terminal(runner: CliRunner):
    result = invoke(runner, ["probe", "echo"])
    assert ANSI not in result.stdout


# --- Verbose ----------------------------------------------------------------


@pytest.mark.parametrize("extra", [[], ["--json"]])
def test_verbose_writes_only_to_stderr(runner: CliRunner, extra: list[str]):
    quiet = invoke(runner, ["probe", "echo", *extra])
    loud = invoke(runner, ["-v", "probe", "echo", "-v", *extra])
    assert quiet.stdout == loud.stdout
    assert quiet.exit_code == loud.exit_code == 0
    assert quiet.stderr == ""
    assert "probe diagnostics" in loud.stderr


# --- Bare commands, version, errors -----------------------------------------


def test_bare_root_shows_help_and_exits_2(runner: CliRunner):
    result = runner.invoke(app, [], prog_name="finos")
    assert result.exit_code == 2
    assert "Usage: finos" in result.output
    assert "state" in result.output


def test_bare_module_shows_help_and_exits_2(runner: CliRunner):
    result = runner.invoke(app, ["state"], prog_name="finos")
    assert result.exit_code == 2
    assert "Usage: finos state" in result.output


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_version_flag(runner: CliRunner, flag: str):
    result = runner.invoke(app, [flag], prog_name="finos")
    assert result.exit_code == 0
    assert result.stdout.strip() == f"finos {version('finos')}"


def test_unknown_option_exits_2_on_stderr(runner: CliRunner):
    result = invoke(runner, ["probe", "echo", "--bogus", "--json"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "--bogus" in result.stderr
    assert not result.stderr.lstrip().startswith("{")


# --- Entry points and import weight -----------------------------------------


def test_main_uses_finos_as_program_name(monkeypatch: pytest.MonkeyPatch, capsys):
    from finos.cli import main as cli_main

    monkeypatch.setattr(sys, "argv", ["anything", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        cli_main.main()
    assert exit_info.value.code == 0
    assert "Usage: finos " in capsys.readouterr().out


def test_module_invocation_matches_script():
    module = subprocess.run(
        [sys.executable, "-m", "finos", "state", "show"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert module.returncode == 0, module.stderr
    script = CliRunner().invoke(app, ["state", "show"], prog_name="finos")
    assert module.stdout == script.stdout


def test_importing_the_cli_stays_light():
    code = (
        "import sys, finos.cli.main\n"
        "heavy = sorted({m.split('.')[0] for m in sys.modules}"
        " & {'langchain', 'langgraph', 'chromadb', 'langchain_core', 'langsmith'})\n"
        "print(','.join(heavy))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


# =============================================================================
# Tracing on the command line (hardening 1, observability: design D6, D7)
# =============================================================================

TRACED_COMMANDS = {
    "supervisor ask": ["supervisor", "ask", "-q", "What is the overdraft fee?"],
    "supervisor classify": ["supervisor", "classify", "-q", "What is the overdraft fee?"],
    "policy ask": ["policy", "ask", "-q", "What is the overdraft fee?"],
    "policy search": ["policy", "search", "-q", "What is the overdraft fee?"],
    "account ask": ["account", "ask", "-q", "What is the balance on ACC-12345?"],
    "escalation ask": ["escalation", "ask", "-q", "I'm furious!"],
}
"""Every model-calling command, with a query each can answer offline."""

UNTRACED_COMMANDS = {
    "supervisor graph": ["supervisor", "graph"],
    "policy ingest": ["policy", "ingest"],
    "account lookup": ["account", "lookup", "-i", "ACC-12345"],
    "account list": ["account", "list"],
    "escalation contact": ["escalation", "contact"],
    "state show": ["state", "show"],
}
"""Commands that call no model, so they report nothing about tracing."""

ROOTS = {
    "supervisor ask": "support_query",
    "supervisor classify": "supervisor_classify",
    "policy ask": "policy_query",
    "policy search": "policy_search",
    "account ask": "account_query",
    "escalation ask": "escalation_query",
}


def _invoke(*args: str):
    return CliRunner().invoke(app, list(args), prog_name="finos")


@pytest.fixture
def offline_models(policy_env, recording_chat, monkeypatch):
    """Tracing on in the private config, no LangSmith key, fake models."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    recording_chat.reply = "policy"  # a clean route for the supervisor
    policy_env.set_config("tracing = false", "tracing = true")
    return policy_env


@pytest.fixture
def fake_tracing(offline_models, monkeypatch):
    """Tracing on with a fake key and an offline recording client."""
    from langsmith import tracing_context

    from finos import observability
    from tests.test_observability import FakeClient

    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-test-not-a-real-key")
    offline_models.clear_caches()
    fake = FakeClient(hide_inputs=observability.mask, hide_outputs=observability.mask)
    monkeypatch.setattr(observability, "masking_client", lambda: fake)
    with tracing_context(enabled=True, client=fake, project_name="finos"):
        yield fake


@pytest.mark.parametrize("name", list(TRACED_COMMANDS))
def test_no_key_line_is_written_once(offline_models, name):
    from finos.cli.shared import NO_KEY_LINE

    quiet = _invoke(*TRACED_COMMANDS[name])
    loud = _invoke(*TRACED_COMMANDS[name], "-v")
    assert quiet.exit_code == loud.exit_code == 0, quiet.output
    assert quiet.stderr.splitlines() == [NO_KEY_LINE]
    assert loud.stderr.count(NO_KEY_LINE) == 1
    assert "debug: trace: none (tracing off)" in loud.stderr
    assert quiet.stdout == loud.stdout


@pytest.mark.parametrize("name", list(TRACED_COMMANDS))
def test_no_key_output_matches_tracing_off(offline_models, name):
    """stdout and the exit code are the same as with tracing = false."""
    with_tracing = _invoke(*TRACED_COMMANDS[name])
    offline_models.set_config("tracing = true", "tracing = false")
    without = _invoke(*TRACED_COMMANDS[name])
    assert with_tracing.exit_code == without.exit_code == 0
    assert with_tracing.stdout == without.stdout
    assert without.stderr == ""


@pytest.mark.parametrize("name", list(TRACED_COMMANDS))
def test_verbose_trace_line_names_the_trace(fake_tracing, name):
    quiet = _invoke(*TRACED_COMMANDS[name])
    loud = _invoke(*TRACED_COMMANDS[name], "-v")
    assert quiet.exit_code == loud.exit_code == 0, loud.output
    assert quiet.stderr == ""
    assert quiet.stdout == loud.stdout
    roots = fake_tracing.named(ROOTS[name])
    assert len(roots) == 2 and len(fake_tracing.roots()) == 2
    trace_id = roots[-1]["trace_id"]
    assert f"debug: trace: {trace_id} (project finos)\n" in loud.stderr
    assert f"entry:{name.replace(' ', '-')}" in roots[-1]["tags"]


def test_verbose_trace_line_notes_sampling(fake_tracing, offline_models):
    offline_models.set_config("sampling_rate = 1.0", "sampling_rate = 0.25")
    result = _invoke("policy", "ask", "-q", "What is the overdraft fee?", "-v")
    assert result.exit_code == 0
    trace_id = fake_tracing.one("policy_query")["trace_id"]
    assert (
        f"debug: trace: {trace_id} (project finos, sampling 0.25: may not be recorded)"
        in result.stderr
    )


def test_verbose_trace_line_with_tracing_off(policy_env, recording_chat):
    result = _invoke("supervisor", "ask", "-q", "What is the overdraft fee?", "-v")
    assert result.exit_code == 0
    assert "debug: trace: none (tracing off)" in result.stderr
    assert "tracing: off" not in result.stderr


@pytest.mark.parametrize(
    "name, units",
    [
        ("supervisor ask", ["classify_intent", "policy_agent"]),
        ("supervisor classify", ["supervisor_classify"]),
        ("policy ask", ["policy_query"]),
        ("policy search", ["policy_search"]),
        ("account ask", ["account_query"]),
        ("escalation ask", ["escalation_query"]),
    ],
)
def test_verbose_timing_lines(policy_env, recording_chat, name, units):
    recording_chat.reply = "policy"
    result = _invoke(*TRACED_COMMANDS[name], "-v")
    assert result.exit_code == 0, result.output
    lines = result.stderr.splitlines()
    start = lines.index("debug: trace: none (tracing off)")
    # The timing lines, the total, then the cost line (Hardening 4).
    cost_line = lines[-1]
    timing = lines[start + 1 : -1]
    assert cost_line.startswith("debug: cost: ")
    assert re.search(r" calls?; prices as of 2026-11-20\)$", cost_line)
    assert [line.split(":")[1].strip() for line in timing[:-1]] == units
    assert re.fullmatch(r"debug: total: \d+\.\d\d s", timing[-1])
    for line in timing[:-1]:
        assert re.search(r": \d+ ms", line)
    if name in ("supervisor ask", "policy ask"):
        retrieval_line = timing[-2]
        assert re.search(r"\d+ ms \(retrieval \d+ ms\)", retrieval_line)
    if name != "policy search":
        # The recording fake reports no usage, so model calls read n/a.
        assert timing[-2].endswith(", n/a tokens")


@pytest.mark.parametrize("name", list(UNTRACED_COMMANDS))
def test_commands_without_a_model_report_no_tracing(offline_models, name):
    result = _invoke(*UNTRACED_COMMANDS[name], "-v")
    assert result.exit_code == 0, result.output
    for marker in ("tracing: off", "debug: trace:", "debug: total:"):
        assert marker not in result.stderr


@pytest.mark.parametrize("name", list(TRACED_COMMANDS))
def test_failed_command_keeps_one_error_line(offline_models, monkeypatch, name):
    """A failure writes only its Error line, even with no key."""
    from finos import llm

    def unreachable(*args, **kwargs):
        raise ConnectionError("provider down")

    if name == "policy search":
        offline_models.use_embeddings(_BrokenEmbeddings())
    else:
        monkeypatch.setattr(llm, "get_llm", unreachable)
    result = _invoke(*TRACED_COMMANDS[name])
    assert result.exit_code == 1
    assert len(result.stderr.splitlines()) == 1
    assert result.stderr.startswith("Error: ")


class _BrokenEmbeddings:
    documents_embedded = 0

    def embed_documents(self, texts):
        raise ConnectionError("provider down")

    def embed_query(self, text):
        raise ConnectionError("provider down")


# --- Hardening 4: the --verbose cost line (observability delta) -------------

COST_LINE = re.compile(
    r"debug: cost: \$\d+\.\d{6} \(\d+\+\d+ tokens, \d+ calls?; guards \$\d+\.\d{6}; "
    r"prices as of 2026-11-20\)"
)


@pytest.fixture
def priced_models(policy_env, monkeypatch):
    """Chat calls reported as gpt-4o-mini with usage, embeddings as text-embedding-3-small."""
    from finos import llm
    from tests.test_observability import NamedChat

    monkeypatch.delenv("NO_COLOR", raising=False)
    model = NamedChat(calls=[], replies=["policy", "The fee is $35."], usage=[{"input": 100, "output": 5}] * 4)
    monkeypatch.setattr(llm, "get_llm", lambda *a, **k: model)
    monkeypatch.setattr(llm, "embedding_identity", lambda: ("openai", "text-embedding-3-small"))
    return model


@pytest.mark.parametrize("name", list(TRACED_COMMANDS))
def test_verbose_cost_line_is_priced(priced_models, name):
    result = _invoke(*TRACED_COMMANDS[name], "-v")
    assert result.exit_code == 0, result.output
    last = result.stderr.splitlines()[-1]
    assert COST_LINE.fullmatch(last), last


@pytest.mark.parametrize("name", list(TRACED_COMMANDS))
def test_stdout_unchanged_by_the_cost_line(priced_models, name):
    plain = _invoke(*TRACED_COMMANDS[name])
    priced_models.calls.clear()
    verbose = _invoke(*TRACED_COMMANDS[name], "-v")
    assert plain.exit_code == verbose.exit_code == 0
    assert plain.stdout == verbose.stdout
    assert "cost:" not in plain.stderr


def test_verbose_cost_line_names_an_unpriced_model(priced_models, policy_env):
    class Nano(type(priced_models)):
        def _get_ls_params(self, stop=None, **kwargs):
            params = super()._get_ls_params(stop=stop, **kwargs)
            params["ls_model_name"] = "gpt-4.1-nano"
            return params

    from finos import llm

    nano = Nano(calls=[], replies=["I hear you."], usage=[{"input": 100, "output": 5}])
    policy_env.monkeypatch.setattr(llm, "get_llm", lambda *a, **k: nano)
    result = _invoke("escalation", "ask", "-q", "I'm furious!", "-v")
    assert result.exit_code == 0
    last = result.stderr.splitlines()[-1]
    assert last.startswith("debug: cost: unpriced (gpt-4.1-nano has no price; ")
    assert result.stderr.count("cost: no price for gpt-4.1-nano") == 1


def test_verbose_guards_line_with_the_classifier(priced_models, policy_env, monkeypatch):
    from finos import llm
    from tests.test_guardrails import _UsageClassifier

    policy_env.set_config("injection_classifier = false", "injection_classifier = true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")

    class NamedClassifier(type(_UsageClassifier.make())):
        def _get_ls_params(self, stop=None, **kwargs):
            params = super()._get_ls_params(stop=stop, **kwargs)
            params.update(ls_provider="openai", ls_model_name="gpt-4o-mini")
            return params

    monkeypatch.setattr(llm, "get_classifier_llm", lambda: NamedClassifier(calls=[], reply="safe"))
    result = _invoke("supervisor", "ask", "-q", "What is the overdraft fee?", "-v")
    assert result.exit_code == 0, result.output
    lines = result.stderr.splitlines()
    guards = next(i for i, line in enumerate(lines) if line.startswith("debug: guards: "))
    classify = next(i for i, line in enumerate(lines) if line.startswith("debug: classify_intent: "))
    assert guards < classify and lines[guards].endswith(", 150+1 tokens")
    classifier_cost = (150 * 0.15 + 1 * 0.60) / 1_000_000
    assert f"guards ${classifier_cost:.6f};" in lines[-1]
