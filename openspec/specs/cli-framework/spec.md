# cli-framework Specification

## Purpose

Defines the `finos` command line that every module plugs into: how it is started, how modules attach, and the options, exit codes, and output streams they all share.

## Requirements

### Requirement: CLI is available as a script and a module
The project SHALL provide the command line both as an installed `finos` script and as `python -m finos`, with the same behavior through either route.

#### Scenario: Installed script
- **WHEN** `uv run finos --help` runs after `uv sync`
- **THEN** it exits 0 and lists the `state` module

#### Scenario: Module invocation
- **WHEN** `uv run python -m finos state show` runs
- **THEN** it exits 0 with the same output as `uv run finos state show`

### Requirement: Modules attach as command groups
Each module SHALL be a command group under the root command, invoked as `finos <module> <command> [options]`. Adding a module MUST NOT require changes to any existing module or to the shared options.

#### Scenario: Group help
- **WHEN** `finos state --help` runs
- **THEN** it exits 0 and lists all six `state` commands

### Requirement: Bare commands show help and never start the graph
Running `finos` or a module with no command SHALL print help and exit 2. It MUST NOT invoke a model or the graph.

#### Scenario: Bare root command
- **WHEN** `finos` runs with no arguments
- **THEN** it prints the help screen and exits 2

#### Scenario: Bare module command
- **WHEN** `finos state` runs with no command
- **THEN** it prints the group help and exits 2

### Requirement: Version is reported from the installed package
The root command SHALL accept `--version` and `-V`, which print the installed package version and exit 0. The flag SHALL work without a `config.toml` or a `pyproject.toml` present.

#### Scenario: Version flag
- **WHEN** `finos --version` runs
- **THEN** it prints `finos` followed by the installed package version and exits 0

### Requirement: Shared options work in either position
Every command SHALL accept `--json/-j`, `--verbose/-v`, and `--no-color` both before the module name and after the command. A flag set in either position SHALL take effect, and setting it in both SHALL behave the same as setting it once.

#### Scenario: Flag before the module
- **WHEN** `finos --json state show` runs
- **THEN** it exits 0 and prints the same JSON as `finos state show --json`

#### Scenario: Flag after the command
- **WHEN** `finos state show --no-color` runs
- **THEN** it exits 0 and its output contains no ANSI escape sequences

#### Scenario: Flag in both positions
- **WHEN** `finos -v state show -v` runs
- **THEN** it exits 0 with the same output as setting `-v` once

#### Scenario: Shared options appear in command help
- **WHEN** `finos state show --help` runs
- **THEN** the help lists `--json`, `--verbose`, and `--no-color`

### Requirement: The json flag only selects output format
`--json` SHALL be a boolean flag that requests machine-readable output and MUST NOT take a value or supply input on any command, in any module. Commands whose only output is already JSON SHALL accept the flag and produce the same output.

#### Scenario: Value after the flag is rejected
- **WHEN** `finos state validate --json '{"query":"test"}'` runs
- **THEN** it exits 2, because the JSON text is an unexpected argument and not input

### Requirement: Color can be disabled
Commands SHALL emit no ANSI escape sequences when `--no-color` is set, when the `NO_COLOR` environment variable is set to a non-empty value, or when output is not a terminal.

#### Scenario: Environment variable
- **WHEN** a command that prints a colored verdict runs with `NO_COLOR=1` and color otherwise enabled
- **THEN** its output contains no ANSI escape sequences

### Requirement: Verbose output goes to stderr
`--verbose` SHALL write diagnostic detail to stderr only. It MUST NOT change what a command writes to stdout or its exit code.

#### Scenario: Stdout is unchanged
- **WHEN** a command runs with and without `--verbose` on the same input
- **THEN** stdout and the exit code are identical in both runs

### Requirement: Exit codes distinguish verdicts from unusable input
Across all modules, a successful command SHALL exit 0, input that was understood but rejected on its merits SHALL exit 1, and unusable invocations or input SHALL exit 2. Exit-2 messages SHALL go to stderr as plain text, including when `--json` is set.

#### Scenario: Unknown option
- **WHEN** a command runs with an option it does not define
- **THEN** it exits 2 and reports the problem on stderr

### Requirement: The CLI loads without heavy dependencies or settings
Importing the CLI and running `--help` MUST NOT import the LangChain, LangGraph, or Chroma packages, and MUST NOT load settings. Each module SHALL import heavy dependencies inside the command that needs them.

#### Scenario: Import stays light
- **WHEN** a fresh Python process imports the CLI's root module
- **THEN** none of `langchain`, `langgraph`, or `chromadb` appear in its loaded modules
