# Design

## Context

See `proposal.md` for motivation and `specs/` for required behavior. Today `finos` points at a `finos.main.main` stub that raises `NotImplementedError`, `state.py` imports only `typing`, and `typer` 0.27.3 and `rich` are installed only because `chromadb` depends on them.

This design records the decisions from the Step 1b explore session. Sources:

- **Explore doc**: the Step 1b explore notes, updated to match this change
- **Context doc**: `docs/systems-design-and-architecture.md` §2.3 and §8

## Goals / Non-Goals

**Goals:**

- A pattern a later step can follow by adding one file and one registration line.
- One definition of the contract's rules, usable with or without the CLI.
- Output that scripts can rely on: clean stdout and meaningful exit codes.
- Debugging fixtures can be written straight to a file.

**Non-Goals:**

- Creating `policy`, `account`, `escalation`, or `run` modules, even as stubs.
- Enforcing the contract inside the graph. Validation stays opt-in.
- Shell completion, config files for the CLI, or Rich-formatted tables.

## Decisions

### Departures from the explore doc

| Explore doc | This change | Why |
| --- | --- | --- |
| `--json TEXT` as input on `validate` and `deserialize` | `--data/-d` and `--file/-f` for input; `--json` is output only | One flag can't mean both, and a root-level `--json` can't take a value (D3) |
| `--file` only on `serialize` | `--data` and `--file` on all three input commands | Same input handling everywhere (D6) |
| `FIELD_OWNERSHIP` | `FIELD_METADATA` | It also holds descriptions (D4) |
| `finos.config.get_data_dir()` | The existing `POLICY_DOCS_DIR` | The function doesn't exist |
| `typer>=0.12` | `typer>=0.27,<0.28` | The decorator is tested only on this line (D3) |
| "No `python-dotenv` needed" | Dependency kept | `config.py` imports it for secrets |
| Test expects `"intent"` in stdout, while `error()` writes to stderr | `validate` verdicts on stdout; other errors on stderr | The sample contradicted itself (D7) |
| `validate` sample reports only the bad `intent` | All errors reported | The same input is also missing three fields (D5) |
| Top-level agent import in the `policy` sample | Heavy imports inside commands | Keeps `--help` fast once Step 2 adds Chroma (D2) |

### D1. Package layout and entry points

```
src/finos/
  __main__.py     calls finos.cli.main:main, guarded by __name__
  main.py         ask() only; main() is removed
  state.py        contract, metadata, builder, validator
  cli/
    __init__.py
    main.py       root Typer app, version flag, add_typer registrations
    shared.py     shared options, output and error helpers
    state.py      the six commands
```

`pyproject.toml` points `finos` at `finos.cli.main:main`. Moving it there, rather than keeping `finos.main:main` as a delegate, leaves `finos/main.py` focused on `ask()`, which tests and any future API import without the CLI. `main()` calls `app(prog_name="finos")`, so usage text reads the same through `python -m finos`.

The root app sets `no_args_is_help=True` on every group, `add_completion=False` to keep help focused, and `pretty_exceptions_show_locals=False` so a traceback can't print state values or keys.

### D2. Import rules

`cli/main.py` and module files import only light dependencies at the top. Anything that pulls in LangChain, LangGraph, or Chroma is imported inside the command body. This is a convention with a test: a fresh subprocess imports `finos.cli.main` and asserts those packages aren't loaded. `state` commands never call `get_settings()`, because that call changes tracing environment variables.

The §8 module pattern in the explore doc is updated to match.

### D3. Shared options through one decorator

`--json`, `--verbose`, and `--no-color` must work in both positions (`finos --json state show` and `finos state show --json`). A root callback alone rejects the second form with exit 2, and plain per-command options reject the first. So both positions use the same `Annotated` option definitions:

```
finos [--json -v --no-color] state show [--json -v --no-color]
              |                                |
              +----> ctx.find_root().obj <-----+
                     (a flag set in either place counts)
```

- `shared.py` defines each option with a callback that records `True` on the root context's `obj`. Options only ever turn on, so order can't matter.
- The root callback declares the three options directly.
- `@shared_options` adds them to a command by extending the function's `__signature__` and `__annotations__`, and removes them before calling it. A command takes `ctx: typer.Context` and reads the result with a helper, `shared.options(ctx)`.

**Alternatives**: declaring three parameters on every command is explicit, but adds boilerplate that later modules could get wrong. Root-only placement is simpler, but makes users remember where each flag goes.

A throwaway prototype confirmed this on Typer 0.27.3, including mixed positions, a command's own options alongside them, and all three appearing in command help. Because it depends on how Typer reads signatures, the version is capped at `<0.28`, and the CLI tests cover both positions.

`-j`, `-v`, and `-V` are reserved across all modules.

### D4. Everything about the contract stays in `state.py`

```
SupportState         unchanged
VALID_INTENTS        unchanged
FieldInfo            TypedDict: description, initial, written_by, read_by
FIELD_METADATA       dict[str, FieldInfo], in contract order
PLANNED_FIELDS       {"history": "<note>"}
initial_state(query="")                     --> SupportState
validate_state(value, *, strict=False,
               known_sources=frozenset())   --> list[str]
```

The module docstring already says nothing else defines state fields, so a separate `state_meta.py` would split the contract across two files. `state.py` still imports only from `typing`.

- `initial` is display text, because the matrix's `query` initial value is "customer's question". `initial_state()` builds real values and returns a new list each time. Step 5's `ask()` can reuse it.
- `written_by` and `read_by` use the same words as the docstring matrix, so a test can check them against it after stripping backticks.
- `show` derives types from `get_type_hints`; descriptions come from the metadata.

The existing support-state requirement that ownership not require a runtime validation layer still holds: `validate_state` is only called by the CLI, and may later be called by evaluation code. The graph never calls it. The `SupportState` docstring gains a sentence saying so.

### D5. Validation rules

`validate_state` returns a list of messages, empty if valid. It checks fields in contract order, then reports unknown fields. Message wording follows this shape, and tests match on field names and values, not full sentences:

```
state must be a JSON object (got list)
missing field 'response'
unknown field 'history'
field 'retrieved_sources' must be a list of strings
field 'intent' must be one of: "policy", "account_status", "escalation" (got "unknown_intent")
```

Strict checks run only on fields that passed the base checks, to avoid repeating errors:

- Each source must be in `known_sources`. This is exact set membership with no path joining, so `../config.toml` and `data/policy-docs/account_fees.md` both fail.
- Non-empty `context` or `retrieved_sources` is rejected unless `intent` is `policy`. That includes `intent: ""`, because the policy agent can't have run before classification.

The CLI builds `known_sources` from the regular, non-hidden files directly inside `POLICY_DOCS_DIR`. Keeping disk access out of `validate_state` keeps `state.py` dependency-free and makes the check testable with made-up names. The list is built only with `--strict`.

**Deliberately not checked**: `intent: "policy"` with empty `context`. A lookup can legitimately find nothing, and judging that belongs to evaluation. Rejecting it would also fail the mid-run states the explore doc treats as valid.

### D6. One input pipeline for three commands

```
--data | --file | stdin --> read --> parse --> validate_state --+--> validate:    verdict
       (exit 2)         (exit 2)                                +--> serialize:   canonical JSON   --+--> stdout
                                                                +--> deserialize: SupportState(...) -+--> --output PATH (D10)
```

A private helper in `cli/state.py` checks that exactly one source was given, reads it, and parses it. `--file` is typed as `str`, not `Path`, so `-` can mean stdin. Non-object JSON such as `[1, 2]` parses successfully and is then rejected by `validate_state`, so it exits 1, not 2.

`serialize` and `deserialize` then rebuild the dict in contract order. JSON uses `ensure_ascii=False` with `indent=2`, or `separators=(",", ":")` for `--compact`. `deserialize` formats each value with `repr` as `SupportState(query='test', ...)`, because a `TypedDict` value is a plain dict and has no such `repr` of its own. Calling `SupportState(...)` at runtime returns a dict, so the output works as a pasted fixture.

`serialize` validates even though the explore doc's §3.5 doesn't ask for it. Without validation it would only be a weaker `jq`; with it, the output is guaranteed to be a real `SupportState`, and two runs can be compared with `diff`.

### D7. Output streams and exit codes

| Situation | Exit | Message |
| --- | --- | --- |
| Success | 0 | stdout |
| Invalid state on `validate` | 1 | stdout, because the verdict is the command's output |
| Invalid state on `serialize` or `deserialize` | 1 | stderr, so redirected output stays clean |
| Bad invocation or unusable input | 2 | stderr, as plain text even with `--json` |
| Unusable output destination (exists without `--force`, a directory, no permission) | 2 | stderr |

`shared.py` provides `emit_json`, `fail_usage` (exit 2), and `debug` (stderr, only when verbose).

### D8. Human output and color

Output is plain aligned text through `typer.echo`, with `typer.secho` coloring only the `validate` verdict. A Rich table could wrap or truncate names such as `retrieved_sources` at the 80-column width `CliRunner` uses, so `rich` stays out of command output and isn't added as a direct dependency.

Click strips color when output isn't a terminal but doesn't check `NO_COLOR`, so `shared.py` resolves it: color is `False` if `--no-color` is set or `NO_COLOR` is non-empty, and otherwise `None`, which leaves Click's terminal check in charge.

### D9. Obligations on later steps

Two requirements in `specs/support-state/spec.md` can't be tested until later steps exist, but the toolkit's behavior depends on them:

| Step | Obligation | If ignored |
| --- | --- | --- |
| 2 | `retrieved_sources` holds bare filenames, and Step 2 adds a test for it | `--strict` rejects every real policy state |
| 5 | `classify_intent` writes only a normalized vocabulary member, and Step 5 adds a test for it | `validate` rejects states the graph routed correctly |

So they aren't lost, they're recorded in four places: the spec, the `policy_agent` and `classify_intent` stub docstrings (with a scaffold test, following the existing `build_support_agent` settings-rule test), and `docs/systems-design-and-architecture.md`. **This change implements neither agent.** It delivers only the records and the tests of the records.

The `Intent` docstring in `state.py` currently says the field "has to hold raw model output". That contradicts the Step 5 obligation, so it's corrected. The field stays a plain `str` because of the empty initial value, which the existing spec already gives as the reason. `route_by_intent`'s fallback to `policy_agent` stays as a defensive measure.

### D10. Output destination

`serialize` and `deserialize` take `--output/-o PATH`; no other command does. `--file` stays input-only, so `--file in.json -o out.json` works and no flag has two meanings, for the same reason `--json` takes no value (D3). `--json` can't serve as "write a file": it is a boolean output-format flag, and on `serialize` it is a no-op because the output is already JSON.

- The text is built once, then sent to stdout or to the file, so the file's bytes equal what stdout would show: UTF-8 with a trailing newline, honoring `--compact`, `--sort-keys`, and `--json`.
- Writing happens only after validation, so an invalid state never creates or touches the file. Input is read in full first, so `-f state.json -o state.json --force` is safe.
- Without `--force` the file is opened in exclusive-create mode, so the existence check and the write can't race; with `--force` it is truncated. Parent directories are created first. Any `OSError` (the file exists, is a directory, or lacks permission) exits 2 through `fail_usage`.
- `-` means stdout, mirroring `--file -`. `--force` without `--output` exits 2, so a mistyped command can't silently ignore it.
- Success prints nothing on stdout; `--verbose` reports the path on stderr.

**Alternatives**: shell redirection alone still works, but `>` truncates the target before validation runs, so an invalid state leaves an empty file. Letting `--file` double as the destination was rejected as ambiguous.

## Risks / Trade-offs

- [`@shared_options` relies on how Typer reads function signatures, so an upgrade could break it] → The `<0.28` cap, `uv.lock`, and tests of both positions make a break visible at upgrade time.
- [Ownership facts exist in both the docstring and `FIELD_METADATA`] → Sync tests fail if they drift; the docstring stays because the spec requires it.
- [`state.py` grows from a short contract to a contract plus helpers] → Accepted, and it should stay under about 200 lines.
- [`deserialize --json` duplicates default `serialize`] → Accepted: both share one code path, and `serialize` remains the one with formatting controls.
- [Strict validation can't catch a Step 2 that stores paths until Step 2 runs] → The obligation records in D9, and Step 2's required test.
- [Creating parent directories can turn a typo into a stray directory] → `--verbose` names the path; accepted for debugging convenience.
- [A bare `finos` exits 2 although it only prints help] → This is Click's standard behavior for no arguments and tells scripts nothing ran; `finos --help` exits 0.

## Migration Plan

The entry-point move takes effect on the next `uv sync`. No external consumers exist, and the old target only raised `NotImplementedError`, so nothing that works today breaks. Rollback is reverting the change.
