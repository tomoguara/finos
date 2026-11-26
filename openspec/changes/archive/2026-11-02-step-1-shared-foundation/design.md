# Design

## Context

See `proposal.md` for motivation and `specs/` for required behavior. The repo is an empty `uv_build` package at `src/finos/` on Python 3.12, with `.env` present as a symlink to a shared env file outside the repo and not yet git-ignored.

This design records the Step 1 decisions from the explore session. Sources:

- **Context doc**: `docs/Fintech_Multi-Agent_Support_System—Project_Context_Document.md`
- **Explore doc**: the Step 1 explore notes
- **Class code**: the course's reference implementation (not published)
- **Slides**: the course lecture slides (not published)

## Goals / Non-Goals

**Goals:**

- Settle every point where the sources conflict, so Steps 2–5 don't have to revisit them.
- Make `get_llm()` the only place that knows about providers.
- Keep the foundation testable offline.

**Non-Goals:**

- Choosing local embeddings, which belongs to Step 2. `qwen3-embedding` and `nomic-embed-text` are both on the Ollama host.
- Evaluating how well the local model routes or answers.
- Observability beyond turning tracing on: `@traceable`, tags, sampling, and dashboards stay in the hardening layer.

## Decisions

### Where sources conflict

| Topic | Sources disagree | Decision |
|---|---|---|
| Code location | Docs: `src/state.py`. Repo: `src/finos/` | `src/finos/` |
| Import path | Explore acceptance test: `from src.state` | `from finos.state` |
| Data location | Context doc §8: root `data/`. Explore §4–5, §8: `src/data/` | Root `data/`, with `data/policy-docs/` |
| Python | Docs: 3.11+. Repo: 3.12 | `>=3.12` |
| `context` writer | Class code: account agent also writes JSON. Context doc and slides: policy only | Policy only |
| Model env var | Docs: `MODEL_NAME` in `.env` | `[openai] model` in `config.toml` |
| Local provider | Context doc §3.3 requires it. Explore doc omits it | Included |
| Provider switch | Context doc §3.3: environment variable | `config.toml` |
| Tracing switch | Context doc §9.1 and class `.env.example`: environment variables | `[langsmith]` in `config.toml`, overriding `.env`. `LANGCHAIN_API_KEY` stays in `.env` |

### D1: Package layout

Use `src/finos/`, because the repo's `uv_build` setup already expects it and no build config has to change. `import src.state` was rejected because it would make `src` the import name and require reworking the build.

```
config.toml                  # non-secret settings (new, not in §8)
.env.example                 # OPENAI_API_KEY and LANGCHAIN_API_KEY only
data/policy-docs/*.md
data/mock_accounts.json
docs/systems-design-and-architecture.md      # moved and updated
src/finos/
  __init__.py
  config.py                  # settings loader and data paths (new, not in §8)
  state.py
  llm.py
  graph.py                   # stub, Step 5
  main.py                    # stub, Step 5
  agents/
    __init__.py
    policy.py                # stub, Step 2
    account.py               # stub, Step 3
    escalation.py            # stub, Step 4
    supervisor.py            # stub, Step 5
tests/
  __init__.py
  test_state.py  test_llm.py  test_data.py  test_scaffold.py   # this step
  test_policy.py  test_account.py  test_escalation.py  test_graph.py   # empty until their steps
```

Data stays out of the wheel, which suits a CLI development tool. `config.py` exposes `PROJECT_ROOT`, `POLICY_DOCS_DIR`, and `MOCK_ACCOUNTS_PATH`, derived from `Path(__file__).resolve().parents[2]`, so no step hardcodes a path.

### D2: State contract

```python
Intent = Literal["policy", "account_status", "escalation"]
VALID_INTENTS: frozenset[str] = frozenset(get_args(Intent))

class SupportState(TypedDict):
    query: str
    intent: str
    response: str
    context: str
    retrieved_sources: list[str]
```

`intent` stays `str` because its initial value is `""` and the supervisor has to handle raw LLM text before normalizing it. Typing the field as `Literal[...]` would make the documented initial state a type error, and `Literal["", ...]` would put a non-intent into the vocabulary. The alias still gives Step 5 a type to normalize to.

No `error`, `confidence`, or `account_id` fields: the account ID is local to the account agent, and §7.9 rules out retries that would use the others. Ownership is documented on the class rather than enforced by a runtime hook, because each node returns only its own keys and tests can check this per agent.

### D3: Dependency stack

Stay on the class's 0.3.x generation (your decision), with major-bounded ranges in `pyproject.toml` and exact versions from `uv.lock`:

| Package | Range | Resolved |
|---|---|---|
| `langchain` | `>=0.3.14,<0.4` | 0.3.30 |
| `langchain-openai` | `>=0.3.1,<0.4` | 0.3.35 |
| `langchain-ollama` | `>=0.3,<0.4` | 0.3.10 |
| `langchain-chroma` | `>=0.2.1,<0.3` | 0.2.3 |
| `langgraph` | `>=0.2.60,<0.3` | 0.2.76 |
| `chromadb` | `>=0.6.3,<0.7` | 0.6.3 |
| `openai` | `>=1.59.9,<2` | 1.109.1 |
| `python-dotenv` | `>=1.1.1` | 1.2.4 |
| `tiktoken` | `>=0.8.0` | 0.14.0 |
| `pytest` (dev group) | any | 9.2.0 |

- `langchain-chroma` is added even though §6 omits it, because Step 2 needs it.
- `openai<2` is added because, without it, the resolver picks 2.x, outside the class's range.
- `chromadb` stays direct, as the explore doc suggests.
- Checked in a scratch environment on Python 3.12: all the imports the specs name work, and Chroma add and query work with numpy 2.5.4.
- A separate resolve of this stack with the class hardening packages (`deepeval`, `guardrails-ai==0.6.0`, `presidio-*`, `langchain-community`) also succeeds, so hardening has a path on this generation.

### D4: Settings go in `config.toml`, secrets in `.env`

```toml
[llm]
use_local_ollama_model = true
temperature = 0

[ollama]
model = "qwen3-coder-next:q8_0-gpu"
# Native Ollama endpoint: no /v1 suffix.
base_url = "http://localhost:11434"

[openai]
model = "gpt-4o-mini"

[langsmith]
tracing = true
project = "finos"
```

Read it with stdlib `tomllib`, so this needs no new dependency. This follows your proposal: models and hosts aren't secrets, should be reviewable in git, and are the variables hardening experiments will change, so they belong in version control.

Alternatives rejected:

- **`.env` for everything**: mixes secrets with settings and leaves model changes untracked. Also `.env` here is a file shared across projects, so per-project settings don't belong in it.
- **`[tool.finos]` in `pyproject.toml`**: workable, but mixes runtime settings with packaging metadata.
- **Environment overrides of config values**: not needed yet. They're easy to add if CI needs them, and adding them now would create two sources for each setting.

### D5: Base URL drops your `/v1`

You gave a base URL with a `/v1` suffix, and the shipped value drops it. `/v1` is Ollama's OpenAI-compatible endpoint, while `ChatOllama` calls the native API. Tested against your host: with `/v1`, `ChatOllama` gets `404 page not found` from the server; without it, the same request reaches Ollama, which answers that the probe model doesn't exist. The configured model is in that host's `/api/tags` list.

The alternative, `ChatOpenAI` pointed at `/v1`, would work too, but it wouldn't use the `langchain-ollama` package you asked for.

### D6: `get_llm()`

```python
@lru_cache
def get_llm(model: str | None = None) -> BaseChatModel: ...
```

- Returns `ChatOllama(model, base_url, temperature)` or `ChatOpenAI(model, temperature)`, based on `use_local_ollama_model`.
- Caching matches the single shared instance in §3.3 and simplifies later cost tracking. The cache is keyed on the argument, and tests call `get_llm.cache_clear()`.
- Constructing either model makes no network call, so an unreachable Ollama host surfaces on the first `invoke`, not on import or construction.
- Checks for `OPENAI_API_KEY` only on the OpenAI branch, and raises an error naming the variable.
- `config.py` calls `load_dotenv()` once when settings are first loaded, not at import. This keeps imports free of side effects, and the default `override=False` keeps real environment variables ahead of `.env`.

### D7: Stubs

Stub functions carry the context doc's signatures and raise `NotImplementedError("Implemented in Step N")`: `policy_agent`, `account_agent`, `escalation_agent`, `classify_intent`, `route_by_intent`, `build_support_agent`, and `ask`. Failing loudly beats an empty file, because Steps 2–5 get the signature to fill in and an accidental early call can't pass silently.

Stub modules import only `finos.state`. `main()` moves to `finos/main.py`, and the script entry point becomes `finos.main:main`. Until Step 5 it also raises `NotImplementedError`.

### D8: Corpus

Write original prose instead of copying the class documents, which have no license file and could end up in a public repo. Keep the facts in `specs/policy-corpus/spec.md` exactly, because the slides' keyword evaluation checks those values. Everything else in the documents may follow the same general banking content.

| Contradiction | Source | Treatment |
|---|---|---|
| Replacement card: $5 vs free | Slides list it as a deliberate failure | **Keep**, unqualified. The explore doc's "free for confirmed fraud" is not used, since it would remove the conflict |
| Zero liability within 60 days vs a $50/$500 table | Accidental, in the class fraud doc | **Fix**: use zero liability, matching the explore doc |

The 450–550 word target matches the class documents' 440–530 range, so chunking in Step 2 behaves comparably. Keep the $35 and $105 values together, since the slides' chunk-splitting experiment depends on that fact being a single unit.

### D9: Mock accounts

| ID | Holder | Type | Balance | Status | Fee / waived | SSN last 4 |
|---|---|---|---|---|---|---|
| `ACC-12345` | Alice Johnson | Premium Checking | 12450.75 | active | 12.99 / true | 6789 |
| `ACC-67890` | Bob Smith | Basic Checking | 234.50 | active | 0.00 / false | 4321 |
| `ACC-11111` | Carol Davis | High-Yield Savings | 85320.00 | frozen | 0.00 / true | 9876 |
| `ACC-22222` | Dana Lee | Student Checking | 0.00 | pending | 0.00 / false | 1357 |

- Reuse the first three accounts' transactions and `overdraft_protection` values from the class code, renaming `name` to `holder_name`. `ACC-22222` has no transactions.
- Keep `ACC-11111`'s `freeze_reason` from the class code.
- `ssn_last4` is included so the slides' leak demo has a real target. Whether it reaches the LLM is a Step 3 decision.
- `recent_transactions` is included because §3.2 routes transaction queries to this agent.

### D10: Assumptions to check on review

These were not asked about explicitly, and each is easy to change:

- The context doc moves to `docs/systems-design-and-architecture.md`, per §8, and its §3.3, §6, §7, §8, and §9.1 are updated. The update makes `config.toml` the switch in §3.3 and §9.1, and reflects local Ollama as the current default in §3.3 and §7.5.
- `docs/*.pdf` is git-ignored, because the slides are third-party course material and the repo may go public. The PDF stays on disk.
- `README.md` gets minimal setup instructions.
- Work happens on a `step-1-shared-foundation` branch.

### D11: Tracing settings live in `config.toml`

`LANGCHAIN_TRACING_V2` and `LANGCHAIN_PROJECT` move to `[langsmith]`; `LANGCHAIN_API_KEY` is a secret and stays in `.env`. LangChain reads tracing only from the environment, so a config value does nothing until it's copied there:

- After `load_dotenv()`, `config.py` assigns both values directly to `os.environ`. Direct assignment is what lets `config.toml` win, because `load_dotenv()` alone would keep whichever value is already set. This applies only to finos; the class project doesn't read this file.
- `langsmith` 0.14.17 caches its environment lookups, so these values must be set before the first traced call. `get_llm()` and `build_support_agent()` therefore both load settings before doing anything else. The `build_support_agent` stub's docstring records this for Step 5.
- Settings load once and imports stay free of side effects, so D6's approach holds. Tests use `monkeypatch` to control and restore both variables.

Removing the line from the shared env file isn't required, because `config.toml` overrides it either way. It's currently commented out there, and can be uncommented to run the class project without affecting finos.

## Risks / Trade-offs

- **Secrets could be committed now** → `.env` is not ignored today, and a `git add .` would stage the symlink. Git stores a symlink's target path, not the file's contents, but the risk returns if it's ever replaced by a regular file. Ignoring it is task 1.1. Until then, avoid `git add .`.
- **Prompts and responses go to LangSmith (accepted)** → This applies even with local Ollama, and includes `ssn_last4` if Step 3 sends it to the model. All account data is fictional. Set `tracing = false` for any run that shouldn't leave the machine.
- **Tracing on without a LangSmith key** → A clone with no `LANGCHAIN_API_KEY` has tracing enabled but can't authenticate. How that behaves hasn't been tested. `README.md` will say to set `tracing = false` in that case.
- **`load_dotenv()` loads everything in the shared env file** → Variables meant for other projects also enter this process. Tracing is protected by D11, but other settings aren't. Give finos its own `.env` if this causes problems.
- **The shipped default depends on a reachable Ollama** → A clone with no Ollama listening on `localhost:11434` fails on the first model call. Pointing `[ollama] base_url` at the machine that runs Ollama, or setting `use_local_ollama_model = false`, is the documented fix, and `README.md` says so.
- **No host address is committed** → The shipped `base_url` is `localhost:11434`, so the repo exposes no private address. A developer whose Ollama runs on another machine points `base_url` at it locally.
- **Local model differs from the lecture's baseline** → `qwen3-coder-next:q8_0-gpu` is an 84 GB model that appears to be coding-oriented, and I haven't run a generation on it. The slides' cost figures and targets assume `gpt-4o-mini`. Expect slow cold starts, and use OpenAI when comparing results against the lecture's numbers.
- **Older stack** → 0.3.x is no longer the current LangChain generation, so moving to 1.x later means changing imports (`langchain.text_splitter`, `langchain.prompts`, `langchain.schema.*` all fail on 1.x) and upgrading past `guardrails-ai==0.6.0`, which blocks 1.x. Prefer `langchain_core` and `langchain_text_splitters` imports in new code to reduce that work.
- **Chroma telemetry noise** → `chromadb` 0.6.3 prints `Failed to send telemetry event` lines in the tested environment, even with `ANONYMIZED_TELEMETRY=False` set. Add/query results are correct. Step 2 can decide whether to address it.

## Migration Plan

No deployed system or data exists. Rollback means discarding the branch.

## Open Questions

- What should `build_support_agent()` return? The context doc annotates `-> dict` but returns the compiled app, while the slides return a dict with `app`, `retriever`, and more. The stub keeps `-> dict`, and Step 5 can settle this without changing anything here.
