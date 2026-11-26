"""Output guards: checks on every reply, with fixed replacements (design D4).

In order: SSN redaction; escalation rules; the freeze reason; contacts and
competitors; the crisis sentence. A check that raises fails closed: the
reply becomes the fallback for its intent (the crisis sentence is still
added for a crisis). Nothing regenerates a reply.
"""

from __future__ import annotations

from finos.guardrails import checks
from finos.guardrails.decisions import (
    APPENDED,
    ERROR,
    PASSED,
    REDACTED,
    REPLACED,
    GuardDecision,
    record,
)


def fallback_for(intent: str) -> str:
    """The safe replacement for a reply: empathetic for escalation, generic otherwise."""
    from finos.prompts import (
        ESCALATION_FALLBACK_MESSAGE,
        GUARDRAIL_FALLBACK_MESSAGE,
        SUPPORT_CONTACT,
    )

    if intent == "escalation":
        return f"{ESCALATION_FALLBACK_MESSAGE}\n\n{SUPPORT_CONTACT}"
    return GUARDRAIL_FALLBACK_MESSAGE


def guard_output(
    reply: str, *, query: str, intent: str, crisis: bool
) -> tuple[str, list[GuardDecision]]:
    """Check ``reply`` and return the text to send, with each check's decision."""
    decisions: list[GuardDecision] = []
    text = reply

    def run(guard_type: str, check) -> None:
        decisions.append(record(guard_type, check))

    try:
        def ssn():
            nonlocal text
            text, changed = checks.redact_ssn(text)
            return (REDACTED, "ssn") if changed else (PASSED, "")

        run("output_ssn", ssn)

        if intent == "escalation":
            def escalation():
                nonlocal text
                violation = checks.escalation_violation(text)
                if violation:
                    text = fallback_for(intent)
                    return REPLACED, violation
                return PASSED, ""

            run("output_escalation", escalation)

        if intent == "account_status":
            def freeze_reason():
                nonlocal text
                from finos.accounts import resolve

                record_ = resolve(query).record
                text_, changed = checks.remove_freeze_reason(text, query, record_)
                if not changed:
                    return PASSED, ""
                if not text_:
                    text = fallback_for(intent)
                    return REPLACED, "freeze_reason"
                text = text_
                return REDACTED, "freeze_reason"

            run("output_freeze_reason", freeze_reason)

        def contact():
            nonlocal text
            violation = checks.contact_violation(text)
            if violation:
                text = fallback_for(intent)
                return REPLACED, violation
            return PASSED, ""

        run("output_contact", contact)

        def competitor():
            nonlocal text
            violation = checks.competitor_violation(text, query)
            if violation:
                text = fallback_for(intent)
                return REPLACED, violation
            return PASSED, ""

        run("output_competitor", competitor)
    except Exception as error:  # noqa: BLE001 - fail closed: never return an unchecked reply
        text = fallback_for(intent)
        decisions.append(GuardDecision("output", ERROR, type(error).__name__))

    if crisis:
        def crisis_sentence():
            nonlocal text
            text, added = checks.add_crisis_sentence(text)
            return (APPENDED, "crisis") if added else (PASSED, "")

        try:
            run("output_crisis", crisis_sentence)
        except Exception as error:  # noqa: BLE001 - the sentence is still added below
            text, _ = checks.add_crisis_sentence(fallback_for(intent))
            decisions.append(GuardDecision("output_crisis", ERROR, type(error).__name__))
    return text, decisions
