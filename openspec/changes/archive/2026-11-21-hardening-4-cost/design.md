# Design

## Context

See `proposal.md` for motivation and `specs/` for required behavior. The decisions come from the Hardening 4 explore notes ("Locked decisions" C1–C13). This design records how they are built.

**Current state** (`main` at `934f351`, plus the explore-doc commit):
- `observability.Observation` collects `ModelCall(end, input_tokens, output_tokens)` through a LangChain configure hook. The hook adds the timing handler only while the `_handler` context variable is set, which is only inside `observe()`.
- `Observation.units()` assigns calls to node spans, or else to root spans. The input guards run inside the root but before any node, so a guard call falls outside every node span and is dropped from the `-v` lines.
- `guardrails.input.classify()` runs `model.invoke` in a plain `ThreadPoolExecutor` to enforce a timeout. A plain executor copies no context variables, so the explore probe showed that the call is not collected, has no parent run, and is uploaded by LangSmith's default client without `mask()`.
- Moderation is a direct `openai` client call, and the query embedding is a Chroma call through LangChain `Embeddings`. Neither fires a chat callback or reports usage.
- `evaluation.judge.Usage` counts judge calls and tokens, treating a missing count as 0. The runner wraps a whole experiment in one `observe("eval")`, and LangSmith's `evaluate` runs targets in threads.
- `percentile()` lives in `evaluation/runner.py`, which the light `cost` CLI must not import.
- `config.PROJECT_ROOT` anchors every data path.

**Probe results the design relies on** (from the explore):
1. Both chat adapters report `usage_metadata`, and embeddings never do. Ollama's output count includes thinking tokens.
2. `ls_provider` and `ls_model_name` reach `on_chat_model_start`'s `metadata` for both adapters.
3. `tiktoken` cannot fetch its encoding offline, so it is not used.
4. `RunTree.add_metadata` exists, so a root's metadata can be completed just before it ends.

## Goals / Non-Goals

**Goals:**
- One collector, the Hardening 1 one, is the source of every call's usage. No second callback.
- Every root run is its own cost scope, whether or not the caller entered `observe()`. That gives per-query audit records and per-output evaluation cost from the same mechanism.
- Cost code imports no LangChain, `langsmith`, or `openai`, so `finos cost report` stays light.
- Nothing about cost can change a reply or an exit code (cost-tracking spec).

**Non-Goals:**
- Pre-call estimates, a semantic cache, per-node models (proposal, out of scope).
- Cross-process locking of the audit log beyond append-mode single writes (D6).
- Changing any shipped default before its variant passes the quality floor (D10).

## Decisions

### D1. The classifier runs under a context-preserving executor

`classify()` keeps its thread and timeout, but submits through LangChain's `ContextThreadPoolExecutor` (in `langchain_core`, already imported in that function's path), which runs the task in a copy of the caller's context. The worker then has the timing handler, the LangSmith parent run, and the masking client's tracing context.

- **Alternative**: drop the thread and use the model's own request timeout. Rejected because the timeout would then depend on each adapter's settings (`ChatOllama` has no single total timeout), and H3's fail-open on a slow classifier must hold.
- **Alternative**: `contextvars.copy_context().run` by hand. This is equivalent, but the LangChain helper is the documented pattern.
- Regression tests (guardrails spec): the classifier's usage is in `Observation.calls`; with a fake LangSmith client, its run's parent is the root, and its uploaded input passed through `mask()`.

### D2. `ModelCall` gains identity, and calls are recorded by role

```
ModelCall(end, input_tokens, output_tokens,
          model: str | None, provider: str | None, role: str,
          cached_input_tokens: int | None = None, estimated: bool = False)
```

- The handler stores `metadata["ls_model_name"]` and `["ls_provider"]` from `on_chat_model_start`, keyed by `run_id`, and pops them in `on_llm_end`. It reads `input_token_details.cache_read` when present.
- `role` is the enclosing node's name, or `injection_classifier` and `judge`. The run's name comes from `chain_config`, read from the `name` argument of `on_chat_model_start`; the handler maps `*_llm` run names to roles.
- Calls that fire no LangChain callback are recorded through one function, `observability.record_call(role, provider, model, input_tokens, output_tokens, estimated)`:
  - **moderation**: in `moderation_check`, provider `openai`, model `omni-moderation-latest`, no tokens. It is priced $0 by rule (D4).
  - **embedding**: in `vectorstore.search`, with `embedding_identity()` and tokens of `ceil(len(query) / 4)`, `estimated=True`. The index build in `_open_or_build` is not recorded (cost-tracking spec).
- `Unit.line()` keeps its format; the new fields serve cost only.

### D3. Every root is a cost scope

`root()` opens a `Request` scope for its body: a small object with its own call list and guard decisions, set in a `_request` context variable. Where a scope applies:
- The timing handler and `record_call` append each call to the active observation, if any, **and** to the active request.
- `guardrails.decisions.record` appends decisions to both, the same way.
- If no observation is active (a library caller, entry `api`), `root()` still sets the timing handler for its body, so the request collects calls. Today such a caller collects nothing.
- Nested roots do not occur today; if one did, the inner scope would replace the outer for its duration, and each would write its own record.

When the body ends, `root()` calls `cost.finish(request, root_handle)`, inside a `try` that swallows everything. That one call:
1. prices the calls (D4) and builds the totals and guard subtotal;
2. checks the per-query alert (D7), adding the `cost:alert` tag through the handle;
3. adds `cost_usd`, `guard_cost_usd`, `input_tokens`, and `output_tokens` to the root run with `add_metadata` (observability spec);
4. builds and writes the audit record (D5, D6);
5. attaches the finished `QueryCost` to the active observation (`Observation.requests`), for the `-v` line, and to any active capture (D8).

The record needs the intent and the guard outcome. The intent comes from the `intent:*` tag the root already receives. The guard outcome comes from the request's decisions, through the existing `strongest()` helper.

The `guards` unit (observability spec) is the span from the first to the last guard decision of a request. `Observation.units()` emits it before the node units when it holds a call.

### D4. Pricing: `finos/cost.py`

Pure Python, importing only `finos.config`.

- `price_call(call, prices) -> float | None`:
  - provider `ollama` → `0.0`;
  - role `moderation` → `0.0`;
  - a model with no entry → `None`;
  - missing chat usage → `None`;
  - otherwise `(input − cached) × in + cached × cached_in (or in) + output × out`, per million.
- `QueryCost`: the calls with their costs, `cost_usd` (the sum, or `None` if any call is `None`), `guard_cost_usd` (the roles `moderation` and `injection_classifier`), the token totals, and `unpriced` (sorted model names).
- The stderr line for an unpriced model is printed once per model per process, through a module-level set.
- Stored values are rounded to 8 decimals; printed values to 6.

### D5. The audit record

One `dict`, serialized with `json.dumps(..., separators=(",", ":"), sort_keys=True)`:

```
ts, level, root, trace_id, entry, provider, chat_model, intent,
guard: {outcome, layers: [{type, decision, reason}]}, crisis,
calls: [{role, provider, model, input_tokens, output_tokens, cost_usd, estimated}],
input_tokens, output_tokens, cost_usd, guard_cost_usd, unpriced,
latency_ms, config (root_metadata()), query_chars, response_chars, alerts
```

- `query_chars` comes from the root's `inputs`, and `response_chars` from its outputs' `response` (`root()` already holds both). Neither text is written.
- `config` is exactly `root_metadata()`, which the observability spec already keeps free of customer data.
- Guard `reason` values are the category strings H3 already restricts to names.
- A test runs every dataset query through the record builder and asserts that no query text, account ID, holder name, or record value appears in the serialized line (cost-tracking spec).

### D6. Writing the log

`cost.append_record(record)`:
- resolves `[cost] audit_log_path` against `PROJECT_ROOT`;
- creates the parent directory;
- under a module `threading.Lock`, opens the file in `"a"` mode and makes one `write()` of the line plus `\n`.

Each record is well under the size the OS appends atomically on a local file, so separate processes (two terminals) do not interleave in practice. The how-to guide states this limit.

- On any `OSError` (or a serialization error), it prints `audit: not written (<ErrorType>)` once per process and returns (C6).
- `[cost] audit_log = false` skips the write. The cost line, metadata, and alert still run.
- `.gitignore` gains `logs/`.
- **Tests and the private config**: `policy_env` writes `audit_log_path` into its temporary directory, so the offline suite never touches `logs/`. A conftest guard fails any test that writes to the real path.

### D7. Alerts and the daily budget

- **Per query** (in `finish`): if `cost_usd` exceeds `per_query_alert_usd`, the record gets `level = "WARNING"` and `alerts = ["per_query"]`, the root gets `cost:alert`, and stderr gets `cost: query $X above the $Y alert`. Unknown cost never alerts.
- **Daily**: `cost.daily_status(today=None)` streams the log, sums today's (UTC) known costs, and returns `ok`, `warning` (≥ 80%), or `alert` (> 100%), with the total and share. It is called by `finos cost report` and at the end of `run_experiment`, which prints one line when the status is not `ok`. No query path calls it.

### D8. Evaluation cost

- `cost.capture()` is a context manager that collects the `QueryCost` of every root that finishes inside it.
- The runner wraps each target call in `capture()`, inside the timed wrapper, so it runs in the target's own thread under LangSmith's `evaluate` (which copies context into its workers) and in the local loop alike. The output's cost is the sum of its captured roots (one, `support_query` or an `*_query`, today).
- This replaces the "nested observation per target" idea from the explore. The root scope (D3) already isolates each call, and the experiment-wide `observe("eval")` stays as it is for the trace and the timings.
- `ExperimentResult` gains `costs: list[float | None]` and the token lists, with properties for mean, p50, p95, total, guard share, and unknown count. `as_dict()` gains a `cost` block (with `prices_as_of`), and the judge block gains `cost_usd`.
- The judge's calls run inside the experiment, but outside any target's root, so they never reach an output's cost. `judge.Usage` becomes `input_tokens: int | None`: once a call lacks usage, the total is `None`. The judge's cost is priced from its counts with the judge model's price.
- `percentile()` moves to `finos/stats.py`, imported by the runner and by `cost`, so `finos cost report` stays light.

### D9. Command line

- **`-v`**: `report_tracing` prints, after the timing lines, one cost line built from `Observation.requests`. It sums the requests when a command opened several roots, which does not happen today.
- **`finos cost report`** (`cli/cost.py`, registered in `cli/main.py`):
  - streams the log, skipping and counting bad lines;
  - filters by `--since`/`--until` (inclusive UTC dates) and `--entry`, defaulting to every entry except `eval` and `live-test`;
  - groups by `(intent, provider)`;
  - prints a header (`prices as of`, the daily status) and one row per group; `--json` gives one object.

  Intent for a blocked query is `policy` (H3's blocked state), and its guard outcome shows `blocked`. The report adds a `blocked` count per row, so blocked queries don't hide in the policy mean.
- **`finos eval compare A B`** (`cli/eval.py`):
  - loads both JSON files;
  - requires the same `dataset` and `dataset_version` (exit 2 otherwise);
  - prints a table of metric, before, after, and Δ, then the gates evaluated with `gates.py`'s thresholds, then cost and latency.

  It makes no model call and imports no LangChain.

### D10. Settings and the optimization variants

- **`[cost]`**: `audit_log`, `audit_log_path`, `per_query_alert_usd`, `daily_budget_usd`, and `prices_as_of` are added to `_REQUIRED_SETTINGS`. `_validate_cost` checks types, a positive alert and budget, and `date.fromisoformat(prices_as_of)`.
- **`[cost.prices]`**: a table of model tables, each needing `input_per_1m` with optional `output_per_1m` (embeddings have none) and `cached_input_per_1m`. Every value is a non-negative number. Errors name the full key, for example `[cost.prices."gpt-4o-mini"] output_per_1m`.
- **`[ollama] reasoning` and `num_ctx`**: optional. `_chat_model` passes them to `ChatOllama(reasoning=..., num_ctx=...)` only when set, so an unset config builds the same object as today (llm-access spec). The judge and the classifier on Ollama get them too, since they share `_chat_model`. That is intended: a variant changes the provider's behavior everywhere it is used.
- `--set ollama.reasoning=false` needs the override parser to accept booleans and integers. It already parses TOML values, which tasks verify.
- **Variants** are run in the live group, one at a time against one baseline, each saved with `--json` and compared with `finos eval compare`. A shipped default changes (and its llm-access "Shipped ..." requirement with it) only for a variant that meets C13. That spec edit is a follow-up delta, made after the measurement, because the result cannot be known now.

## Risks / Trade-offs

- **[Risk]** The context-preserving executor makes the classifier's trace visible for the first time, raising LangSmith volume per query by one run. → It was already uploaded, as a separate trace; this moves it under the root and masks it.
- **[Risk]** A future model with an unusual `ls_model_name` (a dated snapshot such as `gpt-4o-mini-2024-07-18`) misses its price entry. → `price_call` falls back to the longest configured name the model starts with, and an unmatched model is unpriced and named on stderr, never 0.
- **[Risk]** The audit log grows without bound. → One line is about 1–2 KB, so 10,000 queries are 10–20 MB. Rotation is documented as a manual step; enforcement is out of scope.
- **[Risk]** Cross-process appends could interleave on a network filesystem. → The guide states that the log assumes a local disk. A strict deployment would ship records to a log service (Phase 2).
- **[Risk]** Recording `response_chars` and `query_chars` leaks a little (length). → Lengths identify no customer, and they make response-length cost analysis possible [lecture p. 63].
- **[Trade-off]** Fail-open auditing means a missing record is possible. → One stderr line marks it. Fail-closed is the Phase 2 choice for a regulated deployment (C6).
- **[Trade-off]** Embedding tokens are estimated. → Their price makes the error below a millionth of a dollar per query, and the record marks them `estimated`.
- **[Risk]** `reasoning=False` changes routing and answers on the local model. → It ships only if it passes the C13 floor on all five datasets.

## Migration Plan

- The new `[cost]` keys are required, so any private `config.toml` copy (the tests' `policy_env`, the evaluation's temporary config) gains them in the same task that adds them.
- No data migration. The audit log starts empty, and `finos cost report` handles a missing file.
- Rollback: set `[cost] audit_log = false` to stop writing. The classifier fix stands on its own and is not rolled back.
