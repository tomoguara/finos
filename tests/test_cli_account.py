"""Tests for ``finos account`` (Step 3, account-cli).

All offline. ``ask`` runs inside ``policy_env`` (a private config with
tracing off) with the shared recording fake as the chat model; ``lookup``
and ``list`` need neither.
"""

import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from finos import config, llm
from finos.cli.main import app
from finos.prompts import (
    ACCOUNT_MULTIPLE_IDS_MESSAGE,
    ACCOUNT_NO_ID_MESSAGE,
    ACCOUNT_NOT_FOUND_MESSAGE,
)

FOUND = "What is the balance on ACC-12345?"


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.delenv("NO_COLOR", raising=False)
    return CliRunner()


def run(runner: CliRunner, *args: str, **kwargs):
    return runner.invoke(app, list(args), prog_name="finos", **kwargs)


@pytest.fixture
def chat(policy_env, recording_chat):
    recording_chat.reply = "The balance on ACC-12345 is $12,450.75."
    return recording_chat


@pytest.fixture
def no_model(policy_env, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("the chat model must not be requested")

    monkeypatch.setattr(llm, "get_llm", forbidden)


@pytest.fixture
def missing_records(tmp_path, monkeypatch):
    path = tmp_path / "missing.json"
    monkeypatch.setattr(config, "MOCK_ACCOUNTS_PATH", path)
    return path


# --- Requirement: The account module attaches as a command group -----------


def test_group_help_lists_the_commands(runner):
    result = run(runner, "account", "--help")
    assert result.exit_code == 0
    for command in ("ask", "lookup", "list"):
        assert command in result.stdout


def test_bare_group_shows_help(runner):
    result = run(runner, "account")
    assert result.exit_code == 2
    assert "lookup" in result.output


def test_importing_the_cli_stays_light_with_account_registered():
    code = (
        "import sys, finos.cli.main, finos.cli.account\n"
        "heavy = sorted({m.split('.')[0] for m in sys.modules}"
        " & {'langchain', 'langgraph', 'chromadb', 'langchain_core', 'langsmith'})\n"
        "print(','.join(heavy))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


# --- Requirement: List shows the available accounts -------------------------


def test_list_human(runner):
    result = run(runner, "account", "list")
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert [line.split()[0] for line in lines] == [
        "ACC-11111",
        "ACC-12345",
        "ACC-22222",
        "ACC-67890",
    ]
    assert "frozen" in lines[0] and "Carol Davis" in lines[0]
    assert "SSN" not in result.stdout and "9876" not in result.stdout


@pytest.mark.parametrize("position", ["before", "after"])
def test_list_json(runner, position):
    args = ["--json", "account", "list"] if position == "before" else ["account", "list", "--json"]
    rows = json.loads(run(runner, *args).stdout)
    assert [row["account_id"] for row in rows] == ["ACC-11111", "ACC-12345", "ACC-22222", "ACC-67890"]
    assert all(set(row) == {"account_id", "status", "account_type", "holder_name"} for row in rows)


# --- Requirement: Lookup shows a record without a model ---------------------


def test_lookup_frozen_record(runner):
    result = run(runner, "account", "lookup", "--id", "ACC-11111")
    assert result.exit_code == 0
    assert "frozen" in result.stdout
    assert "Suspected fraudulent activity under investigation" in result.stdout
    assert "-7,500.00" in result.stdout and "+291.14" in result.stdout


def test_lookup_normalizes_input(runner):
    result = run(runner, "account", "lookup", "-i", "acc-12345")
    assert result.exit_code == 0
    assert "ACC-12345" in result.stdout
    assert "12,450.75" in result.stdout


def test_lookup_pending_record_has_no_transactions(runner):
    result = run(runner, "account", "lookup", "-i", "ACC 22222")
    assert result.exit_code == 0
    assert "pending" in result.stdout and "(none)" in result.stdout


def test_lookup_json_is_the_raw_record(runner):
    result = run(runner, "account", "lookup", "-i", "ACC-12345", "--json")
    record = json.loads(result.stdout)
    raw = json.loads(config.MOCK_ACCOUNTS_PATH.read_text("utf-8"))
    assert record == next(r for r in raw if r["account_id"] == "ACC-12345")


def test_lookup_not_found_is_a_verdict(runner):
    result = run(runner, "account", "lookup", "-i", "ACC-99999")
    assert result.exit_code == 1
    assert result.stdout == "No account found: ACC-99999\n"
    assert result.stderr == ""
    json_result = run(runner, "account", "lookup", "-i", "ACC-99999", "--json")
    assert json_result.exit_code == 1
    assert json.loads(json_result.stdout) == {"account_id": "ACC-99999", "found": False}


@pytest.mark.parametrize("value", ["ACC-1234", "ACC-123456", "12345", "", "ACC-12345x"])
@pytest.mark.parametrize("json_flag", [[], ["--json"]])
def test_lookup_malformed_id_exits_2(runner, value, json_flag):
    result = run(runner, "account", "lookup", "--id", value, *json_flag)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "ACC- followed by five digits" in result.stderr


@pytest.mark.parametrize("command", [["list"], ["lookup", "-i", "ACC-12345"], ["ask", "-q", FOUND]])
@pytest.mark.parametrize("json_flag", [[], ["--json"]])
def test_missing_records_file_exits_1(runner, missing_records, no_model, command, json_flag):
    result = run(runner, "account", *command, *json_flag)
    assert result.exit_code == 1
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 1
    assert str(missing_records) in lines[0]
    assert "Traceback" not in result.stderr


def test_corrupt_records_file_exits_1(runner, tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(config, "MOCK_ACCOUNTS_PATH", path)
    result = run(runner, "account", "list")
    assert result.exit_code == 1
    assert len(result.stderr.splitlines()) == 1 and str(path) in result.stderr


def test_verbose_names_the_records_file_on_stderr_only(runner):
    quiet = run(runner, "account", "lookup", "-i", "ACC-12345")
    loud = run(runner, "account", "lookup", "-i", "ACC-12345", "-v")
    assert quiet.stdout == loud.stdout
    assert quiet.stderr == ""
    assert str(config.MOCK_ACCOUNTS_PATH) in loud.stderr


@pytest.mark.parametrize("command", [["lookup", "--id", "ACC-12345"], ["list"]])
def test_lookup_and_list_stay_light(command):
    """No LangChain or Chroma, and no settings, in a fresh process."""
    code = (
        "import sys\n"
        "from finos import config\n"
        "def no_settings(*a, **k):\n"
        "    raise SystemExit('get_settings was called')\n"
        "config.get_settings = no_settings\n"
        "from typer.testing import CliRunner\n"
        "from finos.cli.main import app\n"
        f"result = CliRunner().invoke(app, {['account', *command]!r}, prog_name='finos')\n"
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


# --- Requirement: Ask prints the answer and the account it used -------------


@pytest.mark.parametrize(
    "query, response, trailer",
    [
        ("What is the balance on ACC-99999?", ACCOUNT_NOT_FOUND_MESSAGE, "Account: ACC-99999 (not found)"),
        ("Show my recent transactions", ACCOUNT_NO_ID_MESSAGE, "Account: none"),
        ("Compare ACC-12345 and acc 67890", ACCOUNT_MULTIPLE_IDS_MESSAGE, "Account: ACC-12345, ACC-67890 (multiple)"),
    ],
)
def test_ask_constant_outcomes(runner, no_model, query, response, trailer):
    result = run(runner, "account", "ask", "-q", query)
    assert result.exit_code == 0, result.stderr
    assert result.stdout == f"{response}\n\n{trailer}\n"


def test_ask_found(runner, chat):
    result = run(runner, "account", "ask", "--query", FOUND)
    assert result.exit_code == 0, result.stderr
    assert result.stdout == "The balance on ACC-12345 is $12,450.75.\n\nAccount: ACC-12345\n"
    assert len(chat.calls) == 1


@pytest.mark.parametrize("position", ["before", "after"])
def test_ask_json_passes_strict_validation(runner, chat, position):
    args = ["account", "ask", "-q", FOUND]
    args = ["-j", *args] if position == "before" else [*args, "-j"]
    result = run(runner, *args)
    assert result.exit_code == 0, result.stderr
    state = json.loads(result.stdout)
    assert list(state) == ["query", "intent", "response", "context", "retrieved_sources"]
    assert state["intent"] == "account_status"
    assert state["context"] == "" and state["retrieved_sources"] == []
    validated = run(runner, "state", "validate", "--strict", "--data", result.stdout)
    assert validated.exit_code == 0, validated.stdout


@pytest.mark.parametrize("extra", [[], ["--json"]])
def test_ask_verbose_writes_diagnostics_to_stderr_only(runner, chat, extra):
    quiet = run(runner, "account", "ask", "-q", FOUND, *extra)
    loud = run(runner, "account", "ask", "-q", FOUND, "--verbose", *extra)
    assert quiet.exit_code == loud.exit_code == 0
    assert quiet.stdout == loud.stdout
    assert quiet.stderr == ""
    assert "outcome: found" in loud.stderr
    assert "account IDs: ACC-12345" in loud.stderr
    assert '"balance": 12450.75' in loud.stderr
    assert "chat model: " in loud.stderr


@pytest.mark.parametrize("query", ["", "   "])
def test_ask_empty_query_exits_2_before_any_model_call(runner, no_model, missing_records, query):
    result = run(runner, "account", "ask", "--query", query, "--json")
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "--query" in result.stderr


@pytest.mark.parametrize("json_flag", [[], ["--json"]])
def test_ask_provider_failure_exits_1(runner, policy_env, monkeypatch, json_flag):
    def unreachable(*args, **kwargs):
        raise ConnectionError("Failed to connect to Ollama.\nIs it running?")

    monkeypatch.setattr(llm, "get_llm", unreachable)
    result = run(runner, "account", "ask", "-q", FOUND, *json_flag)
    assert result.exit_code == 1
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("Error: Failed to connect to Ollama. Is it running?")
    assert "Traceback" not in result.stderr


def test_ask_constant_outcome_needs_no_provider(runner, policy_env, monkeypatch):
    """A not-found answer works even when the provider would fail."""

    def unreachable(*args, **kwargs):
        raise ConnectionError("down")

    monkeypatch.setattr(llm, "get_llm", unreachable)
    result = run(runner, "account", "ask", "-q", "What is the balance on ACC-99999?")
    assert result.exit_code == 0


def test_verbose_record_is_what_the_model_receives(runner, recording_chat):
    """`-v` shows the minimized record: no ssn_last4 reaches the model (Hardening 3)."""
    result = run(runner, "account", "ask", "-q", "What is the balance on ACC-12345?", "-v")
    assert result.exit_code == 0
    assert "record sent to the model:" in result.stderr
    assert "ssn_last4" not in result.stderr and "6789" not in result.stderr
    assert "12450.75" in result.stderr
