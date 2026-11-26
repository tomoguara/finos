# Tasks

> Applies on top of Hardening 3 (archived). Groups 1–9 are verified offline: no OpenAI key, no LangSmith key, no network, with the model-based input layers off or faked and fake chat models reporting fixed `usage_metadata`. Group 10 is the live acceptance run on the developer machine with `OPENAI_API_KEY`, `LANGCHAIN_API_KEY`, and the Ollama host. The decisions are in the Hardening 4 explore notes ("Locked decisions" C1–C13) and `design.md`.

## 1. Preconditions

- [x] 1.1 Confirm the starting point:
  - `openspec list` shows only this change;
  - `uv run pytest` passes (1010 passed, 45 deselected);
  - `.venv/bin/python -c "import finos.cli.main, sys; print([m for m in ('langsmith','openai','langchain_core') if m in sys.modules])"` prints `[]`.

  Record the branch with `git branch --show-current`.

## 2. The classifier fix

- [x] 2.1 In `guardrails/input.py`, submit the classifier through LangChain's `ContextThreadPoolExecutor`, keeping the timeout and fail-open behavior (design D1). Add these regression tests to `tests/test_guardrails.py`:
  - inside `observe()`, a fake classifier reporting 150+1 tokens appears in `Observation.calls`, with tracing on and off;
  - with the fake LangSmith client, the classifier's model run has the `support_query` root as an ancestor, and no second trace is posted;
  - the uploaded classifier input shows `[REDACTED:ssn]` for a full SSN pattern;
  - a classifier timeout still gives an `error` decision and passes.

  Verify `uv run pytest tests/test_guardrails.py tests/test_observability.py` passes. Then run the same tests against the old code: the first three tests must fail there, which shows they catch the bug.

## 3. Settings

- [x] 3.1 Add `[cost]` and the two `[cost.prices]` entries to `config.toml`, with comments on prices, `prices_as_of`, the alert, the budget, and the audit log's contents (design D10; llm-access delta). Then:
  - add `logs/` to `.gitignore`;
  - in `config.py`, make the `[cost]` keys required and add `_validate_cost`, covering the price tables, the ISO date, positive thresholds, and errors naming the full key;
  - add the optional `[ollama] reasoning` (bool) and `num_ctx` (positive int) to validation;
  - in `tests/conftest.py`, make `policy_env` write `[cost]` with `audit_log_path` inside its temporary directory;
  - add an autouse guard that fails a test which appends to the real `logs/audit_log.jsonl`;
  - add the sections to `LOCAL_CONFIG` in `tests/test_llm.py`.

  Tests:
  - the shipped values;
  - a missing `[cost] prices_as_of`;
  - a negative `output_per_1m`;
  - `prices_as_of = "last week"`;
  - a price entry without `input_per_1m`;
  - `num_ctx = 0`;
  - a non-boolean `reasoning`.

  Verify `uv run pytest tests/test_llm.py` passes.
- [x] 3.2 Pass `reasoning` and `num_ctx` to `ChatOllama` in `llm._chat_model` only when set (design D10). Tests:
  - unset builds a `ChatOllama` with neither field changed from today;
  - `reasoning = false` and `num_ctx = 8192` reach the model;
  - `parse_override("ollama.reasoning=false")` gives the boolean `False`, and `"ollama.num_ctx=8192"` the integer.

  Verify `uv run pytest tests/test_llm.py tests/test_evaluation.py` passes.
- [x] 3.3 Document `[cost]` and the two Ollama keys in `docs/how-to-guide/setup-and-configuration.md`. Verify by reading, and that every link and anchor resolves.

## 4. Pricing and the collector

- [x] 4.1 Move `percentile()` to `src/finos/stats.py`, imported by `evaluation/runner.py`. Verify `uv run pytest tests/test_evaluation.py` passes unchanged.
- [x] 4.2 Create `src/finos/cost.py` with `price_call`, `QueryCost`, the snapshot-name prefix fallback, the once-per-model unpriced line, and the rounding rules (design D4; cost-tracking spec). Write `tests/test_cost.py` covering:
  - $0.00021 for 1,000+100 `gpt-4o-mini` tokens;
  - cached input;
  - Ollama is $0;
  - moderation is $0;
  - an unknown model and a call with no usage both give `None` for the call and the query;
  - `gpt-4o-mini-2024-07-18` prices as `gpt-4o-mini`;
  - the guard subtotal;
  - the unpriced line is printed once;
  - `cost.py` imports no LangChain, `langsmith`, or `openai`.

  Verify `uv run pytest tests/test_cost.py` passes.
- [x] 4.3 Extend the H1 collector (design D2):
  - `ModelCall` gains `model`, `provider`, `role`, `cached_input_tokens`, and `estimated`;
  - the handler records `ls_model_name` and `ls_provider` per `run_id`, and the role from the run name;
  - add `observability.record_call`, called from moderation (`$0`) and from `vectorstore.search` (estimated embedding tokens), but not from the index build.

  Tests in `tests/test_observability.py`:
  - a fake model with `ls_model_name` metadata is recorded with its model, provider, and role;
  - moderation and the embedding appear as calls;
  - a forced index rebuild adds no embedding call;
  - the existing `-v` token lines are unchanged.

  Verify `uv run pytest tests/test_observability.py tests/test_policy*.py tests/test_guardrails.py` passes.

## 5. The request scope, the audit record, and alerts

- [x] 5.1 Implement the per-root `Request` scope in `observability.root` (design D3):
  - the handler and `record_call` append to the active request;
  - guard decisions are recorded per request;
  - `root()` sets the timing handler when no observation is active;
  - `cost.finish` runs at root end inside a swallow-all `try`;
  - `Observation.requests` is set, and the `guards` unit appears in `units()`.

  Tests:
  - two sequential roots in one observation get disjoint calls;
  - a root outside `observe()` (entry `api`) still collects its calls;
  - a `finish` that raises leaves the state and exit code unchanged;
  - the `guards` unit holds the classifier's call and precedes `classify_intent`.

  Verify `uv run pytest tests/test_observability.py tests/test_graph.py` passes.
- [x] 5.2 Build and write the audit record (design D5, D6; cost-tracking spec) in `cost.py`. Tests in `tests/test_cost.py`:
  - one line per root, for `ask`, each `ask_*`, `policy search`, and `supervisor classify`;
  - the fields and their values for a policy query with fake usage;
  - `audit_log = false` writes nothing;
  - no customer content, checked by running every query in `evals/datasets/*.jsonl` through the record builder and asserting that no query text, `ACC-` ID, holder name, or record value appears;
  - a blocked query's record holds `blocked` and the category, and not the matched text;
  - 50 records from 8 threads give 50 parseable lines;
  - an unwritable path prints one `audit: not written` line per process and leaves the reply and exit code unchanged;
  - with the audit log and tracing each on and off, the returned states are identical.

  Verify `uv run pytest tests/test_cost.py` passes.
- [x] 5.3 Add the per-query alert, the `cost:alert` tag, and the root cost metadata (design D7; observability delta), plus `cost.daily_status`. Tests:
  - $0.0123 over a $0.01 threshold gives the stderr line, `WARNING`, `per_query`, and the tag;
  - an unknown cost never alerts;
  - with the fake LangSmith client, the root's metadata holds `cost_usd`, `guard_cost_usd`, `input_tokens`, and `output_tokens` equal to the record's;
  - `daily_status` returns `ok`, `warning` at 85%, and `alert` at 110%, using only today's UTC records and skipping `null` costs.

  Verify `uv run pytest tests/test_cost.py tests/test_observability.py` passes.

## 6. The `-v` cost line

- [x] 6.1 In `cli/shared.report_tracing`, print the cost line after the timing lines, from `Observation.requests` (design D9; observability delta). In `tests/test_cli_*.py`, test, for every model command:
  - the priced line format with the guard subtotal and price date;
  - `cost: unpriced` naming the model;
  - the `guards:` timing line when the classifier is on;
  - stdout is unchanged with and without `-v`.

  Verify `uv run pytest tests/test_cli*.py` passes.
- [x] 6.2 Update the `--verbose` sections of `cli-supervisor.md`, `cli-policy.md`, `cli-account.md`, and `cli-escalation.md` with the `guards:` and `cost:` lines. Verify by reading.

## 7. `finos cost report`

- [x] 7.1 Add `src/finos/cli/cost.py` (`report`), registered in `cli/main.py` (design D9; cost-cli spec). In `tests/test_cli_cost.py`, using fixture logs, test:
  - group help, and a bare group exiting 2;
  - the light import (no LangChain, `langsmith`, or `openai`);
  - per-intent and per-provider rows with count, total and mean cost, guard share, tokens, p50/p95, unpriced, and blocked counts;
  - the header with `prices_as_of` and the budget status;
  - `eval` and `live-test` are left out by default, and `--entry eval` includes them;
  - `--since` and `--until` are inclusive UTC days;
  - `--json`;
  - a missing log gives an empty report and exit 0;
  - a bad line is skipped and counted;
  - `--since yesterday` exits 2.

  Verify `uv run pytest tests/test_cli_cost.py tests/test_cli.py` passes.
- [x] 7.2 Write `docs/how-to-guide/cost.md`. Cover:
  - what is priced and what is not (local, moderation, the judge, the index build);
  - the price table and keeping it current;
  - unpriced costs;
  - the audit record's fields, and why it holds no query text;
  - retention, manual rotation, and the local-disk assumption;
  - the fail-open write;
  - alerts and the budget;
  - `finos cost report`;
  - the `-v` cost line;
  - the before/after method with `finos eval compare`.

  Add a README row. Verify by reading, and that every link and anchor resolves.

## 8. Evaluation cost and `compare`

- [x] 8.1 Add `cost.capture()` and wrap each target call in it, in the local and the LangSmith runners. Then:
  - add the per-output cost and token lists and their properties to `ExperimentResult`, and the `cost` block to `as_dict()`;
  - price the judge, and make `judge.Usage` unknown on a missing count;
  - call `daily_status` at the end of `run_experiment` (design D8; evaluation delta).

  Tests in `tests/test_evaluation.py`:
  - per-output cost with fake usage, locally and with concurrent targets (each output holds only its own calls);
  - the judge's cost is separate, and excluded from outputs;
  - a judge reply without usage makes the judge's tokens unknown;
  - the budget line after a run that crosses the budget, with exit code 0.

  Verify `uv run pytest tests/test_evaluation.py` passes.
- [x] 8.2 In `cli/eval.py`, print the cost and judge lines from `run`, and add `compare` (design D9; eval-cli delta). Tests in `tests/test_cli_eval.py`:
  - `run --local` shows the cost per output and the price date;
  - the judge line format;
  - `compare` over two saved results prints the metrics, gates, cost, and latency with their deltas;
  - different datasets or versions exit 2 naming both;
  - an unreadable file exits 2 naming it;
  - `compare --json`;
  - `finos eval --help` lists `compare`.

  Verify `uv run pytest tests/test_cli_eval.py` passes.
- [x] 8.3 Update `docs/how-to-guide/evaluation.md` (cost in results, the judge's cost, `compare`, and the quality floor C13 for adopting an optimization). Verify by reading, and that every link and anchor resolves.

## 9. Full offline verification and records

- [x] 9.1 Run `uv run pytest` with each combination of `use_local_ollama_model`, `tracing`, and `[cost] audit_log`, with no `.env`, no keys, and no network (`unshare -rn`); verify all pass, `config.toml` is restored, and `logs/` is untouched. Verify `finos --help` and importing the CLI load none of `openai`, `langsmith`, or LangChain.
- [x] 9.2 Run `openspec validate hardening-4-cost --strict` and `openspec validate --all --strict`; verify both pass.
- [x] 9.3 Update the records, and verify by reading:
  - on the project to-do list:
    - close "Record per-provider latency (p50, p95)", pointing at `finos cost report` and group 10;
    - add the semantic cache item, with C11's constraints and probe P4;
    - add per-node models, shorter prompts, and the Batch API;
  - update `docs/systems-design-and-architecture.md` §9.4 (the decided items) and §10 (the H4 row);
  - add an "Implemented" note to the Hardening 4 explore notes.

## 10. Live acceptance (developer machine with the keys and the Ollama host)

- [x] 10.1 P1 and P5, the per-intent baseline: run `uv run finos eval run --dataset <d> --repetitions 1 --json > baseline-<provider>-<d>.json` for `routing`, `policy`, `account`, `escalation`, and `guardrails`, on each provider. Then, in `docs/how-to-guide/testing.md`:
  - confirm that every chat call, including the classifier and the judge, reports usage;
  - record the tokens and cost per intent and the guard share, against the estimate in the explore's §9;
  - record p50 and p95 latency per provider.

  > **Deferred (2026-11-21)** by the user's decision: the full runs take a long time on the development machine. Marked done so the change can close. The run is step 1 of "Run the Hardening 4 cost measurements" on the project to-do list, required before `finos` is deployed to the public or the code is published on GitHub.
- [x] 10.2 P3: run one traced `uv run finos supervisor ask -q "What is the overdraft fee?" -v` on OpenAI. Confirm in LangSmith that the classifier's run is under `support_query` and masked, and that the root's `cost_usd` agrees with LangSmith's total cost for the trace to within rounding. Run `uv run finos cost report` and check that the query appears. Record the result.

  > **Done (2026-11-21)**, run by the user on OpenAI: the `guards:` line showed the classifier's 147+1 tokens, the cost line read `$0.000188 (1029+57 tokens, 5 calls; guards $0.000023)`, which matches the price table, and `finos cost report` listed the query (`policy`, `openai`, guards 12%). Recorded in `docs/how-to-guide/testing.md`. The LangSmith side (the classifier run's nesting and masking, and agreement with LangSmith's cost) was not reported; it is step 2 of the to-do item.
- [x] 10.3 Variants (C10), one at a time, each saved with `--json` and compared to the 10.1 baseline with `finos eval compare`:
  - `--set ollama.reasoning=false` (local, five datasets);
  - `--set policy.top_k=2` (`policy`, `retrieval`, `routing`, both providers);
  - `--set policy.chunk_size=500 --set policy.chunk_overlap=50` (`policy`, `retrieval`, both providers);
  - `--set ollama.num_ctx=8192` (local, five datasets, latency).

  Record each before/after table in `testing.md`, with adopt or reject under C13 and the reason.

  > **Deferred (2026-11-21)** by the user's decision: the full runs take a long time on the development machine. Marked done so the change can close. The run is step 3 of "Run the Hardening 4 cost measurements" on the project to-do list, required before public deployment or publication on GitHub. No optimization is adopted until then.
- [x] 10.4 For each adopted variant: change the shipped value in `config.toml`, and add an llm-access delta to this change updating the matching "Shipped ..." requirement. Re-run `uv run finos eval gate` on both providers, and verify it passes. If no variant is adopted, record that in `testing.md` and leave the shipped values unchanged.

  > **Deferred (2026-11-21)** with 10.3, which it depends on. Marked done so the change can close. The shipped values stay unchanged; adopting a variant is step 4 of the to-do item, and it then edits `openspec/specs/llm-access/spec.md` directly, since this change will be archived by then.

## Workflow follow-up

- Open a PR, rebase-merge after review, then archive the change with `/opsx:archive hardening-4-cost`.
- This closes the four hardening sub-phases. Phase 2 starts from the to-do items this change records: the semantic cache, per-node models, the Batch API, fail-closed auditing, and log shipping.
