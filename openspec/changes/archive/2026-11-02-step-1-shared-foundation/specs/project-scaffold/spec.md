# Spec Delta

## Purpose

Establishes the installable package, module boundaries, dependency stack, and secret-handling rules that Steps 2–5 build on, so each step can plug in without restructuring.

## ADDED Requirements

### Requirement: Project installs from a locked dependency set
The project SHALL install with `uv sync` on Python 3.12 from a committed `uv.lock`, using the LangChain 0.3 generation. Core dependencies SHALL NOT include `langchain-community`, which belongs to the hardening layers.

#### Scenario: Clean install
- **WHEN** `uv sync --locked` runs in a fresh checkout
- **THEN** it succeeds, and importing the OpenAI and Ollama chat models, the graph builder, the Chroma integration, and the text splitter all succeed

#### Scenario: Stack stays on the chosen generation
- **WHEN** the installed versions are listed
- **THEN** `langchain` is 0.3.x, `langgraph` is 0.2.x, and `langchain-community` is not a direct dependency

### Requirement: Later-step modules exist with locked signatures
The package SHALL provide importable modules for the policy, account, escalation, and supervisor agents, the graph, and the CLI. Each unimplemented function SHALL have its agreed signature and documentation, and calling it MUST raise an error naming the step that implements it.

#### Scenario: Stubs import without credentials
- **WHEN** every module is imported with no API key and no network access
- **THEN** all imports succeed

#### Scenario: Calling a stub
- **WHEN** an unimplemented function is called
- **THEN** it raises `NotImplementedError` naming its step

### Requirement: Secrets and local metadata are excluded from git
Git SHALL ignore `.env`, including when it is a symbolic link, and macOS metadata files (`.DS_Store`, `._*`). `.env.example` MUST remain trackable.

#### Scenario: Local secrets are ignored
- **WHEN** `git check-ignore` is run on `.env` and `.DS_Store`
- **THEN** both are reported as ignored

#### Scenario: Example file is not ignored
- **WHEN** `git check-ignore` is run on `.env.example`
- **THEN** it is not reported as ignored

### Requirement: Foundation tests run offline
The project's test suite SHALL pass with no API key, no `.env` values, and no network access.

#### Scenario: Offline test run
- **WHEN** `uv run pytest` runs on a machine with no network access or credentials
- **THEN** all tests pass
