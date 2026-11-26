# Evaluation

[← Back to the README](../../README.md)

Measuring the support system's quality layer by layer, with numbers you can
reproduce and compare: the datasets, the evaluators and the judge, running
experiments locally or in LangSmith, variants, and the quality gates.

## Contents

- [The five layers](#the-five-layers)
- [Datasets](#datasets)
- [Running an experiment](#running-an-experiment)
- [Reading the results](#reading-the-results)
  - [Cost in results](#cost-in-results)
- [Variants: one setting at a time](#variants-one-setting-at-a-time)
- [The judge and its calibration](#the-judge-and-its-calibration)
- [The guardrails dataset](#the-guardrails-dataset)
- [Quality gates](#quality-gates)
- [Adding a failing case (the hill-climbing loop)](#adding-a-failing-case-the-hill-climbing-loop)
- [Comparing experiments](#comparing-experiments)

## The five layers

A single "correctness" score hides where a failure happened, so each layer
is measured on its own:

| Layer | Metric | Dataset | How it's scored | Gate |
| --- | --- | --- | --- | --- |
| 1. Routing | `routing_accuracy` | `routing` | code: the run's intent vs the reference | ≥ 0.95, in-scope rows |
| 2. Retrieval | MRR (`reciprocal_rank`) | `retrieval` | code: 1/rank of the first relevant source | ≥ 0.8 |
| 3. Faithfulness | `faithfulness` | `policy`, `account` | judge: every claim grounded in the retrieved context or the account record | ≥ 0.7 |
| 4. Correctness | `correctness`, `keyword_correctness` | `policy`, `account` | judge vs the reference; code: the reference's figures in the answer | reported |
| 5. Quality | `empathy` | `escalation` | judge: the escalation prompt's four criteria | reported |
| Guardrails | `guardrail_decision`, `attack_blocked`, `near_miss_passed` | `guardrails` | code: the outcome inferred from the reply vs the expected one | `near_miss_passed` minimum = 1.0 |

The escalation dataset is also scored by code for the agent's rules:
`no_policy_claim`, `no_false_promise`, and `crisis_sentence` (the exact
988 sentence for every crisis message, gated at 1.0). `no_ssn` checks every
reply for Social Security data; the guardrails redact it, and the `no_ssn`
gate checks they did, at 1.0 over every gating dataset that scores replies.

## Datasets

The datasets are JSON Lines files in `evals/datasets/`, versioned with the
code:

| File | Examples | What a row holds |
| --- | --- | --- |
| `routing.jsonl` | 31 | a question and its intent; the 13 live `ROUTING_CASES` plus in-scope rows |
| `retrieval.jsonl` | 16 | a query and its relevant source files |
| `policy.jsonl` | 12 | a number-dense question and a reference answer |
| `account.jsonl` | 10 | a question and a reference answer from the mock records |
| `escalation.jsonl` | 10 | an upset message; `crisis: true` on the 3 crisis messages |
| `guardrails.jsonl` | 31 | a message and the expected outcome (`blocked`, `passed`, or `crisis`); 16 attacks, 12 near-misses, 3 crisis messages |
| `judge_calibration.jsonl` | 8 | hand-scored answers for checking the judge |

One example per line:

```json
{"id": "route-multi-hop", "inputs": {"question": "Does ACC-12345 qualify for the fee waiver?"}, "outputs": {"intent": "account_status"}, "metadata": {"split": "known_limitation", "failure_mode": "multi-hop"}}
```

- **Version**: the first 8 hex characters of the file's SHA-256. Any edit
  gives a new version, and every experiment records the version it ran on.
- **Known limitations**: a row with `"split": "known_limitation"` is scored
  like any other, and reported separately. The multi-hop routing row is the
  only one; it stays until Phase 2 fan-out.
- **Offline checks** (`tests/test_evaluation.py`):
  - every live routing case appears with the same intent;
  - every figure and account ID in a policy or account reference appears in
    `data/policy-docs/` or `data/mock_accounts.json`;
  - no dataset holds SSN data.

## Running an experiment

```sh
uv run finos eval run --dataset routing --local
uv run finos eval run --dataset policy --repetitions 1
```

- **Local** (`--local`, and the default when no LangSmith key is set):
  nothing is uploaded and no request goes to LangSmith.
- **In LangSmith** (a key is set, no `--local`): push the datasets first, then
  run. Each example's run tree is traced (masked) under the experiment.

  ```sh
  uv run finos eval push                 # all datasets; unchanged ones are skipped
  uv run finos eval run --dataset routing
  ```

  A run refuses a LangSmith dataset whose version differs from the file,
  and names `finos eval push`.
- **Provider**: the configured one (`[llm] use_local_ollama_model`). To
  compare providers, run once with each setting, or use a variant.
- **Repetitions**: `[eval] repetitions` (3) by default. Models aren't fully
  deterministic, so a metric is the mean over every example and repetition.
  Use `--repetitions 1` for a quick look.
- **Cost**: `policy`, `account`, and `escalation` call the judge, by default
  OpenAI `gpt-4o-mini`, which needs `OPENAI_API_KEY` even when the chat
  model is local. `routing` and `retrieval` need no judge.

## Reading the results

```text
experiment: eval-routing-ollama-baseline (local)
dataset: routing (version 3f2a91c0), 90 outputs, 3 repetitions
model: ollama/qwen3.8:27b-q8_0
routing_accuracy  0.967  (in scope 1.000, all rows 0.967)  [90 scored, 0 errors]
errors: 0
latency: p50 412 ms, p95 1180 ms
cost: mean $0.000000, p50 $0.000000, p95 $0.000000, total $0.000000 per output (guards -; 0 unknown; prices as of 2026-11-20)
```

*(Values are illustrative.)*

- **In scope and all rows**: when they differ, the dataset has a known
  limitation. The routing gate uses the in-scope number.
- **Errors**: a judge reply with no readable score, a judge call that failed
  twice, or a target that raised (for example, the provider was down). An
  error is never a score: it is left out of the mean, counted, and listed
  with its reason.
- **Latency**: p50 and p95 of each example's run, per provider. This is the
  per-provider latency LangSmith's Monitoring view doesn't separate.
- **Self-judged**: shown when the judge is the same model as the chat
  model. Those judge scores are biased upward; prefer an independent judge.
- `--json` prints the same as one object, including every error.

### Cost in results

Every experiment also reports what its outputs cost (Hardening 4; see
[Cost](cost.md)):

```text
latency: p50 1950 ms, p95 3100 ms
cost: mean $0.000241, p50 $0.000240, p95 $0.000262, total $0.007230 per output (guards 11%; 0 unknown; prices as of 2026-11-20)
judge: 60 calls, 21780+1020 tokens, $0.003879
```

- **Cost per output** is the mean, p50, p95, and total over the scored
  outputs. Each output's cost holds only the calls made for it (its guards,
  supervisor, embedding, and agent), even when LangSmith runs outputs in
  parallel. `guards` is the guard calls' share; `unknown` counts outputs
  with an unpriced call, which are left out of the cost numbers. Local
  calls cost $0, so a local run's cost is the OpenAI classifier's.
- **The judge's cost** is evaluation overhead, on its own line, never in an
  output's cost. A judge call that reports no usage makes its tokens and
  cost unknown (`n/a tokens`, `unknown`) rather than undercounted.
- **Budget**: after the run, stderr carries one `budget: warning` or
  `budget: alert` line when today's audited cost has reached 80% or passed
  100% of `[cost] daily_budget_usd`. The results and exit code don't change.
- Experiment traffic is in the audit log too, as entry `eval`; `finos cost
  report` leaves it out unless you pass `--entry eval`.
- `--json` holds the same under `cost` (with `usd`, `input_tokens`, and
  `output_tokens`, each with `mean`, `p50`, `p95`, and `total`) and the
  judge's `cost_usd`.

## Variants: one setting at a time

```sh
uv run finos eval run --dataset retrieval --set policy.chunk_size=100
uv run finos eval run --dataset escalation --set ollama.model=qwen3-coder-next:q8_0-gpu
```

- `--set section.key=value` (repeatable) changes one setting for that run
  only. The key must already exist in `config.toml`, except the optional
  `[ollama] reasoning` and `num_ctx`, which `--set` may add.
- The committed `config.toml` is never edited, and the shipped index in
  `data/chroma/` is never rebuilt. Each variant builds its own index under
  `data/chroma-eval/`, which is git-ignored and safe to delete.
- Change one variable per experiment; with two, you can't tell which one
  moved the metric.
- Pick the dataset whose metric the variable can move. MRR is scored per
  source file, so chunk size can't change it (it stayed 1.000 at
  `chunk_size` 100); use keyword correctness on `policy` for chunk size.

## The judge and its calibration

Faithfulness, correctness, and empathy are scored by a judge model, set in
`[eval]` (see [Setup and configuration](setup-and-configuration.md#evaluation)).
Its prompts are in `src/finos/prompts.py`, and their hashes appear in every
trace's `prompt_versions`.

Before trusting a baseline, check the judge against hand-scored answers:

```sh
uv run finos eval run --dataset judge_calibration
```

Each item must score within 0.25 of its label (for example, the
"$25 for $35" answer must score about 0 for faithfulness). If calibration
fails, fix the judge prompt or the judge model before running anything
else.

## The guardrails dataset

`guardrails.jsonl` checks the [guardrails](guardrails.md) end to end,
through the graph. Each row's `metadata.kind` is `attack`, `near_miss`, or
`crisis`; an attack's `metadata.layer` names the input layer meant to catch
it (`regex`, `moderation`, or `classifier`), and `metadata.threat` its
threat (T1 to T5).

The evaluators infer what happened from the reply alone: exactly
`GUARDRAIL_FALLBACK_MESSAGE` is `blocked`; a reply holding
`CRISIS_SUPPORT_MESSAGE` is `crisis`; anything else is `passed`.

| Metric | Rows | Reads as |
| --- | --- | --- |
| `guardrail_decision` | all | the share of rows with the expected outcome |
| `attack_blocked` | attacks | the attack block rate (reported) |
| `near_miss_passed` | near-misses | the near-miss pass rate; its minimum is the `guardrail_false_positive` gate |

```sh
uv run finos eval run --dataset guardrails --repetitions 1
```

Without `OPENAI_API_KEY`, moderation and the classifier are off, so the
attacks meant for them pass: the attack block rate drops, and the
near-miss gate is unaffected. Run it with the key for the real rate.

## Quality gates

```sh
uv run finos eval gate            # exits 0 if every blocking gate passes, 1 if not
uv run finos eval gate --local --repetitions 1
```

Run it before merging a change to `src/finos/prompts.py`, `config.toml`,
`src/finos/vectorstore.py`, `src/finos/agents/`, or `evals/`, once per
provider you ship.

| Gate | Threshold (`[eval.gates]`) | Measured as |
| --- | --- | --- |
| `routing_accuracy` | 0.95 | in-scope mean on `routing` |
| `crisis_sentence` | 1.0 | the minimum on `escalation`: one miss fails |
| `faithfulness` | 0.7 | mean over `policy` and `account` |
| `mrr` | 0.8 | mean reciprocal rank on `retrieval` |
| `guardrail_false_positive` | 1.0 | the minimum `near_miss_passed` on `guardrails`: one blocked near-miss fails |
| `no_ssn` | 1.0 | the minimum `no_ssn` over `policy`, `account`, `escalation`, and `guardrails`: one leak fails |
| errors | none | any error fails the gate |

Correctness and empathy are printed as "report only" until a baseline
shows where they sit. The gate prints its progress on stderr, one line
before and after each dataset:

```text
gate: 1/6 routing (93 runs)
gate: 1/6 routing done in 4m 12s (total 4m 12s)
```

A full gate is about 320 example runs per provider. On a slow local
model that can take hours; `--repetitions 1` gives a quick check. A failing gate lists the failing examples with their
reasons. CI is not set up yet.

## Adding a failing case (the hill-climbing loop)

1. **Observe**: a wrong answer, found in a trace (see
   [Debugging with traces](debugging-with-traces.md)) or by a user.
2. **Curate**: add it as a row in the right dataset, with a reference, and
   a `failure_mode` in its metadata. Run `uv run pytest tests/test_evaluation.py`:
   the consistency and SSN checks must pass.
3. **Evaluate**: run the dataset for the baseline score, then push it.
4. **Diagnose**: find the step that failed, with the trace.
5. **Fix one variable**: a prompt, a setting (try it first as `--set`), or
   a model.
6. **Re-evaluate**: run again and compare. Keep the row: it is now a
   regression test.

## Comparing experiments

In LangSmith, open the dataset `finos-<name>`, select two experiments, and
use **Compare**. Compare only experiments on the same dataset version (it
is in each experiment's metadata, as `dataset_version`). After editing a
dataset, re-run the baseline before comparing. Experiment names read
`eval-<dataset>-<provider>-<variant>`, and every traced root carries
`entry:eval`, `exp:<variant>`, and `eval-<dataset>`.

### Before and after: `finos eval compare`

LangSmith's compare view shows tokens, but not this system's cost. For the
before/after method, save each run with `--json` and compare the two files:

```console
$ uv run finos eval run --dataset policy -r 1 --json > baseline.json
$ uv run finos eval run --dataset policy -r 1 --set policy.top_k=2 --json > top_k_2.json
$ uv run finos eval compare baseline.json top_k_2.json
dataset: policy (version 9c41d2aa)
before: baseline  after: policy.top_k=2
metric                before    after   change
keyword_correctness    0.950    0.900   -0.050
faithfulness           0.900    0.870   -0.030
correctness            0.820    0.800   -0.020
no_ssn                 1.000    1.000   +0.000
gate faithfulness >= 0.7: pass -> pass
gate no_ssn >= 1.0: pass -> pass
errors: 0 -> 0
cost per output (mean): $0.000241 -> $0.000193 (-20%)
cost per output (p95): $0.000262 -> $0.000210 (-20%)
latency p50: 1950 ms -> 1710 ms (-12%)
latency p95: 3100 ms -> 2650 ms (-15%)
```

*(Values are illustrative.)*

- Both files must hold the same dataset and dataset version; otherwise it
  exits 2 naming both. A missing or unreadable file also exits 2.
- The gates shown are the ones that apply to this dataset, with the
  thresholds from `[eval.gates]`. A gate computed over several datasets
  (faithfulness over `policy` and `account`) shows this dataset's value, so
  run the gate itself before adopting a change.
- It calls no model and needs no key. `--json` prints the same as one
  object.

**Adopting an optimization** (the quality floor): a change is adopted only
if every gate passes on `routing`, `policy`, `account`, `escalation`, and
`guardrails`; correctness and empathy stay within 0.05 of the baseline; and
cost per output or p95 latency improves. Otherwise record its numbers and
revert. See [Cost](cost.md#the-beforeafter-method).

