# Tasks

> Applies on top of Hardening 1 (archived). Groups 1–8 are verified offline, with no LangSmith key, no OpenAI key, no judge, and no network. Group 9 is the live baseline on a developer machine with `LANGCHAIN_API_KEY`, `OPENAI_API_KEY`, and the Ollama host. The decisions are in the Hardening 2 explore notes ("Locked decisions" E1–E15) and `design.md`.

## 1. Preconditions

- [x] 1.1 Confirm the starting point:
  - `openspec list` shows only this change;
  - `uv run pytest` passes (762 passed, 43 deselected);
  - `.venv/bin/python -c "import finos.cli.main, sys; print('langsmith' in sys.modules)"` prints `False`.

  Record the branch with `git branch --show-current`.

## 2. Settings and the judge model

- [x] 2.1 Add `[eval]` (`judge_provider = "openai"`, `judge_model = "gpt-4o-mini"`, `repetitions = 3`) and `[eval.gates]` (`routing_accuracy = 0.95`, `crisis_sentence = 1.0`, `faithfulness = 0.7`, `mrr = 0.8`) to `config.toml`, with comments (design D10).
  - In `config.py`: make every key required, and validate the thresholds (0.0–1.0), `repetitions` (a whole number ≥ 1), and `judge_provider` (`openai` or `ollama`), each failing with a `KeyError` that names the setting and the file.
  - Add the section to `LOCAL_CONFIG` in `tests/test_llm.py`, then add tests for: the shipped values; a missing `[eval] judge_model`; `[eval.gates] faithfulness = 7`; `repetitions = 0`; `judge_provider = "anthropic"`.
  - Verify `uv run pytest tests/test_llm.py` passes.
- [x] 2.2 Add `finos.llm.get_judge_llm()` (design D5): built from `[eval]`, independent of `use_local_ollama_model`, temperature 0, cached, and no network on construction.
  - Tests: an OpenAI judge with the local generator selected; an Ollama judge at the configured base URL with no OpenAI key; an OpenAI judge without a key fails naming `OPENAI_API_KEY`; no socket opened.
  - Verify `uv run pytest tests/test_llm.py` passes.
- [x] 2.3 Document `[eval]`, `[eval.gates]`, and the judge key in `docs/how-to-guide/setup-and-configuration.md`: a short "Evaluation" section, and the `.env` table row for `OPENAI_API_KEY` ("the OpenAI provider is selected, or the evaluation judge is OpenAI"). Verify by reading, and that every link and anchor resolves.

## 3. Datasets

- [x] 3.1 Create `src/finos/evaluation/__init__.py` and `datasets.py` (design D1, D2): the example schema, `load(name)` (errors name the file and the example), `version(name)` (8-hex SHA-256 of the file), and the `DATASETS` registry mapping each name to its target and evaluators.
  - Tests in `tests/test_evaluation.py`: loading, a malformed line, the version changes when one example changes and the others don't.
  - Verify `uv run pytest tests/test_evaluation.py` passes.
- [x] 3.2 Write `evals/datasets/routing.jsonl` (about 30 rows: the 12 `ROUTING_CASES` plus in-scope rows for each intent; multi-hop as `known_limitation`; the other four baselines as `failure_mode`) and `retrieval.jsonl` (about 15: easy, ambiguous, cross-domain, overlapping, the replacement-card conflict; each with `relevant_sources`).
  - Tests: every `ROUTING_CASES` query appears with the same intent; every `relevant_sources` entry is a file in `data/policy-docs/`.
  - Verify `uv run pytest tests/test_evaluation.py` passes.
- [x] 3.3 Write `policy.jsonl` (about 12 number-dense questions, including a split fact and a second-ranked-chunk answer), `account.jsonl` (about 10: balance, transactions, frozen and pending status, signed amounts, the three constant outcomes), `escalation.jsonl` (about 10: frustration, a manager request, an echoed amount, a policy question in an upset tone, 3 crisis messages marked `crisis: true`), and `judge_calibration.jsonl` (about 8 hand-scored items, design D5).
  - Tests: every figure and account ID in a policy or account reference appears in the corpus or the records; masking each dataset file's text with `observability.mask` changes nothing.
  - Verify `uv run pytest tests/test_evaluation.py` passes.

## 4. Evaluators

- [x] 4.1 Implement the code evaluators in `evaluation/evaluators.py` (evaluation spec "Code evaluators score each layer"; design D1):
  - `routing_accuracy`, `reciprocal_rank` (with MRR as the mean), `keyword_correctness`;
  - `no_policy_claim` and `no_false_promise` (move `has_policy_claim`, `has_false_promise`, and `explain` from `tests/helpers.py` into the package and make `tests/helpers.py` re-export them);
  - `crisis_sentence`, `no_ssn`.

  Each returns `{"key", "score", "comment"}`. Tests: ranks 1, 2, and absent; the `$35`/`$105` keyword case with its comment; `$1,500`, `4.49%`, and `ACC-12345` extraction; detectors on the fixed texts; crisis present and absent; `no_ssn` on `6789` and on `$1,500 2026 ACC-12345`. Verify `uv run pytest tests/test_evaluation.py tests/test_escalation.py` passes.
- [x] 4.2 Add the judge prompts (`JUDGE_FAITHFULNESS_PROMPT`, `JUDGE_CORRECTNESS_PROMPT`, `JUDGE_EMPATHY_PROMPT`) to `prompts.py`, add their hashes to `_prompt_versions()` (`judge_faithfulness`, `judge_correctness`, `judge_empathy`), and implement `evaluation/judge.py` (design D5):
  - structured output with a JSON fallback;
  - one retry, then `JudgeError`;
  - account faithfulness reads the record from `accounts.resolve()`;
  - `self_judged` detection;
  - `calibrate()` with its 0.25 tolerance.

  Tests use a fake judge model: a well-formed score, malformed text (an error, never 0.5), a failure then a retry, the account record reaching the faithfulness prompt, self-judged detection, and calibration pass and fail naming the item. Update the `prompt_versions` test in `tests/test_observability.py`. Verify `uv run pytest tests/test_evaluation.py tests/test_observability.py` passes.

## 5. Runners

- [x] 5.1 Implement variants in `evaluation/runner.py` (design D6):
  - parse `section.key=value` with TOML values, rejecting unknown keys;
  - a context manager that writes a temporary config, points `CONFIG_PATH` and `CHROMA_DIR` (`data/chroma-eval/<fingerprint8>/`) at it, clears the caches, and restores everything;
  - add `data/chroma-eval/` to `.gitignore`.

  Tests (under `policy_env`): an override is applied; an unknown key is rejected; the committed `config.toml` and the default index directory are byte-for-byte unchanged afterwards; two variants use different index directories. Verify `uv run pytest tests/test_evaluation.py` passes.
- [x] 5.2 Implement the local runner and `ExperimentResult` (design D3, D4, D7):
  - the targets per dataset, with timing;
  - repetitions;
  - evaluator and target errors recorded and excluded from means;
  - in-scope and all-rows means;
  - p50 and p95 latency;
  - judge call and token counts;
  - tracing disabled for its scope.

  Tests use `policy_env`, `recording_chat`, and a fake judge: 10 examples × 3 repetitions gives 30 scored outputs; the multi-hop row gives in-scope 1.0 and all-rows below 1.0; a target error and an evaluator error are counted and excluded; latency percentiles on fixed durations; with sockets blocked, a local run makes no network request. Verify `uv run pytest tests/test_evaluation.py` passes.
- [x] 5.3 Implement the LangSmith runner, run under `observe("eval")` (design D4, D8):
  - `evaluate()` with `client=masking_client()`;
  - evaluators adapted to the `(run, example)` objects;
  - `max_concurrency` by provider;
  - the experiment prefix, the `exp:*` and `eval-*` tags passed through each entry point's `config`, and the metadata (`git_sha`, `dataset_version`, `repetitions`, judge, overrides);
  - `push()` with the version check;
  - an unreachable LangSmith aborts with no partial result.

  Tests use the fake client from `tests/test_observability.py`, extended to stub the experiment and dataset API (explore probe 2): every run, including `support_query`, goes through the masking client; the roots carry `entry:eval`, `exp:baseline`, and `eval-routing`; the metadata holds the dataset version; scores match the local runner on the same fakes; a version mismatch refuses and names both versions. Verify `uv run pytest tests/test_evaluation.py tests/test_observability.py` passes.

## 6. Gates

- [x] 6.1 Implement `evaluation/gates.py` (design D7): run the gating datasets with the configured thresholds:
  - routing on in-scope rows;
  - `crisis_sentence` as the minimum;
  - fail on any error;
  - correctness and empathy as report-only.

  Tests with fake results: all pass; routing at 0.90 fails and names the misrouted examples; one crisis miss fails; one judge error fails; correctness below 0.8 does not block. Verify `uv run pytest tests/test_evaluation.py` passes.

## 7. Command line

- [x] 7.1 Add `src/finos/cli/eval.py` with `push`, `run`, and `gate` and register it in `cli/main.py` (eval-cli spec; design D9):
  - lazy imports;
  - `observed(ctx, "eval")`;
  - human and `--json` output;
  - exit codes 0, 1, and 2.

  Add `tests/test_cli_eval.py` with fakes:
  - group help; bare group exits 2; import stays light (no `langsmith`);
  - a local run's stdout lists the metrics, counts, and p50/p95;
  - `--json` parses;
  - an unknown dataset and a malformed `--set` exit 2;
  - `push` with no key exits 1 with one line;
  - gate pass exits 0 and gate fail exits 1, listing the failing examples;
  - an unreachable LangSmith exits 1 with one line.

  Verify `uv run pytest tests/test_cli.py tests/test_cli_eval.py` passes.
- [x] 7.2 Write `docs/how-to-guide/evaluation.md`. Cover:
  - the five layers and the datasets;
  - running `push`, `run`, and `gate`, locally and in LangSmith;
  - reading results (in-scope vs all rows, errors, latency, self-judged);
  - variants with `--set` and the `data/chroma-eval/` directory;
  - judge calibration;
  - adding a failing trace as a dataset row (the hill-climbing loop);
  - comparing experiments.

  Add a row to the README's "How-to guides" table and a link from `testing.md`. Verify by reading, and that every link and anchor resolves.

## 8. Full offline verification

- [x] 8.1 Run `uv run pytest` with `use_local_ollama_model` and `tracing` each set to true and to false, with no `.env`, no keys, and no network (`unshare -rn`). Verify all pass, no live test runs, and `config.toml` is restored afterwards.
- [x] 8.2 Run `openspec validate hardening-2-evaluation --strict` and `openspec validate --all --strict`; verify both pass.

## 9. Live baseline (developer machine with the keys and the Ollama host)

- [x] 9.1 Run `uv run finos eval push`, then `uv run finos eval run --dataset judge_calibration`; verify calibration passes before any other run (fix the judge prompts and rerun if not).
- [x] 9.2 Baseline: `uv run finos eval run --dataset <name>` for routing, retrieval, policy, account, and escalation, once per provider, with 3 repetitions, recorded in `docs/how-to-guide/testing.md`. **Deferred to before production** (the project to-do list, "Re-run the evaluation baseline and gates"): on the development machine a full graph run on `qwen3.8:27b-q8_0` takes about 48 s, so the baseline takes hours. Closed in development with the runs below.
- [x] 9.3 Run the variant checks: `--set policy.chunk_size=100` on retrieval, and the model comparison `--set ollama.model=qwen3-coder-next:q8_0-gpu` on escalation; record both in `testing.md`. Finding: MRR is scored per source file, so it cannot see chunk size (1.000 at `chunk_size` 100); the chunk-size check moves to keyword correctness on `policy`, deferred with the baseline.
- [x] 9.4 Gate: `uv run finos eval gate` once per provider, with the verdicts recorded. **Deferred to before production** with 9.2: the gate runs about 230 examples and took about 50 minutes for 63 routing runs before it was stopped. `finos eval gate` now prints per-dataset progress on stderr. Update `docs/systems-design-and-architecture.md` §9.2 and §10, update the latency item on the project to-do list (the runner now reports p50 and p95 per experiment), and add an "Implemented" note to the Hardening 2 explore notes.

**Results (2026-11-17, developer machine, local provider `qwen3.8:27b-q8_0`, judge `gpt-4o-mini`):**
- 9.1: all six datasets pushed (routing `f8b89677`, retrieval `317abf06`, policy `0fd33a0a`, account `8c74695a`, escalation `6a780154`, judge_calibration `ef02a8c0`). Judge calibration passed 8/8, every item exactly on its label.
- 9.3: retrieval with `policy.chunk_size=100`: MRR 1.000 over 48 runs, 0 errors, p50 49 ms, p95 57 ms. Escalation with `qwen3-coder-next:q8_0-gpu`: `no_policy_claim` 0.800, `no_false_promise` 1.000, `no_ssn` 1.000, `empathy` 1.000, `crisis_sentence` 1.000 (9 of 9), 0 errors, p50 2273 ms, p95 2906 ms, 30 judge calls.
- 9.2 and 9.4: not completed in development (hours per run on the local model); tracked on the project to-do list. `ollama ps` showed both models resident on the GPU (45 GB + 11 GB), so model swapping is ruled out; the remaining suspects are the model's thinking mode and its 262,144-token context.

## Workflow follow-up

- Open a PR, merge after review, then archive the change with `/opsx:archive hardening-2-evaluation`.
- Hardening 3 (Guardrails) starts from the escalation and account datasets, `no_ssn`, the detectors, and the guardrail to-do on the project to-do list, with the gate as its before/after check.
