# Spec Delta

## ADDED Requirements

### Requirement: Shipped cost settings
The committed configuration SHALL set `[cost] audit_log_path` to `logs/audit_log.jsonl`, `per_query_alert_usd` to 0.01, `daily_budget_usd` to 1.0, and a `prices_as_of` date, with price entries for `gpt-4o-mini` (input $0.15, output $0.60 per million tokens) and `text-embedding-3-small` (input $0.02 per million), confirmed against OpenAI's list prices on that date. The audit log's directory SHALL be ignored by version control.

#### Scenario: Shipped cost settings are read
- **WHEN** the committed `config.toml` is loaded unchanged
- **THEN** the `[cost]` values and both price entries match the values above

### Requirement: The audit log switch is developer-local
The committed configuration SHALL declare `[cost] audit_log`, initially committed as true. Like `tracing`, it is a developer switch: every supported behavior and the offline suite SHALL work with either value.

#### Scenario: Suite passes with the audit log off
- **WHEN** `[cost] audit_log` is set to false and the offline suite runs
- **THEN** it passes, and no audit line is written by a command run with that configuration

### Requirement: Cost settings are validated
Settings loading SHALL raise an error that names the setting and the configuration file when `[cost] audit_log` is not true or false, `audit_log_path` is not a string, `per_query_alert_usd` or `daily_budget_usd` is not a positive number, `prices_as_of` is not an ISO date, or a price entry lacks `input_per_1m` or holds a negative or non-numeric price.

#### Scenario: Negative price
- **WHEN** settings load with `[cost.prices."gpt-4o-mini"] output_per_1m` set to `-1`
- **THEN** an error is raised that names `[cost.prices."gpt-4o-mini"] output_per_1m` and the configuration file

#### Scenario: Bad price date
- **WHEN** settings load with `[cost] prices_as_of` set to `"last week"`
- **THEN** an error is raised that names `[cost] prices_as_of` and the configuration file

### Requirement: Optional local model tuning
`[ollama] reasoning` (true or false) and `[ollama] num_ctx` (a positive integer) SHALL be optional. When set, they SHALL be passed to the local chat model as its reasoning mode and context window; when unset, the model's own defaults SHALL apply. They SHALL be overridable per experiment with `--set`.

#### Scenario: Thinking off for a variant
- **WHEN** a chat model is requested with `[ollama] reasoning = false` and the local provider
- **THEN** the Ollama chat model has reasoning turned off

#### Scenario: Unset keeps defaults
- **WHEN** neither key is set
- **THEN** the Ollama chat model is built exactly as before

#### Scenario: Invalid context window
- **WHEN** settings load with `[ollama] num_ctx` set to `0`
- **THEN** an error is raised that names `[ollama] num_ctx` and the configuration file

## MODIFIED Requirements

### Requirement: Missing configuration fails clearly
The system SHALL raise an error that names the configuration file when `config.toml` is missing or lacks a required setting. The embedding model settings, every `[policy]` setting, `[langsmith] sampling_rate`, every `[eval]` setting, every `[eval.gates]` threshold, every `[guardrails]` setting, and every `[cost]` setting SHALL be required. A `sampling_rate` that is not a number from 0.0 to 1.0 SHALL raise an error that names the setting and the file.

#### Scenario: Configuration file is missing
- **WHEN** a chat model is requested and the configuration file does not exist
- **THEN** an error is raised that names the expected file path

#### Scenario: Retrieval setting is missing
- **WHEN** settings load from a configuration without `[policy] top_k`
- **THEN** an error is raised that names `[policy] top_k` and the configuration file

#### Scenario: Sampling rate is missing
- **WHEN** settings load from a configuration without `[langsmith] sampling_rate`
- **THEN** an error is raised that names `[langsmith] sampling_rate` and the configuration file

#### Scenario: Sampling rate out of range
- **WHEN** settings load with `[langsmith] sampling_rate` set to `1.5`
- **THEN** an error is raised that names `[langsmith] sampling_rate` and the configuration file

#### Scenario: Evaluation setting is missing
- **WHEN** settings load from a configuration without `[eval] judge_model`
- **THEN** an error is raised that names `[eval] judge_model` and the configuration file

#### Scenario: Cost setting is missing
- **WHEN** settings load from a configuration without `[cost] prices_as_of`
- **THEN** an error is raised that names `[cost] prices_as_of` and the configuration file
