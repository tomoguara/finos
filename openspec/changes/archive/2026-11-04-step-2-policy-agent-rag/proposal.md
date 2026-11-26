# Proposal

## Why

The policy agent is the most complex specialist, and Steps 3–5 assume it works: the supervisor's default route is `policy`, and the evaluation and observability layers read the `context` and `retrieved_sources` only this agent writes. Building it alone, with its own entry points, lets retrieval and grounding be checked before the graph adds routing on top. Today `policy_agent` is a stub, nothing chooses an embedding model, and the context document and the Step 2 explore doc disagree on `top_k` and on whether the vector store survives the process.

## What Changes

- Implement `policy_agent(state)` as a RAG pipeline over `data/policy-docs/`: chunk, embed, store in Chroma, retrieve the top 3 chunks, format them into a context string, and generate an answer grounded in that context. It returns only `response`, `context`, and `retrieved_sources`.
- Add `ask_policy(query)`, which runs the agent without the graph and returns a full `SupportState` with `intent` set to `policy`.
- Add `get_embeddings()` to `finos.llm`, following the same provider switch as `get_llm()`: `qwen3-embedding:latest` on Ollama and `text-embedding-3-small` on OpenAI.
- Keep the vector store on disk in git-ignored `data/chroma/`. A fingerprint of the documents, chunk settings, and embedding model is recorded after each build, and a missing or stale index is rebuilt automatically on first use.
- Add a `[policy]` section to `config.toml` for `chunk_size` (1000), `chunk_overlap` (100), `top_k` (3), and the collection name, and add `embedding_model` to `[ollama]` and `[openai]`, so later tuning only edits configuration.
- Put the grounding prompt in a new `finos.prompts` module.
- Add the `finos policy` command group: `ask`, `search` (shows retrieval with scores, without generating), and `ingest` (`--rebuild` forces a rebuild).
- Keep the default test suite offline by using fake embeddings and a fake chat model. Tests that call real models move behind a `live` pytest marker that is skipped by default. They include baseline tests that record the lecture's known failure modes.
- Declare `langchain-text-splitters` as a direct dependency. It is installed today only through `langchain`.
- Update `docs/systems-design-and-architecture.md`, the README, and the Step 2 explore doc to match.

**Out of scope**: the supervisor, the account and escalation agents, graph wiring, `finos run`, reranking, query-instruction prefixes for the embedding model, observability, evaluation, guardrails, cost tracking, retries, and streaming.

## Capabilities

### New Capabilities

- `policy-retrieval`: Loading and chunking the policy corpus, embedding it into a persistent Chroma collection, detecting a stale index, and similarity search with scores.
- `policy-agent`: The grounded-answer node, its prompt, how it writes `SupportState`, and the standalone `ask_policy` helper.
- `policy-cli`: The `finos policy` commands `ask`, `search`, and `ingest`.

### Modified Capabilities

- `llm-access`: Adds the embedding helper and the new shipped settings (embedding models and the `[policy]` section).
- `project-scaffold`: Declares `langchain-text-splitters`, ignores `data/chroma/` in git, and narrows "tests run offline" to the default run, with live tests opt-in.

## Impact

- **Code**: new `src/finos/vectorstore.py`, `src/finos/prompts.py`, and `src/finos/cli/policy.py`; `src/finos/agents/policy.py` implemented; `get_embeddings()` added to `src/finos/llm.py`; `CHROMA_DIR` and new required settings added to `src/finos/config.py`; one `add_typer` line in `src/finos/cli/main.py`; `ask_policy` exported from `finos.agents`.
- **Configuration**: new keys in `config.toml`. Local use needs `ollama pull qwen3-embedding:latest` on the Ollama host.
- **Tests**: new `tests/test_vectorstore.py` and `tests/test_cli_policy.py`; `tests/test_policy.py` filled in; `tests/test_llm.py` and `tests/test_scaffold.py` updated, because `policy_agent` is no longer a stub. A `live` marker and default deselection are added to `pyproject.toml`.
- **Dependencies**: `langchain-text-splitters` declared, with the locked version unchanged. `chromadb` and `langchain-chroma` are already pinned.
- **Runtime**: the first `ask`, `search`, or `ingest` after a corpus, setting, or provider change embeds the whole corpus, about 16 chunks. Later calls embed only the query. `data/chroma/` holds the index and is safe to delete.
- **Documents**: `docs/systems-design-and-architecture.md` (§4.1, §6, §7.10, §8, §10), `README.md`, and the Step 2 explore notes.
