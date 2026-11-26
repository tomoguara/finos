# The `finos state` toolkit

[← Back to the README](../../README.md)

Commands for inspecting, validating, and converting `SupportState`
values. Shared options and exit codes are in the
[command line overview](cli-overview.md).

## Contents

- [Commands](#commands)
- [Writing to a file: `--output/-o` and `--force`](#writing-to-a-file---output-o-and---force)
- [Debugging and testing recipes](#debugging-and-testing-recipes)
  - [1. Save a state as a fixture file](#1-save-a-state-as-a-fixture-file)
  - [2. Check a fixture, strictly](#2-check-a-fixture-strictly)
  - [3. See what a broken state looks like](#3-see-what-a-broken-state-looks-like)
  - [4. Overwrite only on purpose](#4-overwrite-only-on-purpose)
  - [5. Compare two states](#5-compare-two-states)
  - [6. Turn a state into a test fixture](#6-turn-a-state-into-a-test-fixture)
  - [7. Use it from a script](#7-use-it-from-a-script)

## Commands

Every `state` command runs offline: none of them loads settings, calls a
model, or contacts the network, so they need no `.env` and don't touch
tracing.

| Command       | What it does                                                         |
| ------------- | -------------------------------------------------------------------- |
| `show`        | each `SupportState` field with its type and description              |
| `describe`    | each field's initial value, writer, and readers, plus planned fields |
| `init`        | a new state as JSON (`--query/-q` sets the question)                 |
| `validate`    | checks a state against the contract (`--strict` adds more checks)    |
| `serialize`   | validates, then prints canonical JSON in contract order (or `-o` file) |
| `deserialize` | validates, then prints a `SupportState(...)` expression (or `-o` file) |

```sh
uv run finos state show
uv run finos state describe --json
uv run finos state init --query "What is the overdraft fee?"
uv run finos state validate --data '{"query":"test","intent":"policy","response":"","context":"","retrieved_sources":[]}'
uv run finos state validate --strict --file state.json
uv run finos state init --query test | uv run finos state validate --file -
uv run finos state init | uv run finos state serialize --file - --compact | uv run finos state deserialize --file -
```

`validate`, `serialize`, and `deserialize` read one state from exactly one
of `--data/-d` (JSON text) or `--file/-f` (a path; `-` means stdin).
`--file` is always **input**; giving both `--data` and `--file` exits 2.

- **Base checks** (always): a JSON object with exactly the five fields, the
  contract's types, and an `intent` that is empty or one of `policy`,
  `account_status`, `escalation`. Every problem is reported, not just the
  first.
- **`--strict`** (`validate` only): each `retrieved_sources` entry must be
  the bare name of a file in `data/policy-docs/`, such as `account_fees.md`,
  and `context` and `retrieved_sources` must be empty unless `intent` is
  `policy`.
- `serialize` takes `--compact` (one line) and `--sort-keys` (alphabetical
  order); its output is byte-identical for equal states, so it diffs well.
  Its output is always JSON, so `--json` is accepted but changes nothing.
  On `deserialize`, `--json` switches from the Python expression to JSON.

## Writing to a file: `--output/-o` and `--force`

`serialize` and `deserialize` print to stdout unless `--output/-o PATH` is
given. With it, they write exactly what they would have printed (UTF-8,
including `--compact`, `--sort-keys`, and `--json`) and print nothing.

- Missing parent directories are created.
- An existing file is never overwritten unless you add `--force`; without
  it the command exits 2. `--force` without `--output` also exits 2.
- The state is validated first: an invalid state exits 1 and the file is
  neither created nor changed. (Shell `>` can't promise that: it empties
  the file before the command runs.)
- `-o -` means stdout. `-v` reports the path written on stderr.

```sh
uv run finos state serialize --data '{"query":"txo-test","intent":"policy","response":"","context":"","retrieved_sources":[]}' --output /tmp/txo-test.json
uv run finos state serialize --file /tmp/txo-test.json --compact --output /tmp/txo-test.json --force
```

## Debugging and testing recipes

These run as written from the repository root, in order (later recipes
use the files earlier ones write). They put everything under
`/tmp/finos-debug/`, which `-o` creates for you; delete it to start over.

### 1. Save a state as a fixture file

```sh
uv run finos state serialize --data '{"query":"What is the overdraft fee?","intent":"policy","response":"","context":"Overdraft fee: $35","retrieved_sources":["account_fees.md"]}' -o /tmp/finos-debug/policy.json
uv run finos state init --query "What is my balance on ACC-12345?" | uv run finos state serialize --file - -o /tmp/finos-debug/account.json
```

### 2. Check a fixture, strictly

`--strict` also checks that each source
is a real file in `data/policy-docs/` and that only policy states carry
`context` or `retrieved_sources`.

```sh
uv run finos state validate --strict --file /tmp/finos-debug/policy.json
uv run finos state validate --strict --json --file /tmp/finos-debug/account.json
```

### 3. See what a broken state looks like

Every problem is listed, and
the command exits 1:

```sh
uv run finos state validate --strict --data '{"query":"q","intent":"Policy","response":"","context":"","retrieved_sources":["data/policy-docs/account_fees.md"]}'; echo "exit $?"
```

```
invalid SupportState
  - field 'intent' must be one of: "policy", "account_status", "escalation" (got "Policy")
  - field 'retrieved_sources' has unknown source 'data/policy-docs/account_fees.md'
exit 1
```

### 4. Overwrite only on purpose

Writing to an existing file is refused;
`--force` allows it. Reading and writing the same file is safe, so this
also re-formats a hand-edited fixture in place:

```sh
uv run finos state serialize --file /tmp/finos-debug/policy.json -o /tmp/finos-debug/policy.json; echo "exit $?"
uv run finos state serialize --file /tmp/finos-debug/policy.json -o /tmp/finos-debug/policy.json --force
```

### 5. Compare two states

`serialize` gives the same bytes for equal
states whatever their key order or spacing, so `diff` shows only real
differences (bash or zsh; `diff` exits 1 when the states differ):

```sh
diff <(uv run finos state serialize --file /tmp/finos-debug/policy.json) <(uv run finos state serialize --file /tmp/finos-debug/account.json)
```

### 6. Turn a state into a test fixture

`deserialize` prints a
`SupportState(...)` expression to paste into a test, or writes it to a
file:

```sh
uv run finos state deserialize --file /tmp/finos-debug/policy.json
uv run finos state deserialize --file /tmp/finos-debug/policy.json -o /tmp/finos-debug/policy_fixture.py
```

### 7. Use it from a script

Exit codes are stable (0 valid, 1 invalid,
2 unusable input), and `--json` gives a verdict a script can parse:

```sh
if uv run finos state validate --strict --file /tmp/finos-debug/policy.json > /dev/null; then echo "fixture ok"; fi
uv run finos --json state validate --file /tmp/finos-debug/policy.json
```
