# Spec Delta

## Purpose

Gives every agent one way to obtain a chat model, selects between local Ollama and OpenAI from configuration, controls LangSmith tracing of those calls, and keeps non-secret settings separate from secrets.

## ADDED Requirements

### Requirement: Provider is selected from committed configuration
The system SHALL read the provider choice and model settings from a committed `config.toml` at the repository root. Setting `use_local_ollama_model` to true SHALL select Ollama, and false SHALL select OpenAI.

#### Scenario: Local provider selected
- **WHEN** `use_local_ollama_model` is true and an agent requests a chat model
- **THEN** it receives an Ollama chat model using the configured Ollama model and base URL

#### Scenario: OpenAI provider selected
- **WHEN** `use_local_ollama_model` is false, an OpenAI API key is available, and an agent requests a chat model
- **THEN** it receives an OpenAI chat model using the configured OpenAI model

### Requirement: Shipped configuration values
The committed configuration SHALL set the Ollama model to `qwen3-coder-next:q8_0-gpu`, the Ollama base URL to `http://localhost:11434`, the OpenAI model to `gpt-4o-mini`, temperature to 0, and the LangSmith project to `finos`. The Ollama base URL MUST NOT include a `/v1` suffix. It SHALL declare `use_local_ollama_model` and `tracing`, and its initial committed values for both are true.

#### Scenario: Shipped model settings are read
- **WHEN** the committed `config.toml` is loaded unchanged
- **THEN** the model, base URL, temperature, and project values match the values above

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
The system SHALL apply the `[langsmith]` settings in `config.toml` to the process as `LANGCHAIN_TRACING_V2` and `LANGCHAIN_PROJECT` when settings load, before any model call. These values MUST take precedence over any value from `.env` or the process environment.

#### Scenario: Tracing enabled
- **WHEN** settings load with `tracing` set to true
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

### Requirement: Missing configuration fails clearly
The system SHALL raise an error that names the configuration file when `config.toml` is missing or lacks a required setting.

#### Scenario: Configuration file is missing
- **WHEN** a chat model is requested and the configuration file does not exist
- **THEN** an error is raised that names the expected file path
