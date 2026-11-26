# policy-retrieval Specification

## Purpose

Loads and chunks the SecureBank policy corpus, embeds it into a persistent on-disk Chroma collection that is rebuilt whenever it goes stale, and serves ranked similarity search with relevance scores, so the policy agent and developers retrieve from an index that always matches the current documents and settings.

## Requirements

### Requirement: The corpus is chunked per document with traceable metadata
The system SHALL load every Markdown file directly in the policy documents directory and split each file separately with a recursive character splitter, using the configured chunk size and overlap. Each chunk SHALL carry its document's bare filename as `source` and its 0-based position within that document as `chunk_index`. No chunk SHALL contain text from more than one document.

#### Scenario: Shipped settings
- **WHEN** the corpus is chunked with the shipped `chunk_size` of 1000 and `chunk_overlap` of 100
- **THEN** every chunk is at most 1000 characters, each of the four documents yields at least one chunk, and each document's `chunk_index` values run 0, 1, 2, … without gaps

#### Scenario: Sources are bare filenames
- **WHEN** the chunk metadata is read
- **THEN** every `source` names a file in `data/policy-docs/` and contains no path separator

#### Scenario: Corpus directory missing
- **WHEN** the policy documents directory does not exist or holds no Markdown files
- **THEN** loading raises `FileNotFoundError` naming the directory

### Requirement: The index persists on disk and is rebuilt when stale
The system SHALL store the embedded chunks in a Chroma collection on disk in git-ignored `data/chroma/`, using the configured collection name and cosine distance. After all chunks are stored, it SHALL record a fingerprint of everything that shapes the index. On open, a missing, unreadable, or mismatched record SHALL cause a full rebuild, and a matching record SHALL reuse the index.

#### Scenario: First use builds the index
- **WHEN** the index is opened and `data/chroma/` holds no index
- **THEN** the corpus is embedded and stored, and the record is written

#### Scenario: Unchanged inputs reuse the index
- **WHEN** the index is opened a second time, from a new process, with no change to the documents, settings, or embedding model
- **THEN** no document is embedded again

#### Scenario: A change makes the index stale
- **WHEN** a document's content, `chunk_size`, `chunk_overlap`, the collection name, or the embedding provider or model changes, and the index is opened
- **THEN** the old collection is replaced by a full rebuild

#### Scenario: Retrieval depth does not affect the index
- **WHEN** only `top_k` changes
- **THEN** the index is reused

#### Scenario: Failed build leaves no valid record
- **WHEN** embedding fails partway through a build
- **THEN** the error propagates, no matching record exists, and the next open rebuilds from scratch

#### Scenario: Forced rebuild
- **WHEN** a rebuild is requested explicitly
- **THEN** the index is rebuilt even though the record matches

#### Scenario: No telemetry
- **WHEN** the Chroma client is created
- **THEN** anonymized telemetry is disabled

### Requirement: Search returns ranked chunks with scores
The system SHALL return the `k` most similar chunks for a query, ordered from most to least relevant, each with its text, `source`, `chunk_index`, and a relevance score where higher means more relevant. `k` SHALL default to the configured `top_k`, which ships as 3.

#### Scenario: Default depth
- **WHEN** a query is searched without an explicit `k`
- **THEN** at most 3 results are returned, in non-increasing score order

#### Scenario: Explicit depth
- **WHEN** a query is searched with `k` of 2
- **THEN** at most 2 results are returned

### Requirement: Retrieved chunks are formatted into a numbered context
The system SHALL format retrieved chunks into one context string: one block per chunk, in rank order, numbered from 1, each starting with a line `[n] (Source: <filename>)` followed by the chunk text, and blocks separated by a blank line. No results SHALL format as an empty string.

#### Scenario: Two chunks
- **WHEN** two chunks from `account_fees.md` and `fraud_policy.md` are formatted
- **THEN** the context starts with `[1] (Source: account_fees.md)`, contains `[2] (Source: fraud_policy.md)`, and the two blocks are separated by a blank line

#### Scenario: Nothing retrieved
- **WHEN** an empty result list is formatted
- **THEN** the context is an empty string
