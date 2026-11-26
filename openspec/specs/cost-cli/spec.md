# cost-cli Specification

## Purpose

The `finos cost` command group: reads the audit log and reports what queries cost and how long they took, per intent and per provider, against the daily budget.

## Requirements

### Requirement: The cost module attaches as a command group
The CLI SHALL provide a `cost` command group with the command `report`, registered with one line in the root module, following the cli-framework conventions: shared options in either position, help on a bare `finos cost`, and no heavy imports when the CLI is imported or help is shown.

#### Scenario: Group help
- **WHEN** `finos cost --help` runs
- **THEN** it exits 0 and lists `report`

#### Scenario: Bare group
- **WHEN** `finos cost` runs with no command
- **THEN** it prints help and exits 2

#### Scenario: Import stays light
- **WHEN** a fresh Python process imports the CLI's root module
- **THEN** none of `langchain`, `langgraph`, `chromadb`, `langsmith`, or `openai` appear in its loaded modules

### Requirement: Report summarizes cost and latency per intent and provider
`finos cost report` SHALL read the audit log and print, per intent and per provider, the query count, total and mean cost, the guard share of cost, mean input and output tokens, p50 and p95 latency, and the count of unpriced queries, under a header naming the price date and the daily budget status. It SHALL call no model and need no key.

#### Scenario: Report over a log
- **WHEN** `finos cost report` runs over a log holding policy and account records from both providers
- **THEN** it exits 0 and prints one row per intent and provider with the fields above, and the header names `prices_as_of`

#### Scenario: Unpriced queries
- **WHEN** some records have a `null` cost
- **THEN** those queries are counted as unpriced and left out of the cost totals and means, and still counted in latency

### Requirement: Report filters by date and entry
`finos cost report` SHALL accept `--since DATE` and `--until DATE` (ISO dates, UTC, inclusive) and a repeatable `--entry NAME`. Without `--entry`, records from the `eval` and `live-test` entries SHALL be left out.

#### Scenario: Default leaves out evaluation traffic
- **WHEN** the log holds `supervisor-ask` and `eval` records and `finos cost report` runs without `--entry`
- **THEN** only the `supervisor-ask` records are summarized

#### Scenario: Date range
- **WHEN** `finos cost report --since 2026-11-18 --until 2026-11-19` runs
- **THEN** only records timestamped on those two UTC days are summarized

### Requirement: Report output as JSON
With `--json`, `finos cost report` SHALL print the same summary as one JSON object, with costs as numbers or `null`.

#### Scenario: JSON report
- **WHEN** `finos cost report --json` runs
- **THEN** stdout parses as one JSON object holding `prices_as_of`, the budget status, and the per-intent and per-provider rows

### Requirement: Report handles a missing or damaged log
A missing or empty audit log SHALL give an empty report and exit 0. An unparseable line SHALL be skipped and counted in one stderr line. An invalid date SHALL exit 2 with a message naming the option.

#### Scenario: No log yet
- **WHEN** `finos cost report` runs and the audit log does not exist
- **THEN** it exits 0 and reports no queries

#### Scenario: Bad date
- **WHEN** `finos cost report --since yesterday` runs
- **THEN** it exits 2 and stderr names `--since`
