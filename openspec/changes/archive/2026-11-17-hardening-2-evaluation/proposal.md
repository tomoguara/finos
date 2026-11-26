# Proposal

## Why

Today quality is a set of pass/fail live tests, one run each, so a prompt or RAG change that helps one question and hurts three looks like a pass, and provider and model choices rest on single runs. Evaluation measures the system layer by layer: routing, retrieval, faithfulness, correctness, and empathy [lecture p. 30]. Each number is reproducible, comparable across providers and settings, and cheap enough to rerun before every change that touches a prompt or a RAG setting. Guardrails and Cost both trade quality for safety or money, and need that number first. The decisions are recorded in the Hardening 2 explore notes ("Locked decisions", E1–E15).

## What Changes

- **Datasets in the repository**:
  - one JSON Lines file per layer under `evals/datasets/`: `routing`, `retrieval`, `policy`, `account`, `escalation`, plus `judge_calibration`;
  - each file's SHA-256 prefix is its version, recorded in every experiment;
  - pushed to LangSmith as `finos-<name>`;
  - offline checks keep the files consistent with `ROUTING_CASES`, the policy corpus, and the account records, and free of SSN data;
  - the multi-hop row is labeled `known_limitation` and reported separately.
- **Evaluators**:
  - code: `routing_accuracy`, `mrr`, `keyword_correctness`, `no_policy_claim`, `no_false_promise`, `crisis_sentence`, `no_ssn`;
  - LLM judge: `faithfulness`, `correctness`, `empathy` (the escalation prompt's four criteria);
  - each returns a score in 0–1 and a comment; an unparseable judge reply is an error, never a default score.
- **A judge model**:
  - configured in a new `[eval]` section, shipped as OpenAI `gpt-4o-mini`, so it is independent of the shipped local generator;
  - judge prompts live in `prompts.py`, and their hashes join `prompt_versions`;
  - a calibration set must pass before a baseline is trusted.
- **Two runners with the same evaluators**:
  - LangSmith experiments through `evaluate()` with the masking client, which is required: the explore probes showed that otherwise every run uploads unmasked;
  - a local runner with no network.
  - Both run under `entry:eval`, with repetitions (3 by default), and report each metric's mean, error counts, and p50 and p95 latency.
- **One setting at a time**: `--set section.key=value` runs a variant from a temporary copy of the configuration, with its own index directory. The committed `config.toml` and `data/chroma/` are never touched.
- **Quality gates as a local command**:
  - blocking: routing ≥ 0.95 on in-scope rows, the crisis sentence at 1.0, faithfulness ≥ 0.7, MRR ≥ 0.8, and no errors;
  - reported only: correctness and empathy.
- **A `finos eval` command group**: `push`, `run`, `gate`.
- **Baseline**: both providers × 3 repetitions after judge calibration; a `chunk_size` 100 instrument check; and a model comparison on escalation and account. Recorded in `docs/how-to-guide/testing.md`. The per-provider latency follow-up on the project to-do list is closed by the runner's p50/p95.
- **Docs**: a new `docs/how-to-guide/evaluation.md`, plus updates to the README, `testing.md`, `docs/systems-design-and-architecture.md` §9.2, and the explore document.

**Out of scope**:
- **Guardrails** (Hardening 3): enforcing any rule. This change only measures them, for example `no_ssn` and the escalation detectors.
- **Cost** (Hardening 4): budgets and `CostTracker`. Judge calls and tokens are recorded as an input.
- **Changing what the baseline finds**: a prompt or RAG change that improves a metric is a separate, measured change.
- **CI**: recorded on the project to-do list for before public release.
- **Also out**: DeepEval, multi-agent fan-out, online evaluation, and annotation queues.

## Capabilities

### New Capabilities

- `evaluation`: how the support system's quality is measured. It covers:
  - the datasets, their format, versioning, and consistency checks;
  - the evaluators and their scores;
  - the judge;
  - the LangSmith and local runners, repetitions, masking of experiment uploads, and variants;
  - the quality gates and their thresholds.
- `eval-cli`: the `finos eval` command group (`push`, `run`, `gate`), following the cli-framework conventions.

### Modified Capabilities

- `llm-access`:
  - a required `[eval]` section (judge provider and model, repetitions) and `[eval.gates]` thresholds, validated like the other settings, with shipped values;
  - a judge model obtained through the same provider-neutral helper as the chat model.

## Impact

- **Code**:
  - New: `src/finos/evaluation/` (`datasets.py`, `evaluators.py`, `judge.py`, `runner.py`, `gates.py`) and `src/finos/cli/eval.py`.
  - Changed:
    - `src/finos/config.py` (`[eval]` validation);
    - `src/finos/llm.py` (`get_judge_llm`);
    - `src/finos/prompts.py` (judge prompts);
    - `src/finos/observability.py` (judge prompts in `prompt_versions`);
    - `src/finos/cli/main.py` (one registration line).
- **Data**: `evals/datasets/*.jsonl` (new, committed); `data/chroma-eval/` (variant indexes, git-ignored).
- **Configuration**: `config.toml` gains `[eval]` and `[eval.gates]`.
- **Dependencies**: none new. `langsmith` 0.14 already provides `evaluate()` and the dataset API.
- **Tests**:
  - New: `tests/test_evaluation.py` and `tests/test_cli_eval.py`, offline, with fake targets, a fake judge, and the fake LangSmith client.
  - Updated: `tests/test_llm.py` (the `[eval]` settings). The default suite stays offline, with no key and no judge.
- **Runtime**: no change to any agent, prompt, route, or answer. Evaluation runs only when invoked.
- **Secrets**: no new ones. A baseline needs `OPENAI_API_KEY` for the judge, even for the local provider, and `LANGCHAIN_API_KEY` for LangSmith experiments.
