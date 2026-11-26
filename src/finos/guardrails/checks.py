"""Pure guardrail checks: patterns and text transforms, no I/O and no models.

Input categories are tuned to this system: the explore probe found the
lecture's patterns blocked half of a set of harmless near-misses ("under
investigation", "How is my Social Security number protected?"), so each
category here needs extraction or comparison phrasing, not a bare keyword
(design D3). Output checks reuse the trace-masking SSN detection and the
evaluation detectors (design D4).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_FLAGS = re.IGNORECASE

_SSN_TERM = r"(?:ssn|social\s*security(?:\s*number)?|tax(?:payer)?\s*(?:id|number))"

INPUT_CATEGORIES: dict[str, tuple[re.Pattern[str], ...]] = {
    "ssn_extraction": (
        re.compile(rf"\b{_SSN_TERM}\s+(?:for|on|of|in)\b", _FLAGS),
        re.compile(rf"\blast\s+(?:4|four)\b[^.?!]{{0,30}}\b{_SSN_TERM}", _FLAGS),
        re.compile(rf"\b(?:tell|give|show|reveal|read|print|dump|list)\b[^.?!]{{0,30}}\b{_SSN_TERM}", _FLAGS),
    ),
    "investment_advice": (
        re.compile(r"\bshould\s+i\s+(?:invest|buy|sell|trade)\b", _FLAGS),
        re.compile(r"\bcrypto(?:currency|currencies)?\b|\bbitcoin\b|\bstock\s*market\b", _FLAGS),
        re.compile(r"\binvest(?:ing|ment)?\s+(?:in|my)\b", _FLAGS),
    ),
    "competitor": (
        re.compile(
            r"(?=.*\b(?:chase|wells\s*fargo|citi(?:bank|group)?|bank\s+of\s+america|capital\s*one)\b)"
            r"(?=.*\b(?:better|worse|cheaper|than|vs\.?|versus|compared?|comparison|switch(?:ing)?\s+to|move\s+to)\b)",
            _FLAGS | re.DOTALL,
        ),
    ),
    "harmful": (re.compile(r"\bbombs?\b|\bweapons?\b|\bexplosive\w*|\bfirearms?\b", _FLAGS),),
}
"""Input regex categories, in check order; the first match blocks."""

CRISIS = re.compile(
    r"\b(?:hurt|kill|harm)\s+myself\b|\bend\s+my\s+life\b|\bsuicid\w*|\bwant\s+to\s+die\b"
    r"|\b(?:no|don'?t\s+see\s+the)\s+point\s+(?:of|in)\s+living\b"
    r"|\b(?:not|don'?t\s+feel)\s+safe\b|\bthreaten(?:ing|ed)?\s+me\b"
    r"|\bscared\s+for\s+my\s+(?:life|safety)\b",
    _FLAGS,
)
"""Self-harm or danger: the crisis signal that overrides every input block."""


def input_category(query: str) -> str | None:
    """The first input category ``query`` matches, or ``None``."""
    for category, patterns in INPUT_CATEGORIES.items():
        if any(pattern.search(query) for pattern in patterns):
            return category
    return None


def is_crisis(query: str) -> bool:
    return bool(CRISIS.search(query))


# --- Output checks --------------------------------------------------------------

ALLOWED_EMAILS = frozenset({"support@securebank.example"})
ALLOWED_NUMBERS = frozenset({"988"})

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(
    r"\(?\b\d{3}\)?[ .-]?\d{3}[ .-]\d{4}\b|\b1[ .-]\d{3}[ .-]\d{3}[ .-]\d{4}\b"
    r"|\b\d{3}[ .-]\d{4}\b|\+\d[\d .-]{7,}\d"
)
_COMPETITOR = re.compile(r"\b(?:Chase|Wells Fargo|Citi(?:bank|group)?|Bank of America|Capital One)\b")
_ASKS_WHY = re.compile(r"\bwhy\b|\breason\b|\bcause\b|\bwhat\s+happened\b", _FLAGS)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def redact_ssn(text: str) -> tuple[str, bool]:
    """Redact Social Security data as trace masking does; return ``(text, changed)``."""
    from finos.observability import mask

    masked = mask(text)
    return masked, masked != text


def split_escalation(reply: str) -> tuple[str, bool]:
    """Return the model-written body of an escalation reply, and whether it held the crisis sentence."""
    from finos.prompts import CRISIS_SUPPORT_MESSAGE, SUPPORT_CONTACT

    crisis = CRISIS_SUPPORT_MESSAGE in reply
    body = reply.replace(SUPPORT_CONTACT, "").replace(CRISIS_SUPPORT_MESSAGE, "")
    return body.strip(), crisis


def escalation_violation(reply: str) -> str | None:
    """``policy_claim`` or ``false_promise`` when the model-written body breaks a rule."""
    from finos.evaluation.detectors import has_false_promise, has_policy_claim

    body, _crisis = split_escalation(reply)
    if has_policy_claim(body):
        return "policy_claim"
    if has_false_promise(body):
        return "false_promise"
    return None


def remove_freeze_reason(reply: str, question: str, record: Mapping[str, Any] | None) -> tuple[str, bool]:
    """Drop sentences quoting the record's ``freeze_reason`` unless the question asks why."""
    reason = str((record or {}).get("freeze_reason") or "").strip()
    if not reason or _ASKS_WHY.search(question) or reason.lower() not in reply.lower():
        return reply, False
    sentences = _SENTENCE.split(reply.strip())
    kept = [s for s in sentences if reason.lower() not in s.lower()]
    return " ".join(kept).strip(), True


def contact_violation(text: str) -> str | None:
    """``contact`` when the text holds an email or phone number other than the official ones."""
    for email in _EMAIL.findall(text):
        if email.lower().rstrip(".") not in ALLOWED_EMAILS:
            return "contact"
    for number in _PHONE.findall(text):
        if re.sub(r"\D", "", number) not in ALLOWED_NUMBERS:
            return "contact"
    return None


def competitor_violation(text: str, question: str = "") -> str | None:
    """``"competitor"`` when the reply names a competitor bank the customer didn't name.

    A bank the question names (a transfer to Citibank, say) may be echoed:
    comparisons with competitors are already blocked at the input.
    """
    asked = {m.group(0).lower() for m in _COMPETITOR.finditer(question)}
    for match in _COMPETITOR.finditer(text):
        if match.group(0).lower() not in asked:
            return "competitor"
    return None


def add_crisis_sentence(reply: str) -> tuple[str, bool]:
    """Ensure ``CRISIS_SUPPORT_MESSAGE`` is in the reply, before the contact block."""
    from finos.prompts import CRISIS_SUPPORT_MESSAGE, SUPPORT_CONTACT

    if CRISIS_SUPPORT_MESSAGE in reply:
        return reply, False
    if reply.rstrip().endswith(SUPPORT_CONTACT):
        head = reply.rstrip()[: -len(SUPPORT_CONTACT)].rstrip()
        return f"{head}\n\n{CRISIS_SUPPORT_MESSAGE}\n\n{SUPPORT_CONTACT}", True
    return f"{reply.rstrip()}\n\n{CRISIS_SUPPORT_MESSAGE}\n\n{SUPPORT_CONTACT}", True
