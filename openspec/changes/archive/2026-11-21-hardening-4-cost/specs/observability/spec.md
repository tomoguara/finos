# Spec Delta

## ADDED Requirements

### Requirement: Verbose output shows the query's cost
With `--verbose`, every command that calls a model SHALL write, on stderr after the timing lines, one cost line with the total cost in USD to six decimals, the input and output tokens, the number of calls, the guard subtotal, and the price date; or `cost: unpriced` naming the unpriced models. stdout SHALL be unchanged.

#### Scenario: Priced query
- **WHEN** `finos supervisor ask --query "What is the overdraft fee?" --verbose` runs on OpenAI
- **THEN** stderr ends with a line of the form `cost: $0.000241 (1123+124 tokens, 5 calls; guards $0.000026; prices as of 2026-11-17)`, and stdout is unchanged

#### Scenario: Unpriced query
- **WHEN** the same command runs with a chat model that has no price entry
- **THEN** the cost line reads `cost: unpriced` and names that model

### Requirement: Root runs carry cost metadata
When a root run that made model calls ends, its metadata SHALL gain `cost_usd`, `guard_cost_usd`, `input_tokens`, and `output_tokens`, with `null` for an unknown cost.

#### Scenario: Cost in the trace
- **WHEN** a policy query is traced on OpenAI
- **THEN** the `support_query` run's metadata holds the same cost and token totals as the query's audit record

## MODIFIED Requirements

### Requirement: Root runs carry a fixed tag vocabulary
Every root run SHALL carry an `entry:<point>` tag naming the entry point and a `provider:<name>` tag naming the configured provider. A graph root SHALL also carry `intent:<intent>`, added once the query has been routed. A root where a guardrail did anything but pass SHALL carry `guardrail:<decision>`. A root whose cost exceeded the per-query alert SHALL carry `cost:alert`. The `exp:` and `eval-` prefixes are reserved and SHALL NOT be set by this capability.

#### Scenario: Intent tag after routing
- **WHEN** a query routed to the account agent is traced from the command line
- **THEN** its root run carries the tags `entry:supervisor-ask`, `provider:<configured provider>`, and `intent:account_status`

#### Scenario: Cost alert tag
- **WHEN** a traced query costs more than `[cost] per_query_alert_usd`
- **THEN** its root run carries `cost:alert`

### Requirement: Verbose output shows per-step timings and tokens
With `--verbose`, every command that calls a model SHALL write, on stderr, the elapsed time of each node or standalone step, the retrieval time for the policy route, the prompt and completion token counts of each model call, and the total time. When an input guard made a model call, a `guards:` line SHALL show the input guards' time and tokens. This SHALL work whether tracing is enabled or not.

#### Scenario: Timings with tracing off
- **WHEN** `finos policy ask --query "What is the overdraft fee?" --verbose` runs with tracing disabled
- **THEN** stderr shows the retrieval time, the model call's time and token counts, and the total time, and stdout is unchanged

#### Scenario: Guard line
- **WHEN** `finos supervisor ask --query "What is the overdraft fee?" --verbose` runs with the injection classifier enabled
- **THEN** stderr shows a `guards:` line with the classifier's tokens before the `classify_intent` line
