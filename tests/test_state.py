"""Tests for the shared state contract (Step 1)."""

import ast
from pathlib import Path
from typing import get_type_hints

import pytest

from finos.state import (
    FIELD_METADATA,
    PLANNED_FIELDS,
    VALID_INTENTS,
    Intent,
    SupportState,
    initial_state,
    validate_state,
)


def test_field_set_is_exactly_five_fields() -> None:
    """The contract declares exactly the five agreed fields."""
    assert set(SupportState.__annotations__) == {
        "query",
        "intent",
        "response",
        "context",
        "retrieved_sources",
    }


def test_no_phase_two_history_field() -> None:
    """The Phase 2 `history` field stays out of the core build."""
    assert "history" not in SupportState.__annotations__


def test_field_types() -> None:
    """Four string fields and one list-of-strings field."""
    hints = get_type_hints(SupportState)
    assert hints["query"] is str
    assert hints["intent"] is str
    assert hints["response"] is str
    assert hints["context"] is str
    assert hints["retrieved_sources"] == list[str]


def test_contract_can_be_instantiated() -> None:
    """A state value can be built and read back, with no key or network."""
    state: SupportState = {
        "query": "test",
        "intent": "",
        "response": "",
        "context": "",
        "retrieved_sources": [],
    }
    assert state["query"] == "test"
    assert state["retrieved_sources"] == []


def test_valid_intents_vocabulary() -> None:
    """The runtime collection holds exactly the three intents."""
    assert VALID_INTENTS == frozenset({"policy", "account_status", "escalation"})


def test_intent_alias_matches_runtime_vocabulary() -> None:
    """The type alias and the runtime collection cannot drift apart."""
    from typing import get_args

    assert set(get_args(Intent)) == set(VALID_INTENTS)


def test_empty_initial_intent_is_not_in_vocabulary() -> None:
    """The documented initial intent is valid state but not an intent."""
    state: SupportState = {
        "query": "test",
        "intent": "",
        "response": "",
        "context": "",
        "retrieved_sources": [],
    }
    assert state["intent"] == ""
    assert "" not in VALID_INTENTS


def test_ownership_matrix_is_documented() -> None:
    """The docstring records initial values, writers, and policy-only fields."""
    doc = SupportState.__doc__ or ""
    for field in ("query", "intent", "response", "context", "retrieved_sources"):
        assert field in doc
    assert "classify_intent" in doc
    assert "specialist agent" in doc
    assert "policy_agent" in doc
    assert "policy agent only" in doc


# --- Step 1b: metadata, builder, and validator -------------------------------

FIELDS = ["query", "intent", "response", "context", "retrieved_sources"]


def _state(**overrides) -> dict:
    state = {
        "query": "test",
        "intent": "",
        "response": "",
        "context": "",
        "retrieved_sources": [],
    }
    state.update(overrides)
    return state


def test_metadata_keys_match_contract_in_order() -> None:
    assert list(FIELD_METADATA) == list(SupportState.__annotations__) == FIELDS


def test_metadata_ownership_agrees_with_docstring() -> None:
    doc = (SupportState.__doc__ or "").replace("``", "")
    for name, info in FIELD_METADATA.items():
        assert set(info) == {"description", "initial", "written_by", "read_by"}
        assert info["written_by"] in doc, name
        assert info["read_by"] in doc, name
        assert info["description"]


def test_history_is_only_planned() -> None:
    assert "history" in PLANNED_FIELDS
    assert "history" not in FIELD_METADATA
    assert "history" not in SupportState.__annotations__


def test_initial_state_values() -> None:
    assert initial_state("test") == _state()
    assert initial_state() == _state(query="")


def test_initial_state_lists_are_not_shared() -> None:
    first, second = initial_state(), initial_state()
    first["retrieved_sources"].append("a.md")
    assert second["retrieved_sources"] == []


def test_valid_states_have_no_errors() -> None:
    assert validate_state(initial_state()) == []
    assert validate_state(_state(intent="policy")) == []
    for intent in VALID_INTENTS:
        assert validate_state(_state(intent=intent)) == []


def test_not_an_object() -> None:
    errors = validate_state([1, 2])
    assert len(errors) == 1
    assert "JSON object" in errors[0]


@pytest.mark.parametrize("field", FIELDS)
def test_missing_field(field: str) -> None:
    state = _state()
    del state[field]
    errors = validate_state(state)
    assert len(errors) == 1
    assert "missing" in errors[0] and f"'{field}'" in errors[0]


def test_unknown_field() -> None:
    errors = validate_state(_state(history=[]))
    assert len(errors) == 1
    assert "'history'" in errors[0]


@pytest.mark.parametrize("field", ["query", "intent", "response", "context"])
def test_string_fields_reject_other_types(field: str) -> None:
    errors = validate_state(_state(**{field: 1}))
    assert len(errors) == 1 and f"'{field}'" in errors[0]


@pytest.mark.parametrize("value", ["a.md", ["a.md", 1], None])
def test_retrieved_sources_must_be_list_of_strings(value) -> None:
    errors = validate_state(_state(retrieved_sources=value))
    assert len(errors) == 1 and "'retrieved_sources'" in errors[0]


@pytest.mark.parametrize("intent", ["unknown_intent", "Policy", " policy"])
def test_intent_outside_vocabulary(intent: str) -> None:
    errors = validate_state(_state(intent=intent))
    assert len(errors) == 1
    assert "'intent'" in errors[0]
    for valid in VALID_INTENTS:
        assert valid in errors[0]


def test_all_errors_are_returned_together() -> None:
    errors = validate_state({"query": "test", "intent": "unknown_intent"})
    text = "\n".join(errors)
    assert len(errors) == 4
    for name in ("intent", "response", "context", "retrieved_sources"):
        assert f"'{name}'" in text


def test_strict_accepts_known_sources() -> None:
    state = _state(intent="policy", context="c", retrieved_sources=["a.md"])
    assert validate_state(state, strict=True, known_sources=frozenset({"a.md"})) == []


@pytest.mark.parametrize(
    "source", ["nope.md", "../config.toml", "data/policy-docs/a.md"]
)
def test_strict_rejects_unknown_sources(source: str) -> None:
    state = _state(intent="policy", retrieved_sources=[source])
    errors = validate_state(state, strict=True, known_sources=frozenset({"a.md"}))
    assert len(errors) == 1 and source in errors[0]


@pytest.mark.parametrize("intent", ["", "account_status", "escalation"])
def test_strict_rejects_retrieval_fields_outside_policy(intent: str) -> None:
    errors = validate_state(_state(intent=intent, context="c"), strict=True)
    assert len(errors) == 1 and "'context'" in errors[0]
    errors = validate_state(
        _state(intent=intent, retrieved_sources=["a.md"]),
        strict=True,
        known_sources=frozenset({"a.md"}),
    )
    assert len(errors) == 1 and "'retrieved_sources'" in errors[0]


def test_strict_accepts_policy_state_with_empty_context() -> None:
    assert validate_state(_state(intent="policy"), strict=True) == []


def test_strict_checks_are_off_by_default() -> None:
    assert validate_state(_state(intent="account_status", context="c",
                                 retrieved_sources=["nope.md"])) == []


def test_strict_skips_fields_that_failed_base_checks() -> None:
    errors = validate_state(_state(intent="bad", context="c"), strict=True)
    assert len(errors) == 1 and "'intent'" in errors[0]


def test_validation_is_documented_as_opt_in() -> None:
    doc = SupportState.__doc__ or ""
    assert "validate_state" in doc and "opt-in" in doc


def test_state_module_imports_only_typing() -> None:
    import finos.state as module

    tree = ast.parse(Path(module.__file__).read_text("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert [alias.name for alias in node.names] == ["typing"]
        elif isinstance(node, ast.ImportFrom):
            assert node.module == "typing"
