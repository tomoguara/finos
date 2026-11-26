# Tasks

## 1. Repository safety and dependencies

- [x] 1.1 Add `.env`, `.DS_Store`, `._*`, and `docs/*.pdf` to `.gitignore`; verify `git check-ignore .env .DS_Store` reports both, `git check-ignore .env.example` reports nothing, and `git status --short` no longer lists them.
- [x] 1.2 Create and switch to branch `step-1-shared-foundation`; verify with `git branch --show-current`.
- [x] 1.3 Set the dependency ranges from design D3 in `pyproject.toml`, with `pytest` in a dev dependency group and a project description in place of the placeholder; run `uv lock` and `uv sync`, then verify `uv pip list` shows `langchain` 0.3.x and `langgraph` 0.2.x, and `langchain-community` is absent from `pyproject.toml`.

## 2. State contract

- [x] 2.1 Create `src/finos/state.py` per design D2, with the ownership matrix in the `SupportState` docstring; verify `uv run python -c "from finos.state import SupportState; s: SupportState = {'query': 'test', 'intent': '', 'response': '', 'context': '', 'retrieved_sources': []}; assert s['query'] == 'test'"` exits 0.
- [x] 2.2 Write `tests/__init__.py` and `tests/test_state.py` covering the exact field set and types, `VALID_INTENTS`, and the empty initial intent; verify `uv run pytest tests/test_state.py` passes.

## 3. Configuration and LLM helper

- [x] 3.1 Create `config.toml` with the values in design D4 and `.env.example` listing only placeholder `OPENAI_API_KEY` and `LANGCHAIN_API_KEY` values; verify `grep -c KEY config.toml` prints 0 and `git check-ignore .env.example` reports nothing.
- [x] 3.2 Create `src/finos/config.py` with cached settings loading via `tomllib`, a `load_dotenv()` call on first load followed by assigning the `[langsmith]` values to `os.environ` per design D11, path constants from design D1, and errors naming the file for a missing file or setting; verify through the tests in 3.4.
- [x] 3.3 Create `src/finos/llm.py` with `get_llm()` per design D6; verify through the tests in 3.4.
- [x] 3.4 Write `tests/test_llm.py` covering every scenario in `specs/llm-access/spec.md`, with `load_dotenv` patched out and `OPENAI_API_KEY`, `LANGCHAIN_API_KEY`, `LANGCHAIN_TRACING_V2`, and `LANGCHAIN_PROJECT` controlled through `monkeypatch`, so that the real `.env` is never read and the variables are restored afterward. Include tracing on and off checks using `langsmith.utils.tracing_is_enabled()` with its cache cleared, and a pre-set conflicting `LANGCHAIN_TRACING_V2`; verify `uv run pytest tests/test_llm.py` passes with no network access.
- [x] 3.5 Confirm the shipped Ollama settings against the host without running a generation: verify `curl -s http://<ollama-host>:11434/api/tags` lists `qwen3-coder-next:q8_0-gpu`.
  - Verified against the shipped `http://localhost:11434`: `/api/tags` lists `qwen3-coder-next:q8_0-gpu`. Needs Ollama reachable on that port, either running locally or tunnelled from the host that runs it; a session with neither cannot run this check.

## 4. Mock data

- [x] 4.1 Write `data/policy-docs/account_fees.md` as original prose containing every required fact, and listing the monthly fee for each account type used in design D9; verify the word count with `wc -w` is 450–550.
- [x] 4.2 Write `data/policy-docs/loan_policy.md` as original prose containing every required fact; verify the word count with `wc -w` is 450–550.
- [x] 4.3 Write `data/policy-docs/transfer_policy.md` as original prose containing every required fact; verify the word count with `wc -w` is 450–550.
- [x] 4.4 Write `data/policy-docs/fraud_policy.md` as original prose with the zero-liability rule, no $50 or $500 tier, and unqualified free standard card replacement; verify the word count with `wc -w` is 450–550.
- [x] 4.5 Write `data/mock_accounts.json` with the four accounts in design D9, reusing class-code transactions as described there; verify it parses with `uv run python -m json.tool data/mock_accounts.json`.
- [x] 4.6 Write `tests/test_data.py` covering the scenarios in `specs/policy-corpus/spec.md` and `specs/mock-accounts/spec.md`, including the replacement-card conflict and fee agreement between accounts and `account_fees.md`; verify `uv run pytest tests/test_data.py` passes.

## 5. Stubs and entry point

- [x] 5.1 Create `src/finos/agents/` with `__init__.py` and stubs for `policy_agent`, `account_agent`, `escalation_agent`, `classify_intent`, and `route_by_intent`, using the context doc's signatures and docstrings per design D7; verify through the test in 5.4.
- [x] 5.2 Create `src/finos/graph.py` with a `build_support_agent` stub, whose docstring states it must load settings first per design D11, and `src/finos/main.py` with `ask` and `main` stubs; verify through the test in 5.4.
- [x] 5.3 Remove `main` from `src/finos/__init__.py` and change the script entry to `finos.main:main`; verify `uv sync` succeeds and `uv run finos` fails with the `NotImplementedError` naming Step 5.
- [x] 5.4 Write `tests/test_scaffold.py`, checking that all modules import without credentials and that each stub raises `NotImplementedError` naming its step, and add empty `tests/test_policy.py`, `test_account.py`, `test_escalation.py`, and `test_graph.py` with a docstring naming their step; verify `uv run pytest tests/test_scaffold.py` passes.

## 6. Documentation

- [x] 6.1 Move the context doc to `docs/systems-design-and-architecture.md` and update §3.3, §6, §7, §8, and §9.1 to match design decisions D1, D3, D4, and D11, and delete only its `docs/._*` metadata sibling; verify `grep -n "MODEL_NAME\|policy-docs" docs/systems-design-and-architecture.md` shows no stale `MODEL_NAME` and the updated tree.
- [x] 6.2 Write `README.md` with setup (`uv sync`, copying `.env.example`), how to switch providers in `config.toml`, the LAN Ollama default, that tracing is on by default and sends prompts to LangSmith, setting `tracing = false` when there is no `LANGCHAIN_API_KEY`, and the test command; verify by following its setup and test commands as written.

## 7. Integration check

- [x] 7.1 From a fresh clone of the branch's working tree, run `uv sync --locked` and `env -u OPENAI_API_KEY -u LANGCHAIN_API_KEY uv run pytest` with no `.env`; verify all tests pass.
- [x] 7.2 Run `openspec validate step-1-shared-foundation --strict`; verify it reports the change as valid.

## Workflow follow-up

- Commit the branch once you've reviewed it, leaving push and merge for your own decision.
- Archive the change after review.
