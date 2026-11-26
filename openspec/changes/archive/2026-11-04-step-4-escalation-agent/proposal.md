# Proposal

## Why

The escalation agent handles complaints, frustration, and requests for a person. It is the specialist most likely to receive emotionally charged and misrouted input, including the lecture's "I'm upset about $105! What is your overdraft policy?". Its reply must be warm, must offer contact details the corpus doesn't hold, and must make no policy claim and no promise the system can't keep. Today `escalation_agent` is a stub. The context doc says the reply comes from "a fixed empathy template" (§1) but also from a model call (§4.3), suggests "I'll connect you with a specialist" though no handoff mechanism exists, and gives a contact address that Steps 2 and 3 ruled out.

## What Changes

- Implement `escalation_agent(state)` as a two-stage pipeline: the shared chat model writes 2–4 empathetic sentences, then code appends the official `SUPPORT_CONTACT` block (a hybrid). It returns only `response`.
- Add `ask_escalation(query)`, which runs the agent without the graph and returns a full `SupportState` with `intent` set to `escalation`.
- Add `ESCALATION_SYSTEM_PROMPT` to `finos.prompts`, built on the lecture's four G-Eval empathy criteria. It forbids every amount, percentage, time limit, and policy statement, even ones the customer mentions; forbids claiming a transfer, escalation, case, or callback; forbids promising an outcome or timeline; asks for a calm reply to anger or threats; and requires the reply to include `CRISIS_SUPPORT_MESSAGE` verbatim when the customer expresses thoughts of self-harm or being in danger.
- Add `CRISIS_SUPPORT_MESSAGE` (988 for US customers, local emergency services or a crisis line elsewhere) and `ESCALATION_FALLBACK_MESSAGE` (used when the model returns empty text) to `finos.prompts`. Reuse `SUPPORT_CONTACT`, which `step-3-account-agent` defines.
- Add the `finos escalation` command group: `ask`, and `contact` (the fixed texts, without a model).
- Keep the default test suite offline. Add two test helpers, `has_policy_claim()` and `has_false_promise()`; three hard live tests, including the crisis sentence; and five live `xfail` baselines.
- Correct `docs/systems-design-and-architecture.md` §1, §3.4, §4.3, §9.3, and §10, add a `finos escalation` how-to guide (`docs/how-to-guide/cli-escalation.md`) linked from the README, and annotate the Step 4 explore doc.

**Out of scope**: supervisor routing and the emotional-framing misroute itself (Step 5); the graph and `ask()`; a real handoff (ticketing, queues, callbacks); locale detection, which needs a new state field (Phase 2); per-agent model routing; guardrails, including any deterministic output check, the Moderation API, and Presidio; G-Eval and other evaluation infrastructure; cost tracking, caching, retries, and streaming.

## Capabilities

### New Capabilities

- `escalation-agent`: The escalation node, its prompt rules, how the response is assembled from model text and the contact block, the crisis sentence, the empty-reply fallback, how it writes `SupportState`, and the standalone `ask_escalation` helper.
- `escalation-cli`: The `finos escalation` commands `ask` and `contact`.

### Modified Capabilities

None in `openspec/specs/`. The `live` marker comes from Step 2 (applied) and `SUPPORT_CONTACT` from the not-yet-applied `step-3-account-agent`; the CLI registration and export follow existing requirements.

## Impact

- **Code**: `src/finos/agents/escalation.py` implemented; new `src/finos/cli/escalation.py`; escalation constants added to `src/finos/prompts.py`; `ask_escalation` exported from `finos.agents`; one `add_typer` line in `src/finos/cli/main.py`.
- **Tests**: `tests/test_escalation.py` filled in; new `tests/test_cli_escalation.py` and `tests/helpers.py`; `tests/test_scaffold.py` stops listing `escalation_agent` as a stub.
- **Dependencies and configuration**: none.
- **Ordering**: apply after `step-2-policy-agent-rag` and `step-3-account-agent`. Task 1.1 checks this.
- **Runtime**: one model call per query, with a system prompt of about 300 tokens, against the lecture's ~120 (an accepted trade-off; trimming it is a cost experiment). `finos escalation contact` never loads settings or LangChain.
- **Real-world text**: `CRISIS_SUPPORT_MESSAGE` names the real US 988 Suicide & Crisis Lifeline. It is the only real phone number in the system, and it is there deliberately.
- **Documents**: `docs/systems-design-and-architecture.md`, new `docs/how-to-guide/cli-escalation.md` (linked from `README.md` and `docs/how-to-guide/cli-overview.md`), and the Step 4 explore notes.
