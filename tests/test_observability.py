"""Tests for tracing, masking, and timings (hardening 1, observability).

Every test is offline. :class:`FakeClient` is a ``langsmith.Client`` subclass
that records the runs it is asked to upload instead of sending them, and the
``traced`` fixture turns tracing on through ``tracing_context`` with a fake
key and that client in place of the masking client. ``policy_env`` gives a
private config (tracing off in the file), a ``tmp_path`` index with fake
embeddings, and ``recording_chat`` replaces the chat model.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langsmith import Client, tracing_context

from finos import config, observability
from finos.agents import ask_account, ask_escalation, ask_policy, supervisor
from finos.graph import build_support_agent
from finos.main import ask
from finos.observability import REDACTED, mask, observe, root
from tests.conftest import RecordingChatModel

FAKE_KEY = "lsv2-test-not-a-real-key"


class FakeClient(Client):
    """Records runs instead of uploading them. No network is touched."""

    __slots__ = ("runs", "order", "fail")

    def __init__(self, *, fail: bool = False, **kwargs: Any) -> None:
        from langsmith.schemas import LangSmithInfo

        super().__init__(
            api_key=FAKE_KEY, auto_batch_tracing=False, info=LangSmithInfo(), **kwargs
        )
        self.runs: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.fail = fail

    def create_run(self, name=None, inputs=None, run_type=None, **kwargs):  # noqa: D401
        if self.fail:
            raise ConnectionError("tracing service unreachable")
        run_id = str(kwargs.get("id"))
        self.runs[run_id] = {
            "id": run_id,
            "name": name,
            "run_type": run_type,
            "inputs": inputs,
            "outputs": kwargs.get("outputs"),
            "parent": str(kwargs["parent_run_id"]) if kwargs.get("parent_run_id") else None,
            "trace_id": str(kwargs.get("trace_id")),
            "tags": list(kwargs.get("tags") or []),
            "metadata": dict((kwargs.get("extra") or {}).get("metadata") or {}),
        }
        self.order.append(run_id)

    def update_run(self, run_id, **kwargs):
        if self.fail:
            raise ConnectionError("tracing service unreachable")
        run = self.runs.setdefault(str(run_id), {"id": str(run_id)})
        if kwargs.get("outputs") is not None:
            run["outputs"] = kwargs["outputs"]
        if kwargs.get("tags"):
            run["tags"] = sorted(set(run.get("tags", [])) | set(kwargs["tags"]))
        if kwargs.get("error"):
            run["error"] = kwargs["error"]
        metadata = (kwargs.get("extra") or {}).get("metadata")
        if metadata:
            run.setdefault("metadata", {}).update(metadata)

    # --- Views ---------------------------------------------------------------

    def named(self, name: str) -> list[dict[str, Any]]:
        return [self.runs[i] for i in self.order if self.runs[i]["name"] == name]

    def one(self, name: str) -> dict[str, Any]:
        runs = self.named(name)
        assert len(runs) == 1, (name, [self.runs[i]["name"] for i in self.order])
        return runs[0]

    def roots(self) -> list[dict[str, Any]]:
        return [self.runs[i] for i in self.order if self.runs[i]["parent"] is None]

    def parent_name(self, name: str) -> str | None:
        parent = self.one(name)["parent"]
        return self.runs[parent]["name"] if parent else None

    def children(self, name: str, *, guards: bool = False) -> list[str]:
        """Child run names in order; ``guardrail_check`` runs only with ``guards=True``."""
        parent = self.one(name)["id"]
        return [
            self.runs[i]["name"]
            for i in self.order
            if self.runs[i]["parent"] == parent
            and (guards or self.runs[i]["name"] != "guardrail_check")
        ]

    def names(self) -> list[str]:
        """Visible run names in creation order, LangGraph's hidden runs left out."""
        return [
            self.runs[i]["name"]
            for i in self.order
            if "langsmith:hidden" not in self.runs[i].get("tags", [])
        ]


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeClient):
    monkeypatch.setenv("LANGSMITH_API_KEY", FAKE_KEY)
    monkeypatch.setattr(observability, "masking_client", lambda: fake)


@pytest.fixture
def traced(policy_env, monkeypatch):
    """Tracing on, offline: a fake key, and the fake client for every root."""
    fake = FakeClient(hide_inputs=mask, hide_outputs=mask)
    _install(monkeypatch, fake)
    with tracing_context(enabled=True, client=fake, project_name="finos"):
        yield fake


@pytest.fixture
def steer(monkeypatch):
    """Make the supervisor's model reply with a chosen category."""

    def set_reply(chat: RecordingChatModel, reply: str) -> None:
        chat.reply = reply

    return set_reply


class SequenceChat(RecordingChatModel):
    """Replies with each of ``replies`` in turn, with token usage when given."""

    replies: list[str] = []
    usage: list[dict[str, int] | None] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        self.calls.append(list(messages))
        index = len(self.calls) - 1
        reply = self.replies[min(index, len(self.replies) - 1)] if self.replies else self.reply
        usage = self.usage[index] if index < len(self.usage) else None
        message = AIMessage(reply)
        if usage is not None:
            message = AIMessage(
                reply,
                usage_metadata={
                    "input_tokens": usage["input"],
                    "output_tokens": usage["output"],
                    "total_tokens": usage["input"] + usage["output"],
                },
            )
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.fixture
def sequence_chat(monkeypatch) -> SequenceChat:
    from finos import llm

    model = SequenceChat(calls=[], replies=[], usage=[])
    monkeypatch.setattr(llm, "get_llm", lambda *a, **k: model)
    return model


def _all_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [s for v in value.values() for s in _all_values(v)] + [str(k) for k in value]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _all_values(v)]
    return [str(value)]


# =============================================================================
# 3.1 Roots: tags and metadata
# =============================================================================


def test_root_tags_default_to_the_api_entry(traced):
    with root("policy_query") as run:
        pass
    assert run.traced
    tags = traced.one("policy_query")["tags"]
    assert "entry:api" in tags
    assert any(tag.startswith("provider:") for tag in tags)


def test_root_takes_its_entry_from_the_observation(traced):
    with observe("policy-ask") as observation:
        with root("policy_query") as run:
            pass
    assert "entry:policy-ask" in traced.one("policy_query")["tags"]
    assert observation.trace_id == run.trace_id == traced.one("policy_query")["trace_id"]


def test_root_provider_tag_follows_the_switch(traced, policy_env):
    policy_env.set_local_provider(False)
    with root("policy_query"):
        pass
    policy_env.set_local_provider(True)
    with root("account_query"):
        pass
    assert "provider:openai" in traced.one("policy_query")["tags"]
    assert "provider:ollama" in traced.one("account_query")["tags"]


def test_root_metadata_records_the_configuration(traced, policy_env):
    import hashlib

    from finos import prompts
    from importlib.metadata import version

    with root("policy_query"):
        pass
    metadata = traced.one("policy_query")["metadata"]
    settings = config.get_settings()
    provider = "ollama" if settings["llm"]["use_local_ollama_model"] else "openai"
    assert metadata["provider"] == provider
    assert metadata["chat_model"] == settings[provider]["model"]
    assert metadata["embedding_model"] == settings[provider]["embedding_model"]
    assert metadata["temperature"] == settings["llm"]["temperature"]
    for key in ("chunk_size", "chunk_overlap", "top_k", "collection"):
        assert metadata[key] == settings["policy"][key]
    assert metadata["index_fingerprint"] == "none"  # no index built yet
    assert metadata["finos_version"] == version("finos")
    expected = {
        name: hashlib.sha256(text.encode()).hexdigest()[:8]
        for name, text in {
            "supervisor": prompts.SUPERVISOR_SYSTEM_PROMPT,
            "policy": prompts.POLICY_SYSTEM_PROMPT,
            "account": prompts.ACCOUNT_SYSTEM_PROMPT,
            "escalation": prompts.ESCALATION_SYSTEM_PROMPT,
            "judge_faithfulness": prompts.JUDGE_FAITHFULNESS_PROMPT,
            "judge_correctness": prompts.JUDGE_CORRECTNESS_PROMPT,
            "judge_empathy": prompts.JUDGE_EMPATHY_PROMPT,
        }.items()
    }
    assert metadata["prompt_versions"] == expected
    assert all(len(h) == 8 for h in expected.values())


def test_root_metadata_reads_the_index_fingerprint(traced, policy_env, recording_chat):
    from finos.vectorstore import ensure_index, read_marker

    ensure_index()
    with root("policy_query"):
        pass
    assert traced.one("policy_query")["metadata"]["index_fingerprint"] == read_marker()[
        "fingerprint"
    ]


def test_root_merges_config_tags_and_metadata(traced):
    with root("policy_query", config={"tags": ["extra"], "metadata": {"run_label": "x"}}):
        pass
    run = traced.one("policy_query")
    assert "extra" in run["tags"] and "entry:api" in run["tags"]
    assert run["metadata"]["run_label"] == "x"
    assert "provider" in run["metadata"]


def test_no_customer_data_in_tags_or_metadata(traced, recording_chat):
    query = "What is the balance on ACC-12345?"
    with observe("account-ask"):
        ask_account(query)
    record = json.loads(config.MOCK_ACCOUNTS_PATH.read_text())[0]
    forbidden = {query, "ACC-12345", record["holder_name"]} | {
        str(v) for v in record.values() if not isinstance(v, (list, bool))
    }
    for run in traced.runs.values():
        values = run.get("tags", []) + _all_values(run.get("metadata", {}))
        for value in values:
            for item in forbidden:
                assert item not in value, (run["name"], value, item)


def test_root_untraced_when_tracing_is_off(policy_env, monkeypatch):
    """With tracing off, no client is built and nothing is traced."""

    def no_client():
        raise AssertionError("no client may be built with tracing off")

    monkeypatch.setattr(observability, "masking_client", no_client)
    with observe("policy-ask") as observation:
        with root("policy_query") as run:
            pass
    assert not run.traced
    assert observation.trace_id is None


def test_root_body_exceptions_propagate(traced):
    with pytest.raises(ValueError, match="boom"):
        with root("policy_query"):
            raise ValueError("boom")
    assert "boom" in traced.one("policy_query").get("error", "")


# =============================================================================
# 3.2 Masking
# =============================================================================


@pytest.fixture(autouse=True)
def _fresh_known_values():
    observability._known_ssn_pattern.cache_clear()
    yield
    observability._known_ssn_pattern.cache_clear()


def test_mask_ssn_field_in_json():
    text = json.dumps({"account_id": "ACC-12345", "ssn_last4": "1111"}, indent=2)
    masked = mask(text)
    assert f'"ssn_last4": "{REDACTED}"' in masked
    assert "1111" not in masked
    assert "ACC-12345" in masked


def test_mask_ssn_field_in_python_repr():
    text = repr({"ssn_last4": "1111", "balance": 10.5})
    masked = mask(text)
    assert f"'ssn_last4': '{REDACTED}'" in masked
    assert "1111" not in masked


def test_mask_ssn_dict_key():
    assert mask({"ssn_last4": "6789", "x": 1}) == {"ssn_last4": REDACTED, "x": 1}


@pytest.mark.parametrize("value", ["6789", "4321", "9876", "1357"])
def test_mask_known_values_as_standalone_numbers(value):
    masked = mask(f"The last four are {value}.")
    assert masked == f"The last four are {REDACTED}."
    # Digits adjacent on either side are not a standalone match.
    assert mask(f"ref 1{value}2") == f"ref 1{value}2"


def test_mask_full_ssn():
    assert mask("SSN 123-45-6789 on file") == f"SSN {REDACTED} on file"


def test_mask_marker():
    assert REDACTED == "[REDACTED:ssn]"


def test_mask_nested_dicts_and_lists():
    payload = {
        "messages": [[{"content": "Your SSN ends in 6789."}, ("x", "123-45-6789")]],
        "outer": {"inner": {"text": '"ssn_last4": "6789"'}},
    }
    masked = mask(payload)
    assert "6789" not in json.dumps(masked)
    assert masked["messages"][0][0]["content"] == f"Your SSN ends in {REDACTED}."


def test_mask_pydantic_messages():
    masked = mask({"output": AIMessage("It ends in 6789")})
    assert masked["output"]["content"] == f"It ends in {REDACTED}"


@pytest.mark.parametrize("text", ["$1,500", "2026", "ACC-12345", "12450.75", "2026-10-28"])
def test_mask_leaves_ordinary_numbers(text):
    assert mask(text) == text


def test_mask_without_records_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MOCK_ACCOUNTS_PATH", tmp_path / "missing.json")
    observability._known_ssn_pattern.cache_clear()
    assert mask("ends in 6789") == "ends in 6789"
    assert mask('"ssn_last4": "6789"') == f'"ssn_last4": "{REDACTED}"'
    assert mask("123-45-6789") == REDACTED


def test_masking_client_hides_with_mask(monkeypatch):
    """The process client is built with ``mask`` as both hide functions, once."""
    import langsmith

    built: list[dict[str, Any]] = []

    def offline_client(**kwargs):
        built.append(kwargs)
        return FakeClient(**kwargs)  # a real Client, minus the network

    monkeypatch.setenv("LANGSMITH_API_KEY", FAKE_KEY)
    monkeypatch.setattr(langsmith, "Client", offline_client)
    monkeypatch.setattr(observability, "_client", None)
    client = observability.masking_client()
    assert built == [{"hide_inputs": mask, "hide_outputs": mask}]
    assert client._hide_inputs is mask
    assert client._hide_outputs is mask
    assert observability.masking_client() is client


def test_root_uploads_through_the_masking_client(policy_env, monkeypatch):
    """``root()`` hands its runs to ``masking_client()``, not the context's client."""
    fake = FakeClient(hide_inputs=mask, hide_outputs=mask)
    other = FakeClient()
    _install(monkeypatch, fake)
    with tracing_context(enabled=True, client=other, project_name="finos"):
        with root("policy_query"):
            pass
    assert fake.named("policy_query") and not other.runs


# =============================================================================
# 3.3 Light imports
# =============================================================================


def test_importing_agents_and_observability_loads_no_langsmith():
    code = (
        "import sys\n"
        "import finos.agents, finos.observability, finos.main\n"
        "print('langsmith' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


def test_help_loads_no_langsmith():
    code = (
        "import sys\n"
        "from typer.testing import CliRunner\n"
        "from finos.cli.main import app\n"
        "result = CliRunner().invoke(app, ['--help'], prog_name='finos')\n"
        "assert result.exit_code == 0\n"
        "print('langsmith' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


# =============================================================================
# 4.1 The graph's run tree
# =============================================================================


def test_graph_policy_run_tree(traced, recording_chat):
    recording_chat.reply = "policy"
    with observe("supervisor-ask"):
        ask(build_support_agent(), "What is the overdraft fee?")
    assert [r["name"] for r in traced.roots()] == ["support_query"]
    assert traced.parent_name("support_graph") == "support_query"
    assert traced.parent_name("classify_intent") == "support_graph"
    assert traced.parent_name("policy_agent") == "support_graph"
    assert not traced.named("account_agent") and not traced.named("escalation_agent")
    assert traced.parent_name("supervisor_llm") == "classify_intent"
    assert traced.parent_name("normalize_intent") == "classify_intent"
    assert traced.parent_name("policy_retrieval") == "policy_agent"
    assert traced.parent_name("policy_llm") == "policy_agent"
    order = [n for n in traced.names() if n in {
        "supervisor_llm", "normalize_intent", "policy_retrieval", "policy_llm"}]
    assert order == ["supervisor_llm", "normalize_intent", "policy_retrieval", "policy_llm"]
    assert len({run["trace_id"] for run in traced.runs.values()}) == 1


@pytest.mark.parametrize(
    "reply, intent, node",
    [
        ("account_status", "account_status", "account_agent"),
        ("escalation", "escalation", "escalation_agent"),
        ("policy", "policy", "policy_agent"),
    ],
)
def test_root_gets_the_intent_tag_after_routing(traced, sequence_chat, reply, intent, node):
    sequence_chat.replies = [reply, "An answer."]
    with observe("supervisor-ask"):
        state = ask(build_support_agent(), "Tell me about ACC-12345")
    assert state["intent"] == intent
    tags = traced.one("support_query")["tags"]
    assert {"entry:supervisor-ask", f"intent:{intent}"} <= set(tags)
    assert any(tag.startswith("provider:") for tag in tags)
    assert traced.named(node)
    # The intent tag is added to the root only, after the graph returned.
    assert not any(tag.startswith("intent:") for tag in traced.one("support_graph")["tags"])


def test_normalize_intent_records_its_decision(traced, recording_chat):
    recording_chat.reply = "  Account Status  "
    ask(build_support_agent(), "What is the balance on ACC-12345?")
    run = traced.one("normalize_intent")
    assert run["run_type"] == "parser"
    assert run["inputs"] == {"raw": "  Account Status  "}
    assert run["outputs"] == {"intent": "account_status", "fallback": False}


def test_normalize_intent_marks_the_fallback(traced, recording_chat):
    recording_chat.reply = "I cannot classify this"
    state = ask(build_support_agent(), "What is the overdraft fee?")
    assert state["intent"] == "policy"
    assert traced.one("normalize_intent")["outputs"] == {"intent": "policy", "fallback": True}


def test_ask_with_and_without_config_returns_the_same_state(traced, recording_chat):
    recording_chat.reply = "policy"
    app = build_support_agent()
    plain = ask(app, "What is the overdraft fee?")
    configured = ask(
        app, "What is the overdraft fee?", config={"tags": ["exp-free"], "metadata": {"k": "v"}}
    )
    assert plain == configured
    first, second = traced.named("support_query")
    assert "exp-free" not in first["tags"] and "exp-free" in second["tags"]
    assert second["metadata"]["k"] == "v"


def test_supervisor_classify_root(traced, recording_chat):
    recording_chat.reply = "escalation"
    with root("supervisor_classify"):
        raw, intent = supervisor.classify_query("I'm furious!")
    assert intent == "escalation"
    assert traced.children("supervisor_classify") == ["supervisor_llm", "normalize_intent"]


# =============================================================================
# 4.2 Policy: retrieval as a retriever run
# =============================================================================


def test_standalone_policy_run_tree(traced, recording_chat):
    ask_policy("What is the overdraft fee?")
    assert [r["name"] for r in traced.roots()] == ["policy_query"]
    assert traced.children("policy_query") == ["policy_retrieval", "policy_llm"]
    # The input guards run first, the output guards last (Hardening 3).
    children = traced.children("policy_query", guards=True)
    assert children[0] == "guardrail_check" and children[-1] == "guardrail_check"


def test_policy_retrieval_is_a_retriever_with_documents(traced, recording_chat):
    from finos.vectorstore import search

    state = ask_policy("What is the overdraft fee?")
    run = traced.one("policy_retrieval")
    assert run["run_type"] == "retriever"
    assert run["inputs"] == {"query": "What is the overdraft fee?"}
    documents = run["outputs"]["documents"]
    hits = search("What is the overdraft fee?")
    assert len(documents) == len(hits) > 0
    for document, hit in zip(documents, hits):
        assert document["page_content"] == hit.text
        assert document["metadata"] == {
            "source": hit.source,
            "chunk_index": hit.chunk_index,
            "score": hit.score,
        }
    scores = [d["metadata"]["score"] for d in documents]
    assert scores == sorted(scores, reverse=True)
    assert [d["metadata"]["source"] for d in documents][0] == state["retrieved_sources"][0]


def test_index_builds_produce_no_run(traced, recording_chat, policy_env):
    """The first query builds the index; no run for the build or its embeddings."""
    ask_policy("What is the overdraft fee?")
    assert policy_env.embeddings.documents_embedded > 0  # a build happened
    assert set(traced.names()) <= {
        "policy_query", "policy_retrieval", "policy_llm", "ChatPromptTemplate",
        "RecordingChatModel", "guardrail_check",
    }


def test_policy_search_root(traced, recording_chat):
    from finos.vectorstore import traced_search

    with root("policy_search"):
        traced_search("What is the overdraft fee?", k=2)
    assert traced.children("policy_search") == ["policy_retrieval"]
    assert len(traced.one("policy_retrieval")["outputs"]["documents"]) == 2


# =============================================================================
# 4.3 Account: resolution as a tool run
# =============================================================================


@pytest.mark.parametrize(
    "query, outcome, ids, llm",
    [
        ("What is the balance on ACC-12345?", "found", ["ACC-12345"], True),
        ("What is the balance on ACC-99999?", "not_found", ["ACC-99999"], False),
        ("Show my recent transactions", "no_id", [], False),
        ("Compare ACC-12345 and ACC-67890", "multiple_ids", ["ACC-12345", "ACC-67890"], False),
    ],
)
def test_account_run_trees(traced, recording_chat, query, outcome, ids, llm):
    ask_account(query)
    expected = ["account_resolution", "account_llm"] if llm else ["account_resolution"]
    assert traced.children("account_query") == expected
    run = traced.one("account_resolution")
    assert run["run_type"] == "tool"
    assert run["inputs"] == {"query": query}
    assert run["outputs"] == {"outcome": outcome, "account_ids": ids}


def test_account_resolution_omits_the_record(traced, recording_chat):
    ask_account("What is the balance on ACC-12345?")
    output = json.dumps(traced.one("account_resolution")["outputs"])
    record = json.loads(config.MOCK_ACCOUNTS_PATH.read_text())[0]
    for key, value in record.items():
        if key == "account_id":
            continue
        assert f'"{key}"' not in output
        if not isinstance(value, (list, bool)):
            assert str(value) not in output, key


def test_account_llm_input_is_masked(traced, recording_chat):
    ask_account("What is the balance on ACC-12345?")
    inputs = traced.one("account_llm")["inputs"]
    # Since Hardening 3 the model's record omits ssn_last4 (data
    # minimization), so even the unmasked input holds no SSN data.
    assert "6789" not in json.dumps(inputs)
    assert '\\"ssn_last4\\"' not in json.dumps(inputs)
    masked = json.dumps(mask(inputs))
    assert "6789" not in masked
    assert "12,450.75" in masked or "12450.75" in masked


def test_account_reply_leak_is_masked(traced, recording_chat):
    recording_chat.reply = "Your SSN ends in 6789."
    ask_account("What is the balance on ACC-12345?")
    outputs = json.dumps(mask(traced.one("account_llm")["outputs"]))
    assert "6789" not in outputs and REDACTED in outputs


# =============================================================================
# 4.4 Escalation: assembly as a parser run
# =============================================================================


def test_escalation_run_tree(traced, recording_chat):
    recording_chat.reply = "I'm sorry this has been so frustrating."
    ask_escalation("I'm furious!")
    assert traced.children("escalation_query") == ["escalation_llm", "escalation_assembly"]
    run = traced.one("escalation_assembly")
    assert run["run_type"] == "parser"
    assert run["inputs"] == {"raw": "I'm sorry this has been so frustrating."}
    assert run["outputs"] == {"used_fallback": False}


def test_escalation_assembly_marks_a_blank_reply(traced, recording_chat):
    recording_chat.reply = "   "
    ask_escalation("I'm furious!")
    assert traced.one("escalation_assembly")["outputs"] == {"used_fallback": True}


# =============================================================================
# 4.5 Tracing never changes results
# =============================================================================


QUERIES = {
    "policy": "What is the overdraft fee?",
    "account_status": "What is the balance on ACC-12345?",
    "escalation": "I'm furious! Nobody is helping!",
}


def _run_all(recording_chat) -> list[Any]:
    results = []
    for intent, query in QUERIES.items():
        recording_chat.reply = intent
        results.append(ask(build_support_agent(), query))
    recording_chat.reply = "A fixed answer."
    results.append(ask_policy(QUERIES["policy"]))
    results.append(ask_account(QUERIES["account_status"]))
    results.append(ask_escalation(QUERIES["escalation"]))
    return results


def test_same_results_with_tracing_on_and_off(policy_env, recording_chat, monkeypatch):
    untraced = _run_all(recording_chat)

    fake = FakeClient(hide_inputs=mask, hide_outputs=mask)
    _install(monkeypatch, fake)
    with tracing_context(enabled=True, client=fake, project_name="finos"):
        traced_results = _run_all(recording_chat)
    assert fake.runs  # really traced
    assert traced_results == untraced


# langchain-core's tracer uses deprecated pydantic calls on its error path.
@pytest.mark.filterwarnings("ignore::DeprecationWarning:langchain_core")
def test_upload_failure_does_not_change_results(policy_env, recording_chat, monkeypatch):
    untraced = _run_all(recording_chat)

    broken = FakeClient(fail=True)
    _install(monkeypatch, broken)
    with tracing_context(enabled=True, client=broken, project_name="finos"):
        results = _run_all(recording_chat)
    assert results == untraced


# =============================================================================
# 5.1 Timings and tokens
# =============================================================================


def test_graph_timings_with_tracing_off(policy_env, sequence_chat):
    sequence_chat.replies = ["policy", "The fee is $35."]
    sequence_chat.usage = [{"input": 98, "output": 3}, {"input": 1240, "output": 85}]
    app = build_support_agent()
    with observe("supervisor-ask") as observation:
        ask(app, "What is the overdraft fee?")
    assert observation.trace_id is None
    units = {unit.name: unit for unit in observation.units()}
    assert list(units) == ["classify_intent", "policy_agent"]
    assert units["classify_intent"].tokens == "98+3 tokens"
    assert units["classify_intent"].retrieval_ms is None
    assert units["policy_agent"].tokens == "1240+85 tokens"
    assert units["policy_agent"].retrieval_ms is not None
    assert units["policy_agent"].retrieval_ms <= units["policy_agent"].ms
    lines = observation.timing_lines()
    assert lines[0].startswith("classify_intent: ") and lines[0].endswith(", 98+3 tokens")
    assert " ms (retrieval " in lines[1] and lines[1].endswith(", 1240+85 tokens")
    assert lines[-1].startswith("total: ") and lines[-1].endswith(" s")


def test_standalone_timings_with_tracing_off(policy_env, sequence_chat):
    sequence_chat.replies = ["The fee is $35."]
    sequence_chat.usage = [{"input": 500, "output": 20}]
    with observe("policy-ask") as observation:
        ask_policy("What is the overdraft fee?")
    (unit,) = observation.units()
    assert unit.name == "policy_query"
    assert unit.retrieval_ms is not None
    assert unit.tokens == "500+20 tokens"


def test_missing_usage_reads_n_a(policy_env, recording_chat):
    recording_chat.reply = "I'm sorry."
    with observe("escalation-ask") as observation:
        ask_escalation("I'm furious!")
    (unit,) = observation.units()
    assert unit.tokens == "n/a tokens"
    assert unit.line().endswith(", n/a tokens")


def test_no_model_call_shows_no_tokens(policy_env, recording_chat):
    with observe("account-ask") as observation:
        ask_account("Show my recent transactions")
    (unit,) = observation.units()
    assert unit.tokens is None
    assert unit.line() == f"account_query: {unit.ms:.0f} ms"


def test_nothing_collected_outside_an_observation(policy_env, sequence_chat):
    sequence_chat.replies = ["policy", "The fee is $35."]
    ask(build_support_agent(), "What is the overdraft fee?")
    assert observability.current_observation() is None
    with observe("supervisor-ask") as observation:
        pass
    assert observation.units() == [] and observation.calls == []


def test_timings_also_collected_when_traced(traced, sequence_chat):
    sequence_chat.replies = ["escalation", "I'm sorry."]
    sequence_chat.usage = [{"input": 10, "output": 1}, {"input": 20, "output": 5}]
    with observe("supervisor-ask") as observation:
        ask(build_support_agent(), "I'm furious!")
    assert observation.trace_id == traced.one("support_query")["trace_id"]
    assert [u.line().split(":")[0] for u in observation.units()] == [
        "classify_intent",
        "escalation_agent",
    ]
    assert observation.units()[1].tokens == "20+5 tokens"


# =============================================================================
# 7.1 Live tests run under entry:live-test
# =============================================================================


def test_unmarked_tests_are_not_observed(live_test_tracing):
    assert live_test_tracing is None
    assert observability.current_observation() is None


def test_live_fixture_observes_marked_items(pytester_free_live_item):
    observation, nodeid = pytester_free_live_item
    assert observation.entry == "live-test"
    assert observation.metadata == {"test_id": nodeid}


@pytest.fixture
def pytester_free_live_item(request):
    """Drive the autouse fixture for a fake ``live``-marked item, offline.

    The real live tests are deselected by default, so this applies the
    fixture's generator to a stand-in request whose node carries the mark.
    """
    from tests.conftest import live_test_tracing

    class Node:
        nodeid = "tests/test_policy.py::test_live_example"

        def get_closest_marker(self, name):
            return pytest.mark.live.mark if name == "live" else None

    class Request:
        node = Node()

    generator = live_test_tracing.__wrapped__(Request())
    observation = next(generator)
    assert observability.current_observation() is observation
    yield observation, Node.nodeid
    with pytest.raises(StopIteration):
        next(generator)
    assert observability.current_observation() is None


def test_live_root_carries_entry_and_test_id(traced):
    with observe("live-test", metadata={"test_id": "tests/x.py::test_y"}):
        with root("policy_query"):
            pass
    run = traced.one("policy_query")
    assert "entry:live-test" in run["tags"]
    assert run["metadata"]["test_id"] == "tests/x.py::test_y"


# =============================================================================
# Hardening 4, task 4.3: calls carry their model, provider, and role
# =============================================================================


class NamedChat(SequenceChat):
    """A SequenceChat that reports a model name and provider, as real adapters do."""

    def _get_ls_params(self, stop=None, **kwargs):
        params = super()._get_ls_params(stop=stop, **kwargs)
        params["ls_provider"] = "openai"
        params["ls_model_name"] = "gpt-4o-mini"
        return params


@pytest.fixture
def named_chat(monkeypatch) -> NamedChat:
    from finos import llm

    model = NamedChat(calls=[], replies=[], usage=[])
    monkeypatch.setattr(llm, "get_llm", lambda *a, **k: model)
    return model


def test_calls_carry_model_provider_and_role(policy_env, named_chat):
    named_chat.replies = ["policy", "The fee is $35."]
    named_chat.usage = [{"input": 98, "output": 3}, {"input": 1240, "output": 85}]
    with observe("supervisor-ask") as observation:
        ask(build_support_agent(), "What is the overdraft fee?")
    chat = [c for c in observation.calls if c.chat]
    assert [(c.role, c.provider, c.model) for c in chat] == [
        ("classify_intent", "openai", "gpt-4o-mini"),
        ("policy_agent", "openai", "gpt-4o-mini"),
    ]
    assert [(c.input_tokens, c.output_tokens) for c in chat] == [(98, 3), (1240, 85)]


def test_cached_input_tokens_are_read(policy_env, monkeypatch):
    from finos import llm

    class CachedChat(RecordingChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
            message = AIMessage(
                "policy",
                usage_metadata={
                    "input_tokens": 2000,
                    "output_tokens": 1,
                    "total_tokens": 2001,
                    "input_token_details": {"cache_read": 1024},
                },
            )
            return ChatResult(generations=[ChatGeneration(message=message)])

    monkeypatch.setattr(llm, "get_llm", lambda *a, **k: CachedChat(calls=[]))
    with observe("test") as observation:
        supervisor.classify_query("What is the overdraft fee?")
    assert observation.calls[0].cached_input_tokens == 1024


def test_policy_query_records_the_embedding_and_moderation(policy_env, recording_chat, monkeypatch):
    from finos.guardrails import input as guard_in

    policy_env.set_config("moderation = false", "moderation = true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setattr(guard_in, "moderate", lambda query: set())
    query = "What is the overdraft fee?"
    with observe("policy-ask") as observation:
        ask_policy(query)
    other = [c for c in observation.calls if not c.chat]
    assert [(c.role, c.provider, c.model) for c in other] == [
        ("moderation", "openai", "omni-moderation-latest"),
        ("embedding", "fake", "deterministic-64"),
    ]
    embedding = other[1]
    assert embedding.estimated and embedding.input_tokens == -(-len(query) // 4)
    # The non-chat calls leave the --verbose token counts as they were: a
    # unit holding only them shows no tokens.
    only_other = observability.Unit("x", 1.0, None, other)
    assert only_other.tokens is None


def test_index_build_records_no_embedding_call(policy_env):
    from finos import vectorstore

    with observe("test") as observation:
        vectorstore.ensure_index(rebuild=True)
    assert observation.calls == []


# =============================================================================
# Hardening 4, task 5.1: every root is a cost scope
# =============================================================================


def test_sequential_roots_get_disjoint_calls(policy_env, sequence_chat):
    sequence_chat.replies = ["policy", "account_status"]
    sequence_chat.usage = [{"input": 10, "output": 1}, {"input": 20, "output": 2}]
    with observe("test") as observation:
        with root("supervisor_classify", inputs={"query": "a"}):
            supervisor.classify_query("a")
        with root("supervisor_classify", inputs={"query": "b"}):
            supervisor.classify_query("b")
    first, second = observation.requests
    assert [(c.input_tokens, c.output_tokens) for c in first.cost.calls] == [(10, 1)]
    assert [(c.input_tokens, c.output_tokens) for c in second.cost.calls] == [(20, 2)]


def test_root_outside_observe_still_collects(policy_env, sequence_chat):
    from finos import cost

    sequence_chat.replies = ["The fee is $35."]
    sequence_chat.usage = [{"input": 1240, "output": 85}]
    assert observability.current_observation() is None
    with cost.capture() as finished:
        ask_policy("What is the overdraft fee?")
    (query,) = finished
    assert query.root == "policy_query" and query.record["entry"] == "api"
    chat = [c for c in query.cost.calls if c.role == "policy_agent"]
    assert [(c.input_tokens, c.output_tokens) for c in chat] == [(1240, 85)]


def test_a_failing_cost_finish_changes_nothing(policy_env, recording_chat, monkeypatch):
    from finos import cost

    app = build_support_agent()
    expected = ask(app, "What is the overdraft fee?")

    def broken(*args, **kwargs):
        raise RuntimeError("cost is broken")

    monkeypatch.setattr(cost, "finish", broken)
    assert ask(app, "What is the overdraft fee?") == expected


def test_guards_unit_holds_the_classifier_call(policy_env, sequence_chat, monkeypatch):
    from finos import llm
    from tests.test_guardrails import _UsageClassifier

    policy_env.set_config("injection_classifier = false", "injection_classifier = true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setattr(llm, "get_classifier_llm", _UsageClassifier.make)
    sequence_chat.replies = ["policy", "The fee is $35."]
    sequence_chat.usage = [{"input": 98, "output": 3}, {"input": 1240, "output": 85}]
    with observe("supervisor-ask") as observation:
        ask(build_support_agent(), "What is the overdraft fee?")
    units = observation.units()
    assert [u.name for u in units] == ["guards", "classify_intent", "policy_agent"]
    assert units[0].tokens == "150+1 tokens"
    assert units[1].tokens == "98+3 tokens"
    lines = observation.timing_lines()
    assert lines[0].startswith("guards: ") and lines[0].endswith(", 150+1 tokens")
    # The request holds every call, the classifier's included.
    (query,) = observation.requests
    assert [c.role for c in query.cost.calls if c.role != "embedding"] == [
        "injection_classifier",
        "classify_intent",
        "policy_agent",
    ]
