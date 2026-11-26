# Tasks

> **Before you start.** Local live checks need `ollama pull qwen3-embedding:latest` on the Ollama host that `[ollama] base_url` points at. The default test run needs neither Ollama nor an OpenAI key. Groups 1–8 are verified offline; group 9 is the live acceptance run.

## 1. Branch, dependency, and ignore rules

- [x] 1.1 Create and switch to branch `step-2-policy-agent-rag`; verify with `git branch --show-current`.
- [x] 1.2 Add `langchain-text-splitters>=0.3,<0.4` to `pyproject.toml` dependencies and run `uv lock`; verify `uv sync --locked` succeeds and `uv pip show langchain-text-splitters` still reports 0.3.11.
- [x] 1.3 Add `data/chroma/` to `.gitignore`; verify `git check-ignore data/chroma/x` reports it and `git check-ignore data/policy-docs/account_fees.md` does not.
- [x] 1.4 Add a `[tool.pytest.ini_options]` section to `pyproject.toml` that registers a `live` marker and sets `addopts = "-m 'not live'"`; verify `uv run pytest` still passes and `uv run pytest -m live` collects only `live` tests (none yet).

## 2. Configuration and embeddings

- [x] 2.1 Add `embedding_model` to `[ollama]` and `[openai]` and the `[policy]` section to `config.toml` per design D9, and add the six keys to `_REQUIRED_SETTINGS` in `src/finos/config.py`; extend `tests/test_llm.py` so the shipped-values test covers them and a config missing `[policy] top_k` fails naming that setting and the file; verify `uv run pytest tests/test_llm.py` passes.
- [x] 2.2 Add `CHROMA_DIR = PROJECT_ROOT / "data" / "chroma"` to `src/finos/config.py` with a docstring, and a test for its value; verify `uv run pytest tests/test_llm.py` passes.
- [x] 2.3 Add a cached `get_embeddings()` to `src/finos/llm.py` per design D2, and tests for each provider, the shared instance, the missing-key error, and no network call on construction (both switch values, using the existing patterns that rewrite settings); verify `uv run pytest tests/test_llm.py` passes with `use_local_ollama_model` set to true and again set to false.

## 3. Vector store

- [x] 3.1 Create `src/finos/vectorstore.py` with document loading and per-file chunking per design D4 (`source` as `Path.name`, `chunk_index`, IDs `"{source}:{chunk_index}"`, `FileNotFoundError` naming the directory); add `tests/test_vectorstore.py` covering the shipped-settings scenario, bare filenames, contiguous indexes, and a missing or empty directory; verify `uv run pytest tests/test_vectorstore.py` passes.
- [x] 3.2 Add the fingerprint and the marker file per design D3, and tests that each input in the spec changes the fingerprint, that `top_k` does not, and that file order does not; verify `uv run pytest tests/test_vectorstore.py` passes.
- [x] 3.3 Add build, open-or-rebuild, and the per-process cache per design D3 (PersistentClient with telemetry off, cosine space, delete-then-create, marker written last). Add tests using `DeterministicFakeEmbedding` and a `tmp_path` `CHROMA_DIR`: first open builds, a second open with an embedding fake that counts calls embeds no documents, a stale marker rebuilds, a forced rebuild rebuilds, a different embedding size rebuilds cleanly, and an embedder that fails partway leaves no matching marker. Verify `uv run pytest tests/test_vectorstore.py` passes and nothing is written under the real `data/chroma/`.
- [x] 3.4 Add `search(query, k=None)` returning ranked hits with relevance scores, and `format_docs()` per design D5; add tests for the default and explicit `k`, non-increasing scores, the two-chunk formatting scenario, and empty input formatting as `""`; verify `uv run pytest tests/test_vectorstore.py` passes.

## 4. Prompt and agent

- [x] 4.1 Create `src/finos/prompts.py` with `NOT_FOUND_MESSAGE` and `POLICY_SYSTEM_PROMPT` per design D6 (five rules, `{context}` placeholder only, no contact address); verify by a test that the prompt contains the not-found constant and a `{context}` placeholder but no `{question}` placeholder.
- [x] 4.2 Implement `policy_agent` in `src/finos/agents/policy.py` per design D6 and D7, keeping the bare-filename paragraph in its docstring and removing the `NotImplementedError` note. Write `tests/test_policy.py` with a fake chat model that records its input and fake embeddings in a `tmp_path` store: exactly three keys returned, distinct sources in rank order, `context` equal to what the model received, one system and one human message, empty retrieval still calling the model, and the bare-filename obligation from `specs/support-state/spec.md`. Verify `uv run pytest tests/test_policy.py` passes.
- [x] 4.3 Add `ask_policy(query)` built on `initial_state()` and export it from `finos.agents`; add tests for the complete-state scenario and for `validate_state(strict=True, known_sources=<corpus filenames>)` returning no problems; verify `uv run pytest tests/test_policy.py` passes.
- [x] 4.4 Add a test that importing `finos.agents` in a fresh subprocess, with `CHROMA_DIR` pointing at a missing directory and no key, succeeds without creating that directory; verify `uv run pytest tests/test_policy.py` passes.
- [x] 4.5 Update `tests/test_scaffold.py`: remove `policy_agent` from the stub list, and keep the bare-filename docstring test passing against the implemented function; verify `uv run pytest tests/test_scaffold.py` passes.

## 5. CLI

- [x] 5.1 Create `src/finos/cli/policy.py` with `policy_app` (`no_args_is_help=True`) and register it in `src/finos/cli/main.py` with one `add_typer` line; keep heavy imports inside command bodies; verify `uv run finos policy --help` lists three commands and the existing light-import test in `tests/test_cli.py` still passes.
- [x] 5.2 Implement `ask` per design D8 (human and `--json` output, verbose context on stderr); add `tests/test_cli_policy.py` with the agent patched to a canned state, covering both output modes, `--json` output passing `finos state validate --strict`, and identical stdout with and without `--verbose`; verify `uv run pytest tests/test_cli_policy.py` passes.
- [x] 5.3 Implement `search` per design D8, and tests with fake embeddings for both output modes, `--top-k`, the default from config, and the chat model never being requested; verify `uv run pytest tests/test_cli_policy.py` passes.
- [x] 5.4 Implement `ingest` and `--rebuild` per design D8, and tests for `built`, then `up_to_date`, then `built` with `--rebuild`, in both output modes; verify `uv run pytest tests/test_cli_policy.py` passes.
- [x] 5.5 Add the error handling from design D8: exit 2 for an empty query or `--top-k 0`; exit 1 with one stderr line and empty stdout when the provider raises a connection error or the OpenAI key is missing, including with `--json`; tests for each; verify `uv run pytest tests/test_cli_policy.py` passes.

## 6. Failure-mode baseline (offline part)

- [x] 6.1 Add an offline test to `tests/test_vectorstore.py` that chunks the real corpus at 1000/100 and records whether `$35` and `$105`, and the overdraft protection `$12` fee and its description, share a chunk. It asserts the observed layout, with a comment that it documents the baseline for the evaluation phase. Verify `uv run pytest tests/test_vectorstore.py` passes.

## 7. Documents

- [x] 7.1 Update `docs/systems-design-and-architecture.md` per design D11 (§4.1, §6, §7.10, §8, §10); verify with `grep -n -E "top_k|qwen3-embedding|data/chroma|vectorstore.py|prompts.py" docs/systems-design-and-architecture.md` and by reading each section.
- [x] 7.2 Update `README.md` with the embedding pull step, the `finos policy` commands, `data/chroma/`, and how to run live tests; update the module map in `src/finos/__init__.py` if it lists modules; verify by reading.
- [x] 7.3 Confirm the Step 2 explore notes still match the implementation, and correct any drift; verify by reading their "Locked decisions" section against design D2–D10.

## 8. Full offline verification

- [x] 8.1 Run `uv run pytest` with `use_local_ollama_model` set to true and again set to false, and with `tracing` set to false, with no `.env` and no network; verify all pass and no `live` test runs, then restore `config.toml`.
- [x] 8.2 Run `openspec validate step-2-policy-agent-rag --strict`; verify it passes.

## 9. Live acceptance (developer machine)

- [x] 9.1 Add `live` tests to `tests/test_policy.py` for the overdraft, auto-loan APR, out-of-scope, and sources-in-corpus scenarios, using a `tmp_path` index and real models; verify they are deselected by `uv run pytest`.
- [x] 9.2 Add `live` failure-mode tests marked `xfail(strict=False)` for the split fact (overdraft protection cost), wrong document (replacement card ranks `fraud_policy.md` first), hallucinated amount (an amount in the response that is not in the context), and empty retrieval (a vague query); verify they are deselected by `uv run pytest`.
- [x] 9.3 On a machine with the Ollama models pulled, run the explore doc's acceptance commands: `uv run finos policy ingest`, `uv run finos policy ask --query "What is the overdraft fee?"`, `uv run finos policy ask --query "What is the APR range for auto loans?" --json`, `uv run finos policy search --query "overdraft" --top-k 2`, and `uv run pytest -m live -v`. Verify all exit 0, the answers contain `$35` and `4.49%` or `12.99%`, `account_fees.md` ranks first for "overdraft", and the live tests pass or xfail. Record which failure modes reproduced in the change's notes for the evaluation phase.
- [x] 9.4 Repeat 9.3 with `use_local_ollama_model = false` and an OpenAI key, if one is available, and note any difference from the lecture's figures.
