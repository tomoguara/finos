"""Tests for ``finos policy`` (Step 2, policy-cli).

All offline. ``ask`` runs with the agent patched to a canned state;
``search`` and ``ingest`` run against a ``tmp_path`` index built with fake
embeddings (``policy_env`` in ``conftest.py``), with the chat model made to
fail if it is ever requested.
"""

import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from finos import llm
from finos.agents import policy as policy_module
from finos.cli.main import app
from finos.llm import get_embeddings as real_get_embeddings
from finos.prompts import NOT_FOUND_MESSAGE
from finos.state import initial_state
from tests.conftest import CountingEmbeddings

QUERY = "What is the overdraft fee?"


def _canned_state(query: str = QUERY) -> dict:
    state = initial_state(query)
    state.update(
        intent="policy",
        response="The overdraft fee is $35 per transaction.",
        context="[1] (Source: account_fees.md)\nOverdraft fee: $35 per transaction.",
        retrieved_sources=["account_fees.md"],
    )
    return state


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.delenv("NO_COLOR", raising=False)
    return CliRunner()


def run(runner: CliRunner, *args: str, **kwargs):
    return runner.invoke(app, list(args), prog_name="finos", **kwargs)


@pytest.fixture
def canned_agent(policy_env, monkeypatch):
    """Patch the agent to return a canned state and record its calls."""
    calls: list[str] = []

    def fake_ask_policy(query: str) -> dict:
        calls.append(query)
        return _canned_state(query)

    monkeypatch.setattr(policy_module, "ask_policy", fake_ask_policy)
    return calls


@pytest.fixture
def no_chat_model(policy_env, monkeypatch):
    """Fail loudly if anything asks for the chat model."""

    def forbidden(*args, **kwargs):
        raise AssertionError("the chat model must not be requested")

    monkeypatch.setattr(llm, "get_llm", forbidden)


# --- Requirement: The policy module attaches as a command group -------------


def test_group_help_lists_the_commands(runner):
    result = run(runner, "policy", "--help")
    assert result.exit_code == 0
    for command in ("ask", "search", "ingest"):
        assert command in result.stdout


def test_bare_group_shows_help(runner):
    result = run(runner, "policy")
    assert result.exit_code == 2
    assert "ask" in result.output


def test_importing_the_cli_stays_light_with_policy_registered():
    code = (
        "import sys, finos.cli.main, finos.cli.policy\n"
        "heavy = sorted({m.split('.')[0] for m in sys.modules}"
        " & {'langchain', 'langgraph', 'chromadb', 'langchain_core', 'langsmith'})\n"
        "print(','.join(heavy))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


# --- Requirement: Ask prints a grounded answer ------------------------------


def test_ask_human_output(runner, canned_agent):
    result = run(runner, "policy", "ask", "--query", QUERY)
    assert result.exit_code == 0, result.stderr
    assert result.stdout == (
        "The overdraft fee is $35 per transaction.\n\nSources: account_fees.md\n"
    )
    assert canned_agent == [QUERY]


def test_ask_without_sources_says_none(runner, policy_env, monkeypatch):
    def no_sources(query):
        state = initial_state(query)
        state.update(intent="policy", response=NOT_FOUND_MESSAGE)
        return state

    monkeypatch.setattr(policy_module, "ask_policy", no_sources)
    result = run(runner, "policy", "ask", "-q", "stock market outlook")
    assert result.exit_code == 0
    assert result.stdout.splitlines()[-1] == "Sources: none"


@pytest.mark.parametrize("position", ["before", "after"])
def test_ask_json_output_passes_strict_validation(runner, canned_agent, position):
    args = ["policy", "ask", "-q", QUERY]
    args = ["--json", *args] if position == "before" else [*args, "--json"]
    result = run(runner, *args)
    assert result.exit_code == 0, result.stderr
    state = json.loads(result.stdout)
    assert list(state) == ["query", "intent", "response", "context", "retrieved_sources"]
    assert state["intent"] == "policy"

    validated = run(runner, "state", "validate", "--strict", "--data", result.stdout)
    assert validated.exit_code == 0, validated.stdout
    assert "valid SupportState" in validated.stdout


@pytest.mark.parametrize("extra", [[], ["--json"]])
def test_ask_verbose_writes_context_to_stderr_only(runner, canned_agent, extra):
    quiet = run(runner, "policy", "ask", "-q", QUERY, *extra)
    loud = run(runner, "policy", "ask", "-q", QUERY, "--verbose", *extra)
    assert quiet.exit_code == loud.exit_code == 0
    assert quiet.stdout == loud.stdout
    assert quiet.stderr == ""
    assert "Overdraft fee: $35 per transaction." in loud.stderr
    assert "index" in loud.stderr


# --- Requirement: Search shows retrieval without generating -----------------


def test_search_human_output(runner, no_chat_model):
    result = run(runner, "policy", "search", "-q", "overdraft", "--top-k", "2")
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    headers = [line for line in lines if line.startswith("[")]
    previews = [line for line in lines if line.startswith("    ")]
    assert len(headers) == 2 and len(previews) == 2
    assert headers[0].startswith("[1] Score: ")
    assert headers[1].startswith("[2] Score: ")
    for header in headers:
        assert "  Source: " in header and "(chunk " in header
        assert ".md" in header
    for preview in previews:
        assert len(preview.strip()) <= 203


def test_search_json_output(runner, no_chat_model):
    result = run(runner, "policy", "search", "-q", "overdraft", "-k", "2", "--json")
    assert result.exit_code == 0, result.stderr
    hits = json.loads(result.stdout)
    assert [hit["rank"] for hit in hits] == [1, 2]
    for hit in hits:
        assert set(hit) == {"rank", "score", "source", "chunk_index", "text"}
        assert hit["source"].endswith(".md")
    assert hits[0]["score"] >= hits[1]["score"]


def test_search_defaults_to_configured_top_k(runner, no_chat_model, policy_env):
    result = run(runner, "policy", "search", "-q", "overdraft", "--json")
    assert len(json.loads(result.stdout)) == 3
    policy_env.set_config("top_k = 3", "top_k = 4")
    result = run(runner, "policy", "search", "-q", "overdraft", "--json")
    assert len(json.loads(result.stdout)) == 4


# --- Requirement: Ingest builds or refreshes the index explicitly ----------


def test_ingest_built_then_up_to_date_then_rebuilt(runner, no_chat_model, policy_env):
    first = run(runner, "policy", "ingest")
    assert first.exit_code == 0, first.stderr
    assert first.stdout.startswith("Built index: ")
    assert "from 4 documents (fake/deterministic-64)" in first.stdout

    counter = CountingEmbeddings()
    policy_env.use_embeddings(counter)
    second = run(runner, "policy", "ingest")
    assert second.stdout.startswith("Index up to date: ")
    assert counter.documents_embedded == 0

    third = run(runner, "policy", "ingest", "--rebuild")
    assert third.stdout.startswith("Built index: ")
    assert counter.documents_embedded > 0


def test_ingest_json(runner, no_chat_model):
    first = json.loads(run(runner, "policy", "ingest", "--json").stdout)
    assert first["status"] == "built"
    assert set(first) == {"status", "documents", "chunks", "provider", "model", "collection"}
    assert first["documents"] == 4
    assert first["collection"] == "finos_policy_docs"
    assert (first["provider"], first["model"]) == ("fake", "deterministic-64")

    second = json.loads(run(runner, "--json", "policy", "ingest").stdout)
    assert second == {**first, "status": "up_to_date"}

    third = json.loads(run(runner, "policy", "ingest", "--rebuild", "-j").stdout)
    assert third["status"] == "built"


def test_ingest_verbose_reports_on_stderr_only(runner, no_chat_model):
    run(runner, "policy", "ingest")
    quiet = run(runner, "policy", "ingest")
    loud = run(runner, "policy", "ingest", "-v")
    assert quiet.stdout == loud.stdout
    assert "index reused" in loud.stderr


# --- Requirement: Policy commands report bad input and provider failures ---


@pytest.mark.parametrize("command", ["ask", "search"])
@pytest.mark.parametrize("query", ["", "   "])
def test_empty_query_exits_2(runner, policy_env, monkeypatch, command, query):
    def forbidden(*args, **kwargs):
        raise AssertionError("no model may be called for a usage error")

    monkeypatch.setattr(llm, "get_llm", forbidden)
    monkeypatch.setattr(llm, "get_embeddings", forbidden)
    result = run(runner, "policy", command, "--query", query)
    assert result.exit_code == 2
    assert "--query" in result.stderr
    assert result.stdout == ""


def test_missing_query_option_exits_2(runner, policy_env):
    assert run(runner, "policy", "ask").exit_code == 2


@pytest.mark.parametrize("value", ["0", "-1"])
def test_top_k_below_one_exits_2(runner, no_chat_model, value):
    result = run(runner, "policy", "search", "-q", "overdraft", "--top-k", value)
    assert result.exit_code == 2
    assert "--top-k" in result.stderr
    assert result.stdout == ""


def _broken_embeddings(error: Exception):
    class Broken(CountingEmbeddings):
        def embed_documents(self, texts):
            raise error

        def embed_query(self, text):
            raise error

    return Broken()


PROVIDER_COMMANDS = [
    ["policy", "ask", "-q", QUERY],
    ["policy", "search", "-q", QUERY],
    ["policy", "ingest"],
]


@pytest.mark.parametrize("json_flag", [[], ["--json"]])
@pytest.mark.parametrize("args", PROVIDER_COMMANDS)
def test_unreachable_provider_exits_1_with_one_line(runner, policy_env, args, json_flag):
    policy_env.use_embeddings(
        _broken_embeddings(ConnectionError("Failed to connect to Ollama.\nIs it running?"))
    )
    result = run(runner, *args, *json_flag)
    assert result.exit_code == 1
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("Error: Failed to connect to Ollama. Is it running?")
    assert "Traceback" not in result.stderr


def test_chat_failure_after_retrieval_exits_1(runner, policy_env, monkeypatch):
    def unreachable_chat(*args, **kwargs):
        raise ConnectionError("chat host unreachable")

    monkeypatch.setattr(llm, "get_llm", unreachable_chat)
    result = run(runner, "policy", "ask", "-q", QUERY, "--json")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith("Error: chat host unreachable")
    assert len(result.stderr.splitlines()) == 1


@pytest.mark.parametrize("args", PROVIDER_COMMANDS)
def test_missing_openai_key_exits_1(runner, policy_env, monkeypatch, args):
    """With OpenAI selected and no key, the real embedding helper raises."""
    monkeypatch.setattr(llm, "get_embeddings", real_get_embeddings)
    policy_env.set_local_provider(False)
    result = run(runner, *args, "--json")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "OPENAI_API_KEY" in result.stderr
    assert len(result.stderr.splitlines()) == 1


def test_verbose_failure_names_the_exception_type(runner, policy_env):
    policy_env.use_embeddings(_broken_embeddings(ConnectionError("down")))
    result = run(runner, "policy", "ingest", "--verbose")
    assert result.exit_code == 1
    assert "ConnectionError" in result.stderr
    assert result.stderr.splitlines()[-1].startswith("Error: down")
