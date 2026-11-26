# Tasks

> **Apply after `step-2-policy-agent-rag`** (design D7). That change creates `src/finos/prompts.py`, the `live` pytest marker, the `ask_policy` export, and the CLI patterns this change follows. Groups 1–7 are verified offline; group 8 is the live acceptance run. No dependency or configuration changes are needed.

## 1. Preconditions and branch

- [x] 1.1 Check that Step 2 is applied: `src/finos/prompts.py` exists, `pyproject.toml` registers the `live` marker with `addopts = "-m 'not live'"`, and `finos policy --help` works. If any is missing, stop and apply `step-2-policy-agent-rag` first.
- [x] 1.2 Create and switch to branch `step-3-account-agent`; verify with `git branch --show-current`.
- [x] 1.3 Confirm that no dependency is needed: the new modules import only stdlib, `finos.*`, `typer`, and `langchain_core`; verify `uv sync --locked` succeeds with `pyproject.toml` and `uv.lock` unchanged.

## 2. Lookup module

- [x] 2.1 Create `src/finos/accounts.py` with `ACCOUNT_ID_PATTERN`, `extract_account_ids()`, and `normalize_account_id()` per design D1; add `tests/test_accounts.py` covering the accepted and rejected forms, duplicate collapsing, and bare-token normalization; verify `uv run pytest tests/test_accounts.py` passes.
- [x] 2.2 Add `load_accounts()` and `lookup_account()` per design D2 (read per call, `FileNotFoundError` and `ValueError` naming the path, empty list allowed); add tests for the four shipped IDs, `ACC-99999`, the field list from the mock-accounts spec, and missing, corrupt, wrong-shape, and empty files using `tmp_path` and a patched `MOCK_ACCOUNTS_PATH`; verify `uv run pytest tests/test_accounts.py` passes.
- [x] 2.3 Add `Resolution` and `resolve()` per design D1, and tests for all four outcomes, including that `multiple_ids` does no lookup; add a subprocess test that importing `finos.accounts` loads no `langchain` module; verify `uv run pytest tests/test_accounts.py` passes.

## 3. Prompt and constants

- [x] 3.1 Append `SUPPORT_CONTACT`, `ACCOUNT_SYSTEM_PROMPT`, `ACCOUNT_NO_ID_MESSAGE`, `ACCOUNT_NOT_FOUND_MESSAGE` (ending with `SUPPORT_CONTACT`), and `ACCOUNT_MULTIPLE_IDS_MESSAGE` to `src/finos/prompts.py` with the texts and six rules in design D3 and D4. Add tests that the system prompt has an `{account}` placeholder and no `{question}` placeholder, and names `ssn_last4`, `freeze_reason`, `frozen`, and `pending`; that `SUPPORT_CONTACT` uses `securebank.example` and has no phone number; that the not-found message ends with `SUPPORT_CONTACT`; and that no constant contains any other email address or a phone number. Verify `uv run pytest tests/test_account.py` passes.

## 4. Agent

- [x] 4.1 Implement `account_agent` in `src/finos/agents/account.py` per design D3 and D5, keeping the ownership paragraph in its docstring and removing the `NotImplementedError` note. Move Step 2's prompt-recording fake chat model (`RecordingChatModel`) from `tests/test_policy.py` to `tests/conftest.py`, next to `CountingEmbeddings` and `policy_env`, and use it in both suites. In `tests/test_account.py`, test: exactly one key returned for all four outcomes; for the three constant outcomes, `response` equals the constant and `get_llm` is never called (patched to raise); on found, one system message containing the record JSON and one human message equal to the query; and the brace-safety case. Verify `uv run pytest tests/test_account.py tests/test_policy.py` passes.
- [x] 4.2 Add `ask_account(query)` built on `initial_state()` and export it from `finos.agents`; add tests for the complete-state scenario and for strict validation passing for all four outcomes; verify `uv run pytest tests/test_account.py` passes.
- [x] 4.3 Update `tests/test_scaffold.py` to remove `account_agent` from the stub list; verify `uv run pytest tests/test_scaffold.py` passes.

## 5. CLI

- [x] 5.1 Create `src/finos/cli/account.py` with `account_app` (`no_args_is_help=True`) and register it in `src/finos/cli/main.py` with one `add_typer` line; verify `uv run finos account --help` lists three commands and the root light-import test in `tests/test_cli.py` still passes.
- [x] 5.2 Implement `list` and `lookup` per design D6 (stdlib only, no settings, exit 0/1/2, verdict on stdout); add `tests/test_cli_account.py` covering both output modes, the frozen record, `acc-12345` normalization, `ACC-99999` exiting 1, `ACC-1234` exiting 2, a missing records file exiting 1 with one stderr line, and a subprocess check that `lookup` loads no `langchain` or `chromadb` module and doesn't call `get_settings`; verify `uv run pytest tests/test_cli_account.py` passes.
- [x] 5.3 Implement `ask` per design D6 (trailer from `accounts.resolve`, full state under `--json`, verbose diagnostics on stderr); add tests with a fake chat model for all four trailers, `--json` output passing `finos state validate --strict`, identical stdout with and without `--verbose`, shared options in both positions, an empty query exiting 2 before any model call, and a provider connection error exiting 1 with empty stdout under `--json`; verify `uv run pytest tests/test_cli_account.py` passes.

## 6. Documents

- [x] 6.1 Update `docs/systems-design-and-architecture.md` per design D9 (§3.2, §3.6, §4.2, §8, §10); verify with `grep -n -E "ACCOUNT_NO_ID_MESSAGE|accounts.py|cli/account.py|not_found" docs/systems-design-and-architecture.md` and by reading each section.
- [x] 6.2 Add `docs/how-to-guide/cli-account.md` for the `finos account` commands, following `docs/how-to-guide/cli-policy.md` (back link, table of contents, options, per-command output and JSON shapes, exit codes, recipes); add one row to the README's "How-to guides" table and a link in `docs/how-to-guide/cli-overview.md`'s module list; update the module map in `src/finos/__init__.py` if it lists modules; verify by reading, and check that every new link and `#anchor` resolves.
- [x] 6.3 Confirm that the Step 3 explore notes still match the implementation and correct any drift; verify their "Locked decisions" table against design D1–D8.

## 7. Full offline verification

- [x] 7.1 Run `uv run pytest` with `use_local_ollama_model` set to true and again set to false, and with `tracing` set to false, with no `.env` and no network; verify all pass and no `live` test runs, then restore `config.toml`.
- [x] 7.2 Run `openspec validate step-3-account-agent --strict`; verify it passes.

## 8. Live acceptance (developer machine)

- [x] 8.1 Add the five `live` baseline-fact tests from design D8 to `tests/test_account.py`; verify `uv run pytest` deselects them.
- [x] 8.2 Add the five live failure-mode tests from design D8, marked `xfail(strict=False)` with a reason naming each; verify `uv run pytest` deselects them.
- [x] 8.3 With the configured provider reachable, run `uv run finos account ask --query "What is the balance on ACC-12345?"` (with and without `--json`), the same for `ACC-99999`, `uv run finos account ask --query "Show my recent transactions"`, `uv run finos account lookup --id ACC-11111`, `uv run finos account list`, and `uv run pytest -m live tests/test_account.py -v`. Verify all exit 0, the balance answer contains `12,450.75` or `12450.75`, the not-found and no-ID answers equal their constants, and the live tests pass or xfail. Record which failure modes reproduced for the evaluation phase.
- [x] 8.4 Repeat 8.3 with `use_local_ollama_model = false` and an OpenAI key, if one is available, and note any difference.
