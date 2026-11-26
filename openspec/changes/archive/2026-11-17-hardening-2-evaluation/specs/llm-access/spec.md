# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Missing configuration fails clearly
The system SHALL raise an error that names the configuration file when `config.toml` is missing or lacks a required setting. The embedding model settings, every `[policy]` setting, `[langsmith] sampling_rate`, every `[eval]` setting, and every `[eval.gates]` threshold SHALL be required. A `sampling_rate` that is not a number from 0.0 to 1.0 SHALL raise an error that names the setting and the file.

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
