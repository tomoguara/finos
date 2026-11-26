"""Tests for query cost and the audit log (Hardening 4, cost-tracking spec).

Offline: calls are built by hand or reported by fake chat models with fixed
``usage_metadata``; ``policy_env`` points the audit log into ``tmp_path``.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

import pytest

from finos import config, cost

PRICES = {
    "gpt-4o-mini": {"input_per_1m": 0.15, "cached_input_per_1m": 0.075, "output_per_1m": 0.60},
    "text-embedding-3-small": {"input_per_1m": 0.02},
}


@dataclass
class Call:
    role: str = "policy_agent"
    provider: str | None = "openai"
    model: str | None = "gpt-4o-mini"
    input_tokens: int | None = 1000
    output_tokens: int | None = 100
    cached_input_tokens: int | None = None
    estimated: bool = False


@pytest.fixture(autouse=True)
def fresh_warnings():
    cost._warned.clear()
    yield
    cost._warned.clear()


# =============================================================================
# 4.2 Pricing
# =============================================================================


def test_priced_openai_call():
    assert cost.price_call(Call(), PRICES) == pytest.approx(0.00021)


def test_cached_input_is_priced_at_the_cached_price():
    call = Call(input_tokens=2000, cached_input_tokens=1024, output_tokens=0)
    expected = (976 * 0.15 + 1024 * 0.075) / 1_000_000
    assert cost.price_call(call, PRICES) == pytest.approx(expected)


def test_cached_price_defaults_to_the_input_price():
    table = {"m": {"input_per_1m": 1.0}}
    call = Call(model="m", input_tokens=100, cached_input_tokens=50, output_tokens=0)
    assert cost.price_call(call, table) == pytest.approx(100 / 1_000_000)


def test_local_calls_cost_nothing_whatever_the_tag():
    call = Call(provider="ollama", model="qwen3.8:27b-q8_0", input_tokens=775, output_tokens=317)
    assert cost.price_call(call, PRICES) == 0.0
    assert cost.price_call(Call(provider="ollama", input_tokens=None, output_tokens=None), PRICES) == 0.0


def test_moderation_is_free():
    call = Call(role="moderation", model="omni-moderation-latest", input_tokens=None, output_tokens=None)
    assert cost.price_call(call, PRICES) == 0.0


def test_embedding_is_priced_on_input_only():
    call = Call(role="embedding", model="text-embedding-3-small", input_tokens=7, output_tokens=0, estimated=True)
    assert cost.price_call(call, PRICES) == pytest.approx(7 * 0.02 / 1_000_000)


def test_unknown_model_is_unpriced_and_named_once(capsys):
    calls = [Call(model="gpt-4.1-nano"), Call(model="gpt-4.1-nano"), Call()]
    query = cost.query_cost(calls, PRICES)
    assert [c.cost_usd for c in query.calls][:2] == [None, None]
    assert query.cost_usd is None
    assert query.unpriced == ["gpt-4.1-nano"]
    err = capsys.readouterr().err
    assert err.count("no price for gpt-4.1-nano") == 1


def test_call_without_usage_makes_the_query_unknown():
    query = cost.query_cost([Call(), Call(input_tokens=None, output_tokens=None)], PRICES)
    assert query.calls[1].cost_usd is None and query.cost_usd is None
    assert query.unpriced == ["gpt-4o-mini"]


def test_dated_snapshot_uses_its_base_model_price():
    assert cost.price_call(Call(model="gpt-4o-mini-2024-07-18"), PRICES) == pytest.approx(0.00021)
    # Nothing else is guessed: a longer model name is not its prefix's model.
    assert cost.price_for("gpt-4o-mini-search", PRICES) is None
    assert cost.price_for("gpt-4o", PRICES) is None


def test_guard_subtotal_and_totals():
    calls = [
        Call(role="moderation", model="omni-moderation-latest", input_tokens=None, output_tokens=None),
        Call(role="injection_classifier", input_tokens=170, output_tokens=1),
        Call(role="classify_intent", input_tokens=165, output_tokens=2),
        Call(role="embedding", model="text-embedding-3-small", input_tokens=7, output_tokens=0, estimated=True),
        Call(role="policy_agent", input_tokens=775, output_tokens=120),
    ]
    query = cost.query_cost(calls, PRICES)
    classifier = (170 * 0.15 + 1 * 0.60) / 1_000_000
    assert query.guard_cost_usd == pytest.approx(classifier)
    assert query.cost_usd == pytest.approx(sum(c.cost_usd for c in query.calls))
    assert query.input_tokens == 170 + 165 + 7 + 775
    assert query.output_tokens == 1 + 2 + 120
    assert query.unpriced == []


def test_rounding_rules():
    assert cost.price_call(Call(input_tokens=1, output_tokens=0), PRICES) == 1.5e-07
    assert cost.format_usd(0.000241) == "$0.000241"
    assert cost.format_usd(None) == "unpriced"


def test_cost_module_imports_nothing_heavy():
    code = (
        "import sys\n"
        "import finos.cost, finos.stats\n"
        "print([m for m in ('langchain_core', 'langsmith', 'openai', 'langgraph') if m in sys.modules])\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"


# =============================================================================
# 5.2 The audit record
# =============================================================================

import json
import threading
from pathlib import Path

from typer.testing import CliRunner

from finos.agents import ask_account, ask_escalation, ask_policy
from finos.cli.main import app as cli_app
from finos.graph import build_support_agent
from finos.main import ask

DATASETS = Path(__file__).resolve().parents[1] / "evals" / "datasets"


def records() -> list[dict]:
    found, skipped = cost.read_records()
    assert skipped == 0
    return found


def test_audit_log_is_in_the_tests_directory(policy_env, tmp_path):
    assert cost.audit_log_path() == tmp_path / "logs" / "audit_log.jsonl"


def test_one_record_per_root(policy_env, recording_chat):
    recording_chat.reply = "policy"
    ask(build_support_agent(), "What is the overdraft fee?")
    recording_chat.reply = "The fee is $35."
    ask_policy("What is the overdraft fee?")
    ask_account("What is the balance on ACC-12345?")
    ask_escalation("I want to speak to a person")
    roots = [r["root"] for r in records()]
    assert roots == ["support_query", "policy_query", "account_query", "escalation_query"]


def test_cli_search_and_classify_write_one_record_each(policy_env, recording_chat, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    runner = CliRunner()
    recording_chat.reply = "policy"
    result = runner.invoke(cli_app, ["policy", "search", "-q", "overdraft fee"], prog_name="finos")
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli_app, ["supervisor", "classify", "-q", "What is the overdraft fee?"], prog_name="finos")
    assert result.exit_code == 0, result.output
    found = records()
    assert [(r["root"], r["entry"]) for r in found] == [
        ("policy_search", "policy-search"),
        ("supervisor_classify", "supervisor-classify"),
    ]
    assert found[0]["calls"][0]["role"] == "embedding"
    assert found[1]["intent"] == "policy"


def test_policy_record_fields(policy_env, monkeypatch):
    from finos import llm
    from tests.test_observability import NamedChat

    model = NamedChat(calls=[], replies=["policy", "The overdraft fee is $35."], usage=[])
    model.usage = [{"input": 165, "output": 2}, {"input": 775, "output": 120}]
    monkeypatch.setattr(llm, "get_llm", lambda *a, **k: model)
    state = ask(build_support_agent(), "What is the overdraft fee?")
    (record,) = records()
    assert record["root"] == "support_query" and record["entry"] == "api"
    assert record["level"] == "INFO" and record["error"] is None
    assert record["intent"] == "policy" and record["crisis"] is False
    # The configured provider (the fake reports openai calls either way).
    assert record["provider"] == ("ollama" if config.get_settings()["llm"]["use_local_ollama_model"] else "openai")
    assert [c["role"] for c in record["calls"]] == ["classify_intent", "embedding", "policy_agent"]
    assert record["input_tokens"] == 165 + 775 + 7 and record["output_tokens"] == 122
    expected = (165 * 0.15 + 2 * 0.60 + 775 * 0.15 + 120 * 0.60) / 1_000_000
    # The fake embedding model is unpriced, so the query's total is unknown...
    assert record["cost_usd"] is None and record["unpriced"] == ["deterministic-64"]
    # ...while each chat call is priced.
    chat = [c["cost_usd"] for c in record["calls"] if c["role"] != "embedding"]
    assert sum(chat) == pytest.approx(expected)
    # Every guard that ran is listed (layers that are off don't run), the
    # output checks included.
    guard = record["guard"]
    assert guard["outcome"] == "passed"
    assert guard["layers"][0] == {"type": "regex", "decision": "passed", "reason": ""}
    assert {layer["decision"] for layer in guard["layers"]} == {"passed"}
    assert any(layer["type"].startswith("output_") for layer in guard["layers"])
    assert record["query_chars"] == len("What is the overdraft fee?")
    assert record["response_chars"] == len(state["response"])
    assert record["config"]["top_k"] == 3 and "prompt_versions" in record["config"]
    assert record["ts"].endswith("Z") and record["latency_ms"] > 0
    assert record["alerts"] == [] and record["trace_id"] is None


def test_audit_log_off_writes_nothing(policy_env, recording_chat):
    policy_env.set_config("audit_log = true", "audit_log = false")
    ask_policy("What is the overdraft fee?")
    assert not cost.audit_log_path().exists()


def _accounts() -> list[dict]:
    return json.loads((Path(__file__).resolve().parents[1] / "data" / "mock_accounts.json").read_text())


def _record_strings(account: dict) -> set[str]:
    """Every string value in a record, and every ``ssn_last4``: what must never be logged."""
    found: set[str] = set()

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and len(value) >= 4:
            found.add(value)

    walk(account)
    return found


GENERIC = {"active", "frozen", "closed", "true", "false"}


def test_records_hold_no_customer_content(policy_env, recording_chat):
    queries = []
    for path in sorted(DATASETS.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                question = json.loads(line).get("inputs", {}).get("question")
                if isinstance(question, str) and question.strip():
                    queries.append(question)
    assert len(queries) > 50
    app = build_support_agent()
    recording_chat.reply = "account_status"
    for query in queries:
        ask(app, query)
    lines = cost.audit_log_path().read_text().splitlines()
    assert len(lines) == len(queries)
    forbidden = set()
    for account in _accounts():
        forbidden |= {v for v in _record_strings(account) if v.lower() not in GENERIC}
        forbidden.add(str(account["account_id"]))
    for query, line in zip(queries, lines, strict=True):
        assert query not in line
        assert "ACC-" not in line
        leaked = [value for value in forbidden if value in line]
        assert not leaked, (query, leaked)


def test_blocked_record_holds_the_decision_not_the_text(policy_env, recording_chat):
    ask(build_support_agent(), "Should I invest my savings in crypto?")
    (record,) = records()
    assert record["guard"]["outcome"] == "blocked"
    assert record["guard"]["layers"][0] == {"type": "regex", "decision": "blocked", "reason": "investment_advice"}
    line = cost.audit_log_path().read_text()
    assert "crypto" not in line and "invest my" not in line
    assert record["calls"] == [] and record["cost_usd"] == 0.0


def test_concurrent_appends_keep_records_whole(tmp_path):
    path = tmp_path / "audit.jsonl"
    payload = {"pad": "x" * 2000}

    numbers = list(range(50))

    def write(worker: int) -> None:
        for number in numbers[worker::8]:
            cost.append_record({"n": number, **payload}, path)

    threads = [threading.Thread(target=write, args=(w,)) for w in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    lines = path.read_text().splitlines()
    assert len(lines) == 50
    parsed = [json.loads(line) for line in lines]
    assert all(r["pad"] == payload["pad"] for r in parsed)
    assert sorted(r["n"] for r in parsed) == numbers


def test_unwritable_path_fails_open_once(policy_env, recording_chat, monkeypatch, tmp_path, capsys):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    policy_env.set_config(
        f"audit_log_path = {json.dumps(str(tmp_path / 'logs' / 'audit_log.jsonl'))}",
        f"audit_log_path = {json.dumps(str(blocker / 'logs' / 'audit_log.jsonl'))}",
    )
    monkeypatch.setattr(cost, "_write_failed", False)
    expected = ask_policy("What is the overdraft fee?")
    again = ask_policy("What is the overdraft fee?")
    assert again == expected
    err = capsys.readouterr().err
    assert err.count("audit: not written (") == 1


def test_unwritable_path_leaves_the_exit_code(policy_env, recording_chat, monkeypatch, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    policy_env.set_config(
        f"audit_log_path = {json.dumps(str(tmp_path / 'logs' / 'audit_log.jsonl'))}",
        f"audit_log_path = {json.dumps(str(blocker / 'audit_log.jsonl'))}",
    )
    monkeypatch.setattr(cost, "_write_failed", False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    result = CliRunner().invoke(cli_app, ["policy", "ask", "-q", "What is the overdraft fee?"], prog_name="finos")
    assert result.exit_code == 0
    assert recording_chat.reply in result.stdout


@pytest.mark.parametrize("tracing", [False, True])
def test_same_states_with_the_audit_log_on_and_off(policy_env, recording_chat, monkeypatch, tracing):
    from langsmith import tracing_context

    from finos.observability import mask
    from tests.test_observability import FakeClient, _install

    if tracing:
        fake = FakeClient(hide_inputs=mask, hide_outputs=mask)
        _install(monkeypatch, fake)
    app = build_support_agent()
    queries = ["What is the overdraft fee?", "What is the balance on ACC-12345?", "I want a person"]

    def states():
        if tracing:
            with tracing_context(enabled=True, client=fake, project_name="finos"):
                return [ask(app, q) for q in queries]
        return [ask(app, q) for q in queries]

    with_log = states()
    policy_env.set_config("audit_log = true", "audit_log = false")
    assert states() == with_log


# =============================================================================
# 5.3 Alerts, the cost tag and metadata, and the daily budget
# =============================================================================

import datetime


@pytest.fixture
def priced_chat(monkeypatch):
    """A chat model reporting gpt-4o-mini usage, as ChatOpenAI does."""
    from finos import llm
    from tests.test_observability import NamedChat

    model = NamedChat(calls=[], replies=["I'm sorry to hear that."], usage=[])
    monkeypatch.setattr(llm, "get_llm", lambda *a, **k: model)
    return model


def test_costly_query_alerts_and_still_answers(policy_env, priced_chat, capsys):
    # 82,000 input tokens at $0.15/1M is $0.0123, above the $0.01 alert.
    priced_chat.usage = [{"input": 82000, "output": 0}]
    state = ask_escalation("I want to speak to a person")
    (record,) = records()
    assert record["cost_usd"] == pytest.approx(0.0123)
    assert record["level"] == "WARNING" and record["alerts"] == ["per_query"]
    assert "cost: query $0.012300 above the $0.010000 alert" in capsys.readouterr().err
    assert state["response"]


def test_unknown_cost_never_alerts(policy_env, recording_chat, capsys):
    ask_escalation("I want to speak to a person")
    (record,) = records()
    assert record["cost_usd"] is None and record["alerts"] == [] and record["level"] == "INFO"
    assert "above the" not in capsys.readouterr().err


def test_root_metadata_and_alert_tag(policy_env, priced_chat, monkeypatch):
    from langsmith import tracing_context

    from finos.observability import mask
    from tests.test_observability import FakeClient, _install

    fake = FakeClient(hide_inputs=mask, hide_outputs=mask)
    _install(monkeypatch, fake)
    priced_chat.usage = [{"input": 82000, "output": 10}]
    with tracing_context(enabled=True, client=fake, project_name="finos"):
        ask_escalation("I want to speak to a person")
    (record,) = records()
    run = fake.one("escalation_query")
    assert "cost:alert" in run["tags"]
    assert {key: run["metadata"][key] for key in ("cost_usd", "guard_cost_usd", "input_tokens", "output_tokens")} == {
        "cost_usd": record["cost_usd"],
        "guard_cost_usd": record["guard_cost_usd"],
        "input_tokens": record["input_tokens"],
        "output_tokens": record["output_tokens"],
    }
    assert record["trace_id"] == run["trace_id"]


def _write(path: Path, day: str, value):
    cost.append_record({"ts": f"{day}T12:00:00.000Z", "cost_usd": value}, path)


@pytest.mark.parametrize(
    "spent, status",
    [(0.5, "ok"), (0.85, "warning"), (1.10, "alert")],
)
def test_daily_status(policy_env, tmp_path, spent, status):
    path = tmp_path / "budget.jsonl"
    _write(path, "2026-11-20", spent - 0.05)
    _write(path, "2026-11-20", 0.05)
    _write(path, "2026-11-20", None)  # unknown cost: skipped
    _write(path, "2026-11-19", 50.0)  # another day: ignored
    result = cost.daily_status(today=datetime.date(2026, 11, 20), path=path)
    assert result.status == status
    assert result.total_usd == pytest.approx(spent)
    assert result.budget_usd == 1.0
    assert f"{result.share:.0%}" in result.line()


def test_daily_status_with_no_log(policy_env, tmp_path):
    result = cost.daily_status(path=tmp_path / "missing.jsonl")
    assert result.status == "ok" and result.total_usd == 0.0
