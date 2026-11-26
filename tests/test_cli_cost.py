"""Tests for ``finos cost report`` (Hardening 4, cost-cli spec).

Offline: the audit log is a fixture file in ``tmp_path`` (``policy_env``
points ``[cost] audit_log_path`` there); no model is called.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from finos import cost
from finos.cli.main import app


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    return CliRunner()


def run(runner, *args):
    return runner.invoke(app, list(args), prog_name="finos")


def record(day="2026-11-19", *, intent="policy", provider="openai", entry="supervisor-ask",
           cost_usd=0.00024, guard=0.000026, latency=1000.0, tokens=(1120, 125), outcome="passed"):
    return {
        "ts": f"{day}T10:00:00.000Z",
        "entry": entry,
        "intent": intent,
        "provider": provider,
        "cost_usd": cost_usd,
        "guard_cost_usd": guard,
        "latency_ms": latency,
        "input_tokens": tokens[0],
        "output_tokens": tokens[1],
        "guard": {"outcome": outcome, "layers": []},
    }


@pytest.fixture
def log(policy_env):
    def write(*records, raw_lines=()):
        path = cost.audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(r) for r in records] + list(raw_lines)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    return write


def test_group_help_lists_report(runner):
    result = run(runner, "cost", "--help")
    assert result.exit_code == 0 and "report" in result.stdout


def test_bare_group_prints_help_and_exits_2(runner):
    result = run(runner, "cost")
    assert result.exit_code == 2 and "report" in result.output


def test_import_stays_light():
    code = (
        "import sys\n"
        "import finos.cli.main\n"
        "print([m for m in ('langchain', 'langchain_core', 'langgraph', 'chromadb', 'langsmith', 'openai')"
        " if m in sys.modules])\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"


def test_report_rows_per_intent_and_provider(runner, log):
    log(
        record(latency=1000.0),
        record(latency=3000.0, cost_usd=0.00026, guard=0.000026),
        record(intent="account_status", provider="ollama", cost_usd=0.000026, guard=0.000026, tokens=(800, 60)),
        record(cost_usd=None, guard=None, latency=2000.0),
        record(intent="policy", outcome="blocked", cost_usd=0.0, guard=0.0, latency=1.0, tokens=(0, 0)),
    )
    result = run(runner, "cost", "report", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    rows = {(r["intent"], r["provider"]): r for r in data["rows"]}
    policy = rows[("policy", "openai")]
    assert policy["queries"] == 4 and policy["unpriced"] == 1 and policy["blocked"] == 1
    assert policy["total_cost_usd"] == pytest.approx(0.0005)
    assert policy["mean_cost_usd"] == pytest.approx(0.0005 / 3, abs=1e-8)
    assert policy["guard_share"] == pytest.approx(0.000052 / 0.0005)
    assert policy["latency_ms"] == {"p50": 1000.0, "p95": 3000.0}
    local = rows[("account_status", "ollama")]
    assert local["label"] == "local" and local["guard_share"] == pytest.approx(1.0)
    assert data["prices_as_of"] == "2026-11-20"
    assert data["budget"]["status"] in ("ok", "warning", "alert")


def test_report_text(runner, log):
    log(record(), record(intent="escalation"))
    result = run(runner, "cost", "report")
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].startswith("prices as of 2026-11-20; budget: ")
    assert lines[1] == "queries: 2 (all entries but eval, live-test)"
    assert lines[2].split()[:3] == ["intent", "provider", "queries"]
    assert lines[3].split()[:4] == ["escalation", "openai", "1", "$0.000240"]
    assert "11%" in lines[3]


def test_default_leaves_out_evaluation_traffic(runner, log):
    log(record(entry="supervisor-ask"), record(entry="eval"), record(entry="live-test"))
    data = json.loads(run(runner, "cost", "report", "--json").stdout)
    assert data["queries"] == 1
    data = json.loads(run(runner, "cost", "report", "--entry", "eval", "--json").stdout)
    assert data["queries"] == 1 and data["entries"] == ["eval"]
    data = json.loads(run(runner, "cost", "report", "--entry", "eval", "--entry", "live-test", "--json").stdout)
    assert data["queries"] == 2


def test_date_range_is_inclusive(runner, log):
    log(record("2026-11-17"), record("2026-11-18"), record("2026-11-19"), record("2026-11-20"))
    data = json.loads(
        run(runner, "cost", "report", "--since", "2026-11-18", "--until", "2026-11-19", "--json").stdout
    )
    assert data["queries"] == 2


def test_missing_log_is_an_empty_report(runner, policy_env):
    assert not cost.audit_log_path().exists()
    result = run(runner, "cost", "report")
    assert result.exit_code == 0
    assert result.stdout.splitlines()[1].startswith("queries: 0 ")


def test_unreadable_lines_are_skipped_and_counted(runner, log):
    log(record(), raw_lines=["{not json", "[1, 2]"])
    result = run(runner, "cost", "report", "--json")
    assert result.exit_code == 0
    assert json.loads(result.stdout)["queries"] == 1
    assert "skipped 2 unreadable line(s)" in result.stderr


def test_bad_date_exits_2(runner, policy_env):
    result = run(runner, "cost", "report", "--since", "yesterday")
    assert result.exit_code == 2
    assert "--since" in result.stderr


def test_report_after_real_queries(runner, policy_env, recording_chat):
    from finos.agents import ask_policy

    ask_policy("What is the overdraft fee?")
    data = json.loads(run(runner, "cost", "report", "--entry", "api", "--json").stdout)
    assert data["queries"] == 1 and data["rows"][0]["intent"] == "policy"
