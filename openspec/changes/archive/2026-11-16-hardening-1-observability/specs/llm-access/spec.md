# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

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
The system SHALL raise an error that names the configuration file when `config.toml` is missing or lacks a required setting. The embedding model settings, every `[policy]` setting, and `[langsmith] sampling_rate` SHALL be required. A `sampling_rate` that is not a number from 0.0 to 1.0 SHALL raise an error that names the setting and the file.

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

### Requirement: Shipped configuration values
The committed configuration SHALL set the Ollama model to `qwen3.8:27b-q8_0`, the Ollama embedding model to `qwen3-embedding:latest`, the Ollama base URL to `http://localhost:11434`, the OpenAI model to `gpt-4o-mini`, the OpenAI embedding model to `text-embedding-3-small`, temperature to 0, and the LangSmith project to `finos`. The Ollama base URL MUST NOT include a `/v1` suffix. It SHALL declare `use_local_ollama_model` and `tracing`, both initially committed as true.

#### Scenario: Shipped model settings are read
- **WHEN** the committed `config.toml` is loaded unchanged
- **THEN** the model, embedding model, base URL, temperature, and project values match the values above
