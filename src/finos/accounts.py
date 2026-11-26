"""Account ID extraction, mock-record lookup, and query resolution.

The account agent, the ``finos account`` commands, and the tests share this
module. It imports only the standard library and :mod:`finos.config`, so
``finos account lookup`` and ``list`` stay light: no LangChain, no settings.

Every query resolves to exactly one outcome (design D1)::

    no IDs                 -> no_id
    more than one distinct -> multiple_ids   (nothing is looked up)
    one ID, record exists  -> found
    one ID, no record      -> not_found
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from finos import config

ACCOUNT_ID_PATTERN = re.compile(r"\bACC[ -]?(\d{5})(?!\d)", re.IGNORECASE)
"""``ACC`` in any casing, an optional space or dash, then exactly five digits."""

_BARE_ID = re.compile(r"ACC[ -]?(\d{5})", re.IGNORECASE)

Outcome = Literal["found", "not_found", "no_id", "multiple_ids"]


@dataclass(frozen=True)
class Resolution:
    """What a query resolved to."""

    outcome: Outcome
    account_ids: tuple[str, ...]
    """Distinct, normalized IDs in query order."""
    record: dict[str, Any] | None
    """The account record, only when ``outcome == "found"``."""


def extract_account_ids(query: str) -> list[str]:
    """Return the distinct normalized account IDs in ``query``, in order.

    ``ACC-12345``, ``acc-12345``, ``ACC 12345``, and ``ACC12345`` all become
    ``ACC-12345``. Wrong-length tokens such as ``ACC-1234`` are not IDs.
    """
    ids = (f"ACC-{match.group(1)}" for match in ACCOUNT_ID_PATTERN.finditer(query))
    return list(dict.fromkeys(ids))


def normalize_account_id(token: str) -> str | None:
    """Normalize a token that is only an account ID; otherwise return ``None``."""
    match = _BARE_ID.fullmatch(token.strip())
    return f"ACC-{match.group(1)}" if match else None


def load_accounts() -> dict[str, dict[str, Any]]:
    """Read the mock records and index them by ``account_id``.

    The file is read on every call (it is about 2.5 KB), so tests can point
    ``MOCK_ACCOUNTS_PATH`` at a fixture without clearing a cache. An empty
    list is allowed; every lookup then finds nothing.

    Raises:
        FileNotFoundError: If the file does not exist; names the path.
        ValueError: If the file is not valid JSON, or not a list of objects
            that each hold ``account_id``; names the path.
    """
    path = config.MOCK_ACCOUNTS_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"Account records file not found: {path}") from None
    try:
        records = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"Account records file is not valid JSON: {path} ({error})") from None
    if not isinstance(records, list) or not all(
        isinstance(record, dict) and isinstance(record.get("account_id"), str)
        for record in records
    ):
        raise ValueError(
            f"Account records file must hold a list of objects with account_id: {path}"
        )
    return {record["account_id"]: record for record in records}


def lookup_account(account_id: str) -> dict[str, Any] | None:
    """Return the record for a normalized ID, or ``None`` if there is none."""
    return load_accounts().get(account_id)


def resolve(query: str) -> Resolution:
    """Resolve a query to exactly one outcome, looking up at most one record."""
    ids = tuple(extract_account_ids(query))
    if not ids:
        return Resolution("no_id", ids, None)
    if len(ids) > 1:
        return Resolution("multiple_ids", ids, None)
    record = lookup_account(ids[0])
    if record is None:
        return Resolution("not_found", ids, None)
    return Resolution("found", ids, record)
