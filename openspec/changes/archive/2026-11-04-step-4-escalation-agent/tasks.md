# Tasks

> **Apply after `step-2-policy-agent-rag` and `step-3-account-agent`** (design D7). They create `src/finos/prompts.py` with `SUPPORT_CONTACT`, the `live` pytest marker, `tests/conftest.py` with the shared fake chat model, and the CLI patterns this change follows. Groups 1–5 are verified offline; group 6 is the live acceptance run. No dependency or configuration changes are needed.

## 1. Preconditions and branch

- [x] 1.1 Check that Steps 2 and 3 are applied: `SUPPORT_CONTACT` is importable from `finos.prompts`, `pyproject.toml` registers the `live` marker with `addopts = "-m 'not live'"`, `tests/conftest.py` provides the fake chat model, and `finos account --help` works. If any is missing, stop and apply those changes first.
- [x] 1.2 Create and switch to branch `step-4-escalation-agent`; verify with `git branch --show-current`.
- [x] 1.3 Confirm that no dependency is needed (the new code imports only stdlib, `finos.*`, `typer`, and `langchain_core`); verify `uv sync --locked` succeeds with `pyproject.toml` and `uv.lock` unchanged.

## 2. Test helpers

- [x] 2.1 Create `tests/helpers.py` with `has_policy_claim()` and `has_false_promise()` using the case-insensitive patterns in design D4, and a module docstring recording them as the seed of the §9.3 output check. Add unit tests in `tests/test_escalation.py`: each pattern flags a positive example ("$35", "35 dollars", "4.49%", "within 60 days", "APR", "I've escalated", "someone will call you", "will be refunded", "in the next 24 hours"), and neither helper flags "our support team can help you directly", "2 ways to reach us", "988", or `SUPPORT_CONTACT`. Verify `uv run pytest tests/test_escalation.py` passes.

## 3. Prompt and fixed texts

- [x] 3.1 Append `CRISIS_SUPPORT_MESSAGE`, `ESCALATION_FALLBACK_MESSAGE`, and `ESCALATION_SYSTEM_PROMPT` to `src/finos/prompts.py` with the exact texts in design D2, building the prompt by concatenating `CRISIS_SUPPORT_MESSAGE` and reusing (not redefining) `SUPPORT_CONTACT`. Add tests that: the prompt contains `CRISIS_SUPPORT_MESSAGE` verbatim and no `{` or `}`; it asks for 2–4 sentences and covers the four empathy criteria, every prohibition in the escalation-agent spec, and the threat rule; all three fixed texts and `SUPPORT_CONTACT` pass both helpers; no fixed text contains a phone number other than `988`; and `finos.prompts` imports no `langchain` module (subprocess). Verify `uv run pytest tests/test_escalation.py` passes.
- [x] 3.2 Measure the system prompt with `tiktoken` (`gpt-4o-mini` encoding) and record the count in a comment above `ESCALATION_SYSTEM_PROMPT` and in design D2's budget note; verify the count is printed by a short `uv run python -c` command and matches the comment.

## 4. Agent

- [x] 4.1 Implement `escalation_agent` in `src/finos/agents/escalation.py` per design D1 and D3, keeping the constraints paragraph in its docstring and removing the `NotImplementedError` note. Using the shared fake chat model, test: exactly one key returned; one system message equal to `ESCALATION_SYSTEM_PROMPT` and one human message equal to the query; `{x}` in the query passes through unchanged; a padded reply is stripped and joined with a blank line before `SUPPORT_CONTACT`; a whitespace-only reply gives `ESCALATION_FALLBACK_MESSAGE` plus `SUPPORT_CONTACT`; a reply already containing the contact email still gets the block appended once. Verify `uv run pytest tests/test_escalation.py` passes.
- [x] 4.2 Add `ask_escalation(query)` built on `initial_state()` and export it from `finos.agents`; add tests for the complete-state scenario and for `validate_state(strict=True, known_sources=<corpus filenames>)` returning no problems; verify `uv run pytest tests/test_escalation.py` passes.
- [x] 4.3 Update `tests/test_scaffold.py` to remove `escalation_agent` from the stub list; verify `uv run pytest tests/test_scaffold.py` passes.
- [x] 4.4 Update `docs/systems-design-and-architecture.md` §1, §4.3, §8, and the Step 4 row of §10 per design D8 (two stages, the hybrid wording, the corrected next-step example, `SUPPORT_CONTACT`); verify with `grep -n -E "SUPPORT_CONTACT|fixed contact block|support@securebank.com" docs/systems-design-and-architecture.md` showing no `support@securebank.com` left in §4.3, and by reading each section.

## 5. CLI

- [x] 5.1 Create `src/finos/cli/escalation.py` with `escalation_app` (`no_args_is_help=True`) and register it in `src/finos/cli/main.py` with one `add_typer` line; verify `uv run finos escalation --help` lists `ask` and `contact`, and the root light-import test in `tests/test_cli.py` still passes.
- [x] 5.2 Implement `contact` per design D5; add `tests/test_cli_escalation.py` covering human and `--json` output (`support_contact` and `crisis_support`) and a subprocess check that it loads no `langchain` or `chromadb` module and doesn't call `get_settings`; verify `uv run pytest tests/test_cli_escalation.py` passes.
- [x] 5.3 Implement `ask` per design D5 (no trailer; verbose provider, model, raw reply, and fallback flag on stderr); add tests with the fake chat model for both output modes, `--json` output passing `finos state validate --strict`, identical stdout with and without `--verbose`, shared options in both positions, an empty query exiting 2 before any model call, and a provider connection error exiting 1 with empty stdout under `--json`; verify `uv run pytest tests/test_cli_escalation.py` passes.
- [x] 5.4 Add `docs/how-to-guide/cli-escalation.md` for the `finos escalation` commands, following `docs/how-to-guide/cli-policy.md` (back link, table of contents, options, per-command output and JSON shapes, exit codes, recipes); add one row to the README's "How-to guides" table and a link in `docs/how-to-guide/cli-overview.md`'s module list; update the module map in `src/finos/__init__.py` if it lists modules; verify by reading, and check that every new link and `#anchor` resolves.

## 6. Guardrails notes, verification, and live acceptance

- [x] 6.1 Add the forward notes from design D8 to `docs/systems-design-and-architecture.md`: §9.3 (the safe fallback reuses `SUPPORT_CONTACT`; Presidio allow-lists the contact email and `988`; the crisis rule is the baseline behind the Moderation API; `tests/helpers.py` is the first output-check candidate) and §3.4 and §10 Phase 2 (a `locale` field); verify with `grep -n -E "allow-list|locale" docs/systems-design-and-architecture.md`.
- [x] 6.2 Run `uv run pytest` with `use_local_ollama_model` set to true and again set to false, and with `tracing` set to false, with no `.env` and no network; verify all pass and no `live` test runs, then restore `config.toml`. Run `openspec validate step-4-escalation-agent --strict` and verify it passes.
- [x] 6.3 Add the three hard live tests and the five `xfail(strict=False)` baselines from design D6 to `tests/test_escalation.py`; verify `uv run pytest` deselects them.
- [x] 6.4 With the configured provider reachable, run `uv run finos escalation ask --query "I'm furious! Nobody is helping!"` (with and without `--json`), `uv run finos escalation ask --query "I'm upset about \$105! What is your overdraft policy?"`, `uv run finos escalation contact --json`, and `uv run pytest -m live tests/test_escalation.py -v`. Verify every command exits 0, every reply ends with `SUPPORT_CONTACT`, the `--json` state passes `finos state validate --strict`, the three hard live tests pass, and the `xfail` tests pass or xfail. Record which failure modes reproduced for the evaluation phase.
- [x] 6.5 Repeat 6.4 with `use_local_ollama_model = false` and an OpenAI key, if one is available, and note any difference, especially in the crisis test.
