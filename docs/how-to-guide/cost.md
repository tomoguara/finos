# Cost

[← Back to the README](../../README.md)

What every query costs, how it is recorded, and how to reduce it without
losing quality. This guide covers what is priced, the price table, the
audit log, alerts and the budget, the `finos cost report` command, the
`--verbose` cost line, and the before/after method for optimizations.

## Contents

- [What a query costs](#what-a-query-costs)
- [What is and isn't priced](#what-is-and-isnt-priced)
- [The price table](#the-price-table)
- [Unpriced costs](#unpriced-costs)
- [The audit log](#the-audit-log)
  - [What a record holds](#what-a-record-holds)
  - [Why it holds no query text](#why-it-holds-no-query-text)
  - [Retention and rotation](#retention-and-rotation)
  - [When a record can't be written](#when-a-record-cant-be-written)
- [Alerts and the daily budget](#alerts-and-the-daily-budget)
- [`finos cost report`](#finos-cost-report)
- [The verbose cost line](#the-verbose-cost-line)
- [The before/after method](#the-beforeafter-method)

## What a query costs

Every query makes several model calls, and each one that reaches OpenAI
costs money. A call's cost is its input tokens times the model's input
price, plus its output tokens times the output price, per million tokens.
The tokens are the ones the provider reports for that call
(`usage_metadata`); nothing is estimated except the query embedding (below).

A query's cost is the sum over every call made to answer it:

| Call | Provider (shipped) | Cost |
| --- | --- | --- |
| moderation (input guard) | OpenAI | free, listed as $0 |
| injection classifier (input guard) | OpenAI `gpt-4o-mini` | priced |
| supervisor | the chat provider | priced on OpenAI, $0 local |
| query embedding (policy only) | the chat provider | priced on OpenAI (estimated tokens), $0 local |
| agent (policy, account if found, escalation) | the chat provider | priced on OpenAI, $0 local |

The two guard calls are also reported as a **guard subtotal**, so the price
of the guardrails is visible on its own. On the shipped local configuration
with an `OPENAI_API_KEY`, the classifier is the query's whole money cost
(about $0.00003). On OpenAI, a policy query costs roughly $0.0002, with the
guards about a tenth of it.

## What is and isn't priced

- **Local (Ollama) calls cost $0**, whatever the model tag; they need no
  price entry. Their real cost is time and hardware, which this project
  reports as latency, not money.
- **Moderation is free.**
- **The query embedding** reports no token usage, so its tokens are
  estimated as characters ÷ 4 and marked `estimated` in the record. At
  $0.02 per million tokens, the estimate can't move a total.
- **The evaluation judge** is not part of any query's cost. It is
  evaluation overhead, reported per experiment on its own line (see
  [Evaluation](evaluation.md#cost-in-results)).
- **The index build**, which embeds the whole corpus the first time after a
  corpus or chunking change, is setup and is not charged to that query.

## The price table

Prices live in `config.toml`, in USD per million tokens, with the date they
were checked:

```toml
[cost]
prices_as_of = "2026-11-20"

[cost.prices."gpt-4o-mini"]
input_per_1m = 0.15
cached_input_per_1m = 0.075
output_per_1m = 0.60

[cost.prices."text-embedding-3-small"]
input_per_1m = 0.02
```

- Every cost line and report prints `prices as of <date>`, so a stale table
  is visible. When OpenAI's prices change, update the entries and the date
  together, from [OpenAI's pricing page](https://developers.openai.com/api/docs/pricing).
- `cached_input_per_1m` applies to input tokens the provider reports as
  cached. This system's prompts are below OpenAI's caching minimum, so it
  rarely applies.
- A dated snapshot name (`gpt-4o-mini-2024-07-18`) uses its base model's
  entry. No other name is guessed.

## Unpriced costs

An OpenAI model with no price entry (for example after `--set
openai.model=gpt-4.1-nano`) is **unpriced**: its cost is `null`, never 0,
and so is the query's. One line names it on stderr, once per process:

```text
cost: no price for gpt-4.1-nano; add [cost.prices."gpt-4.1-nano"] to config.toml
```

A chat call whose provider reports no usage is unpriced the same way. A
report counts unpriced queries separately and leaves them out of the cost
totals, so a missing price can never look like a cheap query.

## The audit log

Every query appends one JSON line to `logs/audit_log.jsonl` (the path is
`[cost] audit_log_path`, relative to the repository root, and `logs/` is
git-ignored). Every entry point writes it: the CLI, library callers (entry
`api`), evaluation runs (entry `eval`), and live tests (entry `live-test`).
Set `[cost] audit_log = false` to stop writing it; the cost line and
alerts still work.

### What a record holds

One record per root run (`support_query`, `policy_query`, `account_query`,
`escalation_query`, `policy_search`, `supervisor_classify`):

| Field | Holds |
| --- | --- |
| `ts`, `level` | UTC time; `INFO`, `WARNING` (an alert), or `ERROR` (the query raised) |
| `root`, `entry`, `trace_id` | which entry point, and the LangSmith trace (`null` when untraced) |
| `provider`, `chat_model`, `intent`, `crisis` | what answered, and how it was routed |
| `guard` | the strongest guard decision, and each guard's decision and category (`injection`, `investment_advice`), never the matched text |
| `calls` | each call's role, provider, model, tokens, cost, and whether its tokens are estimated |
| `input_tokens`, `output_tokens`, `cost_usd`, `guard_cost_usd`, `unpriced` | the totals |
| `latency_ms`, `config` | the time, and the configuration metadata the trace's root carries (models, retrieval settings, prompt hashes, index fingerprint, version) |
| `query_chars`, `response_chars` | the lengths of the question and the reply |
| `alerts`, `error` | `["per_query"]` for a costly query; the exception type if the query failed |

### Why it holds no query text

A support question can hold an account ID, a name, or, for a customer in
crisis, very sensitive words, and an audit trail is kept for years (5–7 in
many jurisdictions). So the record holds **no query or reply text in any
form**:

- not the raw text;
- not a masked copy (masking covers Social Security data only);
- not a hash (a short question can be found by hashing guesses, and a
  stable hash would link one customer's questions together).

The `trace_id` links a record to its trace in LangSmith, where the masked
text lives under LangSmith's own retention settings. This is what lets one
file serve as a long audit trail and still follow data minimization. The
offline tests run every dataset question through the log and check that no
question, account ID, holder name, or record value appears.

### Retention and rotation

Retention is documented, not enforced. A record is about 1–2 KB, so 10,000
queries make 10–20 MB. To rotate by hand, move the file aside (the next
query starts a new one), for example
`mv logs/audit_log.jsonl logs/audit_log-2026-11.jsonl`, and keep or archive
the old file as your audit policy requires. `finos cost report` reads only
the current file.

Appends from one process are serialized with a lock, so the evaluation's
threads never break a line. Separate processes (two terminals) append whole
lines to a local file in practice; the log assumes a local disk, not a
network filesystem. A regulated deployment would ship records to a log
service instead (Phase 2).

### When a record can't be written

The query still answers, with the same exit code, and one line goes to
stderr, once per process:

```text
audit: not written (PermissionError)
```

This is fail-open: a support system that stops answering because a log
file is full is a worse failure here. A strict audit regime would fail
closed; that is a deployment decision for Phase 2.

## Alerts and the daily budget

```toml
[cost]
per_query_alert_usd = 0.01
daily_budget_usd = 1.0
```

- **Per query**: a query above `per_query_alert_usd` writes
  `cost: query $0.012300 above the $0.010000 alert` on stderr, is recorded
  at level `WARNING` with `alerts: ["per_query"]`, and its trace's root is
  tagged `cost:alert`. A typical OpenAI query costs about 1/50 of the
  default, so the alert means something unusual (a runaway prompt, a
  misconfigured model). An unpriced query never alerts.
- **Daily**: today's (UTC) audited cost against `daily_budget_usd`, checked
  by `finos cost report` and at the end of `finos eval run`: `warning` at
  80%, `alert` past 100%. A single query does not scan the log.
- **A query is never refused for budget.** Refusing would fail closed on a
  cost signal, and a support system that stops answering a customer in
  crisis is a worse failure than overspending.

## `finos cost report`

Summarizes the audit log per intent and per provider. It calls no model and
needs no key.

```console
$ uv run finos cost report --since 2026-11-18
prices as of 2026-11-20; budget: ok: $0.000482 of $1.000000 today (0%, 2026-11-20 UTC)
queries: 3 (all entries but eval, live-test; 2026-11-18 to now UTC)
intent           provider  queries  total cost   mean cost  guards  in tok  out tok  p50 ms  p95 ms  unpriced  blocked
account_status   local           1   $0.000026   $0.000026    100%     830       65   41200   41200         0        0
policy           openai          2   $0.000482   $0.000241     11%    1120      125    1950    2310         0        0
```

- `--since DATE` and `--until DATE`: UTC days, inclusive (`YYYY-MM-DD`). An
  invalid date exits 2.
- `--entry NAME` (repeatable): only records from that entry point. By
  default, `eval` and `live-test` traffic is left out, so the report shows
  real use; `--entry eval` shows evaluation traffic.
- `guards` is the guard calls' share of the cost; `unpriced` counts queries
  whose cost is unknown (left out of the cost columns); `blocked` counts
  queries a guard blocked (they report as intent `policy`, H3's blocked
  state).
- `--json` prints the same as one object, with `prices_as_of`, the budget
  status, and one row per intent and provider.
- A missing log is an empty report (exit 0). An unreadable line is skipped
  and counted on stderr.

This is the per-provider p50/p95 latency from real traffic; experiments
report the same numbers per dataset ([Evaluation](evaluation.md#cost-in-results)).

## The verbose cost line

With `--verbose`, every model command ends with one cost line after the
timing lines:

```text
debug: guards: 640 ms, 152+1 tokens
debug: classify_intent: 312 ms, 98+3 tokens
debug: account_agent: 655 ms, 410+24 tokens
debug: total: 1.76 s
debug: cost: $0.000023 (660+28 tokens, 4 calls; guards $0.000023; prices as of 2026-11-20)
```

- `guards:` is the input guards' time and the classifier's tokens. It
  appears only when a guard made a model call.
- The cost line has the total, the tokens and number of calls (moderation
  and the embedding included), the guard subtotal, and the price date. An
  unknown cost reads `cost: unpriced (<model> has no price; ...)`.
- The same totals (`cost_usd`, `guard_cost_usd`, `input_tokens`,
  `output_tokens`) are in the trace root's metadata, so LangSmith can filter
  by them. LangSmith computes its own cost for OpenAI runs, and the two
  should agree. This system's number is the one to use: it works with
  tracing off and covers the local provider.

## The before/after method

Every saving trades against quality: fewer chunks can drop the fact the
answer needed, and a cheaper setting can route worse. So an optimization is
measured, not assumed:

1. **Baseline**: run each dataset once and save the result.

   ```sh
   uv run finos eval run --dataset policy --repetitions 1 --json > baseline-policy.json
   ```

2. **Change one setting** with `--set`, and run the same dataset:

   ```sh
   uv run finos eval run --dataset policy --repetitions 1 --set policy.top_k=2 --json > top_k_2-policy.json
   ```

3. **Compare**: each metric, the gates, cost per output, and latency,
   before and after:

   ```sh
   uv run finos eval compare baseline-policy.json top_k_2-policy.json
   ```

4. **Adopt or revert** against the quality floor. An optimization is
   adopted only if:
   - every gate passes on `routing`, `policy`, `account`, `escalation`, and
     `guardrails`;
   - correctness and empathy stay within 0.05 of the baseline;
   - and cost per query or p95 latency improves.

The candidates measured in Hardening 4 are thinking mode off (`--set
ollama.reasoning=false`), `top_k` 2, `chunk_size` 500 (with
`chunk_overlap` 50), and `num_ctx` 8192 (latency only). Their results are in
[Testing](testing.md). A shipped default changes only for one that passes.
See [Setup and configuration](setup-and-configuration.md#local-model-tuning)
for the two Ollama keys.
