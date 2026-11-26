# Spec Delta

## Purpose

Defines the `finos eval` command group, which pushes the evaluation datasets to LangSmith, runs experiments on one dataset and one variant at a time, and applies the quality gates from a terminal, following the shared CLI conventions.

## ADDED Requirements

### Requirement: The eval module attaches as a command group
The CLI SHALL provide an `eval` command group with the commands `push`, `run`, and `gate`, registered with one line in the root module. It SHALL follow the cli-framework conventions: shared options in either position, help without running anything on a bare `finos eval`, and no heavy imports when the CLI is imported or help is shown.

#### Scenario: Group help
- **WHEN** `finos eval --help` runs
- **THEN** it exits 0 and lists `push`, `run`, and `gate`

#### Scenario: Bare group
- **WHEN** `finos eval` runs with no command
- **THEN** it prints help, exits 2, and runs no experiment

#### Scenario: Import stays light with the module registered
- **WHEN** a fresh Python process imports the CLI's root module
- **THEN** none of `langchain`, `langgraph`, `chromadb`, or `langsmith` appear in its loaded modules

### Requirement: Push uploads the datasets with their versions
`finos eval push` SHALL upload every dataset, or the one named with `--dataset`, to LangSmith with its version, and SHALL report each dataset's name, example count, and version. A dataset whose version is already in LangSmith SHALL be reported as up to date and not uploaded again.

#### Scenario: First push
- **WHEN** `finos eval push --dataset routing` runs with a LangSmith key and the dataset is not yet in LangSmith
- **THEN** it exits 0 and stdout names `routing`, its example count, and its version

#### Scenario: No key
- **WHEN** `finos eval push` runs with no LangSmith key set
- **THEN** it exits 1 with one stderr line saying a LangSmith key is required

### Requirement: Run evaluates one dataset and one variant
`finos eval run --dataset <name>` SHALL run an experiment on that dataset with the configured provider, accepting `--set section.key=value` (repeatable), `--repetitions N`, and `--local`. stdout SHALL show each metric's mean (routing in-scope and over all rows), the number of scored outputs and errors, p50 and p95 latency, and, when uploaded, the experiment's URL. `--json` SHALL print the same as one JSON object. A completed run exits 0, whatever its scores.

#### Scenario: Local run
- **WHEN** `finos eval run --dataset routing --local` runs
- **THEN** it exits 0, uploads nothing, and stdout lists `routing_accuracy` in-scope and all-rows, the error count, and p50 and p95 latency

#### Scenario: Unknown dataset
- **WHEN** `finos eval run --dataset nope` runs
- **THEN** it exits 2 and stderr names the known datasets

#### Scenario: Dataset not pushed
- **WHEN** `finos eval run --dataset policy` runs with a LangSmith key and LangSmith holds a different version of the dataset
- **THEN** it exits 1, runs nothing, and stderr names both versions and `finos eval push`

### Requirement: Gate applies the thresholds
`finos eval gate` SHALL run the gating datasets with the configured provider and repetitions and SHALL exit 0 when every blocking threshold is met and no example has an error, or 1 otherwise. stdout SHALL list each metric with its score, threshold, and pass or fail, followed by the failing examples with their reasons. `--local` SHALL run it without LangSmith.

#### Scenario: Gate passes
- **WHEN** `finos eval gate --local` runs and every blocking metric meets its threshold with no errors
- **THEN** it exits 0 and every blocking metric is listed as pass

#### Scenario: Gate fails
- **WHEN** in-scope routing accuracy is 0.90
- **THEN** it exits 1, lists `routing_accuracy` as fail with 0.90 against 0.95, and names the misrouted examples

### Requirement: Eval commands report bad input and failures distinctly
Unusable input (an unknown dataset, a malformed `--set`, repetitions below 1) SHALL exit 2 before any model call. A valid command that cannot complete (a provider, judge, or LangSmith failure that stops the whole run, or a missing dataset file) SHALL exit 1 with one plain-text stderr line, also under `--json`.

#### Scenario: Malformed override
- **WHEN** `finos eval run --dataset policy --set chunk_size=100` runs (no section)
- **THEN** it exits 2 and stderr says overrides take the form `section.key=value`

#### Scenario: LangSmith unreachable
- **WHEN** `finos eval run --dataset routing` runs with a LangSmith key set and LangSmith cannot be reached
- **THEN** it exits 1 with one stderr line, and no partial experiment is reported as complete
