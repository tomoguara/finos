# Design

## Context

See `proposal.md` for motivation and `specs/` for required behavior. The decisions come from the Hardening 1 explore notes ("Locked decisions" O1–O13). This design records how they are built.

**Current state** (`main` at `3f30321`):
- `config.get_settings()` copies `[langsmith] tracing` and `project` into the environment under both the `LANGCHAIN_*` and `LANGSMITH_*` names.
- No code imports `langsmith`. `langsmith` 0.14.17 is installed through `langchain-core` 0.3.86.
- The measured run tree is `LangGraph` → nodes → `RunnableSequence` → prompt and model. Retrieval, normalization, account resolution, and escalation assembly are plain Python and produce no runs.

**Probes run during the explore** (throwaway scripts, nothing kept). They are facts this design relies on:
1. `@traceable` runs called inside a LangGraph node nest under that node's run.
2. One `langsmith.Client` subclass passed through `tracing_context(client=...)` receives both LangChain runs and `@traceable` runs, offline.
3. An owned `@traceable` root can add tags and metadata after the graph has returned. The trace ID is available inside it.
4. A handler held in a `ContextVar` registered with `langchain_core.tracers.context.register_configure_hook` sees every LangChain run started inside that context. With tracing off and no `config` passed, it reported run names (from `run_name`), durations, and the model's `usage_metadata` tokens.
5. LangGraph already tags `__start__` and `ChannelWrite` runs `langsmith:hidden`.

## Goals / Non-Goals

**Goals:**
- All tracing behavior lives behind one module, `finos.observability`, which imports `langsmith` lazily and is the only module that imports it at all.
- Agents keep their contracts. Graph node functions return the same keys, and the standalone `ask_*` helpers return the same states.
- Masking can't be bypassed by any entry point the system offers: the CLI, `ask`, `ask_*`, and the live tests.

**Non-Goals:**
- Tracing direct calls to node functions (`policy_agent(state)`) made outside an entry point. Those runs, when tracing is on, use LangSmith's default client and are not masked. No production path makes such calls (see Risks).
- Any change to what a command prints on stdout, or to `SupportState`.

## Decisions

### D1. One module: `src/finos/observability.py`

Public surface:

| Name | Role |
| --- | --- |
| `observe(entry)` | Context manager the CLI and live tests enter around one command or test. It holds an `Observation`: the entry point, the timing collector, and the trace ID once known. Stored in a `ContextVar`. |
| `root(name, *, config=None)` | Context manager or decorator used by `ask`, `ask_*`, `policy_search`, and `supervisor_classify`. It opens `tracing_context(client=<masking client>, project_name=...)`, starts a `@traceable` root run with the vocabulary's tags and metadata, records the trace ID in the active `Observation`, and lets the caller add tags at the end. |
| `step(name, run_type, *, inputs=..., outputs=...)` | Wraps a plain-Python step as a traced run with input and output adapters, and records its duration in the collector. |
| `chain_config(name)` | `{"run_name": name}` for `with_config` on the four chains. |
| `mask(payload)` | The SSN masking function (D5). |
| `tracing_status()` | Whether tracing is on, the project, the sampling rate, and the reason it is off. |

- **Lazy import:** `langsmith` is imported inside these functions, not at module level. So `finos.cli.main` and `--help` stay free of it (observability spec), and importing `finos.agents` still has no side effects (policy-agent spec).
- **Alternatives rejected:** decorating functions with `@traceable` at import time (that imports `langsmith` wherever the agents are imported), and scattering `langsmith` calls across modules (the explore wants one place for Evaluation, Guardrails, and Cost to import).

### D2. Run tree and names

```
CLI command --> observe(entry) ----------------------------------------------+
                  |                                                          |
ask(app, q) --> root("support_query")                                        | Observation:
                  app.invoke(..., config={"run_name": "support_graph"})      |  entry,
                    classify_intent                                          |  timings,
                      supervisor_llm   (with_config run_name)                |  trace_id
                      normalize_intent (step, parser)                        |
                      route_by_intent                                        |
                    policy_agent                                             |
                      policy_retrieval (step, retriever)                     |
                      policy_llm                                             |
                    account_agent                                            |
                      account_resolution (step, tool)                        |
                      account_llm                                            |
                    escalation_agent                                         |
                      escalation_llm                                         |
                      escalation_assembly (step, parser) <-------------------+
```

- **Standalone roots:** `ask_policy`, `ask_account`, and `ask_escalation` open `root("policy_query" | "account_query" | "escalation_query")`. `finos policy search` opens `root("policy_search")` around `vectorstore.search`. `finos supervisor classify` opens `root("supervisor_classify")` around `classify_query`.
- **No double roots:** graph nodes call the agent functions, not the `ask_*` helpers, so the graph path never creates a second root.
- **Step placement:** steps wrap call sites inside the agent functions. `normalize_intent` and `route_by_intent` keep their signatures. `vectorstore.search` is wrapped where `policy_agent` calls it, and `finos policy search` gets the same wrapping.
- **Untraced:** `ensure_index` (index builds) is not wrapped and runs outside any step.

### D3. What each step records

| Step | Inputs | Outputs |
| --- | --- | --- |
| `normalize_intent` (parser) | `{"raw": <reply>}` | `{"intent": ..., "fallback": <bool>}` (fallback is true when no vocabulary member appears) |
| `policy_retrieval` (retriever) | `{"query": ...}` | `[{"page_content": text, "metadata": {"source", "chunk_index", "score"}}, ...]` in rank order, the document shape LangSmith renders |
| `account_resolution` (tool) | `{"query": ...}` | `{"outcome": ..., "account_ids": [...]}`; the record is stripped by the output adapter |
| `escalation_assembly` (parser) | `{"raw": <reply>}` | `{"used_fallback": <bool>}` |

The functions' own return values don't change; adapters shape only what is traced.

### D4. Tags and metadata

- **Tags on every root:**
  - `entry:<point>`, taken from the active `Observation`. Without one it is `entry:api`, for library callers.
  - `provider:<name>`.
- **The intent tag:** `root("support_query")` adds `intent:<intent>` from the returned state before the root run ends (probe 3).
- **Entry points:** `supervisor-ask`, `supervisor-classify`, `policy-ask`, `policy-search`, `account-ask`, `escalation-ask`, `live-test`, and `api`. `policy-search` is added here: the explore listed `search` among the traced commands (O6) but left it out of the entry list (O4).
- **Metadata,** built once per root from settings:
  - `provider`, `chat_model`, `embedding_model`, `temperature`;
  - `chunk_size`, `chunk_overlap`, `top_k`, `collection`;
  - `index_fingerprint`, read from `data/chroma/finos_index.json`, or `"none"` before the first build;
  - `prompt_versions`, the first 8 hex characters of each system prompt's SHA-256;
  - `finos_version`.
- **`ask(app, query, *, config=None)`** (support-graph delta): `config` may hold `tags` and `metadata`, which are merged into the root's. The same keyword is added to `ask_policy`, `ask_account`, and `ask_escalation`.
- **Never customer data:** no value comes from the query or the records. A test asserts it for an `ACC-12345` query.

### D5. Masking

- **The client:** `root()` uses a `langsmith.Client(hide_inputs=mask, hide_outputs=mask)` created once per process, passed through `tracing_context(client=...)`. Probe 2 showed LangChain runs use the context's client too, so every run under an owned root is masked before upload.
- **What `mask(payload)` does:** it walks dicts, lists, and strings, and on every string applies:
  1. `"ssn_last4": "dddd"` (JSON) and `'ssn_last4': 'dddd'` (Python repr) → the value becomes `[REDACTED:ssn]`;
  2. each known `ssn_last4` value from `mock_accounts.json` as a standalone number (no adjacent digit) → `[REDACTED:ssn]`;
  3. `\b\d{3}-\d{2}-\d{4}\b` → `[REDACTED:ssn]`.
- **Known values** are loaded once, on first use, through `finos.accounts.load_accounts()`. If the records file is missing or invalid, steps 1 and 3 still apply, and nothing is raised: tracing must never fail a request.
- **Ordinary numbers survive:** amounts (`$1,500`), years, and five-digit account IDs don't match these patterns. A test pins it.
- **Alternatives rejected:** LangSmith's `create_anonymizer` (it fits too, but a plain function is easier to test and reason about), and a global four-digit pattern (it masks amounts and years).

### D6. No key, sampling, and the stderr notice

- **In `get_settings()`**, after `load_dotenv()`:
  - if `tracing` is true and neither `LANGSMITH_API_KEY` nor `LANGCHAIN_API_KEY` is set, the tracing variables are written as `"false"`, and `config` records `tracing_off_reason = "no-api-key"`;
  - `sampling_rate` is validated (a number, 0.0–1.0, else a `KeyError` naming the setting and the file, matching the existing missing-setting error) and written to `LANGSMITH_TRACING_SAMPLING_RATE` and `LANGCHAIN_TRACING_SAMPLING_RATE`.
- **The notice:** `cli/shared.py` gains `report_tracing(ctx)`, which the model-calling commands call. When the reason is `no-api-key`, it writes `tracing: off (no LANGSMITH_API_KEY or LANGCHAIN_API_KEY set)` once, verbose or not.
- **Under `--verbose`** it adds the trace line:
  - traced: `debug: trace: <id> (project <p>)`;
  - not traced: `debug: trace: none (tracing off)`;
  - sampling below 1.0: `debug: trace: <id> (project <p>, sampling 0.25: may not be recorded)`.
- **Which commands:** the model-calling ones, `supervisor ask` and `classify`, `policy ask` and `search`, `account ask`, and `escalation ask`. `graph`, `ingest`, `lookup`, `list`, `contact`, and every `state` command print none of this, so existing tests that require empty stderr keep passing. Plain `ingest` embeds only on a rebuild, and index builds are untraced.
- **Alternative rejected:** printing from `config`. Library code stays silent; the CLI reports.

### D7. Timings and tokens

- **The collector** lives in the active `Observation`:
  - LangChain runs are captured by a `BaseCallbackHandler` registered through `register_configure_hook` (probe 4): node runs give elapsed time, and model runs give `usage_metadata` tokens;
  - `step()` records its own duration for traced steps, which callbacks can't see.
- **The `--verbose` lines,** after the result:

```
debug: classify_intent: 312 ms, 98+3 tokens
debug: policy_agent: 1077 ms (retrieval 41 ms), 1240+85 tokens
debug: total: 1.41 s
```

- **Missing usage:** when a model reports no usage, the tokens read `n/a`.
- **Works with tracing off:** the collector doesn't depend on LangSmith at all.
- **Cost reuses it:** the Cost sub-phase reads per-call tokens from the same collector for `audit_log.jsonl`.

### D8. Live tests

An autouse fixture in `tests/conftest.py` applies to items marked `live`. It enters `observe("live-test")` and adds the test's node ID to the root metadata (`test_id`). Live test bodies are unchanged.

### D9. Dependency

`pyproject.toml` declares `langsmith>=0.14,<0.15`. `uv lock` keeps 0.14.17, and `uv.lock` changes only in its declared-dependency entries. No other package is added.

### D10. Testing

- **The fake client:** `tests/test_observability.py` defines a `langsmith.Client` subclass (`__slots__ = ()`) that records `create_run` and `update_run` (probe 2). A fixture enables tracing through `tracing_context(enabled=True, client=fake)`, with a fake key in the environment and no network.
- **Masking is tested two ways:**
  - `mask()` directly: the field, known values, the SSN pattern, the marker, and untouched numbers;
  - that `root()`'s client is configured with `hide_inputs` and `hide_outputs` set to `mask`. The fake client overrides upload, so the SDK's hide hooks aren't exercised end to end; the live acceptance run checks a real trace in LangSmith.
- **Run trees per route,** offline, with the existing fakes (`policy_env`, `recording_chat`):
  - names and nesting;
  - run types;
  - the decision steps' outputs;
  - the root's tags and metadata, including the late intent tag;
  - no customer data.
- **Settings:** `tests/test_llm.py` covers the no-key auto-off, a key present, sampling applied, sampling missing, and sampling out of range. The "Tracing enabled" test now sets a fake key.
- **CLI:** the no-key line, the `-v` trace and timing lines, unchanged stdout and exit codes, and no lines on commands that call no model.
- **Light imports:** the light-import tests also exclude `langsmith`.

## Risks / Trade-offs

- **[Direct node calls outside an entry point are traced unmasked]** → no shipped path does this. Tests run with tracing off. The how-to guide says to trace through `ask`/`ask_*`/the CLI. A Guardrails-era option is to install the masking client as the process default.
- **[The SDK's hide hooks are exercised only in the live run]** → `mask()` is unit-tested, its wiring is asserted, and live acceptance checks a real account trace for `[REDACTED:ssn]`.
- **[Exit can wait on uploads]** → the SDK's non-daemon threads and `atexit` handler guarantee delivery; a slow or unreachable LangSmith delays exit. This is documented in the setup guide.
- **[`register_configure_hook` is process-global registration]** → it is registered once, at import of `finos.observability`, and does nothing outside an `Observation`.
- **[LangSmith's document rendering depends on the output shape]** → the retriever adapter emits `page_content` plus `metadata`, and live acceptance confirms the rendering.
- **[`langsmith` changes quickly]** → pinned below 0.15; tests use only `Client`, `traceable`, `tracing_context`, and `get_current_run_tree`.

## Migration Plan

- **No data migration.** `config.toml` gains `sampling_rate = 1.0`. A developer's local copy without the key fails with the standard missing-setting error, naming the key to add.
- **Rollback** is reverting the change; nothing persistent is created besides LangSmith traces.
