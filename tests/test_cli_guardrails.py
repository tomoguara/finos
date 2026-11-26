"""Guardrails on the model-calling commands (Hardening 3, task 6.1).

All offline: ``policy_env`` turns the OpenAI-backed layers off, so the
regex check is the only input layer unless a test turns the others on
without a key. No chat model may be called for a blocked query.
"""

import json

import pytest
from typer.testing import CliRunner

from finos import llm
from finos.cli.main import app
from finos.cli.shared import GUARDRAILS_NO_KEY_LINE
from finos.prompts import (
    ESCALATION_FALLBACK_MESSAGE,
    GUARDRAIL_FALLBACK_MESSAGE,
    SUPPORT_CONTACT,
)

MODEL_COMMANDS = ("supervisor", "policy", "account", "escalation")
INVEST = "Should I invest my savings in crypto?"
BALANCE = "What is the balance on ACC-12345?"


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.delenv("NO_COLOR", raising=False)
    return CliRunner()


def run(runner: CliRunner, *args: str):
    return runner.invoke(app, list(args), prog_name="finos")


@pytest.fixture
def no_model(policy_env, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("no model may be called for a blocked query")

    # Embeddings stay the policy_env fake: `policy ask` opens (or builds)
    # the index before answering, which is setup, not a model answer.
    monkeypatch.setattr(llm, "get_llm", forbidden)


@pytest.mark.parametrize("module", MODEL_COMMANDS)
def test_blocked_query_exits_0_with_the_fallback(runner, no_model, module):
    result = run(runner, module, "ask", "-q", INVEST)
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith(GUARDRAIL_FALLBACK_MESSAGE)
    assert "Traceback" not in result.output


@pytest.mark.parametrize("module", MODEL_COMMANDS)
def test_verbose_names_the_guard_and_category(runner, no_model, module):
    quiet = run(runner, module, "ask", "-q", INVEST)
    loud = run(runner, module, "ask", "-q", INVEST, "-v")
    assert loud.exit_code == 0, loud.output
    assert "debug: guardrail: regex blocked (investment_advice)" in loud.stderr
    assert "guardrail:" not in quiet.stderr
    assert loud.stdout == quiet.stdout


def test_blocked_json_state(runner, no_model):
    result = run(runner, "supervisor", "ask", "-q", INVEST, "--json")
    assert result.exit_code == 0
    state = json.loads(result.stdout)
    assert state["intent"] == "policy"
    assert state["response"] == GUARDRAIL_FALLBACK_MESSAGE
    assert state["context"] == "" and state["retrieved_sources"] == []


def test_escalation_verbose_shows_the_raw_reply_and_the_replacement(
    runner, policy_env, recording_chat
):
    recording_chat.reply = "I'm sorry about the $35 charge."
    quiet = run(runner, "escalation", "ask", "-q", "I'm furious about this fee!")
    loud = run(runner, "escalation", "ask", "-q", "I'm furious about this fee!", "-v")
    assert loud.exit_code == 0, loud.output
    assert loud.stdout.strip() == f"{ESCALATION_FALLBACK_MESSAGE}\n\n{SUPPORT_CONTACT}"
    assert "$35" not in loud.stdout
    assert "raw model reply:\nI'm sorry about the $35 charge." in loud.stderr
    assert "debug: guardrail: output_escalation replaced (policy_claim)" in loud.stderr
    assert loud.stdout == quiet.stdout


def test_escalation_verbose_blocked_has_no_raw_reply(runner, no_model):
    result = run(runner, "escalation", "ask", "-q", INVEST, "-v")
    assert "raw model reply: (none: the query was blocked)" in result.stderr


def enable_model_layers(policy_env):
    policy_env.set_config("moderation = false", "moderation = true")
    policy_env.set_config("injection_classifier = false", "injection_classifier = true")


def test_no_key_line_once_when_layers_enabled(runner, policy_env, recording_chat, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    enable_model_layers(policy_env)
    recording_chat.reply = "Your balance is $12,450.75."
    for extra in ((), ("-v",)):
        result = run(runner, "account", "ask", "-q", BALANCE, *extra)
        assert result.exit_code == 0, result.output
        line = GUARDRAILS_NO_KEY_LINE.format(layers="moderation and injection_classifier")
        assert result.stderr.count(line) == 1
        assert "12,450.75" in result.stdout


def test_no_key_line_absent_when_layers_disabled(runner, policy_env, recording_chat):
    recording_chat.reply = "Your balance is $12,450.75."
    result = run(runner, "account", "ask", "-q", BALANCE)
    assert result.exit_code == 0
    assert "guardrails:" not in result.stderr


def test_no_key_line_absent_with_a_key(runner, policy_env, recording_chat, monkeypatch):
    from finos.guardrails import input as guard_in

    enable_model_layers(policy_env)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setattr(guard_in, "moderate", lambda query: set())
    monkeypatch.setattr(guard_in, "classify", lambda query: "safe")
    recording_chat.reply = "Your balance is $12,450.75."
    result = run(runner, "account", "ask", "-q", BALANCE)
    assert result.exit_code == 0
    assert "guardrails:" not in result.stderr


def test_passing_query_stdout_unchanged_by_verbose(runner, policy_env, recording_chat):
    recording_chat.reply = "Your balance is $12,450.75."
    quiet = run(runner, "account", "ask", "-q", BALANCE)
    loud = run(runner, "account", "ask", "-q", BALANCE, "-v")
    assert quiet.exit_code == loud.exit_code == 0
    assert quiet.stdout == loud.stdout
    assert "guardrail:" not in loud.stderr
