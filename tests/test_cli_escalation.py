"""Tests for ``finos escalation`` (Step 4, escalation-cli).

All offline. ``ask`` runs inside ``policy_env`` (a private config with
tracing off) with the shared recording fake as the chat model; ``contact``
needs neither.
"""

import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from finos import llm
from finos.cli.main import app
from finos.prompts import (
    CRISIS_SUPPORT_MESSAGE,
    ESCALATION_FALLBACK_MESSAGE,
    SUPPORT_CONTACT,
)

QUERY = "I'm furious! Nobody is helping!"
REPLY = "I'm sorry this has been so frustrating. Our support team can help you directly."


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.delenv("NO_COLOR", raising=False)
    return CliRunner()


def run(runner: CliRunner, *args: str, **kwargs):
    return runner.invoke(app, list(args), prog_name="finos", **kwargs)


@pytest.fixture
def chat(policy_env, recording_chat):
    recording_chat.reply = REPLY
    return recording_chat


# --- Requirement: The escalation module attaches as a command group ---------


def test_group_help_lists_the_commands(runner):
    result = run(runner, "escalation", "--help")
    assert result.exit_code == 0
    assert "ask" in result.stdout and "contact" in result.stdout


def test_bare_group_shows_help(runner):
    result = run(runner, "escalation")
    assert result.exit_code == 2
    assert "contact" in result.output


def test_importing_the_cli_stays_light_with_escalation_registered():
    code = (
        "import sys, finos.cli.main, finos.cli.escalation\n"
        "heavy = sorted({m.split('.')[0] for m in sys.modules}"
        " & {'langchain', 'langgraph', 'chromadb', 'langchain_core', 'langsmith'})\n"
        "print(','.join(heavy))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


# --- Requirement: Contact shows the fixed texts without a model -------------


def test_contact_human(runner):
    result = run(runner, "escalation", "contact")
    assert result.exit_code == 0
    assert result.stdout == SUPPORT_CONTACT + "\n"


@pytest.mark.parametrize("position", ["before", "after"])
def test_contact_json(runner, position):
    args = ["--json", "escalation", "contact"] if position == "before" else ["escalation", "contact", "--json"]
    result = run(runner, *args)
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data == {"support_contact": SUPPORT_CONTACT, "crisis_support": CRISIS_SUPPORT_MESSAGE}
    assert "support@securebank.example" in data["support_contact"]
    assert "988" in data["crisis_support"]


def test_contact_stays_light():
    """No LangChain or Chroma, and no settings, in a fresh process."""
    code = (
        "import sys\n"
        "from finos import config\n"
        "def no_settings(*a, **k):\n"
        "    raise SystemExit('get_settings was called')\n"
        "config.get_settings = no_settings\n"
        "from typer.testing import CliRunner\n"
        "from finos.cli.main import app\n"
        "result = CliRunner().invoke(app, ['escalation', 'contact', '--json'], prog_name='finos')\n"
        "assert result.exit_code == 0, (result.exit_code, result.output)\n"
        "heavy = sorted({m.split('.')[0] for m in sys.modules}"
        " & {'langchain', 'langchain_core', 'langgraph', 'chromadb', 'langsmith'})\n"
        "print(','.join(heavy))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


# --- Requirement: Ask prints the escalation reply ---------------------------


def test_ask_human_output_ends_with_contact_and_no_trailer(runner, chat):
    result = run(runner, "escalation", "ask", "--query", QUERY)
    assert result.exit_code == 0, result.stderr
    assert result.stdout == f"{REPLY}\n\n{SUPPORT_CONTACT}\n"
    assert not result.stdout.splitlines()[-1].startswith(("Account:", "Sources:"))
    assert len(chat.calls) == 1


@pytest.mark.parametrize("position", ["before", "after"])
def test_ask_json_passes_strict_validation(runner, chat, position):
    args = ["escalation", "ask", "-q", QUERY]
    args = ["-j", *args] if position == "before" else [*args, "-j"]
    result = run(runner, *args)
    assert result.exit_code == 0, result.stderr
    state = json.loads(result.stdout)
    assert list(state) == ["query", "intent", "response", "context", "retrieved_sources"]
    assert state["intent"] == "escalation"
    assert state["context"] == "" and state["retrieved_sources"] == []
    assert state["response"] == f"{REPLY}\n\n{SUPPORT_CONTACT}"
    validated = run(runner, "state", "validate", "--strict", "--data", result.stdout)
    assert validated.exit_code == 0, validated.stdout


@pytest.mark.parametrize("extra", [[], ["--json"]])
def test_ask_verbose_writes_diagnostics_to_stderr_only(runner, chat, extra):
    chat.reply = "  " + REPLY + "  "
    quiet = run(runner, "escalation", "ask", "-q", QUERY, *extra)
    loud = run(runner, "escalation", "ask", "-q", QUERY, "--verbose", *extra)
    assert quiet.exit_code == loud.exit_code == 0
    assert quiet.stdout == loud.stdout
    assert quiet.stderr == ""
    assert "chat model: " in loud.stderr
    assert "raw model reply:\n  " + REPLY in loud.stderr
    assert "fallback used: no" in loud.stderr


def test_ask_verbose_reports_the_fallback(runner, chat):
    chat.reply = "   "
    result = run(runner, "escalation", "ask", "-q", QUERY, "-v")
    assert result.exit_code == 0
    assert result.stdout == f"{ESCALATION_FALLBACK_MESSAGE}\n\n{SUPPORT_CONTACT}\n"
    assert "raw model reply:\n(empty)" in result.stderr
    assert "fallback used: yes" in result.stderr


# --- Requirement: bad input and provider failures ---------------------------


@pytest.mark.parametrize("query", ["", "   "])
def test_ask_empty_query_exits_2_before_any_model_call(runner, policy_env, monkeypatch, query):
    def forbidden(*args, **kwargs):
        raise AssertionError("no model may be called for a usage error")

    monkeypatch.setattr(llm, "get_llm", forbidden)
    result = run(runner, "escalation", "ask", "--query", query, "--json")
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "--query" in result.stderr


def test_missing_query_option_exits_2(runner):
    assert run(runner, "escalation", "ask").exit_code == 2


@pytest.mark.parametrize("json_flag", [[], ["--json"]])
def test_ask_provider_failure_exits_1(runner, policy_env, monkeypatch, json_flag):
    def unreachable(*args, **kwargs):
        raise ConnectionError("Failed to connect to Ollama.\nIs it running?")

    monkeypatch.setattr(llm, "get_llm", unreachable)
    result = run(runner, "escalation", "ask", "-q", QUERY, *json_flag)
    assert result.exit_code == 1
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("Error: Failed to connect to Ollama. Is it running?")
    assert "Traceback" not in result.stderr


def test_ask_missing_openai_key_exits_1(runner, policy_env, monkeypatch):
    from finos.llm import get_llm as real_get_llm

    monkeypatch.setattr(llm, "get_llm", real_get_llm)
    policy_env.set_local_provider(False)
    result = run(runner, "escalation", "ask", "-q", QUERY, "--json")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "OPENAI_API_KEY" in result.stderr
    assert len(result.stderr.splitlines()) == 1
