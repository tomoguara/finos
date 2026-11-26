# account-cli Specification

## Purpose

Defines the `finos account` commands `ask`, `lookup`, and `list`, which run the account agent and inspect the mock account records from the command line.

## Requirements

### Requirement: The account module attaches as a command group
The CLI SHALL provide an `account` command group with the commands `ask`, `lookup`, and `list`, registered with one line in the root module. It SHALL follow the cli-framework conventions: shared options in either position, help on a bare `finos account`, and no heavy imports when the CLI is imported or help is shown.

#### Scenario: Group help
- **WHEN** `finos account --help` runs
- **THEN** it exits 0 and lists `ask`, `lookup`, and `list`

#### Scenario: Import stays light with the module registered
- **WHEN** a fresh Python process imports the CLI's root module
- **THEN** none of `langchain`, `langgraph`, or `chromadb` appear in its loaded modules

### Requirement: Ask prints the answer and the account it used
`finos account ask --query <text>` SHALL run the account agent standalone and exit 0 for all four outcomes. In human mode it SHALL print the response, a blank line, and a trailer: `Account: <ID>` when found, `Account: <ID> (not found)`, `Account: none` for no ID, or `Account: <ID>, <ID> (multiple)`. With `--json` it SHALL print the complete `SupportState`.

#### Scenario: Found
- **WHEN** `finos account ask --query "What is the balance on ACC-12345?"` runs and the agent answers
- **THEN** it exits 0 and the last line of stdout is `Account: ACC-12345`

#### Scenario: Not found
- **WHEN** `finos account ask --query "What is the balance on ACC-99999?"` runs
- **THEN** it exits 0, stdout starts with the not-found message, its last line is `Account: ACC-99999 (not found)`, and no model is called

#### Scenario: No ID
- **WHEN** `finos account ask --query "Show my recent transactions"` runs
- **THEN** it exits 0 and the last line of stdout is `Account: none`

#### Scenario: JSON output
- **WHEN** the found command runs with `--json`
- **THEN** stdout is a JSON object with the five contract fields, `intent` equal to `account_status`, and empty `context` and `retrieved_sources`, and it passes `finos state validate --strict`

#### Scenario: Verbose shows what the model saw
- **WHEN** the found command runs with `--verbose`
- **THEN** the outcome, the extracted ID, and the rendered record are written to stderr, and stdout and the exit code are the same as without `--verbose`

### Requirement: Lookup shows a record without a model
`finos account lookup --id <ID>` SHALL show the record for a normalized ID without loading settings or calling a model. It SHALL exit 0 when found and 1 when not found, with the verdict on stdout. In human mode a found record SHALL show its fields, including the status with `freeze_reason` when frozen, and its signed transactions. With `--json` a found record SHALL print as the raw record, and a missing one as `{"account_id": <ID>, "found": false}`.

#### Scenario: Frozen record
- **WHEN** `finos account lookup --id ACC-11111` runs
- **THEN** it exits 0 and stdout shows `frozen` and `Suspected fraudulent activity under investigation`

#### Scenario: Normalized input
- **WHEN** `finos account lookup --id acc-12345` runs
- **THEN** it exits 0 and shows `ACC-12345`

#### Scenario: Not found is a verdict
- **WHEN** `finos account lookup --id ACC-99999` runs
- **THEN** it exits 1 and stdout says no account was found for `ACC-99999`

#### Scenario: Stays light
- **WHEN** `finos account lookup` runs in a fresh process
- **THEN** no `langchain` or `chromadb` module is loaded and settings are not loaded

### Requirement: List shows the available accounts
`finos account list` SHALL print one line per account, sorted by ID, with the ID, status, type, and holder, without loading settings or calling a model. With `--json` it SHALL print a list of objects with `account_id`, `status`, `account_type`, and `holder_name`.

#### Scenario: All accounts
- **WHEN** `finos account list` runs
- **THEN** it exits 0 and stdout has four lines, starting with `ACC-11111`, `ACC-12345`, `ACC-22222`, and `ACC-67890`

### Requirement: Account commands report bad input and environment failures distinctly
An empty or whitespace-only `--query`, or an `--id` that does not normalize to an account ID, SHALL exit 2 with a plain-text message on stderr, even with `--json`, before any file is read or model called. A missing or corrupt records file on any account command, or a provider failure on `ask`, SHALL exit 1 with a one-line plain-text message on stderr, no traceback, and empty stdout, even with `--json`.

#### Scenario: Empty query
- **WHEN** `finos account ask --query "  "` runs
- **THEN** it exits 2, stderr explains the problem, and no model is called

#### Scenario: Malformed ID
- **WHEN** `finos account lookup --id ACC-1234` runs
- **THEN** it exits 2 and stderr explains the expected format

#### Scenario: Records file missing
- **WHEN** `finos account list` runs and the records file does not exist
- **THEN** it exits 1, stderr holds one plain-text line naming the path, and stdout is empty

#### Scenario: Provider unavailable
- **WHEN** `finos account ask` runs for a found account and the chat provider raises a connection error
- **THEN** it exits 1, stderr holds one plain-text line naming the problem, and stdout is empty
