# Proposal

## Why

Steps 2–5 each need a way to exercise their agent from a terminal, and they only stay consistent if they plug into one CLI with one set of conventions. `SupportState` is also the contract every step depends on, yet nothing can inspect it or check a state value without writing Python. Settling both now, before any agent exists, means each later step adds a module instead of inventing a pattern.

## What Changes

- Add a `finos` command line with one sub-application per module, reachable as `finos` and as `python -m finos`.
- **BREAKING** (internal only): the `finos` script entry point moves from `finos.main:main` to `finos.cli.main:main`, and the `finos.main.main` stub is removed. `finos.main.ask` stays and is still implemented in Step 5.
- Add shared options, `--json/-j`, `--verbose/-v`, and `--no-color`, that work both before and after the subcommand on every command, plus root-only `--version/-V` and support for the `NO_COLOR` environment variable.
- Add the `finos state` toolkit with six commands: `show`, `describe`, `init`, `validate`, `serialize`, and `deserialize`. `serialize` and `deserialize` can write their output to a file with `--output/-o` (`--force` to overwrite).
- Add field metadata, a planned-fields record, an initial-state builder, and an opt-in state validator to the contract module, so non-CLI code can use them too.
- Record two obligations on later steps, because the toolkit's validation depends on them: Step 2 stores bare filenames in `retrieved_sources`, and Step 5 normalizes `intent` before writing it.
- Declare `typer` as a direct dependency. Today it is only installed through `chromadb`.
- Update the context document, README (including debugging and testing recipes), and package module map to match.

**Out of scope**: agent commands (`finos policy ask`, `finos account ask`, and so on), graph invocation (`finos run`), and hardening-layer commands. The later-step sub-applications are not created, even as stubs.

## Capabilities

### New Capabilities

- `cli-framework`: The `finos` command line itself: entry points, how modules attach, shared options, exit codes, and output streams that every module inherits.
- `state-toolkit`: The `finos state` commands for inspecting, validating, and converting `SupportState` values.

### Modified Capabilities

- `support-state`: Adds field metadata, an initial-state builder, an opt-in validator, and the value conventions later steps must honor for `retrieved_sources` and `intent`.
- `project-scaffold`: The CLI is no longer a later-step stub, so the stub requirement narrows to the agents, the graph, and the `ask` helper.

## Impact

- **Code**: new `src/finos/cli/` package and `src/finos/__main__.py`; additions to `src/finos/state.py`; `main()` removed from `src/finos/main.py`; docstring additions on the policy and supervisor stubs.
- **Tests**: new `tests/test_cli.py` and `tests/test_cli_state.py`; additions to `tests/test_state.py`; `tests/test_scaffold.py` updated for the new entry point and stub list.
- **Dependencies**: `typer` added to `pyproject.toml`. The locked version does not change, because it is already installed through `chromadb`.
- **Later steps**: Step 2 and Step 5 inherit the obligations above. They are recorded in `specs/support-state/spec.md` and in the docstrings of the stubs those steps will fill in.
- **Documents**: `docs/systems-design-and-architecture.md` (§2.3, §5, §8, §10), `README.md`, and the `finos/__init__.py` module map. The external explore document is updated to mark where this change supersedes it.
- **Runtime**: no `state` command loads settings, calls a model, or contacts the network. Tracing is not affected. `--output` writes only the file it names.
