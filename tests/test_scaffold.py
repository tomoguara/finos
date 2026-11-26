"""Tests for the package scaffold (Step 1).

Every module must import with no credentials and no network, and every
unimplemented function must fail loudly, naming the step that fills it in.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

MODULES = [
    "finos",
    "finos.config",
    "finos.state",
    "finos.llm",
    "finos.prompts",
    "finos.vectorstore",
    "finos.accounts",
    "finos.graph",
    "finos.main",
    "finos.cli",
    "finos.cli.main",
    "finos.cli.shared",
    "finos.cli.state",
    "finos.cli.policy",
    "finos.cli.account",
    "finos.cli.escalation",
    "finos.cli.supervisor",
    "finos.__main__",
    "finos.agents",
    "finos.agents.policy",
    "finos.agents.account",
    "finos.agents.escalation",
    "finos.agents.supervisor",
]

# The functions Steps 2-5 filled in: (import path, attribute).
CORE_FUNCTIONS = [
    ("finos.agents.policy", "policy_agent"),
    ("finos.agents.account", "account_agent"),
    ("finos.agents.escalation", "escalation_agent"),
    ("finos.agents.supervisor", "classify_intent"),
    ("finos.agents.supervisor", "route_by_intent"),
    ("finos.graph", "build_support_agent"),
    ("finos.main", "ask"),
]


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch: pytest.MonkeyPatch):
    """Imports and stub calls must not depend on any key."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)


@pytest.mark.parametrize("name", MODULES)
def test_module_imports_without_credentials(name: str):
    assert importlib.import_module(name) is not None


def test_no_stub_remains_in_the_core_build():
    """The core build is complete: no NotImplementedError anywhere in src/finos."""
    package = Path(__file__).resolve().parents[1] / "src" / "finos"
    offenders = [
        f"{path.relative_to(package)}:{number}"
        for path in sorted(package.rglob("*.py"))
        for number, line in enumerate(path.read_text("utf-8").splitlines(), start=1)
        if "NotImplementedError" in line
    ]
    assert offenders == []


@pytest.mark.parametrize("module_name, attribute", CORE_FUNCTIONS)
def test_core_functions_are_documented(module_name: str, attribute: str):
    """Every function Steps 2-5 implemented keeps a docstring, with no stub note."""
    function = getattr(importlib.import_module(module_name), attribute)
    doc = (function.__doc__ or "").strip()
    assert doc
    assert "NotImplementedError" not in doc


def test_agents_package_reexports_every_node():
    import finos.agents as agents

    assert set(agents.__all__) == {
        "policy_agent",
        "ask_policy",
        "ask_account",
        "ask_escalation",
        "account_agent",
        "escalation_agent",
        "classify_intent",
        "route_by_intent",
    }


def test_build_support_agent_docstring_records_the_settings_rule():
    """Step 5 must load settings before anything that could be traced."""
    from finos.graph import build_support_agent

    doc = build_support_agent.__doc__ or ""
    assert "settings" in doc
    assert "get_settings" in doc


def test_policy_agent_docstring_records_the_bare_filename_rule():
    """The implemented agent keeps documenting bare filenames in `retrieved_sources`."""
    from finos.agents.policy import policy_agent

    doc = policy_agent.__doc__ or ""
    assert "retrieved_sources" in doc
    assert "bare filenames" in doc
    assert "specs/support-state/spec.md" in doc


def test_classify_intent_docstring_records_the_normalized_intent_rule():
    """Step 5 must write only a normalized vocabulary member to `intent`."""
    from finos.agents.supervisor import classify_intent

    doc = classify_intent.__doc__ or ""
    assert "normalized vocabulary member" in doc
    assert "specs/support-state/spec.md" in doc


def test_package_init_defines_no_entry_point():
    """The `finos` script points at the CLI package, not at `finos.main`."""
    import types

    import finos

    # The only `finos.main` is the submodule, never a function in __init__.
    attribute = getattr(finos, "main", None)
    assert attribute is None or isinstance(attribute, types.ModuleType)
    assert not hasattr(importlib.import_module("finos.main"), "main")

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text("utf-8")
    )
    assert pyproject["project"]["scripts"]["finos"] == "finos.cli.main:main"


def test_core_dependencies_stay_on_the_chosen_generation():
    """0.3.x LangChain, 0.2.x LangGraph, and no langchain-community."""
    from importlib.metadata import version

    assert version("langchain").startswith("0.3.")
    assert version("langgraph").startswith("0.2.")

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text("utf-8")
    )
    declared = " ".join(pyproject["project"]["dependencies"])
    assert "langchain-community" not in declared
    names = {
        dep.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip()
        for dep in pyproject["project"]["dependencies"]
    }
    # Direct imports must be direct dependencies, not transitive luck.
    assert "langchain-text-splitters" in names
    assert "langsmith" in names


def test_third_party_integrations_import():
    """What Steps 2-5 need from the stack is installed and importable."""
    from langchain_chroma import Chroma  # noqa: F401
    from langchain_ollama import ChatOllama  # noqa: F401
    from langchain_openai import ChatOpenAI  # noqa: F401
    from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: F401
    from langsmith import Client, traceable, tracing_context  # noqa: F401
    from langgraph.graph import END, StateGraph  # noqa: F401
