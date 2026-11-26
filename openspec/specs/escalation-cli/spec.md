# escalation-cli Specification

## Purpose
Defines the `finos escalation` command group, which runs the escalation agent from a terminal and shows its fixed customer-facing texts without a model, following the shared CLI conventions.

## Requirements

### Requirement: The escalation module attaches as a command group
The CLI SHALL provide an `escalation` command group with the commands `ask` and `contact`, registered with one line in the root module. It SHALL follow the cli-framework conventions: shared options in either position, help on a bare `finos escalation`, and no heavy imports when the CLI is imported or help is shown.

#### Scenario: Group help
- **WHEN** `finos escalation --help` runs
- **THEN** it exits 0 and lists `ask` and `contact`

#### Scenario: Import stays light with the module registered
- **WHEN** a fresh Python process imports the CLI's root module
- **THEN** none of `langchain`, `langgraph`, or `chromadb` appear in its loaded modules

### Requirement: Ask prints the escalation reply
`finos escalation ask --query <text>` SHALL run the escalation agent standalone through the guardrails and exit 0 on success, including when a guard blocks or replaces the reply. In human mode it SHALL print the response, which already ends with the support contact block, with no trailer line. With `--json` it SHALL print the complete `SupportState`.

#### Scenario: Human output
- **WHEN** `finos escalation ask --query "I'm furious! Nobody is helping!"` runs and the agent answers
- **THEN** it exits 0 and stdout ends with the support contact block

#### Scenario: JSON output
- **WHEN** the same command runs with `--json`
- **THEN** stdout is a JSON object with the five contract fields, `intent` equal to `escalation`, and empty `context` and `retrieved_sources`, and it passes `finos state validate --strict`

#### Scenario: Verbose shows the raw reply
- **WHEN** the command runs with `--verbose`
- **THEN** the provider and model, the model's raw reply before the guards and the contact block, and whether the fallback message was used are written to stderr, and stdout and the exit code are the same as without `--verbose`

### Requirement: Contact shows the fixed texts without a model
`finos escalation contact` SHALL print the support contact block and exit 0, without loading settings, importing LangChain, or calling a model. With `--json` it SHALL print an object with `support_contact` and `crisis_support`, holding the support contact block and the crisis support message.

#### Scenario: Human output
- **WHEN** `finos escalation contact` runs
- **THEN** it exits 0 and stdout is the support contact block

#### Scenario: JSON output
- **WHEN** `finos escalation contact --json` runs
- **THEN** stdout is an object whose `support_contact` contains `support@securebank.example` and whose `crisis_support` contains `988`

#### Scenario: Stays light
- **WHEN** `finos escalation contact` runs in a fresh process
- **THEN** no `langchain` or `chromadb` module is loaded and settings are not loaded

### Requirement: Escalation commands report bad input and provider failures distinctly
An empty or whitespace-only `--query` SHALL exit 2 with a plain-text message on stderr, even with `--json`, before any model is called. A provider failure on `ask`, such as an unreachable Ollama host, a missing model, or a missing OpenAI key, SHALL exit 1 with a one-line plain-text message on stderr, no traceback, and empty stdout, even with `--json`.

#### Scenario: Empty query
- **WHEN** `finos escalation ask --query "  "` runs
- **THEN** it exits 2, stderr explains the problem, and no model is called

#### Scenario: Provider unavailable
- **WHEN** `finos escalation ask` runs and the chat provider raises a connection error
- **THEN** it exits 1, stderr holds one plain-text line naming the problem, and stdout is empty
