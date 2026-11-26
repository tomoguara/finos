# Proposal

## Why

The three specialists (Steps 2–4) exist only as standalone `ask_*` paths. Nothing classifies a customer's query, routes it, or runs the system end to end. Routing is the system's most critical metric, because a wrong route makes every downstream metric meaningless. Steps 2–4 also gave routing consequences the context doc doesn't reflect:
- the crisis sentence exists only in the escalation agent;
- an account ID no longer implies an account question;
- the account agent answers ID-less queries without a model.

Step 5 also owes the support-state obligation that only a normalized intent reaches the state, and it must settle the `build_support_agent()` return shape that Step 1 left open. It completes the core build.

## What Changes

- Implement the supervisor:
  - `classify_query(query)` makes one model call and returns the raw reply and a normalized intent;
  - `classify_intent(state)` is the graph node and writes only `intent`;
  - `normalize_intent(raw)` lets the first whole-word vocabulary member win, defaulting to `policy`;
  - `route_by_intent(state)` maps an intent to a node, falling back to `policy_agent`.
- Add `SUPERVISOR_SYSTEM_PROMPT` to `finos.prompts`. It names distress or danger as `escalation`, classifies by what is asked rather than by tone or by an account number, and makes `policy` the explicit catch-all for anything else.
- Implement `build_support_agent()`, which returns the compiled LangGraph app. The graph has an explicit path map on the conditional edge. Building it loads settings first, makes no model call, builds no index, and caches nothing.
- Implement `ask(app, query)`, which runs the graph from `initial_state(query)` and returns the final `SupportState`. Exceptions propagate; only unrecognized model output falls back to `policy`.
- Add the `finos supervisor` command group:
  - `ask`: the full graph, with the specialist's trailer followed by `Intent:`;
  - `classify`: routing only; `-v` shows the raw reply;
  - `graph`: prints the wiring as PlantUML state-diagram text from the project's own renderer, or as Mermaid with `--format mermaid`.
- Keep the default test suite offline, including the normalization tests the support-state spec requires. Add a parametrized live routing table with 7 hard cases, including an end-to-end crisis-routing case, and 5 `xfail` baselines. Convert the scaffold stub test into a "no stubs remain" check.
- Correct `docs/systems-design-and-architecture.md` (§2.2, §2.4, §5, §8, §9.4, §10), add a `finos supervisor` how-to guide (`docs/how-to-guide/cli-supervisor.md`) linked from the README, annotate the Step 5 explore doc, and mark the CLI architecture doc's reserved `finos run` as superseded.

**Out of scope**: multi-agent fan-out; re-routing and retries; few-shot examples, structured output, `max_tokens`, and the account-ID routing shortcut (all recorded as experiments); run tags and metadata, and `ask(config=…)` or `ask(session_id=…)` (recorded as extension points only); evaluation datasets and the 0.95 routing gate; guardrails; cost tracking; per-agent model routing; rendering PlantUML to an image.

## Capabilities

### New Capabilities

- `supervisor-routing`: Intent classification (prompt rules, one model call, normalization of the raw reply) and mapping an intent to a specialist node.
- `support-graph`: The compiled graph (wiring, build-time guarantees, per-route final state), the `ask` invocation helper, and the graph's diagram rendering.
- `supervisor-cli`: The `finos supervisor` commands `ask`, `classify`, and `graph`.

### Modified Capabilities

- `project-scaffold`: "Later-step modules exist with locked signatures" is fulfilled once the supervisor, graph, and `ask` are implemented. The requirement changes to "no stub remains in the core build".

## Impact

- **Code**: `src/finos/agents/supervisor.py`, `src/finos/graph.py`, and `src/finos/main.py` implemented; `SUPERVISOR_SYSTEM_PROMPT` added to `src/finos/prompts.py`; new `src/finos/cli/supervisor.py`; one `add_typer` line in `src/finos/cli/main.py`.
- **Tests**: new `tests/test_supervisor.py` and `tests/test_cli_supervisor.py`; `tests/test_graph.py` filled in; `tests/test_scaffold.py` stub test converted.
- **Dependencies and configuration**: none. LangGraph 0.2.76 is already locked. PlantUML output is plain text, so neither Java nor `grandalf` is needed.
- **Ordering**: applied last, after `step-2-policy-agent-rag`, `step-3-account-agent`, and `step-4-escalation-agent`. Task 1.1 checks this.
- **Runtime**: two model calls per query (supervisor plus specialist). An account query without a found ID makes one, because the account agent answers it with a fixed message. The supervisor prompt is 141 tokens (measured; the explore estimated about 230), against the lecture's ~90, on every query.
- **Documents**: `docs/systems-design-and-architecture.md`, new `docs/how-to-guide/cli-supervisor.md` (linked from `README.md` and `docs/how-to-guide/cli-overview.md`), the Step 5 explore notes, and the Step 1b explore notes (`finos run` superseded).
