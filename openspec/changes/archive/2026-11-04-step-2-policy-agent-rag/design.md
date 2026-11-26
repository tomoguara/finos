# Design

## Context

See `proposal.md` for motivation and `specs/` for required behavior. Today `policy_agent` raises `NotImplementedError`, `get_llm()` is the only provider-aware code, `chromadb` 0.6.3 and `langchain-chroma` 0.2.3 are already locked, and `langchain-text-splitters` 0.3.11 is installed through `langchain`. The corpus is four Markdown files of about 3.2 KB each, roughly 13 KB in total.

This design records the decisions from the Step 2 explore session. Sources:

- **Explore doc**: the Step 2 explore notes, updated to match this change
- **Context doc**: `docs/systems-design-and-architecture.md` §2.3, §3.6, §4.1, §6, §7

Decisions the developer made during the explore:

| Question | Decision |
| --- | --- |
| Embedding model | `qwen3-embedding:latest` on Ollama, `text-embedding-3-small` on OpenAI |
| Store lifetime | On-disk store in git-ignored `data/chroma/`, with fingerprint-based automatic rebuild and `ingest --rebuild` |
| Baseline | `RecursiveCharacterTextSplitter`, 1000/100, `top_k` 3 |

## Goals / Non-Goals

**Goals:**

- `ask_policy(query)` and `finos policy ask` produce a grounded answer and a `SupportState` that passes `finos state validate --strict`.
- Every RAG setting the hardening phase will tune is in `config.toml`.
- The index can never be silently stale: a change to a document, a chunk setting, or the embedding model causes a rebuild.
- The default test suite stays offline and needs no credentials, as in Steps 1 and 1b.
- The lecture's known failure modes stay reproducible, so evaluation has a baseline to improve on.

**Non-Goals:**

- Reranking, hybrid search, query rewriting, or embedding-model instruction prefixes.
- Concurrent writers to the index. This is a single-developer CLI tool.
- Retries, streaming, `max_tokens` limits, or context-length truncation (§7.6, §7.9).
- Fixing the replacement-card conflict or the wrong-document failure. Hardening does that.

## Decisions

### Departures from the explore doc

| Explore doc | This change | Why |
| --- | --- | --- |
| `chromadb.EphemeralClient()` plus a `finos policy ingest` command | Persistent store in `data/chroma/` | An in-memory index is gone when `ingest` exits, so the command would do nothing (D3) |
| `OpenAIEmbeddingFunction` from `chromadb.utils` | `get_embeddings()` in `finos.llm` through `langchain-chroma` | Keeps providers in one module, and works with Ollama (D2) |
| Collection `support_docs_multi` | `finos_policy_docs`, set in `config.toml` | Names what it holds, and the store is no longer shared with lecture notebooks |
| `content` in chunk metadata | Not stored | Chroma already stores the chunk text, so the copy would double the index (D4) |
| `{question}` in both the system and human messages | Context in the system message, question only in the human message | The question was sent twice (D6) |
| Fallback text names `support@securebank.com` | Fallback text names "SecureBank customer support" with no address | The corpus has no support address, and the agent must not invent contact details (D6) |
| `ask_policy` returns `policy_agent(state)` | Merges the agent's keys into `initial_state(query)` | The agent returns only its own three keys, so the sample lost `query` and `intent` (D7) |
| "With 4 docs, `top_k=3` retrieves 75% of the corpus" | Retrieval is over chunks, about 16, so 3 is roughly 20% | Recorded so the hardening phase reasons from the right baseline (D5) |
| Tests call the real model by default | Offline fakes by default; real-model tests behind a `live` marker | Steps 1 and 1b keep the suite runnable with no network or key (D10) |
| `uv add chromadb` | Already locked; only `langchain-text-splitters` is declared | Step 1 pinned the vector stack |
| Context doc §4.1: `top_k` baseline 5 | 3 | The developer chose the explore doc's baseline; §4.1 is updated |
| Context doc §7.10: in-memory vector store | On-disk index, still in-process | Same reason as the first row; §7.10 is updated |

### D1. Module layout

```
config.toml          [policy] section; embedding_model under [ollama] and [openai]
src/finos/
  config.py          + CHROMA_DIR = PROJECT_ROOT / "data" / "chroma"; new required settings
  llm.py             + get_embeddings(): the only provider-aware embedding code
  prompts.py         NEW: POLICY_SYSTEM_PROMPT, NOT_FOUND_MESSAGE
  vectorstore.py     NEW: load, chunk, fingerprint, build, open, search, format_docs
  agents/policy.py   policy_agent(state), ask_policy(query)
  agents/__init__.py + ask_policy export
  cli/policy.py      NEW: policy_app with ask, search, ingest
  cli/main.py        + app.add_typer(policy_app, name="policy")
data/chroma/         git-ignored on-disk index (created on first build)
```

`vectorstore.py` knows nothing about the agent or the prompt, so `finos policy search` and the hardening phase's experiments can use it without generating. `agents/policy.py` imports the store through a helper rather than building it at import time, so importing the agents package still makes no network call and needs no credentials (project-scaffold).

`cli/policy.py` follows the cli-framework rule: its top-level imports are `typer` and `finos.cli.shared` only. The agent, store, and LangChain imports happen inside each command body.

### D2. Embeddings follow the provider switch

`get_embeddings()` lives next to `get_llm()` and reads the same `use_local_ollama_model` flag:

| Switch | Class | Model setting | Shipped value |
| --- | --- | --- | --- |
| `true` | `langchain_ollama.OllamaEmbeddings` | `[ollama] embedding_model`, with the existing `base_url` | `qwen3-embedding:latest` |
| `false` | `langchain_openai.OpenAIEmbeddings` | `[openai] embedding_model` | `text-embedding-3-small` |

It is `lru_cache`d like `get_llm()`, makes no network call when constructed, and raises the same `RuntimeError` naming `OPENAI_API_KEY` when OpenAI is selected without a key. Chat and embedding providers are never mixed: one switch selects both, so a local run never needs an OpenAI key. Mixing would be easy to add later with a separate flag, but nothing needs it now.

Qwen3-Embedding scores better when queries carry an instruction prefix. `OllamaEmbeddings` does not add one, and this change does not either. That is recorded as a hardening option, because adding it later changes the fingerprint (D3) and rebuilds the index automatically.

### D3. On-disk store with a fingerprint marker

```
ask / search / ingest
        │
        ▼
 read data/chroma/finos_index.json ──► fingerprint matches current? ── yes ──► open collection
        │ no / missing / unreadable                                              │
        ▼                                                                        ▼
 delete collection (if any) → create → add all chunks → write marker last      query
```

- **Client**: `chromadb.PersistentClient(path=CHROMA_DIR)` with `anonymized_telemetry=False`, wrapped by `langchain_chroma.Chroma(client=..., collection_name=..., embedding_function=get_embeddings(), collection_metadata={"hnsw:space": "cosine"})`. Turning telemetry off keeps the offline suite offline and stops usage pings from a banking-support tool.
- **Fingerprint**: a SHA-256 over a canonical JSON object holding a schema version, the collection name, the splitter name, `chunk_size`, `chunk_overlap`, the embedding provider and model, and each document's bare filename and content hash, sorted by filename. `top_k` is left out because it doesn't change the index.
- **Marker**: `data/chroma/finos_index.json` holds the fingerprint, collection name, document and chunk counts, embedding provider and model, and build time. It is written only after every chunk has been added. A build that fails partway therefore leaves no matching marker, and the next call rebuilds from scratch. That answers the explore doc's question about partial ingestion: there is no rollback, but there is no silent partial index either.
- **Rebuild** deletes the collection first, because switching embedding models changes the vector size and Chroma rejects mixed sizes in one collection.
- **Process cache**: the opened store is cached per process (`lru_cache` on a zero-argument opener), and a rebuild clears that cache. Tests point `CHROMA_DIR` at `tmp_path` and clear the cache.
- **Ingest** without `--rebuild` builds only if the index is stale and otherwise reports that it is up to date. With `--rebuild` it always rebuilds.
- **Concurrency**: none. Two processes rebuilding at once can conflict. A single-developer CLI tool accepts this.

### D4. Loading and chunking

- **Loading**: every `*.md` file directly in `POLICY_DOCS_DIR`, read as UTF-8, in sorted filename order. No LangChain document loader is used, so `source` is set from `Path.name` and is a bare filename by construction (support-state obligation). A missing directory or a directory with no `.md` files raises `FileNotFoundError` naming the path.
- **Splitter**: `RecursiveCharacterTextSplitter(chunk_size, chunk_overlap)` with its default separators (`"\n\n"`, `"\n"`, `" "`, `""`), applied to each file separately so no chunk spans two documents. A Markdown-header splitter was rejected for the baseline because it would hide the chunk-splitting failure mode the evaluation phase is meant to find.
- **Metadata** per chunk: `source` (bare filename) and `chunk_index` (0-based position within its file). Chunk IDs are `"{source}:{chunk_index}"`, so a rebuild is deterministic and duplicates are impossible.

### D5. Retrieval and formatting

- `search(query, k)` calls `similarity_search_with_relevance_scores`. With cosine space, langchain-chroma reports relevance as `1 - distance`, so scores fall roughly in 0–1 and higher is better. `k` defaults to `[policy] top_k`.
- Results are ordered by score. `retrieved_sources` is the list of distinct `source` values in rank order, so the top source is first. That order is what the wrong-document check in the evaluation phase reads.
- `format_docs` produces one block per chunk, numbered from 1, separated by a blank line:

  ```
  [1] (Source: account_fees.md)
  <chunk text>
  ```

  Including the source lets the model cite it, and lets a developer reading `context` see where each passage came from.
- No relevance threshold and no length guard. At 3 × 1000 characters the context stays under about 1,000 tokens. Thresholds are a hardening experiment.
- Zero results (an empty collection should not happen after a build) give `context = ""` and `retrieved_sources = []`, and generation still runs, as §3.6 requires.

### D6. Prompt and generation

`finos/prompts.py` holds the prompts, so they can be compared side by side without touching agent code. Steps 3–5 add theirs here too.

```
system:  POLICY_SYSTEM_PROMPT with {context} filled in
human:   {question}
```

The system prompt keeps the explore doc's five rules, with two changes. The not-found sentence is a constant, `NOT_FOUND_MESSAGE` = "I don't have that information in our policy documents. Please contact SecureBank customer support.", so tests and the prompt share one string. Rule 5 (present both sides of a conflict and note the discrepancy) stays, because the replacement-card conflict is deliberate (policy-corpus). Few-shot examples and a stricter "every amount verbatim" rule were left out: they are prompt experiments for the evaluation phase, and the baseline should stay comparable to the lecture.

Generation is `ChatPromptTemplate | get_llm()` invoked once, and the response is the message's text content. Temperature comes from the shared `[llm] temperature`, which is 0. The chain lives inside `policy_agent`. Step 5 wraps the function as a graph node without changing it.

### D7. Agent contract

```python
def policy_agent(state: SupportState) -> dict:   # returns exactly {response, context, retrieved_sources}
def ask_policy(query: str) -> SupportState:       # {**initial_state(query), "intent": "policy", **policy_agent(...)}
```

`policy_agent` reads only `query` and never writes `query` or `intent`. `ask_policy` uses `initial_state()` from Step 1b instead of repeating the dict literal, and sets `intent` itself, because without the supervisor nothing else would. Its result passes `validate_state(strict=True, known_sources=<the corpus filenames>)`.

### D8. CLI

| Command | Options | Human output (stdout) | `--json` output |
| --- | --- | --- | --- |
| `finos policy ask` | `--query/-q` (required) | the answer, a blank line, `Sources: a.md, b.md` (or `Sources: none`) | the full `SupportState` |
| `finos policy search` | `--query/-q` (required), `--top-k/-k` (default from config, ≥ 1) | per hit: `[n] Score: 0.82  Source: file.md (chunk 2)` and an indented 200-character preview | list of `{rank, score, source, chunk_index, text}` |
| `finos policy ingest` | `--rebuild` | `Built index: 16 chunks from 4 documents (ollama/qwen3-embedding:latest)` or `Index up to date: …` | `{status: "built"\|"up_to_date", documents, chunks, provider, model, collection}` |

- `--verbose` writes diagnostics to stderr only: whether the index was reused or rebuilt, the provider and models, and for `ask` the full `context` the model saw. That last item is the lecture's debugging workflow. Stdout and the exit code stay the same with or without `--verbose` (cli-framework).
- An empty or whitespace-only `--query`, or `--top-k` below 1, exits 2 through `fail_usage`.
- A failure reaching a model or embedding provider (Ollama not running, embedding model not pulled, missing OpenAI key, API error) exits 1 with a one-line plain-text message on stderr and no traceback, including under `--json`. The command was valid but could not complete, so it is not a usage error. With `--verbose`, the exception type is also written.
- Every `policy` command loads settings, because it needs models. That is allowed: the "no settings" rule belongs to `state` commands and to `--help`.

### D9. Configuration

```toml
[ollama]
embedding_model = "qwen3-embedding:latest"

[openai]
embedding_model = "text-embedding-3-small"

[policy]
# RAG baseline from the lecture. The hardening phase tunes these.
collection = "finos_policy_docs"
chunk_size = 1000
chunk_overlap = 100
top_k = 3
```

All six keys join `_REQUIRED_SETTINGS`, so a missing one fails with the existing error that names the setting and the file. Paths stay as constants in `config.py` (`CHROMA_DIR`) like `POLICY_DOCS_DIR`, not in `config.toml`.

### D10. Testing

```
default run (offline, no key)                      uv run pytest -m live (developer, real models)
────────────────────────────────                   ───────────────────────────────────────────────
DeterministicFakeEmbedding + tmp CHROMA_DIR        real get_embeddings() + tmp CHROMA_DIR
GenericFakeChatModel / a prompt-capturing fake     real get_llm()
→ plumbing, contracts, CLI, fingerprints           → acceptance facts + failure-mode baseline
```

- **Offline** (`tests/test_vectorstore.py`, `tests/test_policy.py`, `tests/test_cli_policy.py`): chunk counts and metadata, bare filenames, deterministic IDs, fingerprint changes for each input that should change it (and none for `top_k`), rebuild on a stale or missing marker, no matching marker after a failed build, `format_docs` layout, distinct sources in rank order, the agent returning exactly three keys, the prompt sent to the model containing the context and the question, `ask_policy` passing strict validation, CLI output in both modes, exit codes 0/1/2, verbose output on stderr only, `get_embeddings()` provider selection and its missing-key error, and the light-import test still passing with `policy` registered.
- **Live** (`@pytest.mark.live`, deselected by `addopts = "-m 'not live'"` in `pyproject.toml`): the explore doc's acceptance facts ($35 overdraft, 4.49% or 12.99% APR, `account_fees.md` ranked first for "overdraft", the not-found message for an out-of-scope question, sources within the corpus). They run against whichever provider `config.toml` selects.
- **Failure-mode baseline**: the lecture's four failure modes (split fact, wrong document, hallucinated amount, empty retrieval) are recorded as live tests marked `xfail(strict=False)` with a reason that names the failure. They document the baseline without failing the build, and an XPASS shows that one no longer reproduces. The split-fact case also gets an offline, deterministic check of which chunk each key fact lands in at 1000/100, which needs no model.

### D11. Documents

- `docs/systems-design-and-architecture.md`: §4.1 `top_k` baseline 3 and the store lifetime; §6 embeddings row decided; §7.10 an on-disk, in-process index; §8 layout with `prompts.py`, `vectorstore.py`, `cli/policy.py`, and `data/chroma/`; §10 Step 2 row.
- `README.md`: `ollama pull qwen3-embedding:latest`, the `finos policy` commands, and running live tests.
- The explore doc is updated now, alongside this change, to record the locked decisions.

## Risks / Trade-offs

- **Local embedding model not pulled** → the first `ask` fails. The CLI error names the model and the Ollama base URL, and the README lists the pull step.
- **Embeddings differ by provider**, so retrieval results and scores from Ollama and OpenAI are not comparable. The fingerprint forces a rebuild on every switch, so wrong vectors are never used. Comparisons against the lecture's figures should use OpenAI.
- **A switch-and-back costs two rebuilds**, about 16 embedding calls each. One collection per provider would avoid that but add state for little gain at this corpus size.
- **Live tests depend on the model**: a different local model can phrase the not-found answer differently. The live tests check for the constant and the key figures, not exact text.
- **`data/chroma/` can be deleted at any time**, and the next call rebuilds it.

## Open Questions

None blocking. The query-instruction prefix for Qwen3-Embedding, relevance thresholds, and Markdown-aware splitting are recorded as hardening experiments.
