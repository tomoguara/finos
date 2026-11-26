# The `finos policy` commands

[← Back to the README](../../README.md)

Shared options are described in the [command line overview](cli-overview.md);
unit and live tests are in the [testing guide](testing.md).

## Contents

- [Overview](#overview)
- [Options](#options)
- [`finos policy ingest`](#finos-policy-ingest)
- [`finos policy search`](#finos-policy-search)
- [`finos policy ask`](#finos-policy-ask)
- [The index (`data/chroma/`)](#the-index-datachroma)
- [Settings you can tune](#settings-you-can-tune)
- [Exit codes and errors](#exit-codes-and-errors)
- [Recipes: quick tests and optimization checks](#recipes-quick-tests-and-optimization-checks)
  - [1. Smoke-test the whole path](#1-smoke-test-the-whole-path)
  - [2. See why it answered that](#2-see-why-it-answered-that)
  - [3. Is the right document ranked first?](#3-is-the-right-document-ranked-first)
  - [4. Find which chunk holds a fact](#4-find-which-chunk-holds-a-fact)
  - [5. Compare retrieval depth (`top_k`)](#5-compare-retrieval-depth-top_k)
  - [6. Compare chunk settings](#6-compare-chunk-settings)
  - [7. Compare providers](#7-compare-providers)
  - [8. Run a question set](#8-run-a-question-set)
  - [9. Check an answer's amounts against its context](#9-check-an-answers-amounts-against-its-context)
  - [10. Measure context size and latency](#10-measure-context-size-and-latency)
  - [11. Save an answer as a test fixture](#11-save-an-answer-as-a-test-fixture)
  - [12. Use it from a script](#12-use-it-from-a-script)

## Overview

Runs the policy agent on its own, without the supervisor or the graph. Use
these commands for quick checks of retrieval and answers, and for trying
out RAG settings before changing code.

| Command  | What it does | Models it calls |
| -------- | ------------ | --------------- |
| `ingest` | builds the index if it is missing or stale, otherwise reports it is up to date | embeddings, for every chunk, only when it builds |
| `search` | shows the ranked chunks retrieval returns for a query, with scores; **no answer is generated** | embeddings, for the query only |
| `ask`    | answers a query from the retrieved chunks and lists the sources | embeddings for the query, then one chat call |

Unlike `state`, these commands load `config.toml` and call models, so they
need the configured provider:

- **Local (default, `use_local_ollama_model = true`)**: Ollama must be
  reachable at `[ollama] base_url`, with both the chat model and
  `qwen3-embedding:latest` pulled (`ollama pull qwen3-embedding:latest`).
- **OpenAI (`use_local_ollama_model = false`)**: `OPENAI_API_KEY` must be
  in `.env` or the environment.

> **Tracing and stderr.** With `[langsmith] tracing = true` and no
> `LANGCHAIN_API_KEY`, the LangSmith client prints warnings on stderr after
> `ask`, because it has nowhere to send the trace. stdout and the exit code
> are unaffected. For quick local checks, set `tracing = false`.

> **Quoting.** Put queries that contain `$` in single quotes. In double
> quotes the shell expands `"$35"` to `5` before `finos` sees it:
> `-q 'Is the overdraft fee $35?'`.

## Options

| Option | Commands | Meaning |
| ------ | -------- | ------- |
| `--query/-q TEXT` | `ask`, `search` | The question. Required; empty or whitespace-only exits 2. |
| `--top-k/-k N` | `search` | How many chunks to return. Default `[policy] top_k` (3); must be at least 1. `ask` has no `--top-k`: it always uses `[policy] top_k`. |
| `--rebuild` | `ingest` | Rebuild the index even if it is up to date. |
| `--json/-j` | all | Machine-readable JSON on stdout (shapes below). |
| `--verbose/-v` | all | Diagnostics on stderr; stdout and exit code do not change. |
| `--no-color` | all | No ANSI color. |

The shared options work before the module name or after the command:
`finos --json policy search -q overdraft` and
`finos policy search -q overdraft --json` are the same.

## `finos policy ingest`

Builds or checks the index explicitly. You never *have* to run it: `ask`
and `search` build a missing or stale index on first use. Run it after
changing documents or settings, so the rebuild cost isn't counted in your
first `ask`.

```console
$ uv run finos policy ingest
Built index: 16 chunks from 4 documents (ollama/qwen3-embedding:latest)

$ uv run finos policy ingest
Index up to date: 16 chunks from 4 documents (ollama/qwen3-embedding:latest)

$ uv run finos policy ingest --rebuild --verbose
debug: index rebuilt: 16 chunks from 4 documents in collection finos_policy_docs (ollama/qwen3-embedding:latest)
Built index: 16 chunks from 4 documents (ollama/qwen3-embedding:latest)
```

`--json` prints one object:

```json
{
  "status": "up_to_date",
  "documents": 4,
  "chunks": 16,
  "provider": "ollama",
  "model": "qwen3-embedding:latest",
  "collection": "finos_policy_docs"
}
```

| Field | Meaning |
| ----- | ------- |
| `status` | `built` (embedded every chunk just now) or `up_to_date` (reused the index; nothing embedded) |
| `documents`, `chunks` | what the index holds |
| `provider`, `model` | the embedding provider and model the index was built with |
| `collection` | the Chroma collection name (`[policy] collection`) |

## `finos policy search`

Shows what the retriever returns, ranked, **without** calling the chat
model. It is the cheapest way to check retrieval: one query embedding per
run.

```console
$ uv run finos policy search --query "overdraft" --top-k 2
[1] Score: 0.71  Source: account_fees.md (chunk 2)
    An account enrolled in overdraft protection has a linked savings account drawn on instead. Each overdraft protection transfer carries a fee of $12, which is lower than the overdraft fee it replaces. T...
[2] Score: 0.69  Source: account_fees.md (chunk 1)
    The Premium Checking monthly fee of $12.99 is waived for any statement cycle in which the account holder keeps an average daily balance above $1,500, or receives a qualifying direct deposit of $500 or...
```

*(Scores and the order shown are illustrative. Real values depend on the
embedding model.)*

How to read each hit:

- **`[n]`** is the rank, from 1. `ask` puts the same chunks in the same
  order into the model's context, numbered the same way.
- **`Score`** is cosine relevance (`1 − cosine distance`), shown to two
  decimals. Higher is more relevant, and values fall roughly between 0 and
  1. Hits are always in non-increasing score order. Scores are only
  comparable within one embedding model, so don't compare Ollama scores
  with OpenAI scores.
- **`Source`** is the bare filename in `data/policy-docs/`.
- **`chunk n`** is the 0-based position of the chunk within that file.
  With the shipped 1000/100 settings the corpus makes 16 chunks.
- The indented line is a preview: the chunk's first 200 characters with
  line breaks collapsed, then `...` if it was cut. Use `--json` for the
  full text.

`--json` prints a list, best first:

```json
[
  {
    "rank": 1,
    "score": 0.7134,
    "source": "account_fees.md",
    "chunk_index": 2,
    "text": "An account enrolled in overdraft protection has a linked savings account\ndrawn on instead. ..."
  }
]
```

`score` is unrounded in JSON, and `text` is the whole chunk with its
original line breaks.

`--verbose` adds the index status, the trace line, and the timings to
stderr. `search` is traced as its own `policy_search` root, with one
`policy_retrieval` run holding the hits as documents:

```console
$ uv run finos policy search -q "overdraft" -k 2 --verbose > /dev/null
debug: index reused: 16 chunks from 4 documents in collection finos_policy_docs (ollama/qwen3-embedding:latest)
debug: trace: 01a1e308-fe0f-7201-90f2-2bc9870ce72f (project finos)
debug: policy_search: 52 ms (retrieval 51 ms)
debug: total: 0.31 s
debug: cost: $0.000000 (3+0 tokens, 1 call; guards $0.000000; prices as of 2026-11-20)
```

The last line is the cost (Hardening 4): `search` makes one query
embedding, whose tokens are estimated (characters ÷ 4) and which costs $0
on the local provider. See [Cost](cost.md#the-verbose-cost-line).

## `finos policy ask`

Runs the policy agent: retrieves the top `[policy] top_k` chunks, puts
them in the system prompt (`src/finos/prompts.py`), sends the question as
the human message, and prints the model's answer and the distinct sources
in rank order.

```console
$ uv run finos policy ask --query "What is the overdraft fee?"
The overdraft fee is $35 per transaction, with a maximum of 3 overdraft fees per day ($105).

Sources: account_fees.md
```

*(The answer text depends on the chat model.)* The output is always the
response, a blank line, then `Sources: a.md, b.md`, or `Sources: none` if
nothing was retrieved. When the answer is not in the context, the agent
replies with the fixed not-found message, "I don't have that information
in our policy documents. Please contact SecureBank customer support."

`--json` prints the complete `SupportState`, with `intent` set to `policy`.
It always passes `finos state validate --strict`:

```json
{
  "query": "What is the overdraft fee?",
  "intent": "policy",
  "response": "The overdraft fee is $35 per transaction, ...",
  "context": "[1] (Source: account_fees.md)\n...\n\n[2] (Source: account_fees.md)\n...",
  "retrieved_sources": ["account_fees.md"]
}
```

`context` is exactly what the model received: one block per chunk,
numbered from 1, each headed `[n] (Source: file.md)`, separated by a blank
line.

`--verbose` is the main debugging tool. It writes the chat model, whether
the index was reused or rebuilt, **the full context the model saw**, the
trace, and where the time went, all to stderr:

```console
$ uv run finos policy ask -q "What is the overdraft fee?" --verbose
debug: chat model: ollama/qwen3.8:27b-q8_0
debug: index reused: 16 chunks from 4 documents in collection finos_policy_docs (ollama/qwen3-embedding:latest)
debug: context sent to the model:
[1] (Source: account_fees.md)
...
The overdraft fee is $35 per transaction, with a maximum of 3 overdraft fees per day ($105).

Sources: account_fees.md
debug: trace: 01a1e308-fe0f-7201-90f2-2bc9870ce72f (project finos)
debug: policy_query: 1077 ms (retrieval 41 ms), 1240+85 tokens
debug: total: 1.41 s
debug: cost: $0.000000 (1247+85 tokens, 2 calls; guards $0.000000; prices as of 2026-11-20)
```

The `cost:` line (Hardening 4) totals every call the query made: here the
query embedding (7 estimated tokens) and the policy model, both local and
so $0. With the shipped OpenAI guard layers and a key, a `guards:` line
comes first and the cost is the classifier's. See [Cost](cost.md#the-verbose-cost-line).

- **The trace line** names the LangSmith trace (root run `policy_query`,
  with `policy_retrieval` and `policy_llm` beneath it). With tracing off it
  reads `debug: trace: none (tracing off)`; with a sampling rate below 1.0
  it adds `sampling 0.25: may not be recorded`.
- **The timing line** gives the whole request's time, the retrieval time
  inside it, and the model call's prompt+completion tokens (`n/a tokens`
  when the provider reports no usage). It works with tracing off.
- **The total** is the command's wall time, including opening the index.

**Guardrails** (Hardening 3): every guard that did anything but pass adds
one `debug: guardrail: ...` line before the trace line, for example
`debug: guardrail: regex blocked (investment_advice)`; a blocked query
prints the safe fallback on stdout and exits 0. With the model-based input
layers enabled but no `OPENAI_API_KEY`, one
`guardrails: moderation and injection_classifier off (no OPENAI_API_KEY)`
line is written, verbose or not. See [Guardrails](guardrails.md#reading-guard-decisions).

See [Debugging with traces](debugging-with-traces.md) for reading the trace.

Because diagnostics go to stderr, you can split them from the answer:
`... --verbose 2> context.txt`.

## The index (`data/chroma/`)

Chunks are embedded into a Chroma collection (cosine distance) stored on
disk in `data/chroma/`, which is git-ignored. After every successful build
the index records a fingerprint in `data/chroma/finos_index.json`. Every
`ask`, `search`, and `ingest` compares that fingerprint with the current
inputs and rebuilds the whole index if they differ. A stale index is
never used.

| You change | Index rebuilt on next use? |
| ---------- | -------------------------- |
| A policy document's text, or add, remove, or rename a `.md` file in `data/policy-docs/` | yes |
| `[policy] chunk_size` or `chunk_overlap` | yes |
| `[policy] collection` | yes; the old collection is deleted |
| `[llm] use_local_ollama_model` (switches the embedding provider too) | yes |
| `[ollama] embedding_model` or `[openai] embedding_model` | yes |
| `[policy] top_k` | no; it changes retrieval depth, not the index |
| Chat model, temperature, `[ollama] base_url`, tracing, or the prompt | no |

- A rebuild embeds every chunk (16 at 1000/100). Later calls embed only
  the query.
- If a build fails partway (for example, Ollama stops), no valid
  fingerprint is left behind, so the next call rebuilds from scratch.
- Switching provider and back costs two rebuilds: the index holds one
  provider's vectors at a time.
- Inspect the index with `cat data/chroma/finos_index.json`. It shows the
  fingerprint, collection, document and chunk counts, provider, model, and
  build time.
- Delete `data/chroma/` at any time (`rm -rf data/chroma`). It is rebuilt
  on next use.
- Don't run two rebuilding commands at once: concurrent writers are not
  supported.

## Settings you can tune

All RAG settings are in `config.toml`. Edit the file, then run any
`policy` command; no code changes are needed.

```toml
[policy]
# RAG baseline from the lecture. The hardening phase tunes these.
collection = "finos_policy_docs"
chunk_size = 1000      # max characters per chunk
chunk_overlap = 100    # characters repeated between neighbouring chunks
top_k = 3              # chunks retrieved per question
```

| Setting | Effect | Trade-off |
| ------- | ------ | --------- |
| `chunk_size` | Max characters per chunk. Chunks are split per file with `RecursiveCharacterTextSplitter` (paragraph, then line, then word breaks), so no chunk spans two documents. | Smaller chunks are more precise but can split a fact from its context. |
| `chunk_overlap` | Characters repeated at each chunk boundary. | More overlap means fewer split facts, but more duplicated text in the context. |
| `top_k` | Chunks placed in the context for `ask` (and the default for `search`). | More chunks give better recall but more tokens and more noise. |
| `collection` | The Chroma collection name. | Rename it to keep an experiment's index apart. |

Chunk counts for the current corpus, so you know what you're comparing:

| `chunk_size` / `chunk_overlap` | Chunks |
| ------------------------------ | ------ |
| 1500 / 150 | 12 |
| **1000 / 100 (shipped)** | **16** |
| 800 / 100 | 21 |
| 600 / 60 | 29 |
| 400 / 50 | 46 |

To preview chunking for other settings without embedding anything:

```sh
uv run python -c "from finos.vectorstore import load_documents, chunk_documents as c; print(len(c(load_documents(), 400, 50)))"
```

## Exit codes and errors

| Exit | When | stderr |
| ---- | ---- | ------ |
| 0 | success | empty (diagnostics only with `--verbose`), except `ask` and `search` write `tracing: off (no LANGSMITH_API_KEY or LANGCHAIN_API_KEY set)` when tracing is on but no key is set |
| 1 | the command was valid, but a model or embedding provider could not be reached or used: Ollama not running, model not pulled, missing `OPENAI_API_KEY`, API error | one plain-text line, even with `--json`; stdout is empty |
| 2 | unusable input: empty `--query`, `--top-k` below 1, unknown option | `Error: --query must not be empty` / `Error: --top-k must be at least 1` |

A provider failure names the provider and models, so you can see what was
configured:

```console
$ uv run finos policy ask -q "What is the overdraft fee?"
Error: Failed to connect to Ollama. Please check that Ollama is downloaded, running and accessible. https://ollama.com/download (ollama at http://localhost:11434, chat model qwen3.8:27b-q8_0, embedding model qwen3-embedding:latest)
```

Add `--verbose` to see the exception type as well (for example
`debug: builtins.ConnectionError`). A failed command prints no trace,
timing, or no-key line, so stderr stays one line.

## Recipes: quick tests and optimization checks

These run from the repository root. The JSON recipes use
[`jq`](https://jqlang.github.io/jq/). Most write to `/tmp/finos-policy/`.

### 1. Smoke-test the whole path

These are the acceptance checks: all
exit 0, the overdraft answer contains `$35`, the APR answer contains
`4.49%` or `12.99%`, and `account_fees.md` ranks first for "overdraft".

```sh
uv run finos policy ingest
uv run finos policy ask --query "What is the overdraft fee?"
uv run finos policy ask --query "What is the APR range for auto loans?" --json
uv run finos policy search --query "overdraft" --top-k 2
```

### 2. See why it answered that

Print only the context the model saw, or
only the answer and sources:

```sh
uv run finos policy ask -q "How much does overdraft protection cost?" --json | jq -r .context
uv run finos policy ask -q "How much does overdraft protection cost?" --json | jq '{response, retrieved_sources}'
```

### 3. Is the right document ranked first?

One compact line per hit, with
the score to three decimals:

```sh
uv run finos policy search -q "How much does a replacement debit card cost?" -k 5 --json \
  | jq -r '.[] | "\(.rank)  \(.score * 1000 | round / 1000)  \(.source):\(.chunk_index)"'
```

The replacement-card question is the corpus's deliberate conflict: $5 in
`account_fees.md`, free in `fraud_policy.md`. Rule 5 of the prompt asks
the model to present both.

### 4. Find which chunk holds a fact

Retrieve every chunk (16 at the
shipped settings) and filter by text. The text keeps its line breaks, so
search for a short phrase:

```sh
uv run finos policy search -q "overdraft protection" -k 16 --json \
  | jq -r '.[] | select(.text | contains("$12,")) | "\(.rank)  \(.source):\(.chunk_index)"'
```

If the chunk holding the answer ranks below `top_k`, `ask` will not see it.

### 5. Compare retrieval depth (`top_k`)

No rebuild needed. `search`
shows what each depth would retrieve:

```sh
for k in 1 2 3 4 5; do
  printf 'k=%s  ' "$k"
  uv run finos policy search -q "How much does overdraft protection cost?" -k "$k" --json \
    | jq -r '[.[] | "\(.source):\(.chunk_index)"] | join(", ")'
done
```

To see the effect on answers, change `[policy] top_k` in `config.toml`
and re-run `ask`. The index is reused.

### 6. Compare chunk settings

Each setting triggers one rebuild. This
block runs in a subshell, backs up `config.toml`, tries each pair, shows
the top hits, and restores the file when it finishes or is interrupted:

```sh
(
  cp config.toml /tmp/config.toml.bak
  trap 'cp /tmp/config.toml.bak config.toml' EXIT
  for pair in 1000:100 800:100 600:60 400:50; do
    size=${pair%:*} overlap=${pair#*:}
    sed -i.tmp -e "s/^chunk_size = .*/chunk_size = $size/" \
               -e "s/^chunk_overlap = .*/chunk_overlap = $overlap/" config.toml && rm -f config.toml.tmp
    echo "== chunk_size=$size chunk_overlap=$overlap"
    uv run finos policy ingest
    uv run finos policy search -q "How much does overdraft protection cost?" --json \
      | jq -r '.[] | "  \(.rank)  \(.score * 1000 | round / 1000)  \(.source):\(.chunk_index)"'
  done
)
```

Afterwards, the next `policy` command rebuilds the index back to the
shipped settings.

### 7. Compare providers

Flip `[llm] use_local_ollama_model` and run the
same commands. The index rebuilds automatically with the other embedding
model. Compare which sources rank first and what the answers say, not the
raw scores. Use OpenAI (`false`) when comparing against the lecture's
figures.

### 8. Run a question set

Put one question per line in a file, collect
one JSON state per line, then summarize:

```sh
mkdir -p /tmp/finos-policy
cat > /tmp/finos-policy/questions.txt <<'EOF'
What is the overdraft fee?
How much does overdraft protection cost?
What is the APR range for auto loans?
How much does a replacement debit card cost?
What are the wire transfer fees?
How long do I have to report fraud?
What is the stock market outlook?
EOF

while IFS= read -r q; do
  uv run finos policy ask -q "$q" --json | jq -c .
done < /tmp/finos-policy/questions.txt > /tmp/finos-policy/results.jsonl

jq -r '"\(.retrieved_sources | join(","))\t\(.query)"' /tmp/finos-policy/results.jsonl
jq -r 'select(.response | startswith("I don'"'"'t have that information")) | .query' /tmp/finos-policy/results.jsonl
```

The first summary lists the sources for each question. The second lists
the questions answered with the not-found message. Re-run after a
settings change and `diff` the outputs. For a retrieval-only version
(cheaper, no chat calls), use `search ... --json` in the loop.

### 9. Check an answer's amounts against its context

This is a quick
manual version of the live hallucination test. It lists any dollar
amounts in the response that do not appear in the context:

```sh
uv run finos policy ask -q "How much does overdraft protection cost?" --json > /tmp/finos-policy/answer.json
amounts() { grep -oE '\$[0-9]{1,3}(,[0-9]{3})+(\.[0-9]+)?|\$[0-9]+(\.[0-9]+)?' | sort -u; }
comm -23 <(jq -r .response /tmp/finos-policy/answer.json | amounts) \
         <(jq -r .context /tmp/finos-policy/answer.json | amounts)
```

No output means every amount was grounded. A derived figure, such as a
difference between two fees, also shows up here. Read it before calling it
a hallucination.

### 10. Measure context size and latency

```sh
time uv run finos policy ask -q "What is the overdraft fee?" > /dev/null
uv run finos policy ask -q "What is the overdraft fee?" --json | jq '.context | length'   # characters sent as context
```

The first call after a rebuild-triggering change also embeds the whole
corpus. Run `ingest` first so it isn't counted in your timing. For a
breakdown, `--verbose` prints the retrieval time, the model call's time and
tokens, and the total:

```sh
uv run finos policy ask -q "What is the overdraft fee?" -v 2>&1 >/dev/null | grep -E "policy_query|total"
```

### 11. Save an answer as a test fixture

`ask --json` output is a valid
`SupportState`, so it pipes straight into the `state` toolkit:

```sh
uv run finos policy ask -q "What is the overdraft fee?" --json | uv run finos state validate --strict --file -
uv run finos policy ask -q "What is the overdraft fee?" --json \
  | uv run finos state serialize --file - -o /tmp/finos-policy/overdraft.json --force
```

### 12. Use it from a script

Exit codes are stable: 0 success, 1
provider failure, 2 bad input. stdout holds only the result, so
`--json` output can be parsed safely:

```sh
if out=$(uv run finos policy ask -q "What is the overdraft fee?" --json); then
  echo "$out" | jq -r .response
else
  echo "policy ask failed with exit $?" >&2
fi
```
