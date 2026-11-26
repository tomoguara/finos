"""Tests for ``finos guard`` (Hardening 3, guard-cli).

All offline: ``policy_env`` turns the OpenAI-backed layers off; tests that
need them on use fakes, and none calls an agent.
"""

import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from finos import llm
from finos.cli.main import app

COMPETITOR = "Is SecureBank better than Chase?"
CRISIS = "I want to hurt myself"


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.delenv("NO_COLOR", raising=False)
    return CliRunner()


def run(runner: CliRunner, *args: str):
    return runner.invoke(app, list(args), prog_name="finos")


@pytest.fixture
def no_agent(policy_env, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("guard check must not call an agent")

    monkeypatch.setattr(llm, "get_llm", forbidden)
    monkeypatch.setattr(llm, "get_embeddings", forbidden)


@pytest.fixture
def layers_on(no_agent, policy_env, monkeypatch):
    from finos.guardrails import input as guard_in

    policy_env.set_config("moderation = false", "moderation = true")
    policy_env.set_config("injection_classifier = false", "injection_classifier = true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    calls: list[str] = []

    def fake_moderate(query):
        calls.append("moderation")
        return set()

    def fake_classify(query):
        calls.append("classifier")
        return "safe"

    monkeypatch.setattr(guard_in, "moderate", fake_moderate)
    monkeypatch.setattr(guard_in, "classify", fake_classify)
    return calls


# --- Requirement: The guard module attaches as a command group --------------


def test_group_help_lists_check(runner):
    result = run(runner, "guard", "--help")
    assert result.exit_code == 0
    assert "check" in result.stdout


def test_bare_group_shows_help(runner):
    result = run(runner, "guard")
    assert result.exit_code == 2
    assert "check" in result.output


def test_root_help_lists_guard(runner):
    result = run(runner, "--help")
    assert result.exit_code == 0
    assert "guard" in result.stdout


def test_importing_the_cli_stays_light_with_guard_registered():
    code = (
        "import sys, finos.cli.main, finos.cli.guard\n"
        "heavy = ('langchain', 'langgraph', 'chromadb', 'langsmith', 'openai')\n"
        "print([m for m in sys.modules if m.split('.')[0] in heavy])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"


# --- Requirement: Check shows each input layer's decision -------------------


def test_competitor_blocked_by_regex_later_layers_skipped(runner, layers_on):
    result = run(runner, "guard", "check", "-q", COMPETITOR)
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "regex: blocked (competitor)",
        "moderation: skipped",
        "injection_classifier: skipped",
        "verdict: blocked",
        "crisis: no",
    ]
    assert layers_on == []


def test_passing_query_runs_every_layer(runner, layers_on):
    result = run(runner, "guard", "check", "-q", "What is the overdraft fee?")
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "regex: passed",
        "moderation: passed",
        "injection_classifier: passed",
        "verdict: passed",
        "crisis: no",
    ]
    assert layers_on == ["moderation", "classifier"]


def test_crisis_is_not_blocked(runner, no_agent):
    result = run(runner, "guard", "check", "-q", CRISIS)
    assert result.exit_code == 0
    assert "crisis: yes" in result.stdout
    assert "verdict: passed" in result.stdout


def test_json(runner, layers_on):
    result = run(runner, "guard", "check", "-q", COMPETITOR, "--json")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["verdict"] == "blocked" and data["crisis"] is False
    assert data["layers"][0] == {"layer": "regex", "decision": "blocked", "category": "competitor"}
    assert [layer["decision"] for layer in data["layers"][1:]] == ["skipped", "skipped"]


def test_layers_off_in_config(runner, no_agent):
    result = run(runner, "guard", "check", "-q", "What is the overdraft fee?")
    assert result.exit_code == 0
    assert "moderation: off" in result.stdout
    assert "injection_classifier: off" in result.stdout


def test_layers_off_without_key_say_so(runner, policy_env, no_agent, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    policy_env.set_config("moderation = false", "moderation = true")
    policy_env.set_config("injection_classifier = false", "injection_classifier = true")
    result = run(runner, "guard", "check", "-q", "What is the overdraft fee?")
    assert result.exit_code == 0
    assert "moderation: off (no OPENAI_API_KEY)" in result.stdout
    assert "injection_classifier: off (no OPENAI_API_KEY)" in result.stdout
    assert "regex: passed" in result.stdout


@pytest.mark.parametrize("query", ["", "   "])
def test_empty_query_exits_2(runner, monkeypatch, query):
    from finos.guardrails import input as guard_in

    def forbidden(q):
        raise AssertionError("no check may run for an empty query")

    monkeypatch.setattr(guard_in, "guard_input", forbidden)
    result = run(runner, "guard", "check", "--query", query)
    assert result.exit_code == 2
    assert "--query must not be empty" in result.stderr
