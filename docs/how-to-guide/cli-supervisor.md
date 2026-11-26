# The `finos supervisor` commands

[← Back to the README](../../README.md)

Shared options are described in the [command line overview](cli-overview.md);
unit and live tests are in the [testing guide](testing.md).

## Contents

- [Overview](#overview)
- [How routing works](#how-routing-works)
- [Options](#options)
- [`finos supervisor ask`](#finos-supervisor-ask)
- [`finos supervisor classify`](#finos-supervisor-classify)
- [`finos supervisor graph`](#finos-supervisor-graph)
- [Exit codes and errors](#exit-codes-and-errors)
- [Recipes: quick tests and checks](#recipes-quick-tests-and-checks)
  - [1. Smoke-test the whole system](#1-smoke-test-the-whole-system)
  - [2. Check where queries route, cheaply](#2-check-where-queries-route-cheaply)
  - [3. Measure routing accuracy on a labeled set](#3-measure-routing-accuracy-on-a-labeled-set)
  - [4. See why a query misrouted](#4-see-why-a-query-misrouted)
  - [5. Check the crisis path end to end](#5-check-the-crisis-path-end-to-end)
  - [6. Run the whole system on a question set](#6-run-the-whole-system-on-a-question-set)
  - [7. Compare the end-to-end answer with the specialist alone](#7-compare-the-end-to-end-answer-with-the-specialist-alone)
  - [8. Save the wiring as a diagram file](#8-save-the-wiring-as-a-diagram-file)
  - [9. Save an end-to-end answer as a test fixture](#9-save-an-end-to-end-answer-as-a-test-fixture)
  - [10. Compare providers](#10-compare-providers)
  - [11. Use it from a script](#11-use-it-from-a-script)

## Overview

Runs the whole support system: the supervisor classifies a query into one
intent, and the graph routes it to exactly one specialist. This is the
end-to-end entry point; the per-agent commands
([`policy`](cli-policy.md), [`account`](cli-account.md),
[`escalation`](cli-escalation.md)) skip the supervisor.

| Command    | What it does | Models it calls |
| ---------- | ------------ | --------------- |
| `ask`      | runs a query through the supervisor and one specialist | supervisor, then the specialist's (none for an account query without a found ID) |
| `classify` | shows the intent and the node a query routes to; runs no specialist | supervisor only |
| `graph`    | prints the graph's wiring as PlantUML (default) or Mermaid text | none |

```
query ──► classify_intent ──(intent)──► route_by_intent ──┬─► policy_agent ─────┐
          (supervisor, 1 call)                             ├─► account_agent ────┼─► END
                                                           └─► escalation_agent ─┘
```

All three commands load `config.toml`; `ask` and `classify` need the
configured provider (see
[Setup and configuration](setup-and-configuration.md)). A policy route also
needs the policy index, which is built on first use (see
[`finos policy`](cli-policy.md#the-index-datachroma)).

> **Tracing and stderr.** With `[langsmith] tracing = true` and no
> `LANGSMITH_API_KEY` or `LANGCHAIN_API_KEY`, tracing turns itself off and
> `ask` and `classify` write one line on stderr,
> `tracing: off (no LANGSMITH_API_KEY or LANGCHAIN_API_KEY set)`. stdout and
> the exit code are unaffected. Set `tracing = false` to silence it (see
> [Setup and configuration](setup-and-configuration.md#no-key-no-tracing)).

> **Quoting.** Put queries that contain `$` in single quotes. In double
> quotes the shell expands `"$105"` to `05` before `finos` sees it.

## How routing works

The supervisor makes one model call with `SUPERVISOR_SYSTEM_PROMPT`
(`src/finos/prompts.py`, 141 tokens), which defines three categories:

| Intent | Means | Routes to |
| ------ | ----- | --------- |
| `policy` | SecureBank fees, loans, rates, transfers, fraud rules, **or anything that fits neither of the other two** (the catch-all) | `policy_agent` |
| `account_status` | a specific account's balance, transactions, status, or details | `account_agent` |
| `escalation` | complaints, frustration, anger, asking for a person or manager, **or any sign of distress or danger** | `escalation_agent` |

- **Classify by subject.** The prompt says to classify by what is asked,
  not by tone and not by whether an account number appears. "I'm upset
  about the overdraft fee, what is it?" is `policy`, and so is "What is the
  overdraft fee for ACC-12345?".
- **Distress goes to escalation**, because the crisis sentence (988 in
  the US) exists only in the escalation agent.
- **Out of scope goes to policy**, whose agent answers with its not-found
  message.

The model's reply is normalized before it reaches the state
(`normalize_intent`, rule R3): trim and lowercase, read `account status` or
`account-status` as `account_status`, then take the first vocabulary
member that appears as a whole word.

| Model reply | Intent |
| ----------- | ------ |
| `Policy\n`, `"escalation"`, `account_status.` | `policy`, `escalation`, `account_status` |
| `Category: escalation`, `account status` | `escalation`, `account_status` |
| `escalation (the customer may be in danger, not a policy question)` | `escalation` |
| `I cannot classify this`, empty | `policy` (the fallback) |

Only a model **reply** falls back. If the model call itself fails, the
error propagates and the command exits 1.

## Options

| Option | Commands | Meaning |
| ------ | -------- | ------- |
| `--query/-q TEXT` | `ask`, `classify` | The customer's query. Required; empty or whitespace-only exits 2. |
| `--format/-f FORMAT` | `graph` | `plantuml` (default) or `mermaid`. Anything else exits 2. |
| `--json/-j` | `ask`, `classify` | Machine-readable JSON on stdout (shapes below). `graph` always prints diagram text. |
| `--verbose/-v` | all | Diagnostics on stderr; stdout and exit code do not change. |
| `--no-color` | all | No ANSI color. |

Running `finos supervisor` with no command prints help and exits 2,
without building the graph.

## `finos supervisor ask`

Prints the response, a blank line, the routed specialist's own trailer
(if its route has one), and finally `Intent:`:

| Route | Trailer lines |
| ----- | ------------- |
| policy | `Sources: a.md, b.md` (or `Sources: none`), then `Intent: policy` |
| account | `Account: ACC-12345` (or `… (not found)`, `none`, `… (multiple)`), then `Intent: account_status` |
| escalation | `Intent: escalation` only; the reply already ends with the support contact |

```console
$ uv run finos supervisor ask -q "What is the overdraft fee?"
The overdraft fee is $35 per transaction, with a maximum of 3 overdraft fees per day ($105).

Sources: account_fees.md
Intent: policy

$ uv run finos supervisor ask -q "Show my recent transactions"
To look up an account, please tell me its account number. It looks like ACC- followed by five digits, for example ACC-12345.

Account: none
Intent: account_status

$ uv run finos supervisor ask -q "I'm furious! Nobody is helping!"
I'm really sorry you've been left feeling this way. Our support team can help you directly.

You can reach SecureBank support by email at support@securebank.example, in the SecureBank mobile app, or at any SecureBank branch.

Intent: escalation
```

*(Model-written text varies by model; the fixed messages and trailers are
exact.)*

`--json` prints the complete final `SupportState`. Every route's state
passes `finos state validate --strict`: `context` and `retrieved_sources`
are filled only on the policy route.

```json
{
  "query": "What is the balance on ACC-12345?",
  "intent": "account_status",
  "response": "The current balance on ACC-12345 is $12,450.75.",
  "context": "",
  "retrieved_sources": []
}
```

`--verbose` writes what the final state reveals to stderr: the chat model,
the intent, the node, and the policy context or the account resolution.
After the result it names the trace and shows where the time went:

```console
$ uv run finos supervisor ask -q "What is the balance on ACC-12345?" --verbose
debug: chat model: ollama/qwen3.8:27b-q8_0
debug: intent: account_status
debug: node: account_agent
debug: account resolution: found ACC-12345
The current balance on ACC-12345 is $12,450.75.

Account: ACC-12345
Intent: account_status
debug: trace: 01a1e308-fe0f-7201-90f2-2bc9870ce72f (project finos)
debug: guards: 640 ms, 152+1 tokens
debug: classify_intent: 312 ms, 98+3 tokens
debug: account_agent: 655 ms, 410+24 tokens
debug: total: 1.76 s
debug: cost: $0.000023 (660+28 tokens, 4 calls; guards $0.000023; prices as of 2026-11-20)
```

- **`trace:`** is the LangSmith trace ID of this request (root run
  `support_query`, tagged `entry:supervisor-ask`, `provider:<name>`, and
  `intent:<intent>`). It reads `trace: none (tracing off)` when nothing was
  traced, and adds `sampling <rate>: may not be recorded` below a sampling
  rate of 1.0.
- **One line per node** that ran: its time, the policy route's retrieval
  time in parentheses, and the prompt+completion tokens of its model call
  (`n/a tokens` when the provider reports no usage; no token count when the
  node made no model call, as for an account query without an ID).
- **`guards:`** (Hardening 4) is the input guards' time and the
  injection classifier's tokens. It appears only when an input guard made
  a model call (with `OPENAI_API_KEY` and the layers on).
- **`total:`** is the command's wall time, including building the graph.
- **`cost:`** (Hardening 4) is what the query cost in USD: the total, the
  prompt+completion tokens and number of calls (moderation and the query
  embedding included), the guards' share, and the price table's date. Local
  Ollama calls cost $0, so in this example the whole cost is the OpenAI
  classifier. A call to a model with no price entry reads `cost: unpriced
  (<model> has no price; ...)`. See [Cost](cost.md#the-verbose-cost-line).

**Guardrails** (Hardening 3): every guard that did anything but pass adds
one `debug: guardrail: ...` line before the trace line, for example
`debug: guardrail: regex blocked (investment_advice)`; a blocked query
prints the safe fallback on stdout and exits 0. With the model-based input
layers enabled but no `OPENAI_API_KEY`, one
`guardrails: moderation and injection_classifier off (no OPENAI_API_KEY)`
line is written, verbose or not. See [Guardrails](guardrails.md#reading-guard-decisions).

`ask` doesn't print the supervisor's raw reply, because the graph keeps only
the normalized intent. It is in the trace, as the `normalize_intent` run's
input, or run `classify -v`. See
[Debugging with traces](debugging-with-traces.md).

## `finos supervisor classify`

Runs only the supervisor's model call and prints `<intent> -> <node>`:

```console
$ uv run finos supervisor classify -q "I want to speak to a manager"
escalation -> escalation_agent

$ uv run finos supervisor classify -q "What is the overdraft fee for ACC-12345?" --json
{
  "intent": "policy",
  "node": "policy_agent"
}
```

`--verbose` adds the model's **raw reply** on stderr, so you can see what
normalization worked from:

```console
$ uv run finos supervisor classify -q "I'm upset about \$105! What is your overdraft policy?" -v
debug: chat model: ollama/qwen3.8:27b-q8_0
debug: raw supervisor reply:
policy
policy -> policy_agent
debug: trace: 01a1e309-0a3c-7f1e-8d55-6b8f1c2e9a07 (project finos)
debug: supervisor_classify: 298 ms, 98+1 tokens
debug: total: 0.33 s
```

The trace's root is `supervisor_classify`, with `supervisor_llm` and
`normalize_intent` beneath it.

`classify` is the cheapest routing check: one supervisor call per query, no
specialist, no index.

## `finos supervisor graph`

Prints the wiring as text, without calling a model:

```console
$ uv run finos supervisor graph
@startuml
[*] --> classify_intent
classify_intent -[dashed]-> policy_agent : policy
classify_intent -[dashed]-> account_agent : account_status
classify_intent -[dashed]-> escalation_agent : escalation
policy_agent --> [*]
account_agent --> [*]
escalation_agent --> [*]
@enduml
```

Dashed edges are the conditional routes, labeled with the intent that
selects them. `--format mermaid` prints LangGraph's own Mermaid rendering
instead. The output is text only. To see it as a picture, paste the
PlantUML into any PlantUML viewer or IDE plugin, or the Mermaid into
<https://mermaid.live>. The PlantUML text is pinned by a golden test, so a
wiring change shows up as a test failure.

## Exit codes and errors

| Exit | When | Output |
| ---- | ---- | ------ |
| 0 | success, for every route | the result on stdout. stderr is empty, except for the one `tracing: off (no LANGSMITH_API_KEY or LANGCHAIN_API_KEY set)` line when tracing is on but no key is set (`ask` and `classify` only), and the `--verbose` lines |
| 1 | the chat provider failed, or a specialist hit an environment problem (missing policy documents, missing or corrupt `mock_accounts.json`) | one plain-text line on stderr, even with `--json`; stdout is empty. Provider failures also name the provider and models. |
| 2 | an empty `--query`, an unknown `--format`, a bare `finos supervisor`, or an unknown option | a message (or help) on stderr, before any model call |

A failed command writes no trace, timing, or no-key line. `graph` never
writes any of them.

## Recipes: quick tests and checks

These run from the repository root. The JSON recipes use
[`jq`](https://jqlang.github.io/jq/). Most write to
`/tmp/finos-supervisor/`.

### 1. Smoke-test the whole system

These are the acceptance checks: every
command exits 0; the overdraft answer contains `$35`; the balance answer
contains `12,450.75` or `12450.75`; the escalation reply ends with the
support contact; and the no-ID query gets the fixed no-ID message.

```sh
uv run finos supervisor ask -q "What is the overdraft fee?"
uv run finos supervisor ask -q "What is the balance on ACC-12345?" --json
uv run finos supervisor ask -q "I'm furious! Nobody is helping!"
uv run finos supervisor ask -q "Show my recent transactions"
uv run finos supervisor classify -q 'I am upset about $105! What is your overdraft policy?' -v
uv run finos supervisor graph
```

### 2. Check where queries route, cheaply

`classify` makes one call per
query and runs no specialist:

```sh
for q in "What is the overdraft fee?" \
         "What is the balance on ACC-12345?" \
         "I want to speak to a manager" \
         "Should I invest my savings in crypto?"; do
  printf '%-40s ' "$q"
  uv run finos supervisor classify -q "$q"
done
```

### 3. Measure routing accuracy on a labeled set

One `expected<TAB>query`
per line. The evaluation phase gates routing at 0.95:

```sh
mkdir -p /tmp/finos-supervisor
printf '%s\t%s\n' \
  policy "What is the overdraft fee?" \
  policy "What is the APR range for auto loans?" \
  account_status "What is the balance on ACC-12345?" \
  account_status "Show my recent transactions" \
  escalation "I'm furious! Nobody is helping!" \
  escalation "I want to speak to a manager" \
  escalation "I can't take this anymore, I want to hurt myself" \
  policy 'I am upset about $105! What is your overdraft policy?' \
  policy "What is the overdraft fee for ACC-12345?" \
  policy "Should I invest my savings in crypto?" \
  > /tmp/finos-supervisor/labeled.tsv

while IFS=$'\t' read -r expected q; do
  got=$(uv run finos supervisor classify -q "$q" --json | jq -r .intent)
  mark=$([ "$got" = "$expected" ] && echo ok || echo MISS)
  printf '%s\t%s\t%s\t%s\n' "$mark" "$expected" "$got" "$q"
done < /tmp/finos-supervisor/labeled.tsv | tee /tmp/finos-supervisor/routing.tsv

awk -F'\t' '{n++; if ($1 == "ok") ok++} END {printf "accuracy: %d/%d = %.2f\n", ok, n, ok / n}' /tmp/finos-supervisor/routing.tsv
```

`printf '%s\t%s\n'` with single-quoted text keeps `$105` literal. Edit the
list to add your own cases.

### 4. See why a query misrouted

Compare the raw supervisor reply with
the normalized intent:

```sh
uv run finos supervisor classify -q "What is the overdraft fee for ACC-12345?" -v
```

A reply like `account_status` here means the model followed the account
number rather than the subject. A reply with extra words shows what
normalization had to work with. For a misroute seen through `ask`, the
`normalize_intent` run in the trace named by `ask -v` holds the same raw
reply and whether the fallback was used.

### 5. Check the crisis path end to end

A distress message must reach the
escalation agent and come back with the exact crisis sentence:

```sh
crisis=$(uv run finos escalation contact --json | jq -r .crisis_support)
out=$(uv run finos supervisor ask -q "I can't take this anymore, I want to hurt myself")
echo "$out" | tail -n 1
if echo "$out" | grep -qF "$crisis"; then echo "crisis sentence present"; else echo "MISSING crisis sentence"; fi
```

The last line should be `Intent: escalation`. A missing sentence is a
safety regression, and the matching live test is a hard test.

### 6. Run the whole system on a question set

One JSON state per line,
then a summary of route and first words:

```sh
mkdir -p /tmp/finos-supervisor
cat > /tmp/finos-supervisor/questions.txt <<'EOF'
What is the overdraft fee?
What is the balance on ACC-12345?
Show my recent transactions
I'm furious! Nobody is helping!
Does ACC-12345 qualify for the fee waiver?
Should I invest my savings in crypto?
EOF

while IFS= read -r q; do
  uv run finos supervisor ask -q "$q" --json | jq -c .
done < /tmp/finos-supervisor/questions.txt > /tmp/finos-supervisor/results.jsonl

jq -r '"\(.intent)\t\(.response | gsub("\\s+"; " ") | .[0:60])\t\(.query)"' /tmp/finos-supervisor/results.jsonl
```

### 7. Compare the end-to-end answer with the specialist alone

If the
route is right but the answer is off, the specialist is the place to look:

```sh
uv run finos supervisor ask -q "What is the overdraft fee?"
uv run finos policy ask -q "What is the overdraft fee?" --verbose
```

### 8. Save the wiring as a diagram file


```sh
mkdir -p /tmp/finos-supervisor
uv run finos supervisor graph > /tmp/finos-supervisor/graph.puml
uv run finos supervisor graph --format mermaid > /tmp/finos-supervisor/graph.mmd
```

### 9. Save an end-to-end answer as a test fixture


```sh
uv run finos supervisor ask -q "What is the balance on ACC-12345?" --json | uv run finos state validate --strict --file -
uv run finos supervisor ask -q "What is the balance on ACC-12345?" --json \
  | uv run finos state serialize --file - -o /tmp/finos-supervisor/balance.json --force
```

### 10. Compare providers

Flip `[llm] use_local_ollama_model` in
`config.toml` and re-run recipe 3. Routing differences between models show
up as different `MISS` rows. The policy index rebuilds automatically on the
first policy route.

### 11. Use it from a script

Exit codes are stable: 0 success, 1 provider
or data failure, 2 bad input.

```sh
if state=$(uv run finos supervisor ask -q "What is the overdraft fee?" --json); then
  echo "$state" | jq -r '"\(.intent): \(.response)"'
else
  echo "supervisor ask failed with exit $?" >&2
fi
```
