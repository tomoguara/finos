"""finos: the SecureBank multi-agent customer support system.

Module map:

- :mod:`finos.state` — the shared ``SupportState`` contract (Step 1)
- :mod:`finos.config` — settings, secrets, and data paths (Step 1)
- :mod:`finos.llm` — the one place that knows about providers: chat
  (Step 1) and embedding (Step 2) models
- :mod:`finos.prompts` — agent prompts (Step 2)
- :mod:`finos.vectorstore` — the on-disk policy index and search (Step 2)
- :mod:`finos.accounts` — account ID extraction, record lookup, and query
  resolution (Step 3)
- :mod:`finos.agents` — the supervisor and the three specialists (Steps 2–5);
  ``ask_policy`` (Step 2), ``ask_account`` (Step 3), and ``ask_escalation``
  (Step 4) run agents standalone
- :mod:`finos.graph` — the LangGraph wiring and its diagram text (Step 5)
- :mod:`finos.main` — the ``ask`` invocation helper (Step 5)
- :mod:`finos.cli` — the ``finos`` command line, the ``state`` toolkit
  (Step 1b), and the ``policy`` (Step 2), ``account`` (Step 3),
  ``escalation`` (Step 4), and ``supervisor`` (Step 5) commands

Importing this package has no side effects and needs no credentials.
"""
