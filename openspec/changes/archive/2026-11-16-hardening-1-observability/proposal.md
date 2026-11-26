# Proposal

## Why

A wrong answer can come from misrouting, retrieval, context, or the model, and today a LangSmith trace can't tell them apart. Retrieval, intent normalization, account resolution, and escalation assembly aren't runs. Runs carry no tags or metadata. The CLI never names the trace. The account record, including `ssn_last4`, is uploaded unmasked. A developer with no key gets a warning and upload errors after every model call. Observability is the first hardening sub-phase because evaluation, guardrails, and cost all read traces [lecture p. 17]. The decisions are recorded in the Hardening 1 explore notes ("Locked decisions", O1–O13).

## What Changes

- **Named run tree**:
  - The graph entry point gets an owned root run, `support_query`, with LangGraph's run renamed `support_graph`.
  - The standalone entry points get roots `policy_query`, `account_query`, `escalation_query`, `policy_search`, and `supervisor_classify`.
  - The chains are named `supervisor_llm`, `policy_llm`, `account_llm`, and `escalation_llm`.
  - New runs: `normalize_intent` (parser), `policy_retrieval` (retriever, with scored chunks shown as documents), `account_resolution` (tool, outcome and IDs only), and `escalation_assembly` (parser, with the fallback flag).
  - Index builds stay untraced.
- **Tags and metadata**:
  - A fixed vocabulary on every root: `entry:*`, `provider:*`, and `intent:*`, with the intent tag added after routing.
  - Metadata: models, RAG settings, `index_fingerprint`, a hash per prompt, and `finos_version`.
  - Never customer data. `exp:*` and `eval-*` are reserved for Evaluation.
- **SSN masking before upload**: the `ssn_last4` field, every known `ssn_last4` value, and full SSN patterns become `[REDACTED:ssn]` in every run's inputs and outputs. Tracing stays **on** by default.
- **No key, no tracing**: with `tracing = true` and no LangSmith API key, settings turn tracing off for the process, and model-calling commands write one stderr line saying so.
- **Sampling**: a new required `[langsmith] sampling_rate`, shipped at `1.0`, validated to 0.0–1.0, and applied to the environment like `tracing`.
- **`--verbose` diagnostics** on model-calling commands:
  - the trace line, `debug: trace: <id> (project finos)` or `debug: trace: none (tracing off)`;
  - per-step timings and token counts.
  - stdout, `--json`, exit codes, and `SupportState` are unchanged.
- **One module**: `src/finos/observability.py` owns all of the above and is the only importer of `langsmith`. `ask()` gains the keyword-only `config` recorded in Step 5, and `ask_policy`, `ask_account`, and `ask_escalation` gain the same.
- **Dependency**: `langsmith>=0.14,<0.15` is declared in `pyproject.toml`; `uv.lock` is unchanged (0.14.17 is already locked).
- **Live tests** run under `entry:live-test`, with the test ID in metadata.
- **Docs**:
  - a new `docs/how-to-guide/debugging-with-traces.md`;
  - updates to the setup guide, the testing guide (a p95 latency baseline for both providers, judged against `gpt-4o-mini`), and `docs/systems-design-and-architecture.md` §9.1.

**Out of scope**:
- Evaluation datasets and experiments, and `git_sha`.
- Guardrails: response redaction, the guardrail event log, the query hash.
- Cost: `CostTracker`, `audit_log.jsonl`, budgets.
- Any change to agent behavior, prompts, or routing.
- A `finos trace` command group, command-line tags, a local p95 command, and other tracing vendors.

## Capabilities

### New Capabilities

- `observability`: How requests are traced. It covers:
  - the named run tree and what each run records;
  - the tag and metadata vocabulary;
  - SSN masking before upload;
  - the `--verbose` trace line and per-step timings;
  - the guarantee that tracing never changes results;
  - tagging of live tests.

### Modified Capabilities

- `llm-access`:
  - Tracing turns itself off when no API key is available.
  - The `[langsmith] sampling_rate` setting is applied to the environment, required, and validated.
  - The shipped tracing settings now include `sampling_rate = 1.0`.
- `support-graph`: the `ask` helper accepts an optional keyword-only `config` for tags and metadata, as recorded in Step 5.
- `project-scaffold`: `langsmith` is a declared direct dependency.

## Impact

- **Code**:
  - New: `src/finos/observability.py`.
  - Changed:
    - `src/finos/config.py`: sampling, the no-key auto-off, and the reason it records;
    - `src/finos/main.py`: `ask` gains `config` and its owned root;
    - `src/finos/agents/supervisor.py`, `policy.py`, `account.py`, and `escalation.py`: named runs and steps;
    - `src/finos/vectorstore.py`: `search()` becomes a retriever run;
    - `src/finos/cli/shared.py` and each `cli/*.py` that calls a model: the trace line, timings, and the no-key line.
- **Configuration**: `config.toml` gains `[langsmith] sampling_rate = 1.0`.
- **Dependencies**: `langsmith` is declared. No new package is installed.
- **Tests**:
  - New: `tests/test_observability.py`, a fake `langsmith.Client` that captures run trees offline.
  - Updated: `tests/test_llm.py` (tracing scenarios with and without a key, `sampling_rate`), the CLI tests (`-v` lines), and `tests/conftest.py` (live-test config).
  - The default suite stays offline, with no key.
- **Runtime**:
  - One extra traced run per decision step, negligible next to the model calls.
  - Traces from short commands are flushed at exit by the SDK; a slow or unreachable LangSmith can delay exit.
- **Docs**:
  - New: `docs/how-to-guide/debugging-with-traces.md`.
  - Updated: `docs/how-to-guide/setup-and-configuration.md`, `docs/how-to-guide/testing.md`, the README guide table, and `docs/systems-design-and-architecture.md` §9.1 and §8.
