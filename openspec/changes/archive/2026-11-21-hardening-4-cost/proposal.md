# Proposal

## Why

The system counts tokens for each model call (Hardening 1) but never turns them into money. Nothing adds up cost across queries or alerts on a spike, and no audit record of any query exists. Hardening 3 added a paid `gpt-4o-mini` classifier call to every query, even under the local provider, and nobody has measured what that costs. The explore also found that the classifier call is lost: it runs in a plain thread pool, so its tokens never reach the collector, and with tracing on it uploads as a separate, unmasked trace. Cost comes last because every saving trades against quality, and quality is now measurable (Hardening 2) and guarded (Hardening 3). The decisions are recorded in the Hardening 4 explore notes ("Locked decisions", C1–C13).

## What Changes

- **Classifier fix** (first, because cost attribution depends on it): the injection classifier runs its model under a context-preserving executor. Its call reaches the timing collector, nests under the request's root run, and uploads through the masking client.
- **Cost per call and per query**, from the `usage_metadata` each chat call already reports, priced from a `[cost.prices."<model>"]` table in `config.toml` with a required `prices_as_of` date.
  - The query's cost covers every call made to answer it: classifier, moderation ($0, listed), supervisor, query embedding, and agent. The guard calls form a separate `guard` subtotal. The judge and the index build are not query cost.
  - An OpenAI model with no price is unpriced: its cost is `null`, never 0, with one stderr line per process. A chat call with no usage also makes the query's cost `null`.
  - Ollama calls cost $0 by rule. Embedding tokens are estimated as characters ÷ 4 and marked as estimated.
  - No `tiktoken`, no `get_openai_callback`, no new dependency.
- **Audit log**: one JSON line per root run, appended to `logs/audit_log.jsonl` (git-ignored), on by default with a switch.
  - It records the trace ID, entry, provider, models, intent, guard outcome, crisis flag, each call's tokens and cost, totals, latency, configuration, and the query and reply lengths. It holds **no query text in any form**.
  - Writes are thread-safe. A write failure leaves the answer and exit code unchanged and prints one stderr line (fail-open).
  - This closes Hardening 3's deferred guard event log.
- **Alerts and budgets**: a query above `per_query_alert_usd` prints a stderr line, is recorded at level `WARNING`, and its root is tagged `cost:alert`. The daily budget is checked from the audit log by the report and at the end of an evaluation run: a warning at 80%, an alert past 100%. A query is never refused for budget.
- **`finos cost report`**: per intent and per provider, from the audit log, for a date range and an entry filter. It shows count, total and mean cost, the guard share, tokens, p50/p95 latency, unpriced count, the price date, and the budget status. It closes the to-do "Record per-provider latency (p50, p95)".
- **`--verbose`**: a `guards:` timing line for the input guards, and a cost line after the timing lines. The root run's metadata gains its cost and token totals.
- **Evaluation**:
  - each experiment reports per-output tokens and cost (mean, p50, p95, total), the guard share, and unpriced outputs, with the judge's cost on its own line;
  - judge usage with a missing count becomes unknown;
  - a new `finos eval compare A.json B.json` prints each metric, the gates, cost, and latency before and after.

  Cost is report-only: no cost gate.
- **Optimizations, measured with the before/after method**: thinking mode off (new optional `[ollama] reasoning`), `top_k` 2, `chunk_size` 500, and `num_ctx` 8192 (new optional `[ollama] num_ctx`; latency only). Each is adopted only above the quality floor (C13): every Hardening 2 and 3 gate passes, correctness and empathy stay within 0.05 of the baseline, and cost or p95 latency improves. The shipped defaults change only for adopted variants.
- **Docs**: a new `docs/how-to-guide/cost.md` (prices, the audit log and its retention, alerts, the report, the before/after method), updates to the setup, evaluation, and testing guides, `docs/systems-design-and-architecture.md` §9.4, and the project to-do list.

**Out of scope**:
- A semantic cache (C11): its constraints and the P4 probe go to the to-do.
- Per-node models, shorter prompts, and the Batch API (to-do). Output caps and a rule-based pre-route are rejected (explore §7).
- `finos cost estimate`, billing reconciliation, multi-tenant attribution, a notional local hosting price, retention enforcement and log shipping, and CI for the gates.

## Capabilities

### New Capabilities

- `cost-tracking`:
  - the price table and its date;
  - per-call and per-query cost, the guard subtotal, unpriced and local calls;
  - the audit record, its fields, the no-query-text rule, the thread-safe append, and fail-open writes;
  - the per-query alert and the daily budget;
  - cost never changing an answer or exit code.
- `cost-cli`: the `finos cost` command group (`report`).

### Modified Capabilities

- `observability`:
  - `--verbose` gains the `guards:` timing line and the cost line;
  - the root run's metadata gains cost and token totals;
  - the tag vocabulary gains `cost:alert`.
- `guardrails`: the classifier's model call belongs to the request's trace, is masked, and its usage is collected.
- `evaluation`: results report tokens and cost per output beside latency, and the judge's cost separately.
- `eval-cli`:
  - `run` prints cost;
  - a new `compare` command;
  - the group lists `compare`.
- `llm-access`:
  - a required, validated `[cost]` section with shipped prices;
  - the optional `[ollama] reasoning` and `num_ctx` passed to the local chat model.

## Impact

- **Code**:
  - New:
    - `src/finos/cost.py`: prices, cost arithmetic, the audit record and writer, and the alert;
    - `src/finos/cli/cost.py`.
  - Changed:
    - `src/finos/guardrails/input.py` (the executor);
    - `src/finos/observability.py` (`ModelCall` gains model, provider, and role; the `guards` unit; a per-root audit hook; cost metadata and tag);
    - `src/finos/cli/shared.py` (the cost line);
    - `src/finos/evaluation/runner.py` and `judge.py` (per-output cost, the judge's cost);
    - `src/finos/cli/eval.py` (cost output, `compare`);
    - `src/finos/config.py` (`[cost]`, the optional Ollama keys);
    - `src/finos/llm.py` (`reasoning`, `num_ctx`);
    - `src/finos/cli/main.py` (one registration line).
- **Configuration**: `config.toml` gains `[cost]` and `[cost.prices."gpt-4o-mini"]` and `[cost.prices."text-embedding-3-small"]`. `.gitignore` gains `logs/`.
- **Dependencies**: none new.
- **Runtime**:
  - Every root run appends one line to the audit log, a small local write.
  - The classifier's traces move under the request's root, so LangSmith shows one trace per query instead of two.
  - No added model calls.
- **Tests**:
  - New: `tests/test_cost.py` and `tests/test_cli_cost.py`, offline, with fake usage.
  - Updated: the observability, guardrails, evaluation, eval CLI, and `tests/test_llm.py` tests.
- **Secrets**: none new.
