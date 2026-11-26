# project-scaffold Specification

## Purpose

Establishes the installable package, module boundaries, dependency stack, and secret-handling rules that Steps 2–5 build on, so each step can plug in without restructuring.

## Requirements

### Requirement: Project installs from a locked dependency set
The project SHALL install with `uv sync` on Python 3.12 from a committed `uv.lock`, using the LangChain 0.3 generation. `langchain-text-splitters` SHALL be a direct dependency, because the policy agent imports it, and `langsmith` SHALL be a direct dependency, because the observability support imports it. Core dependencies SHALL NOT include `langchain-community`, which belongs to the hardening layers.

#### Scenario: Clean install
- **WHEN** `uv sync --locked` runs in a fresh checkout
- **THEN** it succeeds, and importing the OpenAI and Ollama chat and embedding models, the graph builder, the Chroma integration, the text splitter, and the tracing client all succeed

#### Scenario: Stack stays on the chosen generation
- **WHEN** the installed versions are listed
- **THEN** `langchain` is 0.3.x, `langgraph` is 0.2.x, `langchain-text-splitters` and `langsmith` are declared in `pyproject.toml`, and `langchain-community` is not a direct dependency

### Requirement: Later-step modules exist with locked signatures
The package SHALL provide importable modules for the policy, account, escalation, and supervisor agents, the graph, and the `ask` invocation helper, each with its agreed signature and documentation. Once the core build is complete, no function in the package SHALL raise `NotImplementedError`.

#### Scenario: Stubs import without credentials
- **WHEN** every module is imported with no API key and no network access
- **THEN** all imports succeed

#### Scenario: Calling a stub
- **WHEN** the package's source is searched for `NotImplementedError` after Step 5 is applied
- **THEN** none is found, so no function remains a stub

### Requirement: Secrets and local metadata are excluded from git
Git SHALL ignore `.env`, including when it is a symbolic link, macOS metadata files (`.DS_Store`, `._*`), and the generated vector index in `data/chroma/`. `.env.example` and the policy documents MUST remain trackable.

#### Scenario: Local secrets are ignored
- **WHEN** `git check-ignore` is run on `.env` and `.DS_Store`
- **THEN** both are reported as ignored

#### Scenario: Generated index is ignored
- **WHEN** `git check-ignore` is run on a file inside `data/chroma/`
- **THEN** it is reported as ignored

#### Scenario: Example file is not ignored
- **WHEN** `git check-ignore` is run on `.env.example`
- **THEN** it is not reported as ignored

#### Scenario: Corpus is not ignored
- **WHEN** `git check-ignore` is run on `data/policy-docs/account_fees.md`
- **THEN** it is not reported as ignored

### Requirement: Foundation tests run offline
The project's default test run SHALL pass with no API key, no `.env` values, no Ollama host, and no network access. Tests that need real models SHALL carry a `live` marker and SHALL be excluded from the default run, and a developer SHALL be able to run them on request.

#### Scenario: Offline test run
- **WHEN** `uv run pytest` runs on a machine with no network access or credentials
- **THEN** all selected tests pass and no `live` test is run

#### Scenario: Live tests on request
- **WHEN** `uv run pytest -m live` runs
- **THEN** only the `live` tests are selected, and they use the models `config.toml` selects
