# Spec Delta

## Purpose

Defines the `finos supervisor` command group, which runs the whole support system from a terminal, shows how a query is routed, and prints the graph's wiring, following the shared CLI conventions.

## ADDED Requirements

### Requirement: The supervisor module attaches as a command group
The CLI SHALL provide a `supervisor` command group with the commands `ask`, `classify`, and `graph`, registered with one line in the root module. It SHALL follow the cli-framework conventions: shared options in either position, help without starting the graph on a bare `finos supervisor`, and no heavy imports when the CLI is imported or help is shown.

#### Scenario: Group help
- **WHEN** `finos supervisor --help` runs
- **THEN** it exits 0 and lists `ask`, `classify`, and `graph`

#### Scenario: Bare group
- **WHEN** `finos supervisor` runs with no command
- **THEN** it prints help, exits 2, and invokes no model or graph

#### Scenario: Import stays light with the module registered
- **WHEN** a fresh Python process imports the CLI's root module
- **THEN** none of `langchain`, `langgraph`, or `chromadb` appear in its loaded modules

### Requirement: Ask runs the whole system
`finos supervisor ask --query <text>` SHALL build the graph, run the query through `ask`, and exit 0 for every route. In human mode it SHALL print the response, a blank line, the routed specialist's own trailer when its route has one (`Sources: …` for policy, `Account: …` for account), and finally `Intent: <intent>`. With `--json` it SHALL print the complete `SupportState`.

#### Scenario: Policy route
- **WHEN** `finos supervisor ask --query "What is the overdraft fee?"` runs and the query is routed to policy
- **THEN** it exits 0, stdout includes a `Sources:` line, and the last line is `Intent: policy`

#### Scenario: Escalation route
- **WHEN** the query is routed to escalation
- **THEN** stdout has no `Sources:` or `Account:` line, and the last line is `Intent: escalation`

#### Scenario: JSON output
- **WHEN** the command runs with `--json`
- **THEN** stdout is a JSON object with the five contract fields, and it passes `finos state validate --strict`

#### Scenario: Verbose shows what the final state reveals
- **WHEN** the command runs with `--verbose`
- **THEN** stderr shows the intent, the node taken, and the provider and model, plus the policy context or the account resolution for those routes, and a line pointing to `finos supervisor classify -v` and the trace for the raw supervisor reply, while stdout and the exit code are the same as without `--verbose`

### Requirement: Classify shows routing only
`finos supervisor classify --query <text>` SHALL classify the query with one model call, run no specialist, and print the intent and the node it routes to. With `--json` it SHALL print an object with `intent` and `node`. With `--verbose` it SHALL also write the model's raw reply to stderr.

#### Scenario: Routing only
- **WHEN** `finos supervisor classify --query "I want to speak to a manager"` runs
- **THEN** it exits 0, stdout shows `escalation` and `escalation_agent`, and no specialist runs

#### Scenario: Raw reply in verbose
- **WHEN** the command runs with `--verbose`
- **THEN** stderr contains the model's raw reply, and stdout is unchanged

### Requirement: Graph prints the wiring
`finos supervisor graph` SHALL print the graph's diagram text without calling a model: PlantUML by default, or Mermaid with `--format mermaid`. Any other format SHALL exit 2.

#### Scenario: Default format
- **WHEN** `finos supervisor graph` runs
- **THEN** it exits 0, and stdout is PlantUML text that starts with `@startuml`

#### Scenario: Mermaid format
- **WHEN** `finos supervisor graph --format mermaid` runs
- **THEN** it exits 0, and stdout is Mermaid text naming all four nodes

#### Scenario: Unknown format
- **WHEN** `finos supervisor graph --format png` runs
- **THEN** it exits 2 with a message on stderr

### Requirement: Supervisor commands report bad input and failures distinctly
An empty or whitespace-only `--query` SHALL exit 2 with a plain-text message on stderr, even with `--json`, before any model is called. A provider failure, or a specialist's environment failure such as a missing corpus or a corrupt accounts file, SHALL exit 1 with a one-line plain-text message on stderr, no traceback, and empty stdout, even with `--json`.

#### Scenario: Empty query
- **WHEN** `finos supervisor ask --query "  "` runs
- **THEN** it exits 2, stderr explains the problem, and no model is called

#### Scenario: Provider unavailable
- **WHEN** `finos supervisor ask` runs and the chat provider raises a connection error
- **THEN** it exits 1, stderr holds one plain-text line naming the problem, and stdout is empty
