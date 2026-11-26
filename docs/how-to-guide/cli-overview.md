# Command line overview

[← Back to the README](../../README.md)

How the `finos` command line is organised, the options every command
shares, and what the exit codes mean. Each module has its own guide:

- [`finos state`](cli-state.md): inspect, validate, and convert `SupportState` values
- [`finos policy`](cli-policy.md): ask the policy agent, inspect retrieval, and manage the index
- [`finos account`](cli-account.md): ask the account agent, and inspect the mock account records
- [`finos escalation`](cli-escalation.md): ask the escalation agent, and show the fixed support texts
- [`finos supervisor`](cli-supervisor.md): run the whole system, show routing, and print the graph
- [`finos eval`](evaluation.md): push datasets, run experiments, and check the quality gates
- [`finos guard`](guardrails.md#finos-guard-check): show how the input guardrails judge a query

## Contents

- [Running the CLI](#running-the-cli)
- [Shared options](#shared-options)
- [Exit codes](#exit-codes)

## Running the CLI

`uv sync` installs a `finos` command; `python -m finos` runs the same thing.
Each module is a command group, invoked as `finos <module> <command>`. So
there are seven modules: `state`, `policy`, `account`, `escalation`,
`supervisor`, `eval`, and `guard`. `finos supervisor ask` runs the whole
system; the other agent modules run one specialist on its own. Every
command that calls a model passes through the guardrails (see
[Guardrails](guardrails.md)).

```sh
uv run finos --help                # list modules and shared options
uv run finos --version             # finos 0.1.0
uv run finos state --help          # list the six state commands
```

## Shared options

These work on every command, either before the module name or after the
command (`finos --json state show` and `finos state show --json` are the
same):

| Option            | Effect                                                         |
| ----------------- | -------------------------------------------------------------- |
| `--json`, `-j`    | machine-readable JSON output; it never takes a value or input  |
| `--verbose`, `-v` | diagnostic detail on stderr; stdout and exit code don't change |
| `--no-color`      | no ANSI color; the `NO_COLOR` environment variable does the same |

`--version/-V` is accepted at the root only.

## Exit codes

| Code | Meaning                                                    | Message on                                   |
| ---- | ---------------------------------------------------------- | -------------------------------------------- |
| 0    | success                                                    | stdout                                       |
| 1    | input understood but rejected, such as an invalid state; for `policy`, a model or embedding provider could not be reached or used | stdout for `validate`; stderr for converters and `policy` |
| 2    | unusable invocation or input: bad option, malformed JSON, missing or non-UTF-8 file, no or two input sources, an `--output` path that exists (without `--force`) or can't be written, an empty `--query`, `--top-k` below 1 | stderr, as plain text even with `--json` |

Running `finos`, `finos state`, or `finos policy` with no command prints help and exits 2.
