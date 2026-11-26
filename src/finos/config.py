"""Settings loading and project paths.

Non-secret settings live in the committed ``config.toml`` at the repository
root; secrets come from the process environment or a local ``.env``.

Importing this module has no side effects. The first call to
:func:`get_settings` loads ``.env``, reads ``config.toml``, and applies the
``[langsmith]`` settings to the process environment. Everything that can
trigger a traced model call therefore loads settings first.

With ``tracing = true`` and no LangSmith API key in the environment after
``.env`` is read, tracing is turned off for the process and
:func:`tracing_status` records why. This module never prints; the CLI
reports it.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
"""The repository root, two levels above ``src/finos/``."""

CONFIG_PATH: Path = PROJECT_ROOT / "config.toml"
"""The committed non-secret settings file."""

POLICY_DOCS_DIR: Path = PROJECT_ROOT / "data" / "policy-docs"
"""Directory holding the SecureBank policy documents."""

MOCK_ACCOUNTS_PATH: Path = PROJECT_ROOT / "data" / "mock_accounts.json"
"""The mock account records the account agent looks up."""

CHROMA_DIR: Path = PROJECT_ROOT / "data" / "chroma"
"""The git-ignored on-disk Chroma index for the policy documents.

Created on first use and rebuilt automatically when stale, so it is safe to
delete at any time.
"""

_REQUIRED_SETTINGS: tuple[tuple[str, str], ...] = (
    ("llm", "use_local_ollama_model"),
    ("llm", "temperature"),
    ("ollama", "model"),
    ("ollama", "base_url"),
    ("ollama", "embedding_model"),
    ("openai", "model"),
    ("openai", "embedding_model"),
    ("policy", "collection"),
    ("policy", "chunk_size"),
    ("policy", "chunk_overlap"),
    ("policy", "top_k"),
    ("langsmith", "tracing"),
    ("langsmith", "project"),
    ("langsmith", "sampling_rate"),
    ("eval", "judge_provider"),
    ("eval", "judge_model"),
    ("eval", "repetitions"),
    ("eval.gates", "routing_accuracy"),
    ("eval.gates", "crisis_sentence"),
    ("eval.gates", "faithfulness"),
    ("eval.gates", "mrr"),
    ("eval.gates", "guardrail_false_positive"),
    ("eval.gates", "no_ssn"),
    ("guardrails", "input_regex"),
    ("guardrails", "moderation"),
    ("guardrails", "injection_classifier"),
    ("guardrails", "classifier_provider"),
    ("guardrails", "classifier_model"),
    ("cost", "prices_as_of"),
    ("cost", "audit_log"),
    ("cost", "audit_log_path"),
    ("cost", "per_query_alert_usd"),
    ("cost", "daily_budget_usd"),
)
"""Every required ``(section, key)``; a dotted section is a nested table."""

JUDGE_PROVIDERS: tuple[str, ...] = ("openai", "ollama")
"""The providers ``[eval] judge_provider`` may name."""

API_KEY_VARS: tuple[str, ...] = ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY")
"""The environment variables either of which supplies a LangSmith API key."""

NO_API_KEY = "no-api-key"
"""The reason recorded when ``tracing = true`` but no API key is set."""

DISABLED_IN_CONFIG = "disabled-in-config"
"""The reason recorded when ``[langsmith] tracing`` is false."""


@dataclass(frozen=True)
class TracingStatus:
    """Whether this process traces, where to, how often, and if not, why."""

    enabled: bool
    """Whether tracing is on for the process after settings load."""
    project: str
    sampling_rate: float
    off_reason: str | None
    """``None`` when enabled; else :data:`NO_API_KEY` or :data:`DISABLED_IN_CONFIG`."""


_tracing_off_reason: str | None = None


@lru_cache
def get_settings() -> dict[str, Any]:
    """Return the parsed ``config.toml``, loading it once per process.

    On the first call this loads ``.env`` (without overriding real
    environment variables), then assigns the ``[langsmith]`` settings to
    ``os.environ`` so that ``config.toml`` wins over any value from ``.env``
    or the environment. No network call is made.

    Returns:
        The settings mapping, cached for the life of the process.

    Raises:
        FileNotFoundError: If ``config.toml`` does not exist; the message
            names the expected path.
        KeyError: If a required setting is missing, or a value is out of
            range (``[langsmith] sampling_rate`` and the ``[eval.gates]``
            thresholds from 0.0 to 1.0, ``[eval] repetitions`` a whole
            number of at least 1, ``[eval] judge_provider`` and
            ``[guardrails] classifier_provider`` one of
            :data:`JUDGE_PROVIDERS`, the ``[guardrails]`` switches booleans);
            the message names the setting and the file.
    """
    global _tracing_off_reason

    load_dotenv()

    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(
            f"Settings file not found: {CONFIG_PATH}. "
            "Copy the committed config.toml to the repository root."
        )

    with CONFIG_PATH.open("rb") as handle:
        settings = tomllib.load(handle)

    for section, key in _REQUIRED_SETTINGS:
        if key not in _section(settings, section):
            raise KeyError(
                f"Missing required setting [{section}] {key} in {CONFIG_PATH}"
            )
    _validate_fraction("langsmith", "sampling_rate", settings["langsmith"]["sampling_rate"])
    _validate_eval(settings["eval"])
    _validate_guardrails(settings["guardrails"])
    _validate_ollama(settings["ollama"])
    _validate_cost(settings["cost"])

    _tracing_off_reason = _apply_langsmith_settings(settings)
    return settings


def tracing_status() -> TracingStatus:
    """Return the tracing state settings put the process in.

    Loads settings if they are not loaded yet, so it raises the same errors
    as :func:`get_settings`. It imports nothing from ``langsmith``.
    """
    langsmith = get_settings()["langsmith"]
    return TracingStatus(
        enabled=_tracing_off_reason is None,
        project=str(langsmith["project"]),
        sampling_rate=float(langsmith["sampling_rate"]),
        off_reason=_tracing_off_reason,
    )


def _section(settings: dict[str, Any], section: str) -> Any:
    """Return a (possibly dotted, nested) section, or ``{}`` if absent."""
    node: Any = settings
    for part in section.split("."):
        node = node.get(part, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def _invalid(section: str, key: str, expected: str, value: Any) -> KeyError:
    return KeyError(
        f"Invalid setting [{section}] {key} in {CONFIG_PATH}: "
        f"expected {expected}, got {value!r}"
    )


def _validate_fraction(section: str, key: str, value: Any) -> None:
    number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not number or not 0.0 <= value <= 1.0:
        raise _invalid(section, key, "a number from 0.0 to 1.0", value)


def _validate_guardrails(guardrails: dict[str, Any]) -> None:
    for key in ("input_regex", "moderation", "injection_classifier"):
        if not isinstance(guardrails[key], bool):
            raise _invalid("guardrails", key, "true or false", guardrails[key])
    provider = guardrails["classifier_provider"]
    if provider not in JUDGE_PROVIDERS:
        raise _invalid(
            "guardrails", "classifier_provider", " or ".join(map(repr, JUDGE_PROVIDERS)), provider
        )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_ollama(ollama: dict[str, Any]) -> None:
    """The optional local-model tuning keys: ``reasoning`` and ``num_ctx``."""
    if "reasoning" in ollama and not isinstance(ollama["reasoning"], bool):
        raise _invalid("ollama", "reasoning", "true or false", ollama["reasoning"])
    if "num_ctx" in ollama:
        value = ollama["num_ctx"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise _invalid("ollama", "num_ctx", "a whole number of at least 1", value)


OPTIONAL_SETTINGS: frozenset[tuple[str, str]] = frozenset(
    {("ollama", "reasoning"), ("ollama", "num_ctx")}
)
"""Settings that may be absent; a ``--set`` variant may add them."""


PRICE_KEYS: tuple[str, ...] = ("input_per_1m", "cached_input_per_1m", "output_per_1m")
"""The keys a ``[cost.prices."<model>"]`` entry may hold; ``input_per_1m`` is required."""


def _validate_cost(cost: dict[str, Any]) -> None:
    """``[cost]`` and its price table (cost-tracking, llm-access specs)."""
    import datetime

    as_of = cost["prices_as_of"]
    if not isinstance(as_of, datetime.date):
        try:
            datetime.date.fromisoformat(str(as_of))
        except ValueError:
            raise _invalid("cost", "prices_as_of", "an ISO date such as 2026-11-20", as_of) from None
    if not isinstance(cost["audit_log"], bool):
        raise _invalid("cost", "audit_log", "true or false", cost["audit_log"])
    if not isinstance(cost["audit_log_path"], str) or not cost["audit_log_path"].strip():
        raise _invalid("cost", "audit_log_path", "a file path", cost["audit_log_path"])
    for key in ("per_query_alert_usd", "daily_budget_usd"):
        if not _is_number(cost[key]) or cost[key] <= 0:
            raise _invalid("cost", key, "a positive number", cost[key])
    prices = cost.get("prices", {})
    if not isinstance(prices, dict):
        raise _invalid("cost", "prices", "a table of model price tables", prices)
    for model, entry in prices.items():
        section = f'cost.prices."{model}"'
        if not isinstance(entry, dict):
            raise _invalid("cost.prices", f'"{model}"', "a table of prices", entry)
        if "input_per_1m" not in entry:
            raise KeyError(f"Missing required setting [{section}] input_per_1m in {CONFIG_PATH}")
        for key, value in entry.items():
            if key not in PRICE_KEYS:
                raise _invalid(section, key, "one of " + ", ".join(PRICE_KEYS), key)
            if not _is_number(value) or value < 0:
                raise _invalid(section, key, "a non-negative number of USD per 1M tokens", value)


def _validate_eval(evaluation: dict[str, Any]) -> None:
    provider = evaluation["judge_provider"]
    if provider not in JUDGE_PROVIDERS:
        raise _invalid("eval", "judge_provider", " or ".join(map(repr, JUDGE_PROVIDERS)), provider)
    repetitions = evaluation["repetitions"]
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
        raise _invalid("eval", "repetitions", "a whole number of at least 1", repetitions)
    for key, value in evaluation["gates"].items():
        _validate_fraction("eval.gates", key, value)


def _apply_langsmith_settings(settings: dict[str, Any]) -> str | None:
    """Copy the ``[langsmith]`` settings into the process environment.

    LangChain reads tracing only from the environment, so these values do
    nothing until they are assigned there. Direct assignment (rather than
    ``setdefault``) is what lets ``config.toml`` override ``.env``.

    The ``LANGSMITH_*`` aliases are assigned too, because the ``langsmith``
    client reads them ahead of the ``LANGCHAIN_*`` names; leaving them alone
    would let a stray ``LANGSMITH_TRACING`` in the environment defeat
    ``tracing = false``.

    With ``tracing = true`` and neither API key variable set, the tracing
    variables are written as ``"false"``: without a key every upload would
    fail, and the SDK would warn after every model call.

    Returns:
        Why tracing is off, or ``None`` when it is on.
    """
    langsmith = settings["langsmith"]
    if not langsmith["tracing"]:
        reason: str | None = DISABLED_IN_CONFIG
    elif not any(os.environ.get(name) for name in API_KEY_VARS):
        reason = NO_API_KEY
    else:
        reason = None
    tracing = "false" if reason else "true"
    project = str(langsmith["project"])
    rate = str(float(langsmith["sampling_rate"]))
    for name in ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING_V2", "LANGSMITH_TRACING"):
        os.environ[name] = tracing
    for name in ("LANGCHAIN_PROJECT", "LANGSMITH_PROJECT"):
        os.environ[name] = project
    for name in ("LANGSMITH_TRACING_SAMPLING_RATE", "LANGCHAIN_TRACING_SAMPLING_RATE"):
        os.environ[name] = rate
    return reason
