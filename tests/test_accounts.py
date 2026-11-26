"""Tests for account ID extraction, record lookup, and resolution (Step 3).

All offline: this module touches only ``data/mock_accounts.json`` or a
``tmp_path`` fixture, never a model or settings.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from finos import accounts, config
from finos.accounts import (
    extract_account_ids,
    load_accounts,
    lookup_account,
    normalize_account_id,
    resolve,
)

SHIPPED_IDS = {"ACC-12345", "ACC-67890", "ACC-11111", "ACC-22222"}


@pytest.fixture
def records_file(tmp_path, monkeypatch):
    """Point MOCK_ACCOUNTS_PATH at a tmp file and return a writer for it."""
    path = tmp_path / "mock_accounts.json"
    monkeypatch.setattr(config, "MOCK_ACCOUNTS_PATH", path)

    def write(content: str) -> None:
        path.write_text(content, encoding="utf-8")

    write.path = path  # type: ignore[attr-defined]
    return write


# --- Requirement: Account IDs are extracted and normalized ------------------


@pytest.mark.parametrize(
    "query",
    [
        "Balance on ACC-12345?",
        "balance on acc-12345",
        "What about ACC 12345 please",
        "ACC12345",
        "(ACC-12345).",
        "Acc-12345's balance",
    ],
)
def test_accepted_forms(query):
    assert extract_account_ids(query) == ["ACC-12345"]


@pytest.mark.parametrize(
    "query",
    ["ACC-1234", "ACC-123456", "XY-12345", "ACCT-12345", "12345", "ACC--12345", "$12,345.00"],
)
def test_rejected_forms(query):
    assert extract_account_ids(query) == []


def test_duplicates_collapse_in_order():
    query = "Is ACC-12345 the same as acc 12345? What about ACC-67890?"
    assert extract_account_ids(query) == ["ACC-12345", "ACC-67890"]


@pytest.mark.parametrize(
    "token, expected",
    [
        (" acc-12345 ", "ACC-12345"),
        ("ACC 12345", "ACC-12345"),
        ("ACC12345", "ACC-12345"),
        ("ACC-12345x", None),
        ("ACC-1234", None),
        ("ACC-123456", None),
        ("the ACC-12345", None),
        ("", None),
    ],
)
def test_normalize_bare_token(token, expected):
    assert normalize_account_id(token) == expected


# --- Requirement: Account records load from the mock file -------------------


def test_shipped_records_load():
    records = load_accounts()
    assert set(records) == SHIPPED_IDS
    assert lookup_account("ACC-99999") is None
    assert lookup_account("ACC-12345")["holder_name"] == "Alice Johnson"


def test_shipped_records_have_the_full_field_set():
    """The field list from the mock-accounts spec."""
    for record in load_accounts().values():
        assert isinstance(record["account_id"], str)
        assert isinstance(record["holder_name"], str)
        assert isinstance(record["account_type"], str)
        assert isinstance(record["balance"], (int, float))
        assert isinstance(record["status"], str)
        assert isinstance(record["monthly_fee"], (int, float))
        assert isinstance(record["monthly_fee_waived"], bool)
        assert isinstance(record["overdraft_protection"], bool)
        assert isinstance(record["recent_transactions"], list)
        assert isinstance(record["ssn_last4"], str) and len(record["ssn_last4"]) == 4
        for transaction in record["recent_transactions"]:
            assert {"date", "description", "amount"} <= set(transaction)
            assert isinstance(transaction["amount"], (int, float))


def test_records_are_read_on_every_call(records_file):
    records_file('[{"account_id": "ACC-00001"}]')
    assert set(load_accounts()) == {"ACC-00001"}
    records_file('[{"account_id": "ACC-00002"}]')
    assert set(load_accounts()) == {"ACC-00002"}


def test_missing_file_names_the_path(tmp_path, monkeypatch):
    missing = tmp_path / "nowhere.json"
    monkeypatch.setattr(config, "MOCK_ACCOUNTS_PATH", missing)
    with pytest.raises(FileNotFoundError, match=str(missing)):
        load_accounts()


def test_corrupt_file_names_the_path(records_file):
    records_file("{not json")
    with pytest.raises(ValueError, match=str(records_file.path)):
        load_accounts()


@pytest.mark.parametrize(
    "content",
    ['{"account_id": "ACC-12345"}', '["ACC-12345"]', '[{"holder_name": "x"}]', '[{"account_id": 12345}]'],
)
def test_wrong_shape_names_the_path(records_file, content):
    records_file(content)
    with pytest.raises(ValueError, match=str(records_file.path)):
        load_accounts()


def test_empty_list_finds_nothing(records_file):
    records_file("[]")
    assert load_accounts() == {}
    assert lookup_account("ACC-12345") is None
    assert resolve("ACC-12345").outcome == "not_found"


# --- Requirement: A query resolves to exactly one outcome --------------------


def test_resolve_found():
    resolution = resolve("What is the balance on ACC-12345?")
    assert resolution.outcome == "found"
    assert resolution.account_ids == ("ACC-12345",)
    assert resolution.record["holder_name"] == "Alice Johnson"


def test_resolve_not_found():
    resolution = resolve("What is the balance on ACC-99999?")
    assert resolution.outcome == "not_found"
    assert resolution.account_ids == ("ACC-99999",)
    assert resolution.record is None


def test_resolve_no_id():
    resolution = resolve("Show my recent transactions")
    assert resolution.outcome == "no_id"
    assert resolution.account_ids == ()
    assert resolution.record is None


def test_resolve_multiple_ids_does_no_lookup(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("multiple_ids must not look anything up")

    monkeypatch.setattr(accounts, "lookup_account", forbidden)
    monkeypatch.setattr(accounts, "load_accounts", forbidden)
    resolution = resolve("Compare ACC-12345 and ACC-67890")
    assert resolution.outcome == "multiple_ids"
    assert resolution.account_ids == ("ACC-12345", "ACC-67890")
    assert resolution.record is None


def test_resolve_same_id_twice_is_found():
    assert resolve("ACC-12345 or acc 12345?").outcome == "found"


def test_import_loads_no_langchain():
    code = (
        "import sys, finos.accounts\n"
        "heavy = sorted({m.split('.')[0] for m in sys.modules}"
        " & {'langchain', 'langchain_core', 'langgraph', 'chromadb'})\n"
        "print(','.join(heavy))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""
