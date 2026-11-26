# Spec Delta

## Purpose

Defines how each request to the support system is traced, so a developer can tell from one trace whether a wrong answer came from routing, retrieval, the context, or the model. It covers what the traces may contain and what the command line reports about them.

## ADDED Requirements

### Requirement: A query is traced as one named run tree
When tracing is enabled, a query through the whole system SHALL produce one trace whose root run is named `support_query`, with the graph run named `support_graph` beneath it, and one run per graph node: `classify_intent`, then exactly one of `policy_agent`, `account_agent`, or `escalation_agent`.

#### Scenario: Graph query
- **WHEN** a query is answered through the whole system with tracing enabled
- **THEN** one trace is recorded whose root is `support_query`, whose child is `support_graph`, and whose node runs are `classify_intent` and the one specialist the query was routed to

### Requirement: Standalone entry points have named roots
When tracing is enabled, a request through a single agent or step SHALL produce one trace whose root is named after the entry point: `policy_query`, `account_query`, `escalation_query`, `policy_search`, or `supervisor_classify`. The step runs beneath it SHALL have the same names as in the graph.

#### Scenario: Standalone policy question
- **WHEN** the policy agent answers a question on its own with tracing enabled
- **THEN** one trace is recorded whose root is `policy_query`, containing `policy_retrieval` and `policy_llm` runs

### Requirement: Every step that can fail has its own run
Each decision step SHALL be a named run beneath its node: `supervisor_llm` and `normalize_intent` under `classify_intent`; `policy_retrieval` and `policy_llm` under `policy_agent`; `account_resolution` and, for a found account only, `account_llm` under `account_agent`; and `escalation_llm` and `escalation_assembly` under `escalation_agent`. Building the policy index SHALL NOT be traced.

#### Scenario: Policy route
- **WHEN** a policy query is traced
- **THEN** the trace contains `supervisor_llm`, `normalize_intent`, `policy_retrieval`, and `policy_llm` runs in that order of execution

#### Scenario: Account query without an ID
- **WHEN** an account query with no account ID is traced
- **THEN** the trace contains an `account_resolution` run and no `account_llm` run

#### Scenario: Index build
- **WHEN** a request rebuilds the policy index
- **THEN** no run for the build or its embeddings appears in the trace

### Requirement: Decision runs record their decision
`normalize_intent` SHALL record the raw reply as input and the intent and whether the fallback was used as output. `escalation_assembly` SHALL record the raw reply as input and whether the fallback message was used as output. `account_resolution` SHALL record the query as input and only the outcome and account IDs as output, never the account record.

#### Scenario: Normalization fallback is visible
- **WHEN** the supervisor's reply names no category and the intent falls back to `policy`
- **THEN** the `normalize_intent` run's output shows the intent `policy` with the fallback marked as used

#### Scenario: Account resolution omits the record
- **WHEN** a query for a found account is traced
- **THEN** the `account_resolution` run's output holds the outcome `found` and the account ID, and no field of the account record

### Requirement: Retrieval is a retriever run with scored chunks
`policy_retrieval` SHALL be recorded as a retriever run whose input is the query and whose output is the ranked chunks as documents, each with its text, `source`, `chunk_index`, and relevance score.

#### Scenario: Retrieved chunks are inspectable
- **WHEN** a policy query is traced
- **THEN** the `policy_retrieval` run is of type retriever and lists the retrieved chunks in rank order with their source filenames and scores

### Requirement: Root runs carry a fixed tag vocabulary
Every root run SHALL carry an `entry:<point>` tag naming the entry point and a `provider:<name>` tag naming the configured provider. A graph root SHALL also carry `intent:<intent>`, added once the query has been routed. The `exp:` and `eval-` prefixes are reserved and SHALL NOT be set by this capability.

#### Scenario: Intent tag after routing
- **WHEN** a query routed to the account agent is traced from the command line
- **THEN** its root run carries the tags `entry:supervisor-ask`, `provider:<configured provider>`, and `intent:account_status`

### Requirement: Root runs carry configuration metadata and no customer data
Every root run SHALL carry metadata naming the provider, chat model, embedding model, temperature, chunk size, chunk overlap, top-k, collection, index fingerprint, a short hash of each system prompt, and the package version. Tags and metadata MUST NOT contain the query text, account IDs, holder names, or any account record field.

#### Scenario: Configuration is recorded
- **WHEN** any query is traced
- **THEN** the root run's metadata holds the configured provider, models, retrieval settings, prompt hashes, and package version

#### Scenario: No customer data in tags or metadata
- **WHEN** a query for `ACC-12345` is traced
- **THEN** no tag or metadata value contains the query text, `ACC-12345`, the holder's name, or any record value

### Requirement: Social Security data is masked before upload
Before any run is sent to the tracing service, its inputs and outputs SHALL have every value of the `ssn_last4` field, every `ssn_last4` value present in the account records, and every full SSN pattern (three digits, two digits, four digits, separated by hyphens) replaced with `[REDACTED:ssn]`. Other text SHALL be left unchanged.

#### Scenario: Account prompt is masked
- **WHEN** a found-account query for `ACC-12345` is traced
- **THEN** the uploaded `account_llm` input shows `[REDACTED:ssn]` where the record's `ssn_last4` was, and does not contain `6789`

#### Scenario: A leaked reply is masked but visible
- **WHEN** the model's reply contains `6789`
- **THEN** the uploaded reply shows `[REDACTED:ssn]` in its place

#### Scenario: Ordinary numbers are untouched
- **WHEN** a trace contains amounts, dates, and account IDs such as `$1,500`, `2026`, and `ACC-12345`
- **THEN** they are uploaded unchanged

### Requirement: Verbose output names the trace
With `--verbose`, every command that calls a model SHALL write one stderr line naming its trace: `trace: <trace id> (project <project>)` when traced, or `trace: none (tracing off)` when not. When the sampling rate is below 1.0, the line SHALL state the rate and that the trace may not be recorded. stdout and the exit code SHALL be unchanged.

#### Scenario: Traced command
- **WHEN** `finos supervisor ask --query "What is the overdraft fee?" --verbose` runs with tracing enabled
- **THEN** stderr contains one line naming the trace ID and the project, and stdout is the same as without `--verbose`

#### Scenario: Tracing off
- **WHEN** the same command runs with tracing disabled
- **THEN** stderr contains `trace: none (tracing off)`

#### Scenario: Commands that call no model
- **WHEN** `finos account lookup`, `finos account list`, `finos escalation contact`, or `finos supervisor graph` runs with `--verbose`
- **THEN** no trace line is written

### Requirement: Verbose output shows per-step timings and tokens
With `--verbose`, every command that calls a model SHALL write, on stderr, the elapsed time of each node or standalone step, the retrieval time for the policy route, the prompt and completion token counts of each model call, and the total time. This SHALL work whether tracing is enabled or not.

#### Scenario: Timings with tracing off
- **WHEN** `finos policy ask --query "What is the overdraft fee?" --verbose` runs with tracing disabled
- **THEN** stderr shows the retrieval time, the model call's time and token counts, and the total time, and stdout is unchanged

### Requirement: Tracing never changes results
Tracing, masking, sampling, and an unreachable tracing service SHALL NOT change any response, `SupportState` value, stdout output, or exit code. The default test run SHALL pass with no tracing key and no network.

#### Scenario: Same answer with tracing on and off
- **WHEN** the same query runs once with tracing enabled and once with it disabled, against the same models
- **THEN** stdout, the exit code, and the returned state are identical

#### Scenario: Tracing service unreachable
- **WHEN** a command runs with tracing enabled and the tracing service cannot be reached
- **THEN** the command's stdout and exit code are the same as with tracing disabled

### Requirement: Live tests are traced under their own entry
Tests that call real models SHALL run with the tag `entry:live-test` and the test's identifier in the root run's metadata, so their traces can be found by tag.

#### Scenario: Finding a live baseline
- **WHEN** the live suite runs with tracing enabled
- **THEN** each live test's traces carry `entry:live-test` and the test's identifier

### Requirement: Tracing support stays out of light imports
Importing the CLI's root module or running `--help` MUST NOT import the tracing client library, in addition to the libraries the cli-framework already excludes.

#### Scenario: Import stays light
- **WHEN** a fresh Python process imports the CLI's root module
- **THEN** `langsmith` does not appear in its loaded modules
