# Proposal

## Why

The account agent is the system's non-RAG path. It is the only specialist that reads structured customer data, and it is the system's only source of PII (`holder_name`, `ssn_last4`). Steps 4 and 5 assume it works, and the guardrails layer needs a documented baseline for how it answers PII requests. Today `account_agent` is a stub, nothing extracts an account ID, and the context doc leaves three Step 3 decisions open: not-found behavior, response format, and PII in responses.

## What Changes

- Implement `account_agent(state)` as a three-stage pipeline: extract the account ID with a regex, look the record up in `data/mock_accounts.json`, and have the shared chat model answer from that record. It returns only `response`.
- Resolve every query to exactly one outcome: **found**, **not found**, **no ID**, or **multiple IDs**. Only **found** calls the model. The other three return fixed message constants, so they are deterministic and free.
- Accept `ACC-12345`, `acc-12345`, `ACC 12345`, and `ACC12345`, normalizing each to `ACC-12345`. A wrong-length token such as `ACC-1234` counts as no ID.
- Add `ask_account(query)`, which runs the agent without the graph and returns a full `SupportState` with `intent` set to `account_status`.
- Add the account prompt and three message constants to `finos.prompts`. The prompt sends the full record but forbids revealing any SSN digits, always states a frozen or pending status, quotes `freeze_reason` only when asked why, and declines general policy questions.
- Add a stdlib-only `finos.accounts` module for extraction, loading, and lookup, which the CLI and tests reuse.
- Add the `finos account` command group: `ask`, `lookup` (the record, no model call), and `list` (the account IDs).
- Keep the default test suite offline. Real-model checks, and the account agent's five baseline failure modes, go behind the `live` marker from Step 2.
- Update `docs/systems-design-and-architecture.md` and the Step 3 explore doc, and add a `finos account` how-to guide (`docs/how-to-guide/cli-account.md`) linked from the README.

**Out of scope**: the supervisor and graph, the policy and escalation agents, multi-agent fan-out ("Does ACC-12345 qualify for the fee waiver?"), resolving "my account" (no identity and no history in the core build), comparing accounts, PII redaction and injection defense (guardrails layer), LLM-based ID extraction, template-only responses, a real database, caching, and retries.

## Capabilities

### New Capabilities

- `account-lookup`: Account ID extraction and normalization, loading the mock records, lookup, and resolving a query to one of four outcomes.
- `account-agent`: The account node, its prompt and PII stance, the fixed messages for the three non-found outcomes, how it writes `SupportState`, and the standalone `ask_account` helper.
- `account-cli`: The `finos account` commands `ask`, `lookup`, and `list`.

### Modified Capabilities

None. Registering the CLI group and the export follow existing requirements (cli-framework "Modules attach as command groups"; project-scaffold signatures), and the `live` marker comes from `step-2-policy-agent-rag`.

## Impact

- **Code**: new `src/finos/accounts.py` and `src/finos/cli/account.py`; `src/finos/agents/account.py` implemented; account prompts and constants added to `src/finos/prompts.py`; `ask_account` exported from `finos.agents`; one `add_typer` line in `src/finos/cli/main.py`.
- **Tests**: `tests/test_account.py` filled in; new `tests/test_accounts.py` and `tests/test_cli_account.py`; `tests/test_scaffold.py` stops listing `account_agent` as a stub.
- **Dependencies and configuration**: none. The pipeline uses stdlib `json` and `re` plus the existing `langchain_core` and `get_llm()`, and has no tunable settings.
- **Ordering**: apply after `step-2-policy-agent-rag`, which creates `prompts.py`, the `live` marker, and the `ask_*` and CLI patterns this change follows. Task 1.1 checks this.
- **Runtime**: one model call per found account; none otherwise. `finos account lookup` and `list` never import LangChain and never load settings.
- **Documents**: `docs/systems-design-and-architecture.md` (§3.2, §3.6, §4.2, §8, §10), new `docs/how-to-guide/cli-account.md` (linked from `README.md` and `docs/how-to-guide/cli-overview.md`), and the Step 3 explore notes.
