# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Missing configuration fails clearly
The system SHALL raise an error that names the configuration file when `config.toml` is missing or lacks a required setting. The embedding model settings, every `[policy]` setting, `[langsmith] sampling_rate`, every `[eval]` setting, every `[eval.gates]` threshold, and every `[guardrails]` setting SHALL be required. A `sampling_rate` that is not a number from 0.0 to 1.0 SHALL raise an error that names the setting and the file.

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
