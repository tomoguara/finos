# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Shipped configuration values
The committed configuration SHALL set the Ollama model to `qwen3-coder-next:q8_0-gpu`, the Ollama embedding model to `qwen3-embedding:latest`, the Ollama base URL to `http://localhost:11434`, the OpenAI model to `gpt-4o-mini`, the OpenAI embedding model to `text-embedding-3-small`, temperature to 0, and the LangSmith project to `finos`. Its `[policy]` section SHALL set `collection` to `finos_policy_docs`, `chunk_size` to 1000, `chunk_overlap` to 100, and `top_k` to 3. The Ollama base URL MUST NOT include a `/v1` suffix. It SHALL declare `use_local_ollama_model` and `tracing`, and its initial committed values for both are true.

#### Scenario: Shipped model settings are read
- **WHEN** the committed `config.toml` is loaded unchanged
- **THEN** the model, embedding model, base URL, temperature, and project values match the values above

#### Scenario: Shipped retrieval settings are read
- **WHEN** the committed `config.toml` is loaded unchanged
- **THEN** the `[policy]` values match the values above

### Requirement: Missing configuration fails clearly
The system SHALL raise an error that names the configuration file when `config.toml` is missing or lacks a required setting. The embedding model settings and every `[policy]` setting SHALL be required.

#### Scenario: Configuration file is missing
- **WHEN** a chat model is requested and the configuration file does not exist
- **THEN** an error is raised that names the expected file path

#### Scenario: Retrieval setting is missing
- **WHEN** settings load from a configuration without `[policy] top_k`
- **THEN** an error is raised that names `[policy] top_k` and the configuration file
