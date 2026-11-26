"""The ``finos`` command line.

- :mod:`finos.cli.main` — the root app and module registrations
- :mod:`finos.cli.shared` — shared options and output helpers
- :mod:`finos.cli.state` — the ``finos state`` toolkit

A module is one file holding a ``typer.Typer`` group plus one
``app.add_typer`` line in :mod:`finos.cli.main`. Heavy dependencies
(LangChain, LangGraph, Chroma) are imported inside command bodies, never at
module top level, so ``--help`` stays fast and needs no settings.
"""
