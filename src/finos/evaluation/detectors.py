"""Checks for policy claims and false promises in agent replies (Step 4).

The escalation agent's rules against amounts, policy statements, handoff
claims, and promised outcomes are enforced by its prompt only (design D4).
These detectors measure how well the model follows them: the offline tests
check that the fixed texts are clean, and the live tests check real
replies.

They are also the seed of the guardrails layer's output check
(``docs/systems-design-and-architecture.md`` §9.3): when code-level
enforcement arrives, these patterns are the first candidate.
Patterns match case-insensitively.

Moved from ``tests/helpers.py`` in Hardening 2, so the evaluation
evaluators (``no_policy_claim``, ``no_false_promise``) can use them;
``tests/helpers.py`` re-exports them.
Hedged wording ("our support team can help you directly"), plain digits in
prose, and ``988`` are not flagged.
"""

from __future__ import annotations

import re

POLICY_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # currency
        r"\$\s?\d",
        r"\d+\s?(dollars|USD)\b",
        # percentages
        r"\d+(\.\d+)?\s?%",
        # time limits
        r"\b(within|after|up to)\s+\d+\s+(business\s+)?(days?|hours?)\b",
        # policy words
        r"\b(APR|zero liability|daily maximum|per transaction)\b",
    )
)
"""Amounts, percentages, time limits, and policy terms."""

FALSE_PROMISE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # handoff claims
        r"\b(I('ve| have)|we('ve| have))\s+(transferred|escalated|forwarded|connected|opened|created|logged)\b",
        r"(\bwill|'ll)\s+(call|contact|reach out to)\s+you\b",
        # promised outcomes
        r"(\bwill|'ll)\s+(be\s+)?(refund|reverse|waive|credit|approve)",
        # timelines
        r"\b(within|in the next)\s+\d+\s+(minutes?|hours?|days?)\b",
    )
)
"""Handoff claims, promised outcomes, and timelines."""


def has_policy_claim(text: str) -> bool:
    """Return whether ``text`` states an amount, percentage, time limit, or policy term."""
    return any(pattern.search(text) for pattern in POLICY_CLAIM_PATTERNS)


def has_false_promise(text: str) -> bool:
    """Return whether ``text`` claims a handoff or promises an outcome or timeline."""
    return any(pattern.search(text) for pattern in FALSE_PROMISE_PATTERNS)


def explain(text: str, patterns: tuple[re.Pattern[str], ...] | None = None, width: int = 40) -> list[str]:
    """Return each flagged phrase with up to ``width`` characters of context.

    Used in live-test failure messages so a reader can see exactly what was
    flagged, and judge whether it is a real claim or a detector false
    positive. ``patterns`` defaults to both pattern sets.
    """
    patterns = patterns or POLICY_CLAIM_PATTERNS + FALSE_PROMISE_PATTERNS
    spans = sorted({match.span() for pattern in patterns for match in pattern.finditer(text)})
    snippets = []
    for start, end in spans:
        left = text[max(0, start - width) : start].replace("\n", " ")
        right = text[end : end + width].replace("\n", " ")
        snippets.append(f"...{left}[{text[start:end]}]{right}...")
    return snippets
