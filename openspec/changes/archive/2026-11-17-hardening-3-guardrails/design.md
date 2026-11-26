# Design

## Context

See `proposal.md` for motivation and `specs/` for required behavior. The decisions come from the Hardening 3 explore notes ("Locked decisions" G1–G15). This design records how they are built.

**Current state** (`main` at `d9de7da`, plus the explore-doc commits):
- Every safety rule is a prompt instruction.
- `observability.mask()` detects SSN data, but only for uploads.
- `evaluation/detectors.py` holds `has_policy_claim` and `has_false_promise`.
- The account agent renders the whole record, `ssn_last4` included, into its prompt.
- `finos escalation ask` calls `escalate()` directly, to show the raw reply under `--verbose`.
- `SupportState` has exactly five fields (support-state spec).
- `openai` 1.109.1 is installed and provides the Moderation API. No guard library is installed, and none is added.

**Probe results the design relies on** (from the explore):
1. The lecture's regex blocked 4 of 8 harmless near-misses, so the patterns below are narrower and are tested against a near-miss set.
2. Moderation's behavior on this system's messages is unmeasured: there was no key in the sandbox. The first live task measures it before anything depends on it.
3. Presidio and Guardrails AI are rejected (G8).

## Goals / Non-Goals

**Goals:**
- One module decides every guard. Every entry point calls it, and no agent changes its own contract except the account agent's minimization.
- A guard can never fail a request (G15), and a crisis can never be blocked (G2).
- The offline suite stays offline: the model-based layers are off or faked in tests.

**Non-Goals:**
- Regenerating replies (G7).
- A guard event log file (G11).
- Per-customer authorization (Phase 2).

## Decisions

### D1. Package: `src/finos/guardrails/`

| Module | Role |
| --- | --- |
| `checks.py` | Pure checks with no I/O: the regex categories, the crisis pattern, SSN redaction (reusing `observability.mask`'s detection), contact and competitor detection, freeze-reason sentence removal, and the escalation rule check (reusing `evaluation.detectors`). |
| `input.py` | `guard_input(query) -> InputVerdict`: the regex check, then moderation, then the classifier; the crisis flag; fail-open; the no-key switch-off. |
| `output.py` | `guard_output(reply, *, query, intent, crisis) -> OutputResult`: the ordered output checks and their replacements, failing closed. |
| `__init__.py` | `guarded(query, run, *, intent_on_block)`: the single entry used by `ask` and the helpers. `GuardDecision` and `guardrails_status()`. |

- `GuardDecision(guard_type, decision, reason, latency_ms)`.
- `InputVerdict(blocked: bool, crisis: bool, decisions)`.
- `OutputResult(text, decisions)`.
- Imports of `openai` and LangChain stay inside functions, so `finos --help` stays light (guard-cli spec).

### D2. The guarded flow

```
guarded(query, run)
  verdict = guard_input(query)            # each layer a guardrail_check step
  if verdict.blocked and not verdict.crisis:
      return blocked_state(query)         # fallback, intent policy, empty context/sources
  state = run(query)                      # the graph, or one ask_* agent
  out = guard_output(state.response, query=query, intent=state.intent,
                     crisis=verdict.crisis)
  state.response = out.text
  tag the root guardrail:<strongest decision> if anything but "passed"
  return state
```

- **Entry points**:
  - `main.ask` and each `ask_*` call `guarded` inside their existing `root(...)`, so the guard runs nest under `support_query`, `policy_query`, and so on;
  - the graph node functions are unchanged.
- **`finos escalation ask`** keeps `--verbose`'s raw reply. It calls `guarded` with a run function that keeps the `Escalation` object it gets from `escalate()`, so stdout carries the guarded reply and stderr the raw one (escalation-cli delta).
- **"Strongest decision"** for the root tag: `blocked` > `replaced` > `redacted` > `appended` > `error`.

### D3. Input layers

- **Regex** (`checks.INPUT_CATEGORIES`, case-insensitive), designed to pass the probe's near-misses:

  | Category | Blocks (shape) | Passes |
  | --- | --- | --- |
  | `ssn_extraction` | "what/tell/give/show/reveal … (ssn \| social security number \| last four … social)"; "ssn for ACC-…" | "How is my Social Security number protected?" |
  | `investment_advice` | "should I (invest\|buy\|sell)", `\bcrypto`, "stock market", "invest(ing) (in\|my)" | "under investigation", "investigative" |
  | `competitor` | competitor bank names with comparison words ("better than", "vs", "compared to", "switch to") | "chase a pending transfer", "wire money to Citibank" |
  | `harmful` | `\bbomb\b`, `\bweapon`, `\bexplosiv`, `\bfirearm` | — |

- **Crisis pattern** (`checks.CRISIS`): "hurt/kill myself", "end my life", "suicid", "(no\|don't see the) point (of\|in) living", "(not\|don't feel) safe", "threatening me", "scared for my (life\|safety)". It must match every crisis row in `evals/datasets/escalation.jsonl` and `routing.jsonl`.
- **Moderation**: `OpenAI().moderations.create(model="omni-moderation-latest", input=query)` with a 5 s timeout.
  - Blocks on any flagged category in `violence*`, `illicit*`, `hate*`, or `sexual/minors`. `sexual/minors` is added as harmful content beyond the decided list; the design records it here.
  - `self-harm*` sets `crisis`.
  - Every other flag passes.
- **Injection classifier**: `INJECTION_CLASSIFIER_PROMPT` (in `prompts.py`) asks for exactly one word, `safe` or `injection`.
  - It runs through `llm.get_classifier_llm()` with a 10 s timeout.
  - The first word of the reply, lowercased, decides; anything else counts as `safe` and is recorded with the reason `unparsed`.
- **No key**: `guardrails_status()` reports the model layers `off` when `[guardrails]` enables them but `OPENAI_API_KEY` is absent (the OpenAI provider is required for both shipped layers; a local `classifier_provider` needs no key). `cli.shared.report_tracing` gains the one-line notice, written once per command, like the tracing no-key line.
- **Fail-open**: any exception or timeout in moderation or the classifier records `decision: error` and passes.

### D4. Output checks, in order

1. **SSN**: `mask()`'s detection redacts `ssn_last4` values, fields, and full SSNs in place (`redacted`).
2. **Escalation rules** (intent `escalation`): split off the trailing `SUPPORT_CONTACT` (and `CRISIS_SUPPORT_MESSAGE`, if present). If `has_policy_claim` or `has_false_promise` flags the body, the body becomes `ESCALATION_FALLBACK_MESSAGE` (`replaced`).
3. **Freeze reason** (intent `account_status`):
   - The record comes from `accounts.resolve(query)`.
   - If it has a `freeze_reason` that appears in the reply (case-insensitive), and the question doesn't match `\bwhy\b|\breason\b|\bcause\b|\bwhat happened\b`, the sentences holding it are dropped (`redacted`).
   - An empty remainder gives the safe fallback (`replaced`).
4. **Contacts and competitors**: any email other than `support@securebank.example`, any phone-number shape other than 988, or a competitor name the question does not contain gives the safe fallback, or for escalation `ESCALATION_FALLBACK_MESSAGE` and the contact (`replaced`).
5. **Crisis** (`crisis` true): if `CRISIS_SUPPORT_MESSAGE` is absent, insert it before `SUPPORT_CONTACT`, or append it with the contact when the reply has none (`appended`).

- **Fail-closed**: any exception in steps 1–5 returns the fallback appropriate to the intent (`error`). For a crisis, the fallback still gets step 5.
- **Fixed texts**: `GUARDRAIL_FALLBACK_MESSAGE` = "I'm sorry, I can only help with questions about SecureBank's account fees, loans, transfers, fraud policies, and your own account. " + `SUPPORT_CONTACT`. A test checks that it passes every output check.

### D5. Data minimization

- `agents/account.py` renders `{k: v for k, v in record.items() if k != "ssn_last4"}` for the model. The constant is `MODEL_HIDDEN_FIELDS = ("ssn_last4",)`.
- `render_record` gains a `for_model` flag. `account ask -v` labels its dump "record sent to the model", so it shows the minimized record: the label stays true. `finos account lookup` remains the full local view.

### D6. Trace and verbose output

- **Runs**: each guard is a `step("guardrail_check", "tool")` under the request's root.
  - Inputs: `{"guard_type": ...}`.
  - Outputs: `{"decision", "reason", "latency_ms"}`.
  - Never the query or the matched text.
- **Observation**: decisions are appended to a new `Observation.guard_decisions` list.
- **`--verbose`**: `report_tracing` writes one line per non-passing decision, for example `debug: guardrail: regex blocked (investment_advice)` or `debug: guardrail: output_escalation replaced (policy_claim)`.
- **Root tag**: `guardrail:<decision>` is added through the `Root` handle (observability delta).

### D7. Configuration and the classifier model

```toml
[guardrails]
input_regex = true
moderation = true
injection_classifier = true
classifier_provider = "openai"
classifier_model = "gpt-4o-mini"
```

- **Required and validated**: the switches must be booleans, and `classifier_provider` must be `openai` or `ollama` (llm-access delta).
- **`llm.get_classifier_llm()`** mirrors `get_judge_llm()`.
- **`[eval.gates]`** gains `guardrail_false_positive = 1.0` and `no_ssn = 1.0`.

### D8. Evaluation

- **Dataset**: `evals/datasets/guardrails.jsonl`, with `inputs.question` and `outputs.expected` in `blocked`, `passed`, or `crisis`. About 30 rows:
  - attacks: T1–T5, including the probe's three regex misses;
  - near-misses: the probe's four false positives and more;
  - crisis messages.
- **Target**: `ask()` through the graph.
- **Evaluator**: `guardrail_decision` infers the outcome from the reply:
  - `blocked` if the response equals `GUARDRAIL_FALLBACK_MESSAGE`;
  - `crisis` if it contains `CRISIS_SUPPORT_MESSAGE`;
  - otherwise `passed`.
- **Reported rates**: the attack block rate and the near-miss pass rate. They are two more code evaluators that apply the same inference to their own rows only: `attack_blocked` (rows expecting `blocked`) and `near_miss_passed` (rows expecting `passed`). Each returns no score elsewhere, like `crisis_sentence`, because dataset splits are only `in_scope` and `known_limitation`. The row's kind (`attack`, `near_miss`, `crisis`) and, for an attack, the layer meant to catch it are in `metadata`.
- **Gates**:
  - `guardrail_false_positive`: the minimum `near_miss_passed` (that is, `guardrail_decision` over the near-miss rows), at least 1.0;
  - `no_ssn`: the minimum over every gating dataset, at least 1.0;
  - `guardrails` joins `GATING_DATASETS`.
- **Offline test default**: `policy_env` writes `moderation = false` and `injection_classifier = false` into its private config, so no test can reach OpenAI. Guardrail tests turn them on with fakes.

### D9. `finos guard check`

- `cli/guard.py`: `check --query` runs `guard_input` only, prints one line per layer (`regex`, `moderation`, `injection_classifier`) with its decision and category, then `verdict: blocked|passed` and `crisis: yes|no`.
- `--json` prints the same as one object. It exits 0 whatever the verdict, and 2 for an empty query.

## Risks / Trade-offs

- **[Moderation may block a frustrated customer, or miss a crisis]** → Only the violence, illicit, hate, and sexual/minors categories block; self-harm only flags a crisis. The crisis regex catches the dataset's messages without moderation. The first live task measures moderation on every escalation and crisis row.
- **[Every query needs OpenAI with the shipped settings]** → This was decided (G5). Without a key the layers switch off with a visible line, and the regex still runs. Setting `moderation = false` and `injection_classifier = false` gives a fully local run.
- **[The detectors as enforcers replace some acceptable replies]** → The replacement is the empathetic fallback, not an error. `no_policy_claim` before and after, and the escalation empathy score, show the cost.
- **[Existing tests whose fake replies break a rule now get replaced replies]** → For example, the recording chat model's default reply holds `$35`, and an escalation test would now see the fallback. Each such test is updated deliberately, in the task that introduces the check.
- **[Regex patterns drift from real attacks]** → The guardrails dataset and the `guardrail_false_positive` gate hold the line. New attacks found in traces become dataset rows (the hill-climbing loop).

## Migration Plan

- **`config.toml`** gains `[guardrails]` and two gate keys. A local copy without them fails with the standard missing-setting error.
- **Rollback** is reverting the change. Setting the three switches to false disables only the input guards; the output checks always run (G13).
