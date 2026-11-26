# policy-cli Specification

## Purpose

Defines the `finos policy` commands `ask`, `search`, and `ingest`, which run the policy agent, inspect retrieval, and manage the policy index from the command line.

## Requirements

### Requirement: The policy module attaches as a command group
The CLI SHALL provide a `policy` command group with the commands `ask`, `search`, and `ingest`, registered with one line in the root module. The group SHALL follow the cli-framework conventions: shared options in either position, help on a bare `finos policy`, and no heavy imports when the CLI is imported or help is shown.

#### Scenario: Group help
- **WHEN** `finos policy --help` runs
- **THEN** it exits 0 and lists `ask`, `search`, and `ingest`

#### Scenario: Import stays light with the module registered
- **WHEN** a fresh Python process imports the CLI's root module
- **THEN** none of `langchain`, `langgraph`, or `chromadb` appear in its loaded modules

### Requirement: Ask prints a grounded answer
`finos policy ask --query <text>` SHALL run the policy agent standalone. In human mode it SHALL print the response, a blank line, and `Sources:` followed by the comma-separated source filenames, or `Sources: none`. With `--json` it SHALL print the complete `SupportState` as JSON.

#### Scenario: Human output
- **WHEN** `finos policy ask --query "What is the overdraft fee?"` runs and the agent returns a response with sources `account_fees.md`
- **THEN** it exits 0, stdout starts with the response, and its last line is `Sources: account_fees.md`

#### Scenario: JSON output
- **WHEN** the same command runs with `--json`
- **THEN** stdout is a JSON object with the five contract fields and `intent` equal to `policy`, and it passes `finos state validate --strict`

#### Scenario: Verbose shows what the model saw
- **WHEN** the command runs with `--verbose`
- **THEN** the full context is written to stderr, and stdout and the exit code are the same as without `--verbose`

### Requirement: Search shows retrieval without generating
`finos policy search --query <text> [--top-k N]` SHALL show the ranked chunks the retriever returns, without calling the chat model. In human mode each hit SHALL show its rank, score to two decimals, source filename, chunk index, and a preview of its text. With `--json` it SHALL print a list of objects with `rank`, `score`, `source`, `chunk_index`, and `text`. `--top-k` SHALL default to the configured `top_k`.

#### Scenario: Ranked hits
- **WHEN** `finos policy search --query "overdraft" --top-k 2` runs
- **THEN** it exits 0, prints at most two hits numbered `[1]` and `[2]`, and each hit names a corpus file

#### Scenario: No generation
- **WHEN** `finos policy search` runs
- **THEN** the chat model is not called

### Requirement: Ingest builds or refreshes the index explicitly
`finos policy ingest` SHALL build the index if it is missing or stale and otherwise report that it is up to date. `--rebuild` SHALL force a rebuild. Output SHALL state whether the index was built or reused, with the document count, chunk count, and embedding provider and model. With `--json` this SHALL be an object with `status` (`built` or `up_to_date`), `documents`, `chunks`, `provider`, `model`, and `collection`.

#### Scenario: Up to date
- **WHEN** `finos policy ingest` runs twice with no changes between the runs
- **THEN** the second run reports `up_to_date` and embeds nothing

#### Scenario: Forced rebuild
- **WHEN** `finos policy ingest --rebuild` runs on an up-to-date index
- **THEN** it reports `built`

### Requirement: Policy commands report bad input and provider failures distinctly
An empty or whitespace-only `--query`, or a `--top-k` below 1, SHALL exit 2 with a message on stderr. A failure to reach or use a model or embedding provider, such as an unreachable Ollama host, a missing model, or a missing OpenAI key, SHALL exit 1 with a one-line plain-text message on stderr and no traceback, including when `--json` is set.

#### Scenario: Empty query
- **WHEN** `finos policy ask --query "  "` runs
- **THEN** it exits 2, stderr explains the problem, and no model is called

#### Scenario: Provider unavailable
- **WHEN** `finos policy ask` runs and the embedding or chat provider raises a connection error
- **THEN** it exits 1, stderr holds one plain-text line naming the problem, and stdout is empty
