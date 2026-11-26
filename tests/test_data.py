"""Tests for the policy corpus and the mock account records (Step 1).

These read the committed data files through the path constants in
`finos.config`, so no step hardcodes a path. No network or credentials.
"""

from __future__ import annotations

import json
import re

import pytest

from finos.config import MOCK_ACCOUNTS_PATH, POLICY_DOCS_DIR

EXPECTED_DOCS = {
    "account_fees.md",
    "loan_policy.md",
    "transfer_policy.md",
    "fraud_policy.md",
}


def read_doc(name: str) -> str:
    return (POLICY_DOCS_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def accounts() -> list[dict]:
    return json.loads(MOCK_ACCOUNTS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def by_id(accounts: list[dict]) -> dict[str, dict]:
    return {record["account_id"]: record for record in accounts}


# ======================= policy corpus ====================================


def test_corpus_inventory():
    """Exactly the four named Markdown files exist."""
    assert {p.name for p in POLICY_DOCS_DIR.glob("*.md")} == EXPECTED_DOCS
    assert {p.name for p in POLICY_DOCS_DIR.iterdir() if p.is_file()} == EXPECTED_DOCS


@pytest.mark.parametrize("name", sorted(EXPECTED_DOCS))
def test_document_word_count(name: str):
    """Each document is 450 to 550 words, matching the class corpus size."""
    words = len(read_doc(name).split())
    assert 450 <= words <= 550, f"{name} has {words} words"


def test_overdraft_fact_stays_together():
    """One sentence states both the $35 fee and the $105 daily maximum.

    Step 2's chunk-splitting experiment depends on this being one unit.
    """
    text = read_doc("account_fees.md")
    sentences = re.split(r"(?<=[.!?])\s+", text.replace("\n", " "))
    assert any("$35" in s and "$105" in s for s in sentences)


def test_account_fee_facts():
    """Every required account fee value is present."""
    text = read_doc("account_fees.md")
    for value in ("$35", "$105", "$12", "$12.99", "$1,500", "$500", "$0.00"):
        assert value in text, value
    assert "3 overdraft fees per day" in text
    assert "overdraft protection transfer" in text.lower()


def test_premium_waiver_terms():
    """The waiver names the fee, the balance floor, and the deposit floor."""
    text = read_doc("account_fees.md")
    waiver = text[text.index("$12.99 is waived") : ]
    for value in ("$1,500", "$500"):
        assert value in waiver[:600], value


def test_monthly_fee_listed_for_every_account_type(accounts: list[dict]):
    """Each account type used by the mock data appears in the fee schedule."""
    text = read_doc("account_fees.md")
    for record in accounts:
        assert record["account_type"] in text


def test_loan_facts():
    """Every required loan value is present."""
    text = read_doc("loan_policy.md")
    for value in (
        "4.49%",
        "12.99%",
        "5.49%",
        "14.99%",
        "6.99%",
        "24.99%",
        "620",
        "$39",
        "5%",
    ):
        assert value in text, value
    assert "whichever is less" in text


def test_transfer_facts():
    """Every required transfer value is present."""
    text = read_doc("transfer_policy.md")
    for value in ("$25", "$45", "$15", "$10,000", "$25,000"):
        assert value in text, value
    assert "incoming domestic wires are free" in text.lower()


def test_fraud_liability_window_is_unambiguous():
    """Zero liability within 60 days, with no conflicting tier."""
    text = read_doc("fraud_policy.md")
    assert "zero liability" in text.lower()
    assert "60 days" in text
    assert "$50" not in text
    assert "$500" not in text


def test_replacement_card_conflict_is_preserved():
    """The deliberate $5-versus-free conflict survives, unqualified."""
    fees = read_doc("account_fees.md")
    fraud = read_doc("fraud_policy.md")

    assert "A replacement debit card costs $5." in fees
    assert "Standard replacement cards are free." in fraud

    # Neither side limits its value to fraud or any other circumstance.
    assert "fraud" not in fees.lower()
    assert "$5" not in fraud
    assert "whatever the reason" in fraud


# ======================= mock accounts ====================================


def test_file_parses_to_a_list(accounts: list[dict]):
    assert isinstance(accounts, list)
    assert all(isinstance(record, dict) for record in accounts)


def test_account_ids_are_unique_and_well_formed(accounts: list[dict]):
    ids = [record["account_id"] for record in accounts]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"ACC-\d{5}", account_id) for account_id in ids)


def test_every_record_has_the_full_field_set(accounts: list[dict]):
    """Each record carries every agreed field with the agreed type."""
    for record in accounts:
        assert isinstance(record["account_id"], str)
        assert isinstance(record["holder_name"], str)
        assert isinstance(record["account_type"], str)
        assert isinstance(record["balance"], (int, float))
        assert not isinstance(record["balance"], bool)
        assert isinstance(record["status"], str)
        assert isinstance(record["monthly_fee"], (int, float))
        assert not isinstance(record["monthly_fee"], bool)
        assert isinstance(record["monthly_fee_waived"], bool)
        assert isinstance(record["overdraft_protection"], bool)
        assert isinstance(record["recent_transactions"], list)
        assert re.fullmatch(r"\d{4}", record["ssn_last4"])


def test_transactions_have_date_description_and_amount(accounts: list[dict]):
    for record in accounts:
        for transaction in record["recent_transactions"]:
            assert set(transaction) == {"date", "description", "amount"}
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", transaction["date"])
            assert transaction["description"]
            assert isinstance(transaction["amount"], (int, float))
            assert not isinstance(transaction["amount"], bool)


def test_status_mix(accounts: list[dict]):
    """Two active, one frozen, one pending."""
    statuses = sorted(record["status"] for record in accounts)
    assert statuses == ["active", "active", "frozen", "pending"]


def test_frozen_account_explains_itself(by_id: dict[str, dict]):
    frozen = [r for r in by_id.values() if r["status"] == "frozen"]
    assert len(frozen) == 1
    assert frozen[0]["freeze_reason"].strip()


def test_pending_account_has_no_transactions(by_id: dict[str, dict]):
    pending = [r for r in by_id.values() if r["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["recent_transactions"] == []


def test_reference_account_matches(by_id: dict[str, dict]):
    """ACC-12345 is used by the lecture's evaluation and guardrail examples."""
    record = by_id["ACC-12345"]
    assert record["holder_name"] == "Alice Johnson"
    assert record["account_type"] == "Premium Checking"
    assert record["balance"] == 12450.75
    assert record["status"] == "active"
    assert record["monthly_fee"] == 12.99
    assert record["monthly_fee_waived"] is True
    assert record["ssn_last4"] == "6789"


def test_expected_account_set(by_id: dict[str, dict]):
    assert set(by_id) == {"ACC-12345", "ACC-67890", "ACC-11111", "ACC-22222"}


def test_fees_agree_with_the_policy_document(accounts: list[dict]):
    """Each account's monthly fee equals the one in `account_fees.md`."""
    text = read_doc("account_fees.md")
    rows = re.findall(r"^\|\s*([A-Za-z\- ]+?)\s*\|\s*\$([\d,.]+)\s*\|", text, re.M)
    schedule = {
        name.strip(): float(amount.replace(",", ""))
        for name, amount in rows
        if name.strip() != "Account type"
    }
    for record in accounts:
        account_type = record["account_type"]
        assert account_type in schedule, f"{account_type} missing from fee schedule"
        assert schedule[account_type] == pytest.approx(record["monthly_fee"])


def test_account_data_is_fictional(accounts: list[dict]):
    """SSN fragments are fragments only; no full numbers in the file."""
    raw = MOCK_ACCOUNTS_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b", raw)
    assert all(len(record["ssn_last4"]) == 4 for record in accounts)
