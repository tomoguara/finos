"""Tests for the supervisor (Step 5, supervisor-routing).

All offline: the chat model is the shared
:class:`~tests.conftest.RecordingChatModel`. Live routing tests are in
``tests/test_graph.py``.
"""

from __future__ import annotations

import re

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from finos import llm
from finos.agents import classify_intent, route_by_intent
from finos.agents.supervisor import INTENT_TO_NODE, classify_query, normalize_intent
from finos.prompts import SUPERVISOR_SYSTEM_PROMPT
from finos.state import VALID_INTENTS, initial_state, validate_state

# --- normalize_intent: the explore doc's §4 table (rule R3) ------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("policy", "policy"),
        ("Policy\n", "policy"),  # support-state spec: messy casing and whitespace
        ('"escalation"', "escalation"),
        ("account_status.", "account_status"),
        ("Category: account_status", "account_status"),
        ("Category: escalation", "escalation"),
        ("account status", "account_status"),
        ("account-status", "account_status"),
        ("ACCOUNT STATUS", "account_status"),
        ("escalation (the customer is angry)", "escalation"),
        ("policy or escalation", "policy"),  # two members: the first wins
        ("I cannot classify this", "policy"),  # support-state spec: unrecognized
        ("", "policy"),
        ("   \n", "policy"),
        ("policy_agent", "policy"),  # not a whole-word member, so the fallback
        ("escalation (the customer may be in danger, not a policy question)", "escalation"),
    ],
)
def test_normalize_intent(raw, expected):
    assert normalize_intent(raw) == expected


@pytest.mark.parametrize("raw", ["Policy\n", "I cannot classify this", "", '"escalation"'])
def test_normalized_intent_passes_validation(raw):
    """The support-state obligation: only a vocabulary member reaches the state."""
    state = initial_state("q")
    state["intent"] = normalize_intent(raw)
    assert state["intent"] in VALID_INTENTS
    assert validate_state(state) == []


# --- The supervisor prompt (task 2.2) ----------------------------------------


def test_prompt_has_no_placeholders():
    assert "{" not in SUPERVISOR_SYSTEM_PROMPT and "}" not in SUPERVISOR_SYSTEM_PROMPT


def test_prompt_defines_the_three_categories():
    lines = SUPERVISOR_SYSTEM_PROMPT.splitlines()
    policy = next(line for line in lines if line.startswith("- policy:"))
    account = next(line for line in lines if line.startswith("- account_status:"))
    escalation = next(line for line in lines if line.startswith("- escalation:"))
    assert "anything that is not one of the two categories below" in policy  # catch-all
    for word in ("balance", "transactions", "status", "details"):
        assert word in account
    for phrase in ("complaints", "frustration", "anger", "person or manager", "distress or danger"):
        assert phrase in escalation


def test_prompt_classifies_by_subject():
    assert (
        "Classify by what the customer is asking about, not by their tone or by "
        "whether they mention an account number." in SUPERVISOR_SYSTEM_PROMPT
    )
    assert '"I\'m upset about the overdraft fee, what is it?" is policy.' in SUPERVISOR_SYSTEM_PROMPT


def test_prompt_lists_the_exact_tokens():
    assert SUPERVISOR_SYSTEM_PROMPT.endswith(
        "Respond with ONLY the category name: policy, account_status, or escalation."
    )


# --- classify_query and classify_intent (task 2.3) ---------------------------


def test_prompt_shape(recording_chat):
    recording_chat.reply = "policy"
    query = "What is the overdraft fee?"
    raw, intent = classify_query(query)
    assert (raw, intent) == ("policy", "policy")
    assert len(recording_chat.calls) == 1
    system, human = recording_chat.calls[0]
    assert isinstance(system, SystemMessage) and isinstance(human, HumanMessage)
    assert system.content == SUPERVISOR_SYSTEM_PROMPT
    assert human.content == query


def test_braces_in_the_query_pass_through(recording_chat):
    recording_chat.reply = "policy"
    query = "What is {x} and {{y}}?"
    classify_query(query)
    assert recording_chat.calls[0][1].content == query


def test_raw_reply_is_returned_but_not_stored(recording_chat):
    recording_chat.reply = '"escalation"'
    assert classify_query("help") == ('"escalation"', "escalation")
    result = classify_intent(initial_state("help"))
    assert result == {"intent": "escalation"}


@pytest.mark.parametrize("reply", ["Policy\n", "nonsense", ""])
def test_classify_intent_writes_only_a_vocabulary_member(recording_chat, reply):
    recording_chat.reply = reply
    result = classify_intent(initial_state("q"))
    assert set(result) == {"intent"}
    assert result["intent"] in VALID_INTENTS


def test_model_errors_propagate(monkeypatch):
    def unreachable(*args, **kwargs):
        raise ConnectionError("provider down")

    monkeypatch.setattr(llm, "get_llm", unreachable)
    with pytest.raises(ConnectionError, match="provider down"):
        classify_intent(initial_state("What is the overdraft fee?"))


# --- route_by_intent ---------------------------------------------------------


@pytest.mark.parametrize(
    "intent, node",
    [
        ("policy", "policy_agent"),
        ("account_status", "account_agent"),
        ("escalation", "escalation_agent"),
        ("unknown", "policy_agent"),
        ("", "policy_agent"),
    ],
)
def test_route_by_intent(intent, node, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("routing must not call a model")

    monkeypatch.setattr(llm, "get_llm", forbidden)
    state = initial_state("q")
    state["intent"] = intent
    assert route_by_intent(state) == node


def test_intent_table_covers_the_vocabulary():
    assert set(INTENT_TO_NODE) == set(VALID_INTENTS)


def test_classify_intent_docstring_keeps_the_rule():
    doc = classify_intent.__doc__ or ""
    assert "normalized vocabulary member" in doc
    assert "NotImplementedError" not in doc
    assert re.search(r"specs/support-state/spec\.md", doc)


# --- Diagram rendering (task 3.3) --------------------------------------------

PLANTUML_GOLDEN = """@startuml
[*] --> classify_intent
classify_intent -[dashed]-> policy_agent : policy
classify_intent -[dashed]-> account_agent : account_status
classify_intent -[dashed]-> escalation_agent : escalation
policy_agent --> [*]
account_agent --> [*]
escalation_agent --> [*]
@enduml"""


def test_plantuml_golden_text(policy_env):
    from finos.graph import build_support_agent, render_plantuml

    assert render_plantuml(build_support_agent()) == PLANTUML_GOLDEN


def test_mermaid_names_all_four_nodes(policy_env):
    from finos.graph import build_support_agent, render_mermaid

    text = render_mermaid(build_support_agent())
    assert text.strip()
    for node in ("classify_intent", "policy_agent", "account_agent", "escalation_agent"):
        assert node in text
