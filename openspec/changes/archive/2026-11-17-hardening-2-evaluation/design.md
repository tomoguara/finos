# Design

## Context

See `proposal.md` for motivation and `specs/` for required behavior. The decisions come from the Hardening 2 explore notes ("Locked decisions" E1–E15). This design records how they are built.

**Current state** (`main` at `4be3f63`):
- `finos.observability` owns tracing:
  - `root()` uploads through `masking_client()` (`hide_inputs` and `hide_outputs` set to `mask`);
  - the entry point is read from the active `observe()`;
  - `_prompt_versions()` hashes the four agent system prompts.
- `finos.config.get_settings()` is cached and reads the module-level `CONFIG_PATH`. `vectorstore` keeps one index per `CHROMA_DIR`, identified by a marker file.
- Ground truth exists only inside tests: `ROUTING_CASES` (12 rows) and the live facts in `tests/test_policy.py`, `test_account.py`, and `test_escalation.py`. The escalation detectors are in `tests/helpers.py`.
- `langsmith` 0.14.17 provides `evaluate()` and the dataset API. No evaluation code exists.

**Probes run during the explore** (throwaway scripts, nothing kept). These are facts this design relies on:
1. `evaluate()` runs on a list of in-memory `Example` objects. With `upload_results=False` it still scores every example and repetition, but it always traces the target through its own client, a plain `Client()`, even inside `tracing_context(enabled=False)`.
2. With a fake client that stubs `create_project`, `update_project`, and feedback, `ask()`'s `support_query` root nests under the experiment's `Target` run, and the `exp:*` tags flow down. Every run uploads through the experiment's client: a child inherits its parent's client, so `masking_client()` received nothing.
3. `vectorstore._open_or_build` deletes the collection named in the directory's marker before a rebuild, so two settings that share one `CHROMA_DIR` destroy each other's index.
4. DeepEval 4.3.4 resolves against the lock, but adds 24 packages and downgrades `click`, `rich`, and `huggingface-hub`. It was rejected (E9).

## Goals / Non-Goals

**Goals:**
- One evaluator implementation serves both runners, the gate, and the tests.
- Experiments measure the shipped code paths. A target returns what the CLI's entry point returns.
- Nothing the evaluation does can upload unmasked data, edit `config.toml`, or rebuild `data/chroma/`.
- The default suite stays offline, with no key, no judge, and no LangSmith.

**Non-Goals:**
- Concurrency tuning beyond a per-provider default.
- A results database or dashboard: results print, and LangSmith holds the uploaded history.
- Automatically adding failing traces to datasets. Curation is a documented manual step.

## Decisions

### D1. Package layout: `src/finos/evaluation/`

| Module | Role |
| --- | --- |
| `datasets.py` | `load(name)`, `version(name)`, the example schema, `DATASETS` (name → layer, target, evaluators), push to LangSmith |
| `evaluators.py` | the code evaluators; each is `(run, example) -> {"key", "score", "comment"}` over plain dicts |
| `judge.py` | `faithfulness`, `correctness`, `empathy`, `calibrate()`: judge evaluators with the same signature |
| `runner.py` | `run_experiment(dataset, *, overrides, repetitions, local)`: the target, the two runners, results and latency |
| `gates.py` | `gate(...)`: the gating datasets and thresholds, and the verdict |

- **Lazy imports**: `langsmith`, LangChain, and the agents are imported inside functions, so `finos --help` and `import finos.cli.main` stay light (the eval-cli spec).
- **Evaluators take plain dicts.** Both runners adapt their objects to `run = {"outputs": ...}` and `example = {"inputs", "outputs", "metadata"}`. The LangSmith runner wraps each evaluator in an adapter that reads `run.outputs` and `example.outputs`. Tests call evaluators directly.

### D2. Datasets: JSON Lines under `evals/datasets/`

- **One example per line**: `{"id": "...", "inputs": {...}, "outputs": {...}, "metadata": {"split": "in_scope" | "known_limitation", "failure_mode": "...", "source": "..."}}`.
  - `inputs` is `{"question": ...}`, or `{"query": ...}` for retrieval.
  - `outputs` holds the layer's references: `intent`; `relevant_sources` (a list); `answer`; `crisis` (bool).
- **Version**: the first 8 hex characters of the file's SHA-256, computed by `version(name)`. The LangSmith dataset `finos-<name>` stores it in its metadata. `push` creates the dataset, or replaces its examples, only when the stored version differs.
- **Seeds and sizes** (E2): routing about 30 rows (the 12 `ROUTING_CASES` plus in-scope rows; multi-hop is `known_limitation`); retrieval about 15; policy about 12; account about 10; escalation about 10 (including 3 crisis messages); judge calibration about 8.
- **Consistency checks** (offline tests, the evaluation spec):
  - every `ROUTING_CASES` query appears with the same intent;
  - figures and IDs in policy and account references, extracted with the keyword evaluator's pattern, appear in `data/policy-docs/*.md` or `data/mock_accounts.json`;
  - masking each file's text with `observability.mask` changes nothing, which proves it is SSN-free.
- **Alternative rejected**: LangSmith as the source of truth. That gives no review in pull requests and no offline tests.

### D3. Targets reuse the entry points

| Dataset | Target | Output the evaluators read |
| --- | --- | --- |
| routing | `ask(app, q, config=...)` (one graph per experiment) | the `SupportState` (`intent`, `response`) |
| retrieval | `vectorstore.search(q)` | `{"sources": [hit.source ...]}` in rank order |
| policy | `ask_policy(q, config=...)` | the `SupportState` (`response`, `context`, `retrieved_sources`) |
| account | `ask_account(q, config=...)` | the `SupportState` |
| escalation | `ask_escalation(q, config=...)` | the `SupportState` |

- Account faithfulness gets the record in-process from `accounts.resolve(query).record`. The target never returns it, so experiment outputs carry no record.
- Each target call is timed with `time.perf_counter` for p50 and p95 latency (the nearest-rank method over all example runs).

### D4. Two runners, one evaluator set

```
run_experiment(dataset, overrides, repetitions, local)
   |
   +-- apply_overrides()  (D6)          --> temp config + variant CHROMA_DIR
   |
   +-- local or no LangSmith key? --yes--> LocalRunner
   |                                         with tracing_context(enabled=False):
   |                                           for example x repetition:
   |                                             output = target(inputs)    (timed)
   |                                             scores = [e(run, ex) for e]
   |
   +-- no -------------------------------> langsmith.evaluate(
                                              target, data=finos-<name>,
                                              evaluators=adapted,
                                              client=masking_client(),      (probe 2)
                                              num_repetitions=N,
                                              experiment_prefix=..., metadata=...)
                                           inside observe("eval")
   |
   v
 Results: per-metric means (in-scope and all), counts, errors, p50/p95, URL
```

- **The masking client is mandatory** on the LangSmith path (probes 1–2). `run_experiment` is the only caller of `evaluate()`, and a test asserts the `client` argument is `masking_client()`.
- **The local runner** disables tracing for its scope, so neither `root()` nor LangChain uploads anything (probe 1 showed `evaluate()` would). An offline test blocks sockets and asserts that no LangSmith request is made.
- **Concurrency**: `max_concurrency` 1 for Ollama and 4 for OpenAI on the LangSmith path. The local runner is sequential.
- **Alternative rejected**: `evaluate(upload_results=False)` as the local mode. It still traces through an unmasked client (probe 1).

### D5. The judge

- **`finos.llm.get_judge_llm()`**: built from `[eval] judge_provider` and `judge_model`, with the same construction rules as `get_llm()` (Ollama at `[ollama] base_url`; OpenAI requires `OPENAI_API_KEY`), at temperature 0, cached. It doesn't follow `use_local_ollama_model` (llm-access delta).
- **Prompts** live in `prompts.py`: `JUDGE_FAITHFULNESS_PROMPT`, `JUDGE_CORRECTNESS_PROMPT`, and `JUDGE_EMPATHY_PROMPT`, the last with the four criteria from `ESCALATION_SYSTEM_PROMPT` (acknowledge, validate, next step, tone). `_prompt_versions()` adds `judge_faithfulness`, `judge_correctness`, and `judge_empathy`, which the observability spec's "a short hash of each system prompt" already covers.
- **Output**: `with_structured_output` with a `{score: float 0..1, reason: str}` schema. If the provider rejects structured output, the judge falls back to extracting the first JSON object from the reply. Parse or validation failure, or a call that fails after one retry, raises `JudgeError`; the adapter records an error result (D7).
- **Self-judging**: when the judge's provider and model equal the chat model's, the results carry `self_judged: true` and the report warns.
- **Calibration**: `calibrate()` scores `judge_calibration.jsonl`, whose labels are hand-set. It passes only when every item is within 0.25 of its label. `finos eval run --dataset judge_calibration` runs it, and the baseline task requires a pass first.

### D6. Variants: `--set section.key=value`

- **Parsing**: `section.key=value` with a TOML-parsed value (`100`, `"x"`, `true`). The key must already exist in the shipped settings, else exit 2.
- **Applying**, in the runner's process:
  1. write the shipped `config.toml` with the overrides applied to a temporary file;
  2. set `config.CONFIG_PATH` to it and `config.CHROMA_DIR` to `data/chroma-eval/<fingerprint8>/`, where `fingerprint8` hashes the overrides;
  3. clear the caches of `get_settings`, `get_llm`, `get_judge_llm`, `get_embeddings`, and `get_store`.

  A context manager restores everything on exit. With no overrides, the shipped config and `data/chroma/` are used unchanged.
- **Gitignore**: `data/chroma-eval/` is added to `.gitignore`.
- **Alternative rejected**: a shared `CHROMA_DIR` for variants. Probe 3 showed every switch would rebuild over the shipped index.

### D7. Results, errors, and gates

- **`ExperimentResult`** holds: the dataset, its version, the variant, the provider, the judge and `self_judged`, repetitions, per-metric means over all and in-scope examples, scored and error counts, the error details (example id, key, reason), p50 and p95 in ms, judge call count and tokens, and the URL (`None` when local).
- **Errors**:
  - an evaluator that raises (including `JudgeError`) produces `{"key", "score": None, "comment": "error: ..."}`, excluded from means and counted;
  - a target that raises records a target error for that example, which every evaluator counts as errored, and the run continues;
  - LangSmith unreachable on the LangSmith path aborts with a `RuntimeError` (exit 1). There is no partial result.
- **Gates**: `gate()` runs routing, retrieval, policy, account, and escalation, and compares against `[eval.gates]`:
  - routing uses the in-scope mean;
  - `crisis_sentence` is the minimum over crisis examples, not the mean, so one miss fails;
  - the gate fails on any error;
  - correctness and empathy are printed as "report only".

### D8. Experiment naming and metadata

- **Prefix**: `eval-<dataset>-<provider>-<variant>`. The variant is `baseline`, or the overrides joined, for example `policy.chunk_size=100`.
- **Tags**: `entry:eval` (from `observe("eval")`), plus `exp:<variant>` and `eval-<dataset>`, passed as `config={"tags": [...]}` to the entry points, so they reach every root (probe 2).
- **Metadata**: `git_sha` (8 hex characters, from `git rev-parse`; `"unknown"` outside a checkout), `dataset_version`, `repetitions`, `judge_provider`, `judge_model`, `overrides`, and the Hardening 1 root metadata.

### D9. `finos eval` CLI

- `cli/eval.py` defines `eval_app` with `push`, `run`, and `gate`, registered in `cli/main.py` with one line.
- Bodies import `finos.evaluation` lazily, and use `observed(ctx, "eval")` for the Hardening 1 `--verbose` trace and timing lines.
- Output and exit codes follow the eval-cli spec. Human output is one line per metric, aligned; `--json` prints `ExperimentResult` (or the gate verdict) as a dict.

### D10. Configuration

```toml
[eval]
# The judge scores faithfulness, correctness, and empathy. Keep it a
# different model from the chat model, or results are marked self-judged.
judge_provider = "openai"
judge_model = "gpt-4o-mini"
repetitions = 3

[eval.gates]
routing_accuracy = 0.95   # in-scope rows
crisis_sentence = 1.0
faithfulness = 0.7
mrr = 0.8
```

- `config.py` adds these keys to `_REQUIRED_SETTINGS` (nested `eval.gates` keys included) and validates them (llm-access delta).
- Test configs that write their own `config.toml` (`tests/test_llm.py` `LOCAL_CONFIG`) gain the section. `policy_env` copies the shipped file, so it inherits the section.

## Risks / Trade-offs

- **[Judge scores drift with the judge model's version]** → The judge model and prompt hashes are recorded per experiment. Calibration reruns before any baseline. Comparisons stay within one judge.
- **[OpenAI judge makes local-provider baselines need an OpenAI key]** → This is documented. `[eval] judge_provider = "ollama"` is one setting away, marked self-judged when it matches the generator.
- **[Small datasets give noisy means]** → Three repetitions, an in-scope/all split, and sizes chosen so one row moves routing by about 3%. The instrument check (`chunk_size` 100) proves the datasets can see a regression.
- **[`evaluate()` internals change across `langsmith` releases]** → `langsmith` stays pinned below 0.15. The masking-client and fake-client tests break loudly if parenting or client use changes.
- **[Variant indexes accumulate under `data/chroma-eval/`]** → It is git-ignored and safe to delete. The how-to guide says so.
- **[Hand-written references go stale]** → The reference-figure check fails when the corpus or records change.

## Migration Plan

- **`config.toml`** gains `[eval]` and `[eval.gates]`. A developer's local copy without them fails with the standard missing-setting error, which names the key.
- **No data migration.** LangSmith datasets are created by `finos eval push`.
- **Rollback** is reverting the change. LangSmith datasets and experiments can be deleted by hand.

## Open Questions

- The exact count of each dataset's examples within the stated ranges is settled while writing them (task 3.x). Sizes don't change the design.
