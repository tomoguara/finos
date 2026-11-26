# Setup and configuration

[← Back to the README](../../README.md)

Installing the project, choosing between the local Ollama and OpenAI
providers, and controlling LangSmith tracing.

## Contents

- [Setup](#setup)
- [Choosing a provider](#choosing-a-provider)
- [Tracing](#tracing)
  - [What leaves the machine](#what-leaves-the-machine)
  - [No key, no tracing](#no-key-no-tracing)
  - [Sampling](#sampling)
  - [Exit can wait for uploads](#exit-can-wait-for-uploads)
- [Evaluation](#evaluation)
- [Guardrails](#guardrails)
- [Cost](#cost)

## Setup

```sh
uv sync
cp .env.example .env
```

`uv sync` installs the exact versions in `uv.lock`. Then edit `.env` and
fill in the keys you actually need — none of them are required to run the
test suite:

| Variable            | Needed when                                    |
| ------------------- | ---------------------------------------------- |
| `OPENAI_API_KEY`    | the OpenAI provider is selected, the evaluation judge is OpenAI, or the guardrails' model layers are on (all defaults; see [Evaluation](#evaluation) and [Guardrails](#guardrails)) |
| `LANGCHAIN_API_KEY` | you want traces in LangSmith; without it, tracing turns itself off ([details](#no-key-no-tracing)) |

`.env` is git-ignored and holds **secrets only**. Every non-secret setting
lives in `config.toml`, which is committed on purpose so that model and
host changes are reviewable.

## Choosing a provider

The shipped default is a **local Ollama model**:

```toml
[llm]
use_local_ollama_model = true

[ollama]
model = "qwen3.8:27b-q8_0"
embedding_model = "qwen3-embedding:latest"
base_url = "http://localhost:11434"
```

The policy agent also needs the embedding model on the Ollama host that
`base_url` points at:

```sh
ollama pull qwen3-embedding:latest
```

One switch selects both the chat and the embedding model, so a local run
never needs an OpenAI key, and an OpenAI run uses `[openai]
embedding_model` (`text-embedding-3-small`).

A machine with no Ollama listening on `localhost:11434` will fail on the
first model call — construction itself makes no network request, so the
failure shows up at invoke time, not at import. If your Ollama runs on
another machine, point `base_url` at it. To use OpenAI instead, set:

```toml
[llm]
use_local_ollama_model = false
```

and put an `OPENAI_API_KEY` in `.env`. The OpenAI model is `[openai] model`
(default `gpt-4o-mini`), which is also what the lecture's cost and quality
figures assume, so use it when comparing against those numbers. To point at
a different Ollama host, change `[ollama] base_url` — leave off any `/v1`
suffix, since `ChatOllama` calls Ollama's native API.

### Local model tuning

Two optional `[ollama]` keys tune the local model. Both are unset in the
shipped config, so the model runs with its own defaults:

```toml
[ollama]
reasoning = false   # thinking mode off; true keeps it on and separates it
num_ctx = 8192      # context window in tokens
```

- `reasoning` must be `true` or `false`; `num_ctx` a whole number of at
  least 1. Anything else fails at load with the key named.
- They apply to every Ollama chat model in the process: the agents, and the
  judge or classifier when those are on Ollama.
- They exist to be measured, not guessed: try one with `finos eval run
  --set ollama.reasoning=false` (an unset optional key may be added by
  `--set`) and compare it to the baseline (see [Cost](cost.md#the-beforeafter-method)).
  A shipped value changes only after the variant passes the quality floor.

## Tracing

**Tracing is on by default**, under the LangSmith project `finos`, for every
request:

```toml
[langsmith]
tracing = true
project = "finos"
sampling_rate = 1.0
```

All three settings are required. They are applied to the process
environment when settings load, and they deliberately override anything
`.env` or the shell already set.

### What leaves the machine

Prompts, responses, retrieved chunks, and the account record the account
agent reads are sent to LangSmith. That holds even with the local Ollama
provider: the model runs locally, but the trace still leaves the machine.
All account data in this repository is fictional.

Before any run is uploaded, Social Security data is masked: the
`ssn_last4` field, every `ssn_last4` value in `data/mock_accounts.json`
(as a standalone number), and any full `ddd-dd-dddd` SSN become
`[REDACTED:ssn]`, in every run's inputs and outputs. Amounts, dates, and
account IDs are left as they are. See
[Debugging with traces](debugging-with-traces.md#ssn-masking-and-its-limits)
for the limits.

How long LangSmith keeps traces is a setting of your LangSmith account or
organization, not of this project.

Set `tracing = false` for any run that must stay on the machine.

### No key, no tracing

With `tracing = true` and neither `LANGSMITH_API_KEY` nor
`LANGCHAIN_API_KEY` in the environment or `.env`, tracing turns itself off
for the process. Every command that calls a model then writes one line to
stderr, with or without `--verbose`:

```text
tracing: off (no LANGSMITH_API_KEY or LANGCHAIN_API_KEY set)
```

stdout and the exit code are the same as with `tracing = false`. Commands
that call no model (`account lookup`, `account list`, `escalation contact`,
`supervisor graph`, `policy ingest`, and the `state` commands) never print
it. A command that fails still prints only its `Error:` line.

### Sampling

`sampling_rate` is the fraction of requests traced, from `0.0` to `1.0`.
`1.0` traces every request; `0.25` traces about one in four. A value
outside that range, or one that is not a number, fails with an error naming
`[langsmith] sampling_rate` and `config.toml`. Under a rate below `1.0`,
`--verbose` says the trace may not be recorded:

```text
debug: trace: 01a1e308-... (project finos, sampling 0.25: may not be recorded)
```

### Exit can wait for uploads

The LangSmith SDK uploads traces in the background and flushes them when
the process exits, so a short command waits for its uploads to finish. With
a slow or unreachable LangSmith, exit can take several seconds while the SDK
retries, and the SDK may log upload errors on stderr. The command's stdout
and exit code are unaffected. Set `tracing = false`, or remove the key, if
that delay gets in the way.

## Evaluation

`finos eval` measures answer quality with datasets, evaluators, and a judge
model (see [Evaluation](evaluation.md)). Its settings are required, like
`[policy]`:

```toml
[eval]
judge_provider = "openai"     # or "ollama"
judge_model = "gpt-4o-mini"
repetitions = 3               # runs per example; metrics are the mean

[eval.gates]
routing_accuracy = 0.95       # in-scope rows (known limitations excluded)
crisis_sentence = 1.0         # the minimum over crisis examples
faithfulness = 0.7
mrr = 0.8
```

- **The judge is separate from the chat model.** It follows
  `judge_provider`, not `use_local_ollama_model`, so a local generator is
  judged by an independent model. An OpenAI judge needs `OPENAI_API_KEY`
  in `.env` even when the chat model is local. Set
  `judge_provider = "ollama"` and a local `judge_model` to judge
  on-machine; when the judge and the chat model are the same model, results
  are marked self-judged.
- **Validation**: the thresholds must be numbers from 0.0 to 1.0,
  `repetitions` a whole number of at least 1, and `judge_provider`
  `openai` or `ollama`. Anything else fails with an error naming the
  setting and `config.toml`.
- The offline test suite never calls the judge.

## Guardrails

Every query passes input guards before any model runs, and every reply
passes output checks before it is returned (see [Guardrails](guardrails.md)).
The input layers are set in `[guardrails]`, which is required:

```toml
[guardrails]
input_regex = true            # free, offline
moderation = true             # OpenAI Moderation API
injection_classifier = true   # a small model that labels a query "safe" or "injection"
classifier_provider = "openai"
classifier_model = "gpt-4o-mini"
```

- **The two model layers need `OPENAI_API_KEY`**, even when the chat model
  is local. Without a key they switch off for the process, and every model
  command writes one line on stderr:

  ```text
  guardrails: moderation and injection_classifier off (no OPENAI_API_KEY)
  ```

  The regex still runs.
- **Fully local**: set `moderation = false` and `injection_classifier =
  false`; or set `classifier_provider = "ollama"` and a local
  `classifier_model` to keep the classifier on-machine (slower on a local
  model).
- **The output checks always run** and are not configurable.
- **Validation**: the three switches must be `true` or `false`, and
  `classifier_provider` `openai` or `ollama`.

## Cost

Every query's cost is computed from the tokens its model calls report and a
price table, and one line per query is appended to a local audit log (see
[Cost](cost.md)). The `[cost]` section is required:

```toml
[cost]
prices_as_of = "2026-11-20"           # printed with every cost line and report
audit_log = true                      # false stops writing the log
audit_log_path = "logs/audit_log.jsonl"  # relative to the repository root; git-ignored
per_query_alert_usd = 0.01            # a costlier query prints an alert
daily_budget_usd = 1.0                # checked by `finos cost report` and `finos eval run`

[cost.prices."gpt-4o-mini"]
input_per_1m = 0.15
cached_input_per_1m = 0.075
output_per_1m = 0.60

[cost.prices."text-embedding-3-small"]
input_per_1m = 0.02
```

- **Prices are USD per million tokens.** Each entry needs `input_per_1m`;
  `output_per_1m` and `cached_input_per_1m` are optional. Update the
  entries and `prices_as_of` together.
- **Unpriced models**: an OpenAI model with no entry (for example after
  `--set openai.model=...`) gets a cost of `null`, never 0, and stderr names
  it once. A dated snapshot such as `gpt-4o-mini-2024-07-18` uses the
  `gpt-4o-mini` entry.
- **Local calls cost $0** whatever the Ollama tag, so they need no entry.
  Moderation is free.
- **Validation**: `prices_as_of` must be an ISO date, `audit_log` `true` or
  `false`, the alert and budget positive numbers, and every price a
  non-negative number. A missing or invalid key fails at load, naming it.

