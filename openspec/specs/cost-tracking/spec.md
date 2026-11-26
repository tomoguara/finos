# cost-tracking Specification

## Purpose

Computes what every query costs from the tokens its model calls report and a committed price table, records one audit line per query that holds no customer content, and alerts on a costly query or a spent daily budget without ever changing an answer.

## Requirements

### Requirement: Calls are priced from a dated price table
The system SHALL price each chat and embedding call from the configured price table: input tokens times the model's input price per million, plus output tokens times its output price per million, in USD. Cached input tokens, when reported and when the model has a cached-input price, SHALL be priced at that price. Every cost report and cost line SHALL state the table's `prices_as_of` date.

#### Scenario: Priced OpenAI call
- **WHEN** a `gpt-4o-mini` call reports 1,000 input and 100 output tokens with prices $0.15 and $0.60 per million
- **THEN** its cost is $0.00021

#### Scenario: Cached input
- **WHEN** a call reports 2,000 input tokens of which 1,024 were cached, and the model has a cached-input price
- **THEN** the 1,024 cached tokens are priced at the cached-input price and the rest at the input price

### Requirement: An unpriced or unmeasured call is unknown, never zero
A call to an OpenAI model with no price entry, or a chat call that reports no token usage, SHALL have a cost of `null`, and so SHALL the query that holds it. The unpriced model SHALL be named once per process in one stderr line. Cost SHALL NOT be reported as 0 for such a call.

#### Scenario: Model with no price
- **WHEN** a query runs with `--set openai.model=gpt-4.1-nano` and no price entry for that model
- **THEN** the query's cost is `null`, its record lists `gpt-4.1-nano` as unpriced, and stderr names the model once

#### Scenario: Call without usage
- **WHEN** a chat call returns no token usage
- **THEN** that call's cost and the query's cost are `null`

### Requirement: Local model calls cost nothing in API money
Every call to the local (Ollama) provider SHALL cost $0, whatever its model tag, without a price entry, and SHALL be labeled `local` in cost reports.

#### Scenario: Local query with the classifier on
- **WHEN** a policy query runs on the local provider with the OpenAI injection classifier enabled
- **THEN** the query's cost equals the classifier call's cost, and the local calls cost $0

### Requirement: A query's cost covers every call made to answer it
A query's cost SHALL be the sum over the calls made inside its root run: the input guards' model calls, the supervisor, the query embedding, and the agent. The guard calls SHALL also be reported as a separate guard subtotal. Moderation SHALL be listed as a call priced at $0. The evaluation judge and the policy index build SHALL NOT count toward a query's cost.

#### Scenario: Guard subtotal
- **WHEN** a policy query runs on OpenAI with both model-based input guards enabled
- **THEN** the query lists moderation, the classifier, the supervisor, the embedding, and the policy agent, and its guard subtotal is the classifier's cost

#### Scenario: Index build excluded
- **WHEN** the first query after a corpus change rebuilds the policy index
- **THEN** the corpus embedding is not part of that query's cost

### Requirement: Embedding tokens are estimated and marked
An embedding call SHALL be counted with its tokens estimated from the text length (characters divided by four) and marked as estimated, because embedding providers report no usage.

#### Scenario: Query embedding
- **WHEN** a policy query embeds its 28-character question on OpenAI
- **THEN** its record holds one embedding call of 7 estimated tokens, marked estimated, priced at the embedding model's input price

### Requirement: Every root run writes one audit record
When the audit log is enabled, every root run SHALL append exactly one JSON line to the configured audit log path when it ends. The record SHALL hold the UTC timestamp, level, root name, trace ID or `null`, entry, provider, chat model, intent, guard outcome, crisis flag, each call's role, model, tokens, and cost, the totals, the guard subtotal, unpriced models, latency, the configuration metadata, query and reply lengths, and alerts.

#### Scenario: One line per query
- **WHEN** `finos supervisor ask --query "What is the overdraft fee?"` runs with the audit log enabled
- **THEN** the audit log gains exactly one line, whose root is `support_query`, entry `supervisor-ask`, intent `policy`, and whose calls and totals match the query's

#### Scenario: Audit log disabled
- **WHEN** the same command runs with `[cost] audit_log = false`
- **THEN** no audit line is written and stdout is unchanged

### Requirement: Audit records hold no customer content
An audit record MUST NOT contain the query text in any form (raw, masked, or hashed), the reply text, account IDs, holder names, or any account record value. Guard reasons SHALL be category names only.

#### Scenario: Account query
- **WHEN** "What is the balance on ACC-12345?" is answered and audited
- **THEN** the record contains neither the query, `ACC-12345`, the holder's name, nor any record value, and holds the query's length

#### Scenario: Blocked query
- **WHEN** a query blocked by the regex check is audited
- **THEN** the record holds the guard decision `blocked` and its category, and not the matched text

### Requirement: Concurrent appends keep records whole
Records appended from several threads of one process SHALL each be one complete, parseable line.

#### Scenario: Threaded evaluation
- **WHEN** 50 records are appended from 8 threads at once
- **THEN** the log holds 50 lines and each parses as one JSON record

### Requirement: An audit write failure never fails a query
When the audit record cannot be written, the query SHALL return the same answer and exit code, and one stderr line naming the error type SHALL be written once per process.

#### Scenario: Unwritable path
- **WHEN** the audit log path points into a directory that cannot be created
- **THEN** the command answers as usual, exits as usual, and stderr contains one `audit: not written` line

### Requirement: A costly query raises an alert and is still answered
A query whose cost exceeds `[cost] per_query_alert_usd` SHALL write one stderr line naming its cost and the threshold, be recorded at level `WARNING` with the `per_query` alert, and tag its root run `cost:alert`. The query SHALL still be answered with its usual exit code.

#### Scenario: Threshold exceeded
- **WHEN** a query costs $0.0123 with a $0.01 alert threshold
- **THEN** stderr reads `cost: query $0.012300 above the $0.010000 alert`, the record has level `WARNING` and alert `per_query`, and the answer is unchanged

### Requirement: The daily budget is checked from the audit log
The daily total SHALL be the sum of today's (UTC) audit record costs. Where it is checked, a total at or above 80% of `[cost] daily_budget_usd` SHALL give a warning and a total above it an alert. No query SHALL be refused because of the budget.

#### Scenario: Warning at 80%
- **WHEN** today's records total $0.85 with a $1.00 daily budget and the budget is checked
- **THEN** a budget warning names the total, the budget, and the 85% share

### Requirement: Cost never changes an answer
Computing, recording, or alerting on cost SHALL NOT change any reply, state, or exit code, with the audit log or tracing on or off.

#### Scenario: Same states with and without the audit log
- **WHEN** the same queries run with the audit log on and off, and with tracing on and off
- **THEN** the returned states are identical
