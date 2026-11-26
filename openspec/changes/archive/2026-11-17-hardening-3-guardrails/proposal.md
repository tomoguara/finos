# Proposal

## Why

Every safety rule in the system lives only in a prompt: never reveal SSN digits, no amounts or promises in an escalation reply, quote the freeze reason only when asked, no invented contact details. A model may ignore a prompt under pressure. Hardening 1 caught a shipped model breaking three of these rules, and Hardening 2 measured it (`no_policy_claim` 0.800 with `qwen3-coder-next`). Guardrails turn the non-negotiable rules into code that always runs [lecture p. 43]. Observability makes every guard decision visible, and Evaluation measures that guards stop attacks without blocking legitimate questions. The decisions are recorded in the Hardening 3 explore notes ("Locked decisions", G1–G15).

## What Changes

- **Input guards** before any model, cheapest first:
  - a regex tuned to this system: the lecture's patterns blocked 4 of 8 harmless near-misses in the explore probe;
  - the OpenAI Moderation API;
  - an injection classifier on a configured model, shipped as `gpt-4o-mini`.

  All three are on by default. Without an OpenAI key, the two model layers switch off with one stderr line. Input layers fail open. A blocked query gets one safe fallback that never says why.
- **Output guards** on every reply, with fixed replacements and no regeneration. They fail closed.
  - SSN data is redacted.
  - An escalation reply that states an amount or policy, or makes a promise, gets its body replaced by the empathetic `ESCALATION_FALLBACK_MESSAGE`.
  - A volunteered freeze reason is dropped.
  - Contact details other than the official ones, and competitor names, get the fallback.
- **The crisis path is never blocked.** A self-harm or danger signal overrides every input block. The output guard appends `CRISIS_SUPPORT_MESSAGE` if the reply lacks it.
- **Data minimization**: the account record reaches the model without `ssn_last4`.
- **One choke point**: `ask()`, `ask_policy`, `ask_account`, and `ask_escalation` apply the guards, and `finos escalation ask` moves onto the guarded path.
  - `SupportState` keeps its five fields: a blocked query returns the fallback with intent `policy`.
  - The decision is a `guardrail_check` run in the trace, with a `guardrail:<decision>` root tag, and a `--verbose` line.
- **Evaluation**:
  - a `guardrails` dataset: attacks, harmless near-misses, and crisis messages;
  - a `guardrail_decision` evaluator;
  - two new blocking gates: every near-miss passes, and no SSN data in any reply.
- **Configuration and CLI**: a required `[guardrails]` section, and a `finos guard check -q` command that shows each input layer's decision without running an agent.
- **Docs**: a new `docs/how-to-guide/guardrails.md`, plus updates to the setup and evaluation guides, `testing.md`, `docs/systems-design-and-architecture.md` §9.3, and the project to-do list. This change closes the to-do item "Enforce the account and escalation prompt rules in code".

**Out of scope**:
- Microsoft Presidio and Guardrails AI. Their dependency weight, and Presidio's redaction of holder names, outweigh the benefit for fictional data. Presidio is recorded on the project to-do list.
- A separate guardrail event log: the trace holds every decision, and Cost's audit log comes later.
- Customer identity: anyone can ask about any account until Phase 2 sessions. Recorded on the project to-do list.
- Prompt rewrites, retention enforcement, and Cost.

## Capabilities

### New Capabilities

- `guardrails`:
  - the input layers and their order;
  - the crisis signal;
  - the output checks and their replacements;
  - the safe fallback;
  - fail-open inputs and fail-closed outputs;
  - every entry point guarded;
  - guard runs in the trace and the `--verbose` lines;
  - the no-key switch-off.
- `guard-cli`: the `finos guard` command group (`check`).

### Modified Capabilities

- `account-agent`: the found answer is grounded in the record without `ssn_last4`.
- `support-graph`: `ask` applies the guardrails before and after the graph; a blocked query never invokes it.
- `escalation-cli`: `ask` runs the escalation agent through the guardrails.
- `observability`: the root tag vocabulary gains `guardrail:<decision>`.
- `evaluation`:
  - the `guardrails` dataset;
  - the `guardrail_decision` evaluator;
  - the gates `guardrail_false_positive` and `no_ssn`.
- `llm-access`:
  - a required, validated `[guardrails]` section with shipped values;
  - the classifier model through the provider-neutral helper.

## Impact

- **Code**:
  - New:
    - `src/finos/guardrails/` (`input.py`, `output.py`, `checks.py`);
    - `src/finos/cli/guard.py`.
  - Changed:
    - `src/finos/main.py` and the three `ask_*` helpers (guarded);
    - `src/finos/agents/account.py` (minimization);
    - `src/finos/cli/escalation.py` (the guarded path);
    - `src/finos/prompts.py` (`GUARDRAIL_FALLBACK_MESSAGE`, the classifier prompt);
    - `src/finos/llm.py` (`get_classifier_llm`);
    - `src/finos/config.py` (`[guardrails]`);
    - `src/finos/observability.py` (the `guardrail:*` tag);
    - `src/finos/evaluation/` (the dataset, evaluator, and gates);
    - `src/finos/cli/main.py` (one registration line).
- **Data**: `evals/datasets/guardrails.jsonl`.
- **Configuration**: `config.toml` gains `[guardrails]`, and two new keys in `[eval.gates]`.
- **Dependencies**: none new. The `openai` client already provides the Moderation API.
- **Runtime**:
  - With an OpenAI key, every query adds a Moderation call (about 100 ms) and a classifier call before any agent.
  - Blocked queries make no agent model call at all.
  - Without a key, only the regex runs.
- **Tests**:
  - New: `tests/test_guardrails.py` and `tests/test_cli_guard.py`, offline, with the model layers faked.
  - Updated: the account prompt test (no `ssn_last4`), the evaluation and gate tests, and `tests/test_llm.py`.
- **Secrets**: no new ones. With the model layers on, `OPENAI_API_KEY` is needed even under the local provider.
