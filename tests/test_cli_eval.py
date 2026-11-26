"""Tests for ``finos eval`` (Hardening 2, eval-cli).

All offline: the private config and index from ``policy_env``, the recording
chat model, a fake judge, temporary datasets, and (for LangSmith paths) the
fake experiment client from ``tests/test_evaluation.py``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from finos.cli.main import app
from finos.evaluation import gates, runner
from tests.test_evaluation import (
    _routing_rows,
    dataset_dir,
    eval_env,
    fake_judge,
    langsmith_env,
    passing_results,
    priced_escalation,
    variants_dir,
    write_dataset,
)


def run(*args: str):
    return CliRunner().invoke(app, list(args), prog_name="finos")


# --- The eval module attaches as a command group ----------------------------------


def test_group_help_lists_the_commands():
    result = run("eval", "--help")
    assert result.exit_code == 0
    for command in ("push", "run", "gate", "compare"):
        assert command in result.stdout


def test_bare_group_shows_help_and_runs_nothing(monkeypatch):
    monkeypatch.setattr(runner, "run_experiment", lambda *a, **k: pytest.fail("ran an experiment"))
    result = run("eval")
    assert result.exit_code == 2
    assert "push" in result.output


def test_importing_the_cli_stays_light_with_eval_registered():
    code = (
        "import sys, finos.cli.main, finos.cli.eval\n"
        "heavy = sorted({m.split('.')[0] for m in sys.modules}"
        " & {'langchain', 'langgraph', 'chromadb', 'langchain_core', 'langsmith'})\n"
        "print(','.join(heavy))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == ""


# --- Run ------------------------------------------------------------------------------


def test_local_run_lists_metrics_counts_and_latency(eval_env, dataset_dir):
    write_dataset(dataset_dir, "routing", _routing_rows(3, known=1))
    result = run("eval", "run", "--dataset", "routing", "--local", "--repetitions", "2")
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "(local)" in out and "8 outputs" in out
    assert "routing_accuracy  0.750  (in scope 1.000, all rows 0.750)" in out
    assert "errors: 0" in out
    assert "latency: p50 " in out and "p95 " in out
    assert "url:" not in out


def test_run_json_is_one_object(eval_env, dataset_dir):
    write_dataset(dataset_dir, "routing", _routing_rows(2))
    result = run("eval", "run", "-d", "routing", "--local", "-r", "1", "--json")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["metrics"]["routing_accuracy"]["mean"] == 1.0
    assert data["local"] is True and data["outputs"] == 2


def test_run_exits_0_whatever_the_scores(eval_env, dataset_dir, recording_chat):
    recording_chat.reply = "escalation"  # every row misrouted
    write_dataset(dataset_dir, "routing", _routing_rows(2))
    result = run("eval", "run", "-d", "routing", "--local", "-r", "1")
    assert result.exit_code == 0
    assert "routing_accuracy  0.000" in result.stdout


def test_run_with_an_override(eval_env, dataset_dir):
    write_dataset(dataset_dir, "routing", _routing_rows(1))
    result = run("eval", "run", "-d", "routing", "--local", "-r", "1", "--set", "policy.top_k=1", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["variant"] == "policy.top_k=1" and data["overrides"] == ["policy.top_k=1"]


@pytest.mark.parametrize(
    "args, message",
    [
        (["--dataset", "nope"], "--dataset must be one of: routing"),
        (["--dataset", "policy", "--set", "chunk_size=100"], "section.key=value"),
        (["--dataset", "policy", "--repetitions", "0"], "--repetitions must be at least 1"),
    ],
)
def test_unusable_input_exits_2_before_any_model_call(args, message, monkeypatch):
    from finos import llm

    monkeypatch.setattr(llm, "get_llm", lambda *a, **k: pytest.fail("model requested"))
    result = run("eval", "run", *args)
    assert result.exit_code == 2
    assert message in result.stderr


def test_unknown_setting_exits_2(eval_env, dataset_dir):
    write_dataset(dataset_dir, "routing", _routing_rows(1))
    result = run("eval", "run", "-d", "routing", "--local", "--set", "policy.chunk_sise=1")
    assert result.exit_code == 2
    assert "unknown setting [policy] chunk_sise" in result.stderr


def test_missing_dataset_file_exits_1_with_one_line(eval_env, dataset_dir):
    result = run("eval", "run", "-d", "routing", "--local", "--json")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1 and "routing.jsonl" in result.stderr


def test_calibration_run(policy_env, fake_judge):
    from finos.evaluation import datasets

    labels = [e.outputs["score"] for e in datasets.load("judge_calibration").examples]
    fake_judge.replies = [json.dumps({"score": s, "reason": "ok"}) for s in labels]
    result = run("eval", "run", "-d", "judge_calibration")
    assert result.exit_code == 0, result.output
    assert "calibration: passed" in result.stdout
    assert "cal-hallucinated (faithfulness): label 0.00, judge 0.000" in result.stdout


# --- Push ------------------------------------------------------------------------------


def test_push_without_a_key_exits_1_with_one_line(eval_env, dataset_dir):
    write_dataset(dataset_dir, "routing", _routing_rows(1))
    result = run("eval", "push", "--dataset", "routing")
    assert result.exit_code == 1
    lines = result.stderr.splitlines()
    assert len(lines) == 1 and "LangSmith key is required" in lines[0]


def test_push_reports_name_count_and_version(langsmith_env, dataset_dir):
    from finos.evaluation import datasets

    write_dataset(dataset_dir, "routing", _routing_rows(2))
    first = run("eval", "push", "--dataset", "routing")
    again = run("eval", "push", "--dataset", "routing")
    version = datasets.version("routing")
    assert first.exit_code == again.exit_code == 0
    assert first.stdout.strip() == f"routing: 2 examples, version {version}, uploaded"
    assert again.stdout.strip() == f"routing: 2 examples, version {version}, up to date"


def test_run_refuses_a_stale_langsmith_dataset(langsmith_env, dataset_dir):
    write_dataset(dataset_dir, "routing", _routing_rows(2))
    run("eval", "push", "--dataset", "routing")
    write_dataset(dataset_dir, "routing", _routing_rows(3))
    result = run("eval", "run", "--dataset", "routing")
    assert result.exit_code == 1
    assert "finos eval push" in result.stderr and len(result.stderr.splitlines()) == 1


def test_run_in_langsmith_prints_the_url_when_given(langsmith_env, dataset_dir, monkeypatch):
    write_dataset(dataset_dir, "routing", _routing_rows(1))
    run("eval", "push", "--dataset", "routing")
    result = run("eval", "run", "--dataset", "routing", "-r", "1")
    assert result.exit_code == 0, result.output
    assert "(LangSmith)" in result.stdout


def test_unreachable_langsmith_exits_1_with_one_line(langsmith_env, dataset_dir, monkeypatch):
    from tests.test_evaluation import ExperimentClient

    def down(self, **kwargs):
        raise ConnectionError("langsmith down")

    write_dataset(dataset_dir, "routing", _routing_rows(1))
    monkeypatch.setattr(ExperimentClient, "has_dataset", down)
    result = run("eval", "run", "--dataset", "routing", "--json")
    assert result.exit_code == 1
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 1 and "LangSmith could not be reached" in lines[0]


# --- Gate ------------------------------------------------------------------------------


def _fake_gate(results):
    def fake(repetitions=None, local=None, datasets=None, progress=None):
        if progress:
            progress("gate: 1/1 routing (2 runs)")
        from tests.test_evaluation import THRESHOLDS

        return gates.evaluate_gate(results, THRESHOLDS, "openai")

    return fake


def test_gate_passes_with_exit_0(eval_env, monkeypatch):
    monkeypatch.setattr(gates, "gate", _fake_gate(passing_results()))
    result = run("eval", "gate", "--local")
    assert result.exit_code == 0, result.output
    assert re.search(r"^routing_accuracy +1\.000  >= 0\.95  pass$", result.stdout, re.M)
    assert re.search(r"^guardrail_false_positive  1\.000  >= 1\.0  pass$", result.stdout, re.M)
    assert re.search(r"^correctness +0\.500  \(report only\)$", result.stdout, re.M)
    assert result.stdout.rstrip().endswith("gate: passed (openai)")


def test_gate_fails_with_exit_1_naming_the_examples(eval_env, monkeypatch):
    from tests.test_evaluation import fake_result

    results = passing_results()
    results["routing"] = fake_result(
        "routing", [(f"r{i}", "routing_accuracy", 1.0 if i < 9 else 0.0, True) for i in range(10)]
    )
    monkeypatch.setattr(gates, "gate", _fake_gate(results))
    result = run("eval", "gate", "--local")
    assert result.exit_code == 1
    assert re.search(r"^routing_accuracy +0\.900  >= 0\.95  FAIL$", result.stdout, re.M)
    assert "  - routing/r9: 0.000 comment r9" in result.stdout
    assert "gate: FAILED" in result.stdout


def test_gate_json(eval_env, monkeypatch):
    monkeypatch.setattr(gates, "gate", _fake_gate(passing_results()))
    result = run("eval", "gate", "--local", "--json")
    assert result.exit_code == 0
    assert json.loads(result.stdout)["passed"] is True  # stdout is only the JSON


def test_gate_progress_goes_to_stderr(eval_env, monkeypatch):
    monkeypatch.setattr(gates, "gate", _fake_gate(passing_results()))
    result = run("eval", "gate", "--local")
    assert "gate: 1/1 routing (2 runs)" in result.stderr
    assert "gate: 1/1 routing" not in result.stdout


# --- Hardening 4: cost in `run`, and `compare` (eval-cli delta) ----------------------


def test_run_shows_cost_per_output_and_price_date(eval_env, dataset_dir):
    write_dataset(dataset_dir, "routing", _routing_rows(3))
    result = run("eval", "run", "--dataset", "routing", "--local", "-r", "1")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    latency = next(i for i, line in enumerate(lines) if line.startswith("latency: "))
    assert re.fullmatch(
        r"cost: mean (\$\d+\.\d{6}|unknown), p50 .*, p95 .*, total .* per output "
        r"\(guards .*; \d+ unknown; prices as of 2026-11-20\)",
        lines[latency + 1],
    ), lines[latency + 1]


def test_run_judge_line(priced_escalation, fake_judge):
    result = run("eval", "run", "--dataset", "escalation", "--local", "-r", "1")
    assert result.exit_code == 0, result.output
    line = next(line for line in result.stdout.splitlines() if re.match(r"judge: \d+ calls", line))
    assert re.fullmatch(r"judge: \d+ calls, \d+\+\d+ tokens, \$\d+\.\d{6}", line)


def test_run_json_has_the_cost_block(priced_escalation):
    result = run("eval", "run", "--dataset", "escalation", "--local", "-r", "1", "--json")
    data = json.loads(result.stdout)
    assert data["cost"]["usd"]["total"] > 0 and data["cost"]["prices_as_of"] == "2026-11-20"
    assert "cost_usd" in data["judge"]


def _saved(tmp_path, name, **changes):
    base = {
        "experiment": f"eval-policy-openai-{name}",
        "dataset": "policy",
        "dataset_version": "abc123",
        "variant": name,
        "metrics": {
            "faithfulness": {"mean": 0.9, "in_scope_mean": 0.9, "minimum": 0.5, "scored": 10, "errors": 0},
            "correctness": {"mean": 0.8, "in_scope_mean": 0.8, "minimum": 0.5, "scored": 10, "errors": 0},
            "no_ssn": {"mean": 1.0, "in_scope_mean": 1.0, "minimum": 1.0, "scored": 10, "errors": 0},
        },
        "errors": [],
        "latency_ms": {"p50": 2000.0, "p95": 4000.0},
        "cost": {"usd": {"mean": 0.0002, "p50": 0.0002, "p95": 0.0003, "total": 0.002}},
    }
    for key, value in changes.items():
        base[key] = value
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


def test_compare_prints_before_and_after(policy_env, tmp_path):
    before = _saved(tmp_path, "baseline")
    after = _saved(
        tmp_path,
        "policy.top_k=2",
        metrics={
            "faithfulness": {"mean": 0.6, "minimum": 0.2},
            "correctness": {"mean": 0.75},
            "no_ssn": {"mean": 1.0, "minimum": 1.0},
        },
        latency_ms={"p50": 1500.0, "p95": 3000.0},
        cost={"usd": {"mean": 0.00015, "p50": 0.00015, "p95": 0.0002, "total": 0.0015}},
    )
    result = run("eval", "compare", str(before), str(after))
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "before: baseline  after: policy.top_k=2" in out
    assert re.search(r"faithfulness\s+0\.900\s+0\.600\s+-0\.300", out)
    assert "gate faithfulness >= 0.7: pass -> FAIL" in out
    assert "gate no_ssn >= 1.0: pass -> pass" in out
    assert "cost per output (mean): $0.000200 -> $0.000150 (-25%)" in out
    assert "latency p50: 2000 ms -> 1500 ms (-25%)" in out


def test_compare_json(policy_env, tmp_path):
    before = _saved(tmp_path, "baseline")
    after = _saved(tmp_path, "variant")
    data = json.loads(run("eval", "compare", str(before), str(after), "--json").stdout)
    assert data["dataset"] == "policy"
    assert {g["name"] for g in data["gates"]} == {"faithfulness", "no_ssn"}
    assert data["cost_usd_per_output"]["mean"]["change"] == 0.0
    assert data["latency_ms"]["p95"] == {"before": 4000.0, "after": 4000.0, "change": 0.0}


def test_compare_different_datasets_exits_2(policy_env, tmp_path):
    before = _saved(tmp_path, "baseline")
    after = _saved(tmp_path, "other", dataset="account")
    result = run("eval", "compare", str(before), str(after))
    assert result.exit_code == 2
    assert "policy" in result.stderr and "account" in result.stderr
    after = _saved(tmp_path, "newer", dataset_version="def456")
    result = run("eval", "compare", str(before), str(after))
    assert result.exit_code == 2 and "abc123" in result.stderr and "def456" in result.stderr


def test_compare_unreadable_file_exits_2(policy_env, tmp_path):
    before = _saved(tmp_path, "baseline")
    missing = tmp_path / "missing.json"
    result = run("eval", "compare", str(before), str(missing))
    assert result.exit_code == 2 and str(missing) in result.stderr
    junk = tmp_path / "junk.json"
    junk.write_text('{"hello": 1}')
    result = run("eval", "compare", str(junk), str(before))
    assert result.exit_code == 2 and str(junk) in result.stderr


def test_compare_calls_no_model_and_imports_no_langchain(tmp_path):
    before = _saved(tmp_path, "baseline")
    code = (
        "import sys\n"
        "from typer.testing import CliRunner\n"
        "from finos.cli.main import app\n"
        f"r = CliRunner().invoke(app, ['eval', 'compare', {str(before)!r}, {str(before)!r}])\n"
        "assert r.exit_code == 0, r.output\n"
        "print([m for m in ('langchain_core', 'langsmith', 'openai', 'langgraph') if m in sys.modules])\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip().splitlines()[-1] == "[]"
