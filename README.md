# finos

A multi-agent customer support system for a fictional bank, SecureBank. A
supervisor classifies each customer query into one intent and routes it to
exactly one specialist: a policy agent that answers from a retrieved
document corpus, an account agent that looks up mock account records, or an
escalation agent that hands off to a human.

Built with LangGraph and LangChain 0.3, on Python 3.12, managed with `uv`.

## Contents

- [Status](#status)
- [Quick start](#quick-start)
- [How-to guides](#how-to-guides)
- [Layout](#layout)

## Status

Step 1 (shared foundation) is in place: the `SupportState` contract, the
settings loader, the `get_llm()` helper, the policy corpus, and the mock
accounts. Step 1b adds the `finos` command line and its `finos state`
toolkit for inspecting, validating, and converting state values. Step 2
implements the policy agent: retrieval over the policy corpus from an
on-disk Chroma index, grounded answers, the standalone `ask_policy()`
helper, and the `finos policy` commands. Step 3 implements the account
agent: account ID extraction, lookup in the mock records, answers from the
full record (with fixed messages for no ID, an unknown ID, or several
IDs), the standalone `ask_account()` helper, and the `finos account`
commands. Step 4 implements the escalation agent: an empathetic model
reply followed by the fixed official support contact, a crisis sentence
for customers in distress, the standalone `ask_escalation()` helper, and
the `finos escalation` commands. Step 5 completes the core build: the
supervisor classifies each query into one intent, a LangGraph graph routes
it to exactly one specialist, `ask()` runs the whole system, and the
`finos supervisor` commands run it from a terminal, show routing, and print
the wiring. No stubs remain.

## Quick start

```sh
uv sync                                  # install the exact versions in uv.lock
cp .env.example .env                     # then add keys only if you need them
uv run pytest                            # offline suite: no keys, no network
```

The default provider is a local Ollama host. Pull the embedding model
once, then try the agents:

```sh
ollama pull qwen3-embedding:latest
uv run finos policy ingest
uv run finos policy ask --query "What is the overdraft fee?"
uv run finos account ask --query "What is the balance on ACC-12345?"
uv run finos escalation ask --query "I'm furious! Nobody is helping!"
uv run finos supervisor ask --query "What is the overdraft fee?"   # the whole system
```

To use OpenAI instead, set `use_local_ollama_model = false` in
`config.toml` and put `OPENAI_API_KEY` in `.env`. If you have no
`LANGCHAIN_API_KEY`, set `[langsmith] tracing = false`. Details are in
[Setup and configuration](docs/how-to-guide/setup-and-configuration.md).

## How-to guides

The detailed guides live in [`docs/how-to-guide/`](docs/how-to-guide/):

| Guide | Covers |
| ----- | ------ |
| [Setup and configuration](docs/how-to-guide/setup-and-configuration.md) | installing, `.env` secrets, choosing Ollama or OpenAI, LangSmith tracing |
| [Command line overview](docs/how-to-guide/cli-overview.md) | how the `finos` CLI is organised, shared options (`--json`, `--verbose`, `--no-color`), exit codes |
| [`finos state`](docs/how-to-guide/cli-state.md) | inspecting, validating, and converting `SupportState` values; fixture and debugging recipes |
| [`finos policy`](docs/how-to-guide/cli-policy.md) | `ask`, `search`, `ingest`; the on-disk index; RAG settings; quick-test and optimization recipes |
| [`finos account`](docs/how-to-guide/cli-account.md) | `ask`, `lookup`, `list`; the four outcomes; ID formats; PII and status rules; quick-check recipes |
| [`finos escalation`](docs/how-to-guide/cli-escalation.md) | `ask`, `contact`; how a reply is built; what the agent never says; the crisis sentence; quick-check recipes |
| [`finos supervisor`](docs/how-to-guide/cli-supervisor.md) | the whole system: `ask`, `classify`, `graph`; how routing works; routing-accuracy and crisis-path recipes |
| [Debugging with traces](docs/how-to-guide/debugging-with-traces.md) | the LangSmith run tree, tags and metadata, finding a trace, the four-step debugging workflow, worked cases, SSN masking |
| [Guardrails](docs/how-to-guide/guardrails.md) | the input layers (regex, moderation, injection classifier), the crisis rule, the output checks and their fixed replacements, data minimization, `finos guard check`, reading guard decisions |
| [Cost](docs/how-to-guide/cost.md) | what a query costs and what is priced, the price table, the audit log (no query text) and its retention, alerts and the daily budget, `finos cost report`, the `-v` cost line, the before/after method with `finos eval compare` |
| [Evaluation](docs/how-to-guide/evaluation.md) | the evaluation datasets, evaluators and judge, `finos eval push`/`run`/`gate`, variants, judge calibration, quality gates, the hill-climbing loop |
| [Testing](docs/how-to-guide/testing.md) | the offline suite, opt-in live tests, and the recorded baselines |

[Systems design and architecture](docs/systems-design-and-architecture.md) is the
full design reference, with diagrams of the data flow, each agent, and the guardrails.

## Layout

```
config.toml          non-secret settings (committed)
.env                 secrets only (git-ignored)
data/policy-docs/    the four SecureBank policy documents
data/chroma/         the on-disk policy index (git-ignored, rebuilt on demand)
logs/                the cost audit log, audit_log.jsonl (git-ignored)
data/mock_accounts.json
src/finos/           the installable package
src/finos/cli/       the `finos` command line
openspec/            spec-driven change artifacts
docs/how-to-guide/   the how-to guides linked above
docs/systems-design-and-architecture.md
docs/images/         design diagrams (PlantUML sources and PNGs)
```

Each step's archived OpenSpec change records its design decisions,
including where the step departed from the original plan:

- Step 1: `openspec/changes/archive/2026-11-02-step-1-shared-foundation/design.md`
- Step 1b: `openspec/changes/archive/2026-11-03-step-1b-cli-state-toolkit/design.md`
- Step 2: `openspec/changes/archive/2026-11-04-step-2-policy-agent-rag/design.md`

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
