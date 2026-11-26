# Tasks

> **Apply last**, after `step-2-policy-agent-rag`, `step-3-account-agent`, and `step-4-escalation-agent` (design D9). Groups 1–6 are verified offline; group 7 is the live acceptance run. No dependency or configuration changes are needed.

## 1. Preconditions and branch

- [x] 1.1 Check that Steps 2–4 are applied: `policy_agent`, `account_agent`, and `escalation_agent` import and no longer raise `NotImplementedError`; `finos policy --help`, `finos account --help`, and `finos escalation --help` work; and `SUPPORT_CONTACT`, `CRISIS_SUPPORT_MESSAGE`, `ACCOUNT_NO_ID_MESSAGE`, and `NOT_FOUND_MESSAGE` import from `finos.prompts`. If any is missing, stop and apply those changes first.
- [x] 1.2 Create and switch to branch `step-5-supervisor-graph`; verify with `git branch --show-current`.
- [x] 1.3 Confirm that no dependency is needed (`langgraph` 0.2.76 is locked; no `grandalf`); verify `uv sync --locked` succeeds with `pyproject.toml` and `uv.lock` unchanged.

## 2. Supervisor

- [x] 2.1 Add `normalize_intent()` to `src/finos/agents/supervisor.py` per design D3; create `tests/test_supervisor.py` covering every row of the explore doc's §4 table, the support-state spec's two scenarios, and the distress-explanation case; verify `uv run pytest tests/test_supervisor.py` passes.
- [x] 2.2 Append `SUPERVISOR_SYSTEM_PROMPT` to `src/finos/prompts.py` with the exact text in design D2; add tests that it has no `{` or `}`, names the three categories, places distress or danger under escalation, makes policy the catch-all, has the subject rule, and lists the three exact tokens. Measure it with `tiktoken` (`gpt-4o-mini` encoding) and record the count in a comment above the constant and in design D2. Verify `uv run pytest tests/test_supervisor.py` passes.
- [x] 2.3 Implement `classify_query()` and `classify_intent()` per design D1, keeping the normalized-intent paragraph in the `classify_intent` docstring and removing the `NotImplementedError` note; implement `route_by_intent()` with its fallback. Using the shared fake chat model, test: prompt shape; `{x}` passing through; `classify_intent` returning exactly `{"intent"}` and not storing the raw reply; a raising fake propagating; routing for all three members and an unknown value. Verify `uv run pytest tests/test_supervisor.py` passes.
- [x] 2.4 Update `docs/systems-design-and-architecture.md` §5 per design D9 (few-shot decided, R3 normalization, distress, subject, and catch-all rules); verify with `grep -n -E "R3|distress|catch-all|by what the customer is asking" docs/systems-design-and-architecture.md` and by reading the section.

## 3. Graph and `ask()`

- [x] 3.1 Implement `build_support_agent()` in `src/finos/graph.py` per design D4, keeping the settings-first paragraph in its docstring (the existing scaffold test checks it) and correcting the return annotation. Fill in `tests/test_graph.py` (offline): settings are loaded first; fakes that fail if invoked are never invoked during the build; `data/chroma/` is not created; two builds return distinct objects; the compiled graph declares exactly the three conditional targets. Verify `uv run pytest tests/test_graph.py tests/test_scaffold.py` passes.
- [x] 3.2 Implement `ask()` in `src/finos/main.py` per design D5. Add offline tests where a fake classifier steers each intent to its specialist (specialists or their models patched): each final state passes `validate_state(strict=True, known_sources=<corpus filenames>)`; policy fields are set; account and escalation fields are empty; the escalation response ends with `SUPPORT_CONTACT`; an exception raised inside the graph propagates from `ask`. Verify `uv run pytest tests/test_graph.py` passes.
- [x] 3.3 Add `render_plantuml()` to `src/finos/graph.py` per design D6; add a golden-text test for the PlantUML output and a test that `draw_mermaid()` output names all four nodes; verify `uv run pytest tests/test_supervisor.py tests/test_graph.py` passes.
- [x] 3.4 Update `docs/systems-design-and-architecture.md` §2.2 (return type, path map) and §2.4 (`initial_state()`, the `SupportState` return, recorded extension points); verify by reading both sections.

## 4. Scaffold

- [x] 4.1 Convert the stub-list test in `tests/test_scaffold.py` into "no `NotImplementedError` in `src/finos`" per the modified project-scaffold requirement, keeping the import-without-credentials test; verify `uv run pytest tests/test_scaffold.py` passes and `grep -rn NotImplementedError src/finos` prints nothing.

## 5. CLI

- [x] 5.1 Create `src/finos/cli/supervisor.py` with `supervisor_app` (`no_args_is_help=True`) and register it in `src/finos/cli/main.py` with one `add_typer` line; verify `uv run finos supervisor --help` lists `ask`, `classify`, and `graph`, a bare `uv run finos supervisor` exits 2 without building the graph, and the root light-import test in `tests/test_cli.py` still passes.
- [x] 5.2 Implement `graph` per design D7 (`--format plantuml|mermaid`, default `plantuml`, unknown format exits 2); create `tests/test_cli_supervisor.py` with tests for both formats, the unknown format, and no model being invoked; verify `uv run pytest tests/test_cli_supervisor.py` passes.
- [x] 5.3 Implement `classify` per design D7; add tests for human and `--json` output, the raw reply appearing only on stderr under `--verbose`, no specialist being invoked, and an empty query exiting 2 before any model call; verify `uv run pytest tests/test_cli_supervisor.py` passes.
- [x] 5.4 Implement `ask` per design D7 (trailers: specialist, then `Intent:`; verbose diagnostics and the pointer line on stderr); add tests with fakes for each route's trailers, `--json` output passing `finos state validate --strict` on every route, identical stdout with and without `--verbose`, shared options in both positions, and a provider connection error exiting 1 with empty stdout under `--json`; verify `uv run pytest tests/test_cli_supervisor.py` passes.
- [x] 5.5 Add `docs/how-to-guide/cli-supervisor.md` for the `finos supervisor` commands, following `docs/how-to-guide/cli-policy.md` (back link, table of contents, options, per-command output and JSON shapes, exit codes, recipes); add one row to the README's "How-to guides" table and a link in `docs/how-to-guide/cli-overview.md`'s module list, and replace `cli-overview.md`'s "`finos run` arrives in Step 5" note; update `docs/systems-design-and-architecture.md` §8 (layout) and §10 (Step 5 row, `finos supervisor` instead of `finos run`), plus §9.4 (one call for an account query without a found ID); verify with `grep -rn -E "finos run|finos supervisor" docs/systems-design-and-architecture.md README.md docs/how-to-guide/` showing no remaining `finos run`, and check that every new link and `#anchor` resolves.

## 6. Full offline verification

- [x] 6.1 Run `uv run pytest` with `use_local_ollama_model` set to true and again set to false, and with `tracing` set to false, with no `.env` and no network; verify all pass and no `live` test runs, then restore `config.toml`.
- [x] 6.2 Run `openspec validate step-5-supervisor-graph --strict` and `openspec validate --all --strict`; verify both pass.

## 7. Live acceptance (developer machine)

- [x] 7.1 Add the parametrized `ROUTING_CASES` table from design D8 to `tests/test_graph.py`, with 7 hard rows (crisis included, asserted end to end) and 5 `xfail(strict=False)` rows, each with a reason; verify `uv run pytest` deselects them.
- [x] 7.2 With the configured provider reachable and the Step 2 index buildable, run `uv run finos supervisor ask -q "What is the overdraft fee?"`, `uv run finos supervisor ask -q "What is the balance on ACC-12345?" --json`, `uv run finos supervisor ask -q "I'm furious! Nobody is helping!"`, `uv run finos supervisor ask -q "Show my recent transactions"`, `uv run finos supervisor classify -q "I'm upset about \$105! What is your overdraft policy?" -v`, `uv run finos supervisor graph`, and `uv run pytest -m live tests/test_graph.py -v`. Verify every command exits 0; the overdraft answer contains `$35`; the balance answer contains `12,450.75` or `12450.75`; the escalation reply ends with `SUPPORT_CONTACT`; the no-ID query returns `ACCOUNT_NO_ID_MESSAGE`; the 7 hard live rows pass; the `xfail` rows pass or xfail. Record which baselines reproduced, and any XPASS, for the evaluation phase.
- [x] 7.3 Repeat 7.2 with `use_local_ollama_model = false` and an OpenAI key, if one is available, and note any routing differences, especially on the crisis row.
