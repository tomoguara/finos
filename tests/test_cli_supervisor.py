"""Tests for ``finos supervisor`` (Step 5, supervisor-cli).

All offline. Every command runs inside ``policy_env`` (a private config
with tracing off, a ``tmp_path`` index with fake embeddings). The shared
recording fake is the chat model, and a fake classifier steers ``ask`` to
each route.
"""

import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from finos import config, llm
from finos.agents import supervisor
from finos.cli.main import app
from finos.prompts import ACCOUNT_NO_ID_MESSAGE, SUPPORT_CONTACT
from tests.test_supervisor import PLANTUML_GOLDEN


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.delenv("NO_COLOR", raising=False)
    return CliRunner()


def run(runner: CliRunner, *args: str, **kwargs):
    return runner.invoke(app, list(args), prog_name="finos", **kwargs)


@pytest.fixture
def steer(policy_env, recording_chat, monkeypatch):
    """Make the supervisor return a chosen intent; return the specialist fake."""
    chosen: dict[str, str] = {}

    def fake_classify_query(query: str):
        return f"raw:{chosen['intent']}", chosen["intent"]

    monkeypatch.setattr(supervisor, "classify_query", fake_classify_query)

    def set_intent(intent: str, reply: str = "A grounded answer."):
        chosen["intent"] = intent
        recording_chat.reply = reply
        return recording_chat

    return set_intent


@pytest.fixture
def no_model(policy_env, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("no model may be called here")

    monkeypatch.setattr(llm, "get_llm", forbidden)
    monkeypatch.setattr(llm, "get_embeddings", forbidden)


# --- Requirement: The supervisor module attaches as a command group ---------


def test_group_help_lists_the_commands(runner):
    result = run(runner, "supervisor", "--help")
    assert result.exit_code == 0
    for command in ("ask", "classify", "graph"):
        assert command in result.stdout


def test_bare_group_shows_help_without_building(runner, monkeypatch):
    import finos.graph

    def forbidden():
        raise AssertionError("a bare group must not build the graph")

    monkeypatch.setattr(finos.graph, "build_support_agent", forbidden)
    result = run(runner, "supervisor")
    assert result.exit_code == 2
    assert "classify" in result.output


def test_importing_the_cli_stays_light_with_supervisor_registered():
    code = (
        "import sys, finos.cli.main, finos.cli.supervisor\n"
        "heavy = sorted({m.split('.')[0] for m in sys.modules}"
        " & {'langchain', 'langgraph', 'chromadb', 'langchain_core', 'langsmith'})\n"
        "print(','.join(heavy))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


# --- Requirement: Graph prints the wiring ------------------------------------


def test_graph_default_is_plantuml(runner, no_model):
    result = run(runner, "supervisor", "graph")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == PLANTUML_GOLDEN + "\n"


def test_graph_mermaid(runner, no_model):
    result = run(runner, "supervisor", "graph", "--format", "mermaid")
    assert result.exit_code == 0, result.stderr
    for node in ("classify_intent", "policy_agent", "account_agent", "escalation_agent"):
        assert node in result.stdout


@pytest.mark.parametrize("value", ["png", "svg", ""])
def test_graph_unknown_format_exits_2(runner, no_model, value):
    result = run(runner, "supervisor", "graph", "--format", value)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "--format" in result.stderr


# --- Requirement: Classify shows routing only --------------------------------


def _no_specialists(monkeypatch):
    import finos.agents.account as account_module
    import finos.agents.escalation as escalation_module
    import finos.agents.policy as policy_module

    def forbidden(*args, **kwargs):
        raise AssertionError("classify must not run a specialist")

    for module, name in (
        (policy_module, "policy_agent"),
        (account_module, "account_agent"),
        (escalation_module, "escalation_agent"),
    ):
        monkeypatch.setattr(module, name, forbidden)


def test_classify_human(runner, policy_env, recording_chat, monkeypatch):
    _no_specialists(monkeypatch)
    recording_chat.reply = "Escalation."
    result = run(runner, "supervisor", "classify", "--query", "I want to speak to a manager")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == "escalation -> escalation_agent\n"
    assert len(recording_chat.calls) == 1


@pytest.mark.parametrize("position", ["before", "after"])
def test_classify_json(runner, policy_env, recording_chat, position):
    recording_chat.reply = "account_status"
    args = ["supervisor", "classify", "-q", "balance on ACC-12345?"]
    args = ["--json", *args] if position == "before" else [*args, "--json"]
    result = run(runner, *args)
    assert json.loads(result.stdout) == {"intent": "account_status", "node": "account_agent"}


def test_classify_verbose_shows_the_raw_reply_on_stderr_only(runner, policy_env, recording_chat):
    recording_chat.reply = '  "Policy" (it asks about a fee)  '
    quiet = run(runner, "supervisor", "classify", "-q", "What is the fee?")
    loud = run(runner, "supervisor", "classify", "-q", "What is the fee?", "-v")
    assert quiet.stdout == loud.stdout == "policy -> policy_agent\n"
    assert quiet.stderr == ""
    assert '"Policy" (it asks about a fee)' in loud.stderr
    assert "chat model: " in loud.stderr


# --- Requirement: Ask runs the whole system ----------------------------------


def test_ask_policy_trailers(runner, steer):
    steer("policy", "The overdraft fee is $35.")
    result = run(runner, "supervisor", "ask", "-q", "What is the overdraft fee?")
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "The overdraft fee is $35."
    assert lines[-2].startswith("Sources: ") and ".md" in lines[-2]
    assert lines[-1] == "Intent: policy"


def test_ask_account_trailers(runner, steer):
    steer("account_status", "The balance is $12,450.75.")
    result = run(runner, "supervisor", "ask", "-q", "What is the balance on ACC-12345?")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == "The balance is $12,450.75.\n\nAccount: ACC-12345\nIntent: account_status\n"


def test_ask_account_without_id(runner, steer):
    steer("account_status")
    result = run(runner, "supervisor", "ask", "-q", "Show my recent transactions")
    assert result.stdout == f"{ACCOUNT_NO_ID_MESSAGE}\n\nAccount: none\nIntent: account_status\n"


def test_ask_escalation_has_no_specialist_trailer(runner, steer):
    steer("escalation", "I'm sorry this has been so frustrating.")
    result = run(runner, "supervisor", "ask", "-q", "I'm furious! Nobody is helping!")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == (
        f"I'm sorry this has been so frustrating.\n\n{SUPPORT_CONTACT}\n\nIntent: escalation\n"
    )
    assert "Sources:" not in result.stdout and "Account:" not in result.stdout


@pytest.mark.parametrize(
    "intent, query",
    [
        ("policy", "What is the overdraft fee?"),
        ("account_status", "What is the balance on ACC-12345?"),
        ("escalation", "I'm furious! Nobody is helping!"),
    ],
)
@pytest.mark.parametrize("position", ["before", "after"])
def test_ask_json_passes_strict_validation(runner, steer, intent, query, position):
    steer(intent)
    args = ["supervisor", "ask", "-q", query]
    args = ["-j", *args] if position == "before" else [*args, "-j"]
    result = run(runner, *args)
    assert result.exit_code == 0, result.stderr
    state = json.loads(result.stdout)
    assert list(state) == ["query", "intent", "response", "context", "retrieved_sources"]
    assert state["intent"] == intent
    validated = run(runner, "state", "validate", "--strict", "--data", result.stdout)
    assert validated.exit_code == 0, validated.stdout


@pytest.mark.parametrize(
    "intent, query, expected",
    [
        ("policy", "What is the overdraft fee?", "context sent to the model:"),
        ("account_status", "What is the balance on ACC-12345?", "account resolution: found ACC-12345"),
        ("escalation", "I'm furious!", "node: escalation_agent"),
    ],
)
@pytest.mark.parametrize("extra", [[], ["--json"]])
def test_ask_verbose_on_stderr_only(runner, steer, intent, query, expected, extra):
    steer(intent)
    quiet = run(runner, "supervisor", "ask", "-q", query, *extra)
    loud = run(runner, "supervisor", "ask", "-q", query, "--verbose", *extra)
    assert quiet.exit_code == loud.exit_code == 0
    assert quiet.stdout == loud.stdout
    assert quiet.stderr == ""
    assert f"intent: {intent}" in loud.stderr
    assert "chat model: " in loud.stderr
    assert expected in loud.stderr
    # The trace line replaced the pointer to `classify -v` and LangSmith.
    assert "debug: trace: none (tracing off)" in loud.stderr
    assert "LangSmith trace" not in loud.stderr


# --- Requirement: bad input and failures --------------------------------------


@pytest.mark.parametrize("command", ["ask", "classify"])
@pytest.mark.parametrize("query", ["", "   "])
def test_empty_query_exits_2_before_any_model_call(runner, no_model, command, query):
    result = run(runner, "supervisor", command, "--query", query, "--json")
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "--query" in result.stderr


@pytest.mark.parametrize("command", ["ask", "classify"])
@pytest.mark.parametrize("json_flag", [[], ["--json"]])
def test_provider_failure_exits_1(runner, policy_env, monkeypatch, command, json_flag):
    def unreachable(*args, **kwargs):
        raise ConnectionError("Failed to connect to Ollama.\nIs it running?")

    monkeypatch.setattr(llm, "get_llm", unreachable)
    result = run(runner, "supervisor", command, "-q", "What is the overdraft fee?", *json_flag)
    assert result.exit_code == 1
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("Error: Failed to connect to Ollama. Is it running?")
    assert ", chat model " in lines[0]  # the provider summary, either provider
    assert "Traceback" not in result.stderr


def test_specialist_data_failure_exits_1_without_provider_summary(runner, steer, monkeypatch, tmp_path):
    steer("account_status")
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(config, "MOCK_ACCOUNTS_PATH", missing)
    result = run(runner, "supervisor", "ask", "-q", "What is the balance on ACC-12345?", "--json")
    assert result.exit_code == 1
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 1 and str(missing) in lines[0]
    assert ", chat model " not in lines[0]  # a data problem names no provider


def test_graph_command_writes_nothing_to_stderr():
    """No third-party warning leaks into the CLI's stderr (fresh process)."""
    result = subprocess.run(
        [sys.executable, "-m", "finos", "supervisor", "graph"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.startswith("@startuml")
