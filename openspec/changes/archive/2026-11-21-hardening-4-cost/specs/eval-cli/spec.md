# Spec Delta

## ADDED Requirements

### Requirement: Compare prints an experiment before and after
`finos eval compare <before.json> <after.json>` SHALL read two saved `finos eval run --json` outputs and print, for each metric, the before and after values and their difference, each gate's pass or fail on both sides, and the before and after cost per output and p50/p95 latency. It SHALL call no model and need no key. With `--json` it SHALL print the same as one JSON object.

#### Scenario: Variant compared with the baseline
- **WHEN** `finos eval compare baseline.json top_k_2.json` runs on two results of the policy dataset
- **THEN** it exits 0 and prints each metric, cost, and latency before and after, with the difference

#### Scenario: Different datasets
- **WHEN** the two files hold results of different datasets or dataset versions
- **THEN** it exits 2 and stderr names both

#### Scenario: Unreadable file
- **WHEN** a file is missing or is not a `finos eval run --json` output
- **THEN** it exits 2 and stderr names the file

### Requirement: Run reports cost
`finos eval run` SHALL also show, on stdout and in `--json`, the cost per output (mean, p50, p95, and total) with the guard share, the count of outputs with unknown cost, the price date, and, when a judge ran, the judge's calls, tokens, and cost on their own line.

#### Scenario: Local run with cost
- **WHEN** `finos eval run --dataset routing --local` runs
- **THEN** stdout lists the cost per output and the price date beside p50 and p95 latency

#### Scenario: Judge cost line
- **WHEN** `finos eval run --dataset escalation` runs with the judge
- **THEN** stdout carries a judge line of the form `judge: 10 calls, 3630+170 tokens, $0.000647`

## MODIFIED Requirements

### Requirement: The eval module attaches as a command group
The CLI SHALL provide an `eval` command group with the commands `push`, `run`, `gate`, and `compare`, registered with one line in the root module. It SHALL follow the cli-framework conventions: shared options in either position, help without running anything on a bare `finos eval`, and no heavy imports when the CLI is imported or help is shown.

#### Scenario: Group help
- **WHEN** `finos eval --help` runs
- **THEN** it exits 0 and lists `push`, `run`, `gate`, and `compare`

#### Scenario: Bare group
- **WHEN** `finos eval` runs with no command
- **THEN** it prints help, exits 2, and runs no experiment

#### Scenario: Import stays light with the module registered
- **WHEN** a fresh Python process imports the CLI's root module
- **THEN** none of `langchain`, `langgraph`, `chromadb`, or `langsmith` appear in its loaded modules
