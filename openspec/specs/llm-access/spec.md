# llm-access Specification

## Purpose

Gives every agent one way to obtain a chat model, selects between local Ollama and OpenAI from configuration, controls LangSmith tracing of those calls, and keeps non-secret settings separate from secrets.

## Requirements

### Requirement: Provider is selected from committed configuration
The system SHALL read the provider choice and model settings from a committed `config.toml` at the repository root. Setting `use_local_ollama_model` to true SHALL select Ollama, and false SHALL select OpenAI.

#### Scenario: Local provider selected
- **WHEN** `use_local_ollama_model` is true and an agent requests a chat model
- **THEN** it receives an Ollama chat model using the configured Ollama model and base URL

#### Scenario: OpenAI provider selected
- **WHEN** `use_local_ollama_model` is false, an OpenAI API key is available, and an agent requests a chat model
- **THEN** it receives an OpenAI chat model using the configured OpenAI model

### Requirement: Shipped configuration values
The committed configuration SHALL set the Ollama model to `qwen3.8:27b-q8_0`, the Ollama embedding model to `qwen3-embedding:latest`, the Ollama base URL to `http://localhost:11434`, the OpenAI model to `gpt-4o-mini`, the OpenAI embedding model to `text-embedding-3-small`, temperature to 0, and the LangSmith project to `finos`. The Ollama base URL MUST NOT include a `/v1` suffix. It SHALL declare `use_local_ollama_model` and `tracing`, both initially committed as true.

#### Scenario: Shipped model settings are read
- **WHEN** the committed `config.toml` is loaded unchanged
- **THEN** the model, embedding model, base URL, temperature, and project values match the values above

### Requirement: Shipped retrieval settings
The committed configuration's `[policy]` section SHALL set `collection` to `finos_policy_docs`, `chunk_size` to 1000, `chunk_overlap` to 100, and `top_k` to 3.

#### Scenario: Shipped retrieval settings are read
- **WHEN** the committed `config.toml` is loaded unchanged
- **THEN** the `[policy]` values match the values above

### Requirement: The two switches are developer-local
`use_local_ollama_model` and `tracing` are the settings a developer changes to work: local Ollama for day-to-day development and OpenAI to compare against the lecture's baseline, and tracing off when there is no LangSmith key or a run must stay on the machine. Either value of either switch SHALL be a valid working state, and the test suite MUST NOT assert a particular value for either.

#### Scenario: Suite passes with each provider selected
- **WHEN** the test suite runs with `use_local_ollama_model` set to true, and again with it set to false
- **THEN** it passes both times, and the chat model built from the committed configuration is the provider the switch selects

#### Scenario: Suite passes with tracing off
- **WHEN** the test suite runs with `tracing` set to false
- **THEN** it passes

### Requirement: Secrets stay out of committed configuration
`OPENAI_API_KEY` and `LANGCHAIN_API_KEY` SHALL be supplied through the process environment or a local `.env` file and MUST NOT appear in `config.toml`. Non-secret model and tracing settings MUST NOT be required in `.env`.

#### Scenario: Example environment file lists secrets only
- **WHEN** a developer reads `.env.example`
- **THEN** it lists `OPENAI_API_KEY` and `LANGCHAIN_API_KEY` with placeholder values and no provider, model, or tracing settings

#### Scenario: Local provider needs no key
- **WHEN** Ollama is selected and no OpenAI API key is set
- **THEN** requesting a chat model succeeds

#### Scenario: OpenAI selected without a key
- **WHEN** OpenAI is selected and no OpenAI API key is available
- **THEN** requesting a chat model fails with an error that names `OPENAI_API_KEY`

### Requirement: Chat model is provider-neutral and shared
The helper SHALL return the same instance for repeated requests with the same effective model, and callers MUST be able to use the result without knowing its provider. An optional model name SHALL override the configured model for the selected provider.

#### Scenario: Repeated requests share an instance
- **WHEN** an agent requests the default chat model twice
- **THEN** both requests return the same instance

#### Scenario: Model override
- **WHEN** a caller requests a chat model with an explicit model name
- **THEN** it receives a model of the selected provider using that name

### Requirement: Tracing is controlled by committed configuration
The system SHALL apply the `[langsmith]` settings in `config.toml` to the process as `LANGCHAIN_TRACING_V2`, `LANGCHAIN_PROJECT`, and the tracing sampling rate when settings load, before any model call. These values MUST take precedence over any value from `.env` or the process environment.

#### Scenario: Tracing enabled
- **WHEN** settings load with `tracing` set to true and a LangSmith API key is available
- **THEN** LangSmith reports tracing as enabled and the project is `finos`

#### Scenario: Tracing disabled
- **WHEN** settings load with `tracing` set to false
- **THEN** LangSmith reports tracing as disabled

#### Scenario: Configuration overrides the environment
- **WHEN** `.env` or the process environment sets `LANGCHAIN_TRACING_V2` to a value that differs from `config.toml`
- **THEN** the `config.toml` value is the one in effect after settings load

#### Scenario: Loading settings makes no network call
- **WHEN** settings load with tracing enabled and no LangSmith API key is set
- **THEN** loading succeeds with no network access

#### Scenario: Sampling rate is applied
- **WHEN** settings load with `[langsmith] sampling_rate` set to `0.25`
- **THEN** the tracing sampling rate in effect for the process is `0.25`, whatever the environment held before

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

### Requirement: Embedding model follows the provider switch
The system SHALL provide one helper that returns the embedding model for the provider `use_local_ollama_model` selects: an Ollama embedding model using `[ollama] embedding_model` and the configured base URL when true, and an OpenAI embedding model using `[openai] embedding_model` when false. Chat and embedding models SHALL always come from the same provider. Repeated requests SHALL return the same instance, and creating it MUST NOT make a network call.

#### Scenario: Local embeddings
- **WHEN** `use_local_ollama_model` is true and embeddings are requested
- **THEN** an Ollama embedding model is returned for `qwen3-embedding:latest` at the configured base URL, with no OpenAI key needed

#### Scenario: OpenAI embeddings
- **WHEN** `use_local_ollama_model` is false, an OpenAI API key is available, and embeddings are requested
- **THEN** an OpenAI embedding model is returned for `text-embedding-3-small`

#### Scenario: OpenAI embeddings without a key
- **WHEN** OpenAI is selected and no OpenAI API key is available
- **THEN** requesting embeddings fails with an error that names `OPENAI_API_KEY`

#### Scenario: Shared instance
- **WHEN** embeddings are requested twice
- **THEN** both requests return the same instance

### Requirement: Tracing turns off when no key is available
When settings load with `tracing` set to true and no LangSmith API key (`LANGSMITH_API_KEY` or `LANGCHAIN_API_KEY`) is in the environment after `.env` is read, the system SHALL disable tracing for the process and record that no key was found. Each command that calls a model SHALL then write one stderr line saying tracing is off because no key is set; without `--verbose`, that is the only stderr output about tracing.

#### Scenario: No key
- **WHEN** settings load with `tracing` set to true and no LangSmith API key in the environment or `.env`
- **THEN** LangSmith reports tracing as disabled, and settings record that tracing is off because no key was found

#### Scenario: One line on the command line
- **WHEN** `finos policy ask --query "What is the overdraft fee?"` runs with `tracing` set to true and no key
- **THEN** stderr holds exactly one line saying tracing is off because no key is set, and stdout and the exit code are the same as with `tracing` set to false

#### Scenario: Key present
- **WHEN** settings load with `tracing` set to true and a LangSmith API key in the environment
- **THEN** tracing stays enabled and no such line is written

### Requirement: Shipped tracing settings
The committed configuration's `[langsmith]` section SHALL set `sampling_rate` to `1.0`, so every request is traced unless a developer changes it.

#### Scenario: Shipped sampling rate is read
- **WHEN** the committed `config.toml` is loaded unchanged
- **THEN** `[langsmith] sampling_rate` is `1.0`

### Requirement: Shipped evaluation settings
The committed configuration SHALL set `[eval] judge_provider` to `openai`, `judge_model` to `gpt-4o-mini`, and `repetitions` to 3, and `[eval.gates]` SHALL set `routing_accuracy` to 0.95, `crisis_sentence` to 1.0, `faithfulness` to 0.7, and `mrr` to 0.8.

#### Scenario: Shipped evaluation settings are read
- **WHEN** the committed `config.toml` is loaded unchanged
- **THEN** the `[eval]` and `[eval.gates]` values match the values above

### Requirement: Judge model follows its own configuration
The system SHALL provide a judge model for evaluation from `[eval] judge_provider` and `judge_model`, independent of `use_local_ollama_model`, through the same provider-neutral interface as the chat model, at temperature 0. Requesting it SHALL make no network call. An OpenAI judge without an OpenAI API key SHALL fail with an error that names `OPENAI_API_KEY`.

#### Scenario: OpenAI judge with a local generator
- **WHEN** `use_local_ollama_model` is true and `[eval] judge_provider` is `openai`
- **THEN** the chat model is the Ollama model and the judge is the configured OpenAI model

#### Scenario: Local judge
- **WHEN** `[eval] judge_provider` is `ollama` and `judge_model` names a local model
- **THEN** the judge is an Ollama model with that name at the configured base URL, and no OpenAI key is needed

#### Scenario: OpenAI judge without a key
- **WHEN** the judge is requested with `judge_provider` set to `openai` and no OpenAI API key
- **THEN** an error is raised that names `OPENAI_API_KEY`

### Requirement: Evaluation settings are validated
Settings loading SHALL raise an error that names the setting and the configuration file when an `[eval.gates]` threshold is not a number from 0.0 to 1.0, `[eval] repetitions` is not a whole number of at least 1, or `[eval] judge_provider` is not `openai` or `ollama`.

#### Scenario: Gate threshold out of range
- **WHEN** settings load with `[eval.gates] faithfulness` set to `7`
- **THEN** an error is raised that names `[eval.gates] faithfulness` and the configuration file

#### Scenario: Unknown judge provider
- **WHEN** settings load with `[eval] judge_provider` set to `anthropic`
- **THEN** an error is raised that names `[eval] judge_provider` and the configuration file

#### Scenario: Repetitions below one
- **WHEN** settings load with `[eval] repetitions` set to `0`
- **THEN** an error is raised that names `[eval] repetitions` and the configuration file

### Requirement: Shipped guardrail settings
The committed configuration SHALL set `[guardrails] input_regex`, `moderation`, and `injection_classifier` to true, `classifier_provider` to `openai`, and `classifier_model` to `gpt-4o-mini`, and `[eval.gates]` SHALL set `guardrail_false_positive` and `no_ssn` to 1.0.

#### Scenario: Shipped guardrail settings are read
- **WHEN** the committed `config.toml` is loaded unchanged
- **THEN** the `[guardrails]` values and the two gate thresholds match the values above

### Requirement: Classifier model follows its own configuration
The system SHALL provide the injection classifier's model from `[guardrails] classifier_provider` and `classifier_model`, independent of `use_local_ollama_model`, through the same provider-neutral interface as the chat model, at temperature 0, making no network call when it is requested.

#### Scenario: OpenAI classifier with a local generator
- **WHEN** `use_local_ollama_model` is true and `classifier_provider` is `openai`
- **THEN** the chat model is the Ollama model and the classifier is the configured OpenAI model

### Requirement: Guardrail settings are validated
Settings loading SHALL raise an error that names the setting and the configuration file when a `[guardrails]` switch is not true or false, or `classifier_provider` is not `openai` or `ollama`.

#### Scenario: Unknown classifier provider
- **WHEN** settings load with `[guardrails] classifier_provider` set to `anthropic`
- **THEN** an error is raised that names `[guardrails] classifier_provider` and the configuration file

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
