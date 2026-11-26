"""Tests for the policy agent (Step 2, policy-agent).

The default run is offline: ``policy_env`` (see ``conftest.py``) gives each
test a ``tmp_path`` index built with fake embeddings, and the chat model is
replaced by :class:`~tests.conftest.RecordingChatModel`. Tests that call real models are
marked ``live`` and run only with ``uv run pytest -m live``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from finos import config, vectorstore
from finos.agents import ask_policy, policy_agent
from finos.prompts import NOT_FOUND_MESSAGE, POLICY_SYSTEM_PROMPT
from finos.state import initial_state, validate_state
from finos.vectorstore import SearchHit
from tests.conftest import RecordingChatModel

CORPUS_NAMES = frozenset(p.name for p in config.POLICY_DOCS_DIR.glob("*.md"))


@pytest.fixture
def chat(policy_env, recording_chat) -> RecordingChatModel:
    """The shared recording fake, inside the offline policy world."""
    return recording_chat


def _hit(rank: int, source: str, text: str = "text") -> SearchHit:
    return SearchHit(rank=rank, score=1 - rank / 10, source=source, chunk_index=0, text=text)


# --- Requirement: The prompt enforces grounding ------------------------------


def test_prompt_carries_the_rules():
    assert NOT_FOUND_MESSAGE in POLICY_SYSTEM_PROMPT
    assert "{context}" in POLICY_SYSTEM_PROMPT
    assert "{question}" not in POLICY_SYSTEM_PROMPT
    for rule in ("ONLY", "exactly", "speculate", "financial advice", "conflicting"):
        assert rule in POLICY_SYSTEM_PROMPT
    # The template must have exactly one variable.
    assert set(re.findall(r"\{(\w+)\}", POLICY_SYSTEM_PROMPT)) == {"context"}


def test_not_found_message_has_no_invented_contact_details():
    assert "@" not in NOT_FOUND_MESSAGE
    assert not re.search(r"\d{3}", NOT_FOUND_MESSAGE)
    assert NOT_FOUND_MESSAGE.startswith("I don't have that information")


# --- Requirement: The policy agent writes only the fields it owns ------------


def test_returns_exactly_three_keys(chat):
    result = policy_agent(initial_state("What is the overdraft fee?"))
    assert set(result) == {"response", "context", "retrieved_sources"}
    assert result["response"] == chat.reply


def test_sources_are_distinct_and_ranked(chat, monkeypatch):
    hits = [_hit(1, "account_fees.md"), _hit(2, "account_fees.md"), _hit(3, "fraud_policy.md")]
    monkeypatch.setattr(vectorstore, "search", lambda query, k=None: hits)
    result = policy_agent(initial_state("replacement card"))
    assert result["retrieved_sources"] == ["account_fees.md", "fraud_policy.md"]


def test_context_is_what_the_model_saw(chat):
    result = policy_agent(initial_state("What is the overdraft fee?"))
    assert result["context"]
    (messages,) = chat.calls
    assert result["context"] in messages[0].content
    expected = POLICY_SYSTEM_PROMPT.replace("{context}", result["context"])
    assert messages[0].content == expected


def test_sources_are_bare_filenames_in_the_corpus(chat):
    """The support-state obligation: bare filenames only (specs/support-state)."""
    result = policy_agent(initial_state("How do I report fraud?"))
    assert result["retrieved_sources"]
    for source in result["retrieved_sources"]:
        assert "/" not in source and "\\" not in source
        assert source in CORPUS_NAMES


# --- Requirement: Answers are generated from the retrieved context -----------


def test_prompt_contents(chat):
    query = "What is the overdraft fee?"
    policy_agent(initial_state(query))
    assert len(chat.calls) == 1
    system, human = chat.calls[0]
    assert isinstance(system, SystemMessage)
    assert isinstance(human, HumanMessage)
    assert human.content == query
    assert "[1] (Source: " in system.content
    assert query not in system.content


def test_nothing_retrieved_still_generates(chat, monkeypatch):
    monkeypatch.setattr(vectorstore, "search", lambda query, k=None: [])
    result = policy_agent(initial_state("anything"))
    assert len(chat.calls) == 1
    assert result == {"response": chat.reply, "context": "", "retrieved_sources": []}
    assert chat.calls[0][0].content == POLICY_SYSTEM_PROMPT.replace("{context}", "")


def test_response_is_the_model_text(chat):
    chat.reply = "A specific reply."
    assert policy_agent(initial_state("q"))["response"] == "A specific reply."


def test_list_content_is_joined_as_text():
    from finos.agents.policy import _message_text

    message = AIMessage(content=[{"type": "text", "text": "a"}, "b", {"type": "image"}])
    assert _message_text(message) == "ab"


def test_agent_does_not_touch_query_or_intent(chat):
    state = initial_state("What is the overdraft fee?")
    state["intent"] = "policy"
    before = dict(state)
    result = policy_agent(state)
    assert "query" not in result and "intent" not in result
    assert state == before


# --- Requirement: The policy agent can run without the graph -----------------


def test_ask_policy_returns_a_complete_state(chat):
    state = ask_policy("What is the overdraft fee?")
    assert list(state) == ["query", "intent", "response", "context", "retrieved_sources"]
    assert state["query"] == "What is the overdraft fee?"
    assert state["intent"] == "policy"
    assert state["response"] == chat.reply
    assert state["context"]


def test_ask_policy_passes_strict_validation(chat):
    state = ask_policy("What is the overdraft fee?")
    assert validate_state(state, strict=True, known_sources=CORPUS_NAMES) == []


# --- Requirement: Importing the agent has no side effects --------------------


def test_import_has_no_side_effects(tmp_path):
    """A fresh process imports the agents with no key and no index directory."""
    missing = tmp_path / "chroma-not-here"
    code = (
        "import sys\n"
        "from finos import config\n"
        f"config.CHROMA_DIR = __import__('pathlib').Path({str(missing)!r})\n"
        "import finos.agents, finos.agents.policy\n"
        "assert not config.CHROMA_DIR.exists()\n"
        "assert config.get_settings.cache_info().currsize == 0\n"
        "heavy = [m for m in ('chromadb', 'langchain_chroma') if m in sys.modules]\n"
        "assert not heavy, heavy\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert not missing.exists()


# =============================================================================
# Live tests: real models, run only with `uv run pytest -m live`.
#
# They use whichever provider config.toml selects (and the real .env), with
# the index built into a temporary directory so data/chroma/ is untouched.
# =============================================================================

# Thousands groups must be complete ("$1,500"), so punctuation after an
# amount ("a fee of $12, which ...") is not captured as part of it.
DOLLAR_AMOUNT = re.compile(r"\$\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$\d+(?:\.\d+)?")


def dollar_amounts(text: str) -> set[str]:
    """Return the dollar amounts in ``text``, without trailing punctuation."""
    return set(DOLLAR_AMOUNT.findall(text))


@pytest.mark.parametrize(
    "text, expected",
    [
        ("carries a fee of $12, which is lower", {"$12"}),
        ("The fee is $12.", {"$12"}),
        ("balances of $1,500, or more", {"$1,500"}),
        ("$12.99 per month", {"$12.99"}),
        ("3 fees per day ($105).", {"$105"}),
        ("$35 and $5", {"$35", "$5"}),
        ("no amounts here", set()),
    ],
)
def test_dollar_amounts_ignore_trailing_punctuation(text, expected):
    """Offline check of the extractor the hallucination test relies on."""
    assert dollar_amounts(text) == expected


def test_dollar_amounts_in_overdraft_protection_context():
    """The chunk that answers the protection question yields a clean $12."""
    chunk = next(
        c.page_content
        for c in vectorstore.chunk_documents(vectorstore.load_documents(), 1000, 100)
        if c.id == "account_fees.md:2"
    )
    assert "$12" in dollar_amounts(chunk)
    assert not any(amount.endswith((",", ".")) for amount in dollar_amounts(chunk))


@pytest.fixture(scope="module")
def live_index(tmp_path_factory):
    """Build a real-embedding index once for the live tests in this module."""
    from finos.llm import get_embeddings, get_llm

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(config, "CHROMA_DIR", tmp_path_factory.mktemp("live-chroma"))
        for cached in (config.get_settings, get_llm, get_embeddings, vectorstore.get_store):
            cached.cache_clear()
        vectorstore.ensure_index()
        yield
        vectorstore.get_store.cache_clear()


# --- Requirement: The default answers meet the baseline facts ---------------


@pytest.mark.live
def test_live_overdraft_fee(live_index):
    state = ask_policy("What is the overdraft fee?")
    assert "$35" in state["response"]
    assert "account_fees.md" in state["retrieved_sources"]


@pytest.mark.live
def test_live_auto_loan_apr(live_index):
    state = ask_policy("What is the APR range for auto loans?")
    assert "4.49%" in state["response"] or "12.99%" in state["response"]
    assert "loan_policy.md" in state["retrieved_sources"]


@pytest.mark.live
def test_live_out_of_scope_question(live_index):
    # Not in the corpus, and not a guarded topic: the policy agent itself must
    # give the not-found answer. (Investment questions such as "What is the
    # stock market outlook?" are blocked by the guardrails before the agent
    # runs since Hardening 3; see test_live_investment_question_is_blocked.)
    state = ask_policy("What are SecureBank's branch opening hours on Saturdays?")
    assert "I don't have that information" in state["response"]


@pytest.mark.live
def test_live_investment_question_is_blocked(live_index):
    from finos.prompts import GUARDRAIL_FALLBACK_MESSAGE

    state = ask_policy("What is the stock market outlook?")
    assert state["response"] == GUARDRAIL_FALLBACK_MESSAGE
    assert state["retrieved_sources"] == []


@pytest.mark.live
@pytest.mark.parametrize(
    "query",
    [
        "What is the overdraft fee?",
        "What are the wire transfer fees?",
        "How long do I have to report fraud?",
    ],
)
def test_live_sources_are_in_the_corpus(live_index, query):
    state = ask_policy(query)
    assert state["retrieved_sources"]
    assert validate_state(state, strict=True, known_sources=CORPUS_NAMES) == []


@pytest.mark.live
def test_live_top_hit_for_overdraft_is_account_fees(live_index):
    """The explore doc's search acceptance check."""
    assert vectorstore.search("overdraft", k=2)[0].source == "account_fees.md"


# --- Requirement: Known failure modes are recorded as a baseline ------------
#
# Each test asserts the *correct* behavior. At the lecture's baseline the
# failure is expected to reproduce, so the test is an expected failure
# (XFAIL). An XPASS means the failure no longer reproduces with this
# provider and configuration: worth noting for the evaluation phase.


@pytest.mark.live
@pytest.mark.xfail(
    strict=False,
    reason="split fact: the $12 overdraft protection fee sits in a different "
    "chunk from the $35 fee it replaces, so retrieval can miss it",
)
def test_live_failure_split_fact(live_index):
    state = ask_policy("How much does overdraft protection cost?")
    assert "$12" in state["response"]


@pytest.mark.live
@pytest.mark.xfail(
    strict=False,
    reason="wrong document: the replacement-card question ranks "
    "fraud_policy.md (free replacement) above account_fees.md ($5)",
)
def test_live_failure_wrong_document(live_index):
    hits = vectorstore.search("How much does a replacement debit card cost?")
    assert hits[0].source == "account_fees.md"


@pytest.mark.live
@pytest.mark.xfail(
    strict=False,
    reason="hallucinated amount: the response states a dollar amount that "
    "is not in the retrieved context",
)
@pytest.mark.parametrize(
    "query",
    [
        "How much does overdraft protection cost?",
        "What does a replacement debit card cost?",
        "What is the late fee on a personal loan?",
    ],
)
def test_live_failure_hallucinated_amount(live_index, query):
    state = ask_policy(query)
    context_amounts = dollar_amounts(state["context"])
    response_amounts = dollar_amounts(state["response"])
    assert response_amounts <= context_amounts, (
        f"amounts not in context: {sorted(response_amounts - context_amounts)}; "
        f"response: {state['response']!r}"
    )


@pytest.mark.live
@pytest.mark.xfail(
    strict=False,
    reason="empty retrieval: a vague query retrieves nothing useful, so the "
    "agent answers with the not-found message",
)
def test_live_failure_empty_retrieval(live_index):
    state = ask_policy("What does it cost?")
    assert state["context"]
    assert not state["response"].startswith(NOT_FOUND_MESSAGE[:30])
