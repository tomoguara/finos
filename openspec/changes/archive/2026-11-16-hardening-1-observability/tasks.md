# Tasks

> Applies on top of the completed core build (Steps 1–5 archived). Groups 1–8 are verified offline, with no LangSmith key and no network; group 9 is the live acceptance run on a developer machine with a `LANGCHAIN_API_KEY`. The decisions are in the Hardening 1 explore notes ("Locked decisions") and `design.md`.

## 1. Preconditions and dependency

- [x] 1.1 Confirm the starting point: `openspec list` shows only this change, `uv run pytest` passes (646 passed, 43 deselected), and `.venv/bin/python -c "import finos.cli.main, sys; print('langsmith' in sys.modules)"` prints `False`. Record the branch in use with `git branch --show-current`.
- [x] 1.2 Declare `langsmith>=0.14,<0.15` in `pyproject.toml` dependencies and run `uv lock` (design D9); verify `uv sync --locked` succeeds, `uv pip show langsmith` reports 0.14.17, and `tests/test_scaffold.py` gains an assertion that `langsmith` is declared, alongside `langchain-text-splitters` (project-scaffold delta). Verify `uv run pytest tests/test_scaffold.py` passes.

## 2. Settings: sampling and the no-key auto-off

- [x] 2.1 Add `sampling_rate = 1.0`, with a comment, to `[langsmith]` in `config.toml`. Add it to `_REQUIRED_SETTINGS`, validate it as a number from 0.0 to 1.0 (otherwise a `KeyError` naming `[langsmith] sampling_rate` and the file), and write it to `LANGSMITH_TRACING_SAMPLING_RATE` and `LANGCHAIN_TRACING_SAMPLING_RATE` when settings load (design D6). Extend `tests/test_llm.py`: the shipped value, the rate applied over a conflicting environment value, a missing key, and an out-of-range value (llm-access delta). Verify `uv run pytest tests/test_llm.py` passes.
- [x] 2.2 In `get_settings()`, after `load_dotenv()`: when `tracing` is true and neither `LANGSMITH_API_KEY` nor `LANGCHAIN_API_KEY` is set, write the tracing variables as `"false"` and record the reason `no-api-key`; expose it through `finos.config.tracing_status()` (a stable, langsmith-free accessor; `finos.observability.tracing_status()` re-exports it). Update the "Tracing enabled" tests to set a fake key, and add tests for "no key: off with the reason" and "key present: on". Verify `uv run pytest tests/test_llm.py` passes with tracing set to true and to false in the committed `config.toml`.
- [x] 2.3 Update `docs/how-to-guide/setup-and-configuration.md` ("Tracing"): `sampling_rate`, the no-key auto-off and its stderr line, that traces leave the machine with `ssn_last4` masked, that LangSmith retention is an account setting, and that exit can wait for uploads. Verify by reading, and that every link and anchor resolves.

## 3. The observability module

- [x] 3.1 Create `src/finos/observability.py` with `observe(entry)`, `root(name, *, config=None)`, `step(name, run_type, ...)`, `chain_config(name)`, and `tracing_status()`, importing `langsmith` only inside functions (design D1). Build root tags (`entry:*`, `provider:*`) and metadata (provider, models, temperature, retrieval settings, `index_fingerprint` or `"none"`, `prompt_versions` as 8-hex SHA-256 prefixes, `finos_version`) per design D4, and merge `config` tags and metadata. Create `tests/test_observability.py` with the fake `langsmith.Client` subclass and a fixture that enables tracing through `tracing_context` with a fake key, and test the tags, the metadata keys and values, the `entry:api` default, and that no value contains query text. Verify `uv run pytest tests/test_observability.py` passes.
- [x] 3.2 Add `mask(payload)` and the per-process masking client (`Client(hide_inputs=mask, hide_outputs=mask)`) used by `root()` (design D5). Test: the `ssn_last4` field in JSON and in a Python repr, each of the four known values as standalone numbers, a full `ddd-dd-dddd` SSN, the `[REDACTED:ssn]` marker, nested dicts and lists, untouched `$1,500`, `2026`, `ACC-12345`, and `12450.75`, a missing records file (field and pattern masking only, no error), and that `root()`'s client has `mask` as its hide functions. Verify `uv run pytest tests/test_observability.py` passes.
- [x] 3.3 Extend the light-import tests (`tests/test_cli.py` and each `test_cli_*.py` light-import test) to also exclude `langsmith`, and add a subprocess test that importing `finos.agents` and `finos.observability` loads no `langsmith` until a traced call (observability spec "Tracing support stays out of light imports"). Verify `uv run pytest tests/test_cli.py tests/test_observability.py` passes.

## 4. The run tree

- [x] 4.1 Give `ask(app, query, *, config=None)` the `support_query` root, run the graph with `run_name="support_graph"`, and add `intent:<intent>` to the root after the graph returns (support-graph delta; design D2 and D4). Name the supervisor chain `supervisor_llm` and wrap normalization as the `normalize_intent` parser step, with outputs `{"intent", "fallback"}`. Test offline with the fake client: the root, `support_graph`, and node names; the late intent tag; `normalize_intent` marking a fallback for an unrecognized reply; and that `ask` with and without `config` returns the same state. Verify `uv run pytest tests/test_observability.py tests/test_graph.py tests/test_supervisor.py` passes.
- [x] 4.2 Wrap retrieval as the `policy_retrieval` retriever step, with outputs as documents (`page_content` plus `metadata` with `source`, `chunk_index`, `score`) in rank order, and name the policy chain `policy_llm` (design D3). Give `ask_policy(query, *, config=None)` the `policy_query` root. Test the policy run tree (graph and standalone), the retriever run type and document shape, and that index builds produce no run. Verify `uv run pytest tests/test_observability.py tests/test_policy.py tests/test_vectorstore.py` passes.
- [x] 4.3 Wrap account resolution as the `account_resolution` tool step, with outputs `{"outcome", "account_ids"}` and the record stripped, and name the account chain `account_llm`. Give `ask_account(query, *, config=None)` the `account_query` root. Test all four outcomes' run trees (no `account_llm` for the three constant outcomes), that no record field appears in `account_resolution`'s output, and that the masked `account_llm` input shows `[REDACTED:ssn]` instead of `6789` when passed through `mask`. Verify `uv run pytest tests/test_observability.py tests/test_account.py` passes.
- [x] 4.4 Name the escalation chain `escalation_llm`, and wrap assembly as the `escalation_assembly` parser step with output `{"used_fallback"}`. Give `ask_escalation(query, *, config=None)` the `escalation_query` root. Test the run tree and the fallback flag for a blank reply. Verify `uv run pytest tests/test_observability.py tests/test_escalation.py` passes.
- [x] 4.5 Add a test that the same query through `ask`, and through each `ask_*`, returns identical states with tracing enabled (fake client) and disabled, and that an exception raised by the fake client during upload doesn't change the result (observability spec "Tracing never changes results"). Verify `uv run pytest` passes in full.

## 5. Timings and tokens

- [x] 5.1 Add the timing collector to `Observation`: a callback handler registered once with `register_configure_hook` (node durations and model `usage_metadata` tokens), plus `step()` durations (design D7). Test with tracing off: a graph query and a standalone query record each node's time, the retrieval time, the tokens of each model call (from `recording_chat` with `usage_metadata`), `n/a` when usage is missing, and the total; and that nothing is collected outside an `Observation`. Verify `uv run pytest tests/test_observability.py` passes.

## 6. Command line

- [x] 6.1 Add `report_tracing(ctx)` to `src/finos/cli/shared.py` and call it from every model-calling command (`supervisor ask` and `classify`, `policy ask` and `search`, `account ask`, `escalation ask`), each wrapped in `observe(<entry>)`. Give `policy search` the `policy_search` root and `supervisor classify` the `supervisor_classify` root (design D2, D6). Write the no-key line once (verbose or not), and under `--verbose` the trace line and the timing lines; replace the `supervisor ask -v` pointer. Test, in `tests/test_cli_*.py`: the no-key line with tracing on and no key; the `-v` trace line with the fake client (an ID and the project), `none (tracing off)`, and the sampling note at 0.25; the timing lines; stdout identical with and without `-v`; and no tracing or timing lines from `graph`, `ingest`, `lookup`, `list`, `contact`, and `state` commands. Verify `uv run pytest tests/test_cli.py tests/test_cli_policy.py tests/test_cli_account.py tests/test_cli_escalation.py tests/test_cli_supervisor.py` passes.
- [x] 6.2 Update the `--verbose` examples and the error tables in `docs/how-to-guide/cli-policy.md`, `cli-account.md`, `cli-escalation.md`, and `cli-supervisor.md` to show the trace line, the timing lines, and the no-key line. Verify by reading, and that every link and anchor resolves.

## 7. Live tests and the debugging guide

- [x] 7.1 Add an autouse fixture in `tests/conftest.py` that, for items marked `live`, enters `observe("live-test")` and adds the test's node ID to the root metadata as `test_id` (design D8). Add an offline test that the fixture applies to a `live`-marked item and not to an unmarked one. Verify `uv run pytest` still deselects every live test, and `uv run pytest -m live --collect-only` collects them.
- [x] 7.2 Write `docs/how-to-guide/debugging-with-traces.md`:
  - what each run in the tree shows, with the run tree;
  - the four-step workflow mapped to LangSmith and to the CLI;
  - how to find a trace (`-v`, tags, the `entry:live-test` filter);
  - the three worked cases (fee-waiver routing, the freeze reason, the echoed amount);
  - SSN masking and its limits;
  - the no-key line, and sampling.

  Add a row to the README's "How-to guides" table and a link from `docs/how-to-guide/testing.md`. Verify by reading, and that every link and anchor resolves.
- [x] 7.3 Update `docs/systems-design-and-architecture.md` §9.1 (decided items: run tree, vocabulary, masking, auto-off, sampling key, `--verbose` lines), §8 (`observability.py`, `test_observability.py`, the new guide), and §10 (the hardening rows), and add an "Implemented" note to the Hardening 1 explore notes. Verify with `grep -n -E "observability.py|REDACTED:ssn|sampling_rate" docs/systems-design-and-architecture.md` and by reading each section.

## 8. Full offline verification

- [x] 8.1 Run `uv run pytest` with `use_local_ollama_model` set to true and to false, and with `tracing` set to true and to false, with no `.env`, no key, and no network (`unshare -rn`); verify all pass, no live test runs, and `config.toml` is restored afterwards.
- [x] 8.2 Run `openspec validate hardening-1-observability --strict` and `openspec validate --all --strict`; verify both pass.

## 9. Live acceptance (developer machine with a LangSmith key)

- [x] 9.1 With the key set and `tracing = true`, run `uv run finos supervisor ask -q "Does ACC-12345 qualify for the fee waiver?" -v`, `uv run finos account ask -q "What is the balance on ACC-11111?" -v` (local provider), and `uv run finos escalation ask -q 'You charged me $35 twice and I am furious!' -v` (local provider). For each, open the trace by its ID and confirm the failing step is identifiable from the trace alone: the `classify_intent` / `normalize_intent` runs show a clean `policy` route; the `account_llm` reply quotes `freeze_reason`; the `escalation_llm` raw reply repeats the amount. Confirm the account trace shows `[REDACTED:ssn]` and no `ssn_last4` digits, and that `policy_retrieval` renders as documents with scores.
- [x] 9.2 In the LangSmith dashboard, confirm traces filter by `entry:supervisor-ask`, `intent:account_status`, `provider:<name>`, and `entry:live-test` (after `uv run pytest -m live -v -rxX`); verify the live suite's results are unchanged from the recorded baselines.
- [x] 9.3 Run the question set from `docs/how-to-guide/cli-supervisor.md` recipe 6 once per provider and confirm each run's `support_query` trace reaches LangSmith with its `provider:<name>` tag. Remove the key and confirm the single "tracing: off" line appears and the answers are unchanged. Recording p50 and p95 latency per provider in `docs/how-to-guide/testing.md`, judged against the 3 s target for `gpt-4o-mini`, is deferred: LangSmith's Monitoring view (free developer tier) aggregates latency across both providers, so per-provider percentiles need the trace durations exported and computed separately. Tracked on the project to-do list ("Before production and public release").

**Results (2026-11-16, developer machine):**
- Tracing confirmed: with a key and `tracing = true`, traces reach LangSmith as expected.
- Live suite, both providers: every live test passes except the multi-hop routing row (`tests/test_graph.py::test_live_routing[Does ACC-12345 qualify for the fee waiver?]`), the known single-route limitation parked for Phase 2.
- With the local provider and `qwen3-coder-next:q8_0-gpu`, three failure modes XFAILed: freeze reason volunteered, echoed amount, and misroute claim. They are model behavior against prompt-only rules, not pipeline faults. The shipped local model is now `qwen3.8:27b-q8_0` (`config.toml`, the `llm-access` delta), with which all three pass. Code-level enforcement is deferred to Guardrails (Hardening 3), tracked on the project to-do list.
- The freeze-reason and echoed-amount cases in 9.1 reproduce only with `qwen3-coder-next:q8_0-gpu` selected; with `qwen3.8:27b-q8_0` those traces show the rule followed.
- 9.3: traces arrive per provider, but LangSmith's Monitoring view on the free developer tier shows latency for both providers combined, so per-provider p50 and p95 were not recorded. Deferred to before production and public release (the project to-do list).

## Workflow follow-up

- Open a PR, merge after review, then archive the change with `/opsx:archive hardening-1-observability`.
- Hardening 2 (Evaluation) starts from this change's run names, retriever runs, tag vocabulary (`exp:*`, `eval-*`), and `ROUTING_CASES`.
