# guard-cli Specification

## Purpose
Defines the `finos guard` command group, which shows how the input guardrails judge a query without running any agent, following the shared CLI conventions.

## Requirements

### Requirement: The guard module attaches as a command group
The CLI SHALL provide a `guard` command group with the command `check`, registered with one line in the root module. It SHALL follow the cli-framework conventions: shared options in either position, help without running anything on a bare `finos guard`, and no heavy imports when the CLI is imported or help is shown.

#### Scenario: Group help
- **WHEN** `finos guard --help` runs
- **THEN** it exits 0 and lists `check`

#### Scenario: Import stays light with the module registered
- **WHEN** a fresh Python process imports the CLI's root module
- **THEN** none of `langchain`, `langgraph`, `chromadb`, `langsmith`, or `openai` appear in its loaded modules

### Requirement: Check shows each input layer's decision
`finos guard check --query <text>` SHALL run the input guards on the query, without calling any agent, and print one line per layer with its decision (passed, blocked, off, skipped, or error) and category, then the overall verdict, including whether the query is a crisis. `--json` SHALL print the same as one object. It SHALL exit 0 whatever the verdict.

#### Scenario: Blocked query
- **WHEN** `finos guard check --query "Is SecureBank better than Chase?"` runs
- **THEN** it exits 0, the regex line shows blocked with the competitor category, the later layers show skipped, and the verdict is blocked

#### Scenario: Crisis
- **WHEN** `finos guard check --query "I want to hurt myself"` runs
- **THEN** the verdict says the query is a crisis and is not blocked

#### Scenario: Empty query
- **WHEN** `finos guard check --query ""` runs
- **THEN** it exits 2 before any check runs
