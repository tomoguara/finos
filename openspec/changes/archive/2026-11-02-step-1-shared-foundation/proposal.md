# Proposal

## Why

Steps 2–5 each build one agent of the SecureBank support system, and they only stay self-contained if they plug into the same state contract, layout, data, and LLM access. The repo today is an empty `uv` package, and the planning documents disagree on where code and data live and on how settings are managed, so these need settling before any agent is written.

## What Changes

- Add the `SupportState` contract: exactly five fields, with the intent vocabulary defined alongside it.
- Create the project tree under the existing `src/finos/` package, including signature-only stubs for the agents, graph, and CLI that Steps 2–5 will fill in.
- Pin the class-compatible 0.3.x LangChain stack, plus `langchain-ollama` and `langchain-chroma`, with exact versions locked in `uv.lock`.
- Add one shared LLM helper that selects local Ollama or OpenAI, returning a provider-neutral chat model.
- Separate settings from secrets: non-secret settings move to a committed `config.toml`, and `.env` holds secrets only.
- Control LangSmith tracing from `config.toml`, on by default under the `finos` project. `LANGCHAIN_API_KEY` stays in `.env`.
- Add four originally written policy documents that use the lecture's facts and keep its deliberate replacement-card conflict.
- Add four mock accounts with enough data for transaction queries and the later SSN-leak guardrail demo.
- Ignore `.env` and macOS metadata in git. `.env` is currently **not** ignored and points at a shared secrets file.
- Update the context document where these decisions supersede it (§3.3, §6, §7, §8, §9.1).

**Out of scope**: agent prompts, RAG pipeline, graph wiring, supervisor logic, session management, and all hardening layers. Turning on tracing is the only observability work here; `@traceable`, tags, sampling, and dashboards stay in the hardening layer.

## Capabilities

### New Capabilities

- `support-state`: The shared state contract that every agent, the graph, and the evaluation layers read and write.
- `llm-access`: How the system selects and configures its chat model, and how settings stay separate from secrets.
- `policy-corpus`: The banking policy documents the policy agent will retrieve from, including the facts evaluations depend on.
- `mock-accounts`: The mock account records the account agent will look up.
- `project-scaffold`: The installable package, module boundaries, dependency stack, and secret-handling rules that later steps build on.

### Modified Capabilities

None. `openspec/specs/` is empty.

## Impact

- **Code**: new modules under `src/finos/`; the `finos` script entry point moves from `finos:main` to `finos.main:main`.
- **Dependencies**: `pyproject.toml` and `uv.lock` go from empty to the full core stack.
- **New top-level files**: `config.toml`, `.env.example`, and `data/` contents.
- **Runtime**: the shipped configuration points at a local Ollama endpoint (`localhost:11434`), so a machine without Ollama running must either point `[ollama] base_url` at the host that has it or switch providers in `config.toml`. Tracing is on by default, so prompts and responses go to LangSmith during the core build; this is accepted.
- **Documents**: the context document is moved to `docs/systems-design-and-architecture.md` and updated. The external explore document is not changed; `design.md` records where this change departs from it.
