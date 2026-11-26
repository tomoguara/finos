# Debugging with traces

[← Back to the README](../../README.md)

A wrong answer can come from routing, retrieval, the context, or the
model. Each request to the support system is traced in LangSmith as one
named run tree, so a single trace shows which of those steps went wrong.
This guide covers what each run shows, how to find a trace, a four-step
workflow, three worked cases from the recorded baselines, and what the
traces may contain.

Tracing needs a LangSmith API key in `.env` (`LANGCHAIN_API_KEY` or
`LANGSMITH_API_KEY`) and `[langsmith] tracing = true` in `config.toml`,
which is the default. See
[Setup and configuration](setup-and-configuration.md#tracing).

## Contents

- [The run tree](#the-run-tree)
- [Tags and metadata](#tags-and-metadata)
- [Finding a trace](#finding-a-trace)
- [The four-step workflow](#the-four-step-workflow)
- [Worked cases](#worked-cases)
  - [Fee-waiver routing](#fee-waiver-routing)
  - [The freeze reason](#the-freeze-reason)
  - [The echoed amount](#the-echoed-amount)
- [Timings and tokens without LangSmith](#timings-and-tokens-without-langsmith)
- [SSN masking and its limits](#ssn-masking-and-its-limits)
- [No key, and sampling](#no-key-and-sampling)

## The run tree

`finos supervisor ask` (and `finos.main.ask`) produces one trace:

```text
support_query                         root: tags, metadata, the late intent tag
  support_graph                       LangGraph's run
    classify_intent                   the supervisor node
      supervisor_llm                  prompt and model: the raw reply
      normalize_intent   (parser)     raw reply in; intent and fallback out
    policy_agent                      exactly one specialist runs
      policy_retrieval   (retriever)  query in; ranked chunks with scores out
      policy_llm                      prompt (with the context) and reply
    account_agent
      account_resolution (tool)       query in; outcome and account IDs out
      account_llm                     found accounts only: record and reply
    escalation_agent
      escalation_llm                  prompt and the raw reply
      escalation_assembly (parser)    raw reply in; used_fallback out
```

| Run | What it shows | What a problem there looks like |
| --- | --- | --- |
| `supervisor_llm` | the model's raw classification reply | a wrong category name |
| `normalize_intent` | the intent the reply became, and `fallback: true` when it named no category and became `policy` | a messy reply, or a fallback |
| `policy_retrieval` | each retrieved chunk as a document: text, `source`, `chunk_index`, and `score`, best first | the chunk with the fact is missing or ranked low |
| `policy_llm` | the system prompt with the formatted context, and the reply | the context holds `$35` but the reply says `$25` |
| `account_resolution` | `found`, `not_found`, `no_id`, or `multiple_ids`, and the IDs; never the record | the wrong ID was extracted |
| `account_llm` | the record JSON the model saw (SSN masked) and its reply | the reply volunteers a field or invents a value |
| `escalation_llm` | the empathetic reply before the contact block | an amount or policy repeated back |
| `escalation_assembly` | whether the fallback message replaced an empty reply | `used_fallback: true` |

The standalone commands produce smaller trees with the same step names:

| Command | Root | Beneath it |
| --- | --- | --- |
| `finos policy ask` | `policy_query` | `policy_retrieval`, `policy_llm` |
| `finos policy search` | `policy_search` | `policy_retrieval` |
| `finos account ask` | `account_query` | `account_resolution`, `account_llm` (found only) |
| `finos escalation ask` | `escalation_query` | `escalation_llm`, `escalation_assembly` |
| `finos supervisor classify` | `supervisor_classify` | `supervisor_llm`, `normalize_intent` |

Building or rebuilding the policy index is never traced, so a first query
after a config change doesn't fill its trace with embedding calls.

Trace through an entry point: the CLI, `finos.main.ask`, or the
`ask_policy`, `ask_account`, and `ask_escalation` helpers. Calling a node
function such as `policy_agent(state)` directly, with tracing on, uploads
through LangSmith's default client, which does **not** mask SSN data.

## Tags and metadata

Every root run carries:

- **`entry:<point>`**: `supervisor-ask`, `supervisor-classify`,
  `policy-ask`, `policy-search`, `account-ask`, `escalation-ask`,
  `live-test`, or `api` for a library call outside the CLI.
- **`provider:<name>`**: `ollama` or `openai`.
- **`intent:<intent>`** on `support_query` (and `supervisor_classify`),
  added once the query has been routed.

The `exp:*` and `eval-*` prefixes are reserved for the evaluation phase.

The root's metadata records the configuration the answer came from:
`provider`, `chat_model`, `embedding_model`, `temperature`, `chunk_size`,
`chunk_overlap`, `top_k`, `collection`, `index_fingerprint` (`"none"`
before the first build), `prompt_versions` (the first 8 hex characters of
each system prompt's SHA-256), and `finos_version`. Live tests add
`test_id`. Tags and metadata never hold the query, account IDs, names, or
record values.

From Python, pass extra tags and metadata with `config`:

```python
from finos.graph import build_support_agent
from finos.main import ask

state = ask(
    build_support_agent(),
    "What is the overdraft fee?",
    config={"tags": ["my-experiment"], "metadata": {"note": "chunk test"}},
)
```

`config` never changes the returned state.

## Finding a trace

- **From the command line:** add `--verbose`. After the result, stderr
  names the trace:

  ```text
  debug: trace: 01a1e308-fe0f-7201-90f2-2bc9870ce72f (project finos)
  ```

  Paste the ID into the LangSmith search box of the `finos` project.
- **By tag:** in the project's runs table, filter on a tag, for example
  `intent:account_status` with `entry:supervisor-ask`, or
  `provider:openai`.
- **Live test runs:** run `uv run pytest -m live -v -rxX`, then filter on
  `entry:live-test`. Each root's `test_id` metadata names the test, for
  example `tests/test_account.py::test_live_frozen_account`.

## The four-step workflow

| Step | In LangSmith | From the CLI |
| --- | --- | --- |
| 1. Find the trace | search the trace ID, or filter by tag | `--verbose` prints the trace ID |
| 2. Check the routing. A wrong intent is the most common failure: fix the supervisor prompt | `supervisor_llm` (raw reply) and `normalize_intent` (intent, `fallback`) | `finos supervisor classify -q ... -v` |
| 3. Check retrieval. Does a chunk hold the fact (say, `$35`)? If not, retrieval failed | `policy_retrieval`: the documents, sources, and scores | `finos policy search -q ... --json` |
| 4. Check the model's input and output. `$25` in the reply with `$35` in the context is a hallucination | `policy_llm`, `account_llm`, or `escalation_llm` | `finos policy ask -q ... -v` (the context), `finos account ask -q ... -v` (the record), `finos escalation ask -q ... -v` (the raw reply) |

Stop at the first step that's wrong: everything after it worked from bad
input.

## Worked cases

Each of these reproduces at the recorded baselines (see
[Testing](testing.md)), and each fails at a different step.

### Fee-waiver routing

```sh
uv run finos supervisor ask -q "Does ACC-12345 qualify for the fee waiver?" -v
```

The answer explains the Premium Checking waiver conditions but doesn't say
whether ACC-12345 meets them. In the trace:

- `supervisor_llm` replied `policy`, and `normalize_intent` shows
  `{"intent": "policy", "fallback": false}`: a clean route, so this is not a
  normalization problem.
- The root carries `intent:policy`, and only `policy_agent` ran.

The answer needs both the account record and the policy, and the graph
routes each query to one specialist. This is the known single-route
limitation (multi-hop), not a bug in any one step.

### The freeze reason

With the previous local default, `qwen3-coder-next:q8_0-gpu` (set it as `[ollama] model`
to reproduce; the shipped `qwen3.8:27b-q8_0` follows the rule):

```sh
uv run finos account ask -q "What is the balance on ACC-11111?" -v
```

The question asks only for the balance, but the reply quotes why the
account is frozen. In the trace:

- `account_resolution` shows `{"outcome": "found", "account_ids":
  ["ACC-11111"]}`: resolution worked.
- `account_llm`'s input holds the record, including `freeze_reason`, and
  its output quotes it. The prompt says to quote it only when asked why,
  so this is the model not following a prompt rule. `gpt-4o-mini` follows
  it.

### The echoed amount

Also with `qwen3-coder-next:q8_0-gpu`:

```sh
uv run finos escalation ask -q 'You charged me $35 twice and I am furious!' -v
```

The reply repeats `$35`, which the escalation prompt forbids. In the
trace, `escalation_llm`'s output (the raw reply) already contains the
amount, and `escalation_assembly` shows `used_fallback: false`: code only
appended the contact block. The model broke the rule; assembly didn't add
it.

## Timings and tokens without LangSmith

`--verbose` also prints where the time went, with or without tracing:

```text
debug: classify_intent: 312 ms, 98+3 tokens
debug: policy_agent: 1077 ms (retrieval 41 ms), 1240+85 tokens
debug: total: 1.41 s
```

There is one line per graph node (or one for a standalone command's root),
with the retrieval time on the policy route and the prompt+completion
tokens of its model call. Tokens read `n/a tokens` when the provider
reports no usage, and are left out when the step made no model call.
`total` is the command's wall time.

## SSN masking and its limits

Every run's inputs and outputs are masked before upload. What is replaced
with `[REDACTED:ssn]`:

- the value of any `ssn_last4` field: a dict key, JSON (`"ssn_last4":
  "6789"`), or a Python repr (`'ssn_last4': '6789'`);
- every `ssn_last4` value in `data/mock_accounts.json`, wherever it
  appears as a standalone number (no digit directly before or after), so a
  reply that leaks `6789` is masked too;
- any full SSN, three digits, two digits, and four digits joined by
  hyphens (`123-45-6789`).

Amounts (`$1,500`, `12450.75`), years, dates, and account IDs
(`ACC-12345`) are not touched.

Limits:

- Masking applies to traces only. stdout, `--json`, and the `-v` record
  dump on stderr show the local, unmasked data.
- Only the values in the records file are known. An SSN fragment written
  some other way (spelled out, or with spaces) is not masked.
- A standalone known value is masked wherever it appears, even when it
  means something else, such as a `6789` in a policy document.
- If the records file is missing or invalid, field and full-SSN masking
  still apply; known-value masking doesn't.
- Direct node-function calls outside an entry point are not masked (see
  [The run tree](#the-run-tree)).
- Holder names, balances, and transactions are uploaded. All data in this
  repository is fictional. Response redaction is the guardrails phase's
  job.

## No key, and sampling

With tracing on and no LangSmith key, tracing turns itself off and every
model-calling command writes one line on stderr:

```text
tracing: off (no LANGSMITH_API_KEY or LANGCHAIN_API_KEY set)
```

The answers are unchanged, and `-v` reports `trace: none (tracing off)`
with the timing lines.

`[langsmith] sampling_rate` (shipped at `1.0`) traces a fraction of
requests. Below `1.0`, the `-v` trace line still prints an ID, with a note
that the trace may not be recorded:

```text
debug: trace: 01a1e308-... (project finos, sampling 0.25: may not be recorded)
```

Set it back to `1.0` while debugging a specific query.
