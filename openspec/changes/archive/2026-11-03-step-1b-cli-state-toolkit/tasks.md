# Tasks

> **Obligations on later steps (design D9).** This change does not implement either agent, but `validate` depends on both rules. Group 3 records them where those steps will see them, and the requirements are in `specs/support-state/spec.md`.
>
> - **Step 2** must store bare filenames in `retrieved_sources` and add a test for it, or `--strict` rejects every real policy state.
> - **Step 5** must write only a normalized vocabulary member to `intent` and add a test for it, or `validate` rejects states the graph routed correctly.

## 1. Branch and dependency

- [x] 1.1 Create and switch to branch `step-1b-cli-state-toolkit`; verify with `git branch --show-current`.
- [x] 1.2 Add `typer>=0.27,<0.28` to `pyproject.toml` dependencies and run `uv lock`; verify `uv sync --locked` succeeds and `uv pip show typer` still reports 0.27.3.

## 2. State contract additions

- [x] 2.1 Add `FieldInfo`, `FIELD_METADATA`, and `PLANNED_FIELDS` to `src/finos/state.py` per design D4, and add tests to `tests/test_state.py` that the metadata keys equal the `SupportState` annotations in order, that each `written_by` and `read_by` value appears in the docstring with backticks stripped, and that `history` is only in `PLANNED_FIELDS`; verify `uv run pytest tests/test_state.py` passes.
- [x] 2.2 Add `initial_state()` to `src/finos/state.py`, and add tests for the initial values and for lists not being shared; verify `uv run pytest tests/test_state.py` passes.
- [x] 2.3 Add `validate_state()` to `src/finos/state.py` per design D5, and add tests for every base check, for all errors being returned together, for each strict check using made-up `known_sources`, for `../config.toml` failing, and for a policy state with empty `context` passing strict; verify `uv run pytest tests/test_state.py` passes.
- [x] 2.4 Add a sentence to the `SupportState` docstring saying `validate_state` is opt-in and the graph never calls it, and verify in a test that `state.py` imports only from `typing` by inspecting its source with `ast`; verify `uv run pytest tests/test_state.py` passes, including the existing `test_ownership_matrix_is_documented`.

## 3. Record the later-step obligations

- [x] 3.1 Add the bare-filename rule to the `policy_agent` docstring in `src/finos/agents/policy.py`, and add the normalized-intent rule to the `classify_intent` docstring in `src/finos/agents/supervisor.py`, each naming `specs/support-state/spec.md` as the source. Add scaffold tests that check both docstrings, following `test_build_support_agent_docstring_records_the_settings_rule`; verify `uv run pytest tests/test_scaffold.py` passes and both stubs still raise `NotImplementedError`.
- [x] 3.2 Correct the `Intent` docstring in `src/finos/state.py` so it no longer says the field holds raw model output, keeping the empty initial value as the reason `intent` is a plain `str`; verify `grep -n "raw model output" src/finos/state.py` prints nothing.
- [x] 3.3 Add the bare-filename rule to `docs/systems-design-and-architecture.md` §2.3 and the normalized-intent rule to §5; verify by reading both sections and with `grep -n -E "bare filename|normalized" docs/systems-design-and-architecture.md`.

## 4. CLI framework

- [x] 4.1 Create `src/finos/cli/__init__.py` and `src/finos/cli/shared.py` with the shared option definitions, `@shared_options`, `options(ctx)`, the color resolution from design D8, and the `emit_json`, `fail_usage`, and `debug` helpers from design D7; verify through the tests in 4.4.
- [x] 4.2 Create `src/finos/cli/main.py` with the root app per design D1, `--version/-V` read from package metadata, and a `state` group from a new `src/finos/cli/state.py` holding only the empty `state_app` for now; create `src/finos/__main__.py` guarded by `__name__`; verify through the tests in 4.4.
- [x] 4.3 Point `[project.scripts]` at `finos.cli.main:main`, remove `main()` from `src/finos/main.py`, and update its module docstring. In `tests/test_scaffold.py`, add the new modules to `MODULES`, remove `finos.main.main` from `STUBS`, and update the entry-point assertion; verify `uv sync --locked`, `uv run finos --version`, and `uv run pytest tests/test_scaffold.py` all succeed.
- [x] 4.4 Write `tests/test_cli.py` covering every scenario in `specs/cli-framework/spec.md` that doesn't need a real `state` command, using a small test-only command decorated with `@shared_options`: flags in both positions and in both at once, the command's own options alongside them, help listing, color with `invoke(..., color=True)` compared against `--no-color` and `NO_COLOR=1`, verbose reaching only stderr, bare commands exiting 2, the version flag, and a subprocess check that importing `finos.cli.main` doesn't load `langchain`, `langgraph`, or `chromadb`; verify `uv run pytest tests/test_cli.py` passes.

## 5. Inspection commands

- [x] 5.1 Implement `show` in `src/finos/cli/state.py`, using `get_type_hints` and `FIELD_METADATA`, with human and `--json` output; add tests to `tests/test_cli_state.py` for both forms, including `list[str]`; verify `uv run pytest tests/test_cli_state.py` passes.
- [x] 5.2 Implement `describe` with the initial value, written-by, and read-by columns and the Phase 2 line, with human and `--json` output including `planned`; add tests for both forms; verify `uv run pytest tests/test_cli_state.py` passes.
- [x] 5.3 Implement `init` with `--query`, using `initial_state()`; add tests for the initial values, `--query`, `--json` giving the same output, and `--intent` exiting 2; verify `uv run pytest tests/test_cli_state.py` passes.

## 6. Input pipeline and validate

- [x] 6.1 Implement the private input helper per design D6, with `--data/-d` and `--file/-f` (where `-` means stdin); add tests through `validate` for inline data, a file, stdin, both sources, neither source, malformed JSON, a missing file, and invalid UTF-8, checking exit codes and that exit-2 messages reach stderr and not stdout; verify `uv run pytest tests/test_cli_state.py` passes.
- [x] 6.2 Implement `validate` with human and `--json` verdicts per design D7, and add tests for every scenario under "Validation always checks the contract" and "Validate reports a verdict on stdout" in `specs/state-toolkit/spec.md`; verify `uv run pytest tests/test_cli_state.py` passes.
- [x] 6.3 Add `--strict`, building `known_sources` from `POLICY_DOCS_DIR` per design D5 and exiting 2 if the directory is missing; add tests for every scenario under "Strict validation adds source and ownership checks", including real corpus names and a monkeypatched missing directory; verify `uv run pytest tests/test_cli_state.py` passes.

## 7. Converters

- [x] 7.1 Implement `serialize` with `--compact` and `--sort-keys`; add tests for contract order, compact output, sorted keys, byte-identical output for reordered input, non-ASCII text, and `--json` changing nothing; verify `uv run pytest tests/test_cli_state.py` passes.
- [x] 7.2 Implement `deserialize` with the `SupportState(...)` expression and `--json` output; add tests for the expression's text, an `eval` round trip with `SupportState` in scope, and identical JSON from both flag positions; verify `uv run pytest tests/test_cli_state.py` passes.
- [x] 7.3 Add tests for every scenario under "Converters refuse invalid state on stderr", including empty stdout with `--json` set; verify `uv run pytest tests/test_cli_state.py` passes.
- [x] 7.4 Add a parametrized test running all six commands with `finos.config.get_settings` replaced by one that raises, covering "State commands run offline without settings"; verify `uv run pytest tests/test_cli_state.py` passes.

## 8. Documentation

- [x] 8.1 Update `docs/systems-design-and-architecture.md` §8 layout and file responsibilities for `cli/` and `__main__.py`, and §10 with a Step 1b row, changing Step 5's "`main.py` CLI" to `finos run`; verify with `grep -n -E "cli/|1b|finos run" docs/systems-design-and-architecture.md`.
- [x] 8.2 Update the `src/finos/__init__.py` module map to list `finos.cli` and describe `finos.main` as the `ask` helper; verify `uv run python -c "import finos"` exits 0 and `uv run pytest tests/test_scaffold.py` passes.
- [x] 8.3 Update `README.md` status and layout, and add a short CLI section with `finos state` examples and the exit codes; verify each documented command runs as written.

## 9. Integration check

- [x] 9.1 Run the acceptance commands from a clean sync: `uv sync --locked`, `uv run finos --help`, `uv run finos --version`, `uv run finos state --help`, `uv run finos state show`, `uv run finos state show --json`, `uv run finos --json state show`, `uv run finos state describe`, `uv run finos state init --query "What is the overdraft fee?"`, `uv run finos state validate --data '{"query":"test","intent":"policy","response":"","context":"","retrieved_sources":[]}'`, `uv run finos state serialize --data` and `uv run finos state deserialize --data` with the same state, and `uv run python -m finos state show`; verify each exits 0 with the specified output.
- [x] 9.2 Check the pipeline end to end: `uv run finos state init --query test | uv run finos state validate --file -` exits 0, and `uv run finos state init | uv run finos state serialize --file - --compact | uv run finos state deserialize --file -` prints a `SupportState(...)` expression.
- [x] 9.3 Run the full suite and spec check: verify `uv run pytest` passes with no API key or network access, and `openspec validate step-1b-cli-state-toolkit --strict` reports the change as valid.

## 10. Output destination

- [x] 10.1 Add `--output/-o` and `--force` to `serialize` and `deserialize` per design D10, through one private writer helper in `src/finos/cli/state.py`; reword the `--file` help to say it is input; verify through the tests in 10.2.
- [x] 10.2 Add tests to `tests/test_cli_state.py` for every scenario under "Converters can write to a file" and "Writing to a file never overwrites by accident", and the "JSON flag changes nothing" scenario; verify `uv run pytest tests/test_cli_state.py` passes.

## 11. Documentation and integration check

- [x] 11.1 In `README.md`, document `--output/-o` and `--force`, state that `--json` changes nothing on `serialize`, and add a "Debugging and testing recipes" section (write a fixture, check it strictly, refuse and force an overwrite, diff two states, paste a state into a test, pipelines); verify each documented command runs as written from a scratch directory.
- [x] 11.2 Run the acceptance commands: `uv run finos state serialize --data '<state>' -o <dir>/new/state.json` exits 0 with empty stdout; `uv run finos state validate --file <dir>/new/state.json` exits 0; repeating the write exits 2, and with `--force` exits 0; `uv run finos state deserialize --file <dir>/new/state.json -o <dir>/state.py` exits 0. Then verify `uv run pytest` passes offline and `openspec validate step-1b-cli-state-toolkit --strict` reports the change as valid.

## Workflow follow-up

- Archive the change after review, which syncs the delta specs into `openspec/specs/`.
- Carry the two obligations into the Step 2 and Step 5 explore sessions.
