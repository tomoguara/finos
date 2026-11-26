"""Tests for settings loading, provider selection, and tracing (Step 1).

Every test runs offline. ``load_dotenv`` is patched out so the developer's
real ``.env`` is never read, and all four relevant environment variables are
controlled through ``monkeypatch`` so they are restored afterwards.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from langsmith.utils import get_env_var, tracing_is_enabled

from finos import config as config_module
from finos.config import CONFIG_PATH, PROJECT_ROOT, get_settings
from finos.llm import (
    embedding_identity,
    get_classifier_llm,
    get_embeddings,
    get_judge_llm,
    get_llm,
)

TRACING_VARS = (
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_PROJECT",
    "LANGSMITH_TRACING",
    "LANGSMITH_TRACING_V2",
    "LANGSMITH_PROJECT",
    "LANGSMITH_TRACING_SAMPLING_RATE",
    "LANGCHAIN_TRACING_SAMPLING_RATE",
)

FAKE_LANGSMITH_KEY = "lsv2-test-not-a-real-key"


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch):
    """Keep every test offline, cache-free, and free of ambient state."""
    monkeypatch.setattr(config_module, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    for name in TRACING_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    get_llm.cache_clear()
    get_judge_llm.cache_clear()
    get_embeddings.cache_clear()
    get_env_var.cache_clear()
    yield
    get_settings.cache_clear()
    get_llm.cache_clear()
    get_judge_llm.cache_clear()
    get_embeddings.cache_clear()
    get_env_var.cache_clear()


def write_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> Path:
    """Point the loader at a throwaway config file."""
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    get_settings.cache_clear()
    get_llm.cache_clear()
    get_judge_llm.cache_clear()
    get_embeddings.cache_clear()
    return path


LOCAL_CONFIG = """
[llm]
use_local_ollama_model = true
temperature = 0

[ollama]
model = "test-local-model"
embedding_model = "test-local-embedding"
base_url = "http://127.0.0.1:11434"

[openai]
model = "gpt-4o-mini"
embedding_model = "text-embedding-3-small"

[policy]
collection = "finos_policy_docs"
chunk_size = 1000
chunk_overlap = 100
top_k = 3

[langsmith]
tracing = true
project = "finos"
sampling_rate = 1.0

[eval]
judge_provider = "openai"
judge_model = "gpt-4o-mini"
repetitions = 3

[eval.gates]
routing_accuracy = 0.95
crisis_sentence = 1.0
faithfulness = 0.7
mrr = 0.8
guardrail_false_positive = 1.0
no_ssn = 1.0

[guardrails]
input_regex = true
moderation = true
injection_classifier = true
classifier_provider = "openai"
classifier_model = "gpt-4o-mini"

[cost]
prices_as_of = "2026-11-20"
audit_log = true
audit_log_path = "logs/audit_log.jsonl"
per_query_alert_usd = 0.01
daily_budget_usd = 1.0

[cost.prices."gpt-4o-mini"]
input_per_1m = 0.15
cached_input_per_1m = 0.075
output_per_1m = 0.60

[cost.prices."text-embedding-3-small"]
input_per_1m = 0.02
"""

OPENAI_CONFIG = LOCAL_CONFIG.replace(
    "use_local_ollama_model = true", "use_local_ollama_model = false"
)


# --- Requirement: Provider is selected from committed configuration -------


def test_local_provider_selected(tmp_path, monkeypatch):
    """Ollama is chosen, with the configured model and base URL."""
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    from langchain_ollama import ChatOllama

    llm = get_llm()
    assert isinstance(llm, ChatOllama)
    assert llm.model == "test-local-model"
    assert llm.base_url == "http://127.0.0.1:11434"
    assert llm.temperature == 0


def test_openai_provider_selected(tmp_path, monkeypatch):
    """OpenAI is chosen when the flag is false and a key is present."""
    write_config(tmp_path, monkeypatch, OPENAI_CONFIG)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    from langchain_openai import ChatOpenAI

    llm = get_llm()
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "gpt-4o-mini"
    assert llm.temperature == 0


# --- Requirement: Shipped configuration values ----------------------------


def test_shipped_model_settings_are_read():
    """The committed config.toml holds the agreed model and project values.

    `use_local_ollama_model` and `tracing` are deliberately not pinned
    here: they are the two switches a developer flips locally (local
    Ollama for day-to-day work, OpenAI to check against the lecture's
    baseline; tracing off when there is no LangSmith key). The suite has
    to stay green either way, so they are only checked for type.
    """
    assert CONFIG_PATH == PROJECT_ROOT / "config.toml"
    settings = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert settings["llm"]["temperature"] == 0
    assert settings["ollama"]["model"] == "qwen3.8:27b-q8_0"
    assert settings["ollama"]["base_url"] == "http://localhost:11434"
    assert settings["openai"]["model"] == "gpt-4o-mini"
    assert settings["langsmith"]["project"] == "finos"
    assert settings["ollama"]["embedding_model"] == "qwen3-embedding:latest"
    assert settings["openai"]["embedding_model"] == "text-embedding-3-small"


def test_shipped_retrieval_settings_are_read():
    """The committed [policy] section holds the lecture's RAG baseline."""
    settings = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert settings["policy"] == {
        "collection": "finos_policy_docs",
        "chunk_size": 1000,
        "chunk_overlap": 100,
        "top_k": 3,
    }


def test_shipped_switches_are_booleans():
    """Either value of each switch is valid; the type is not negotiable."""
    settings = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(settings["llm"]["use_local_ollama_model"], bool)
    assert isinstance(settings["langsmith"]["tracing"], bool)


def test_shipped_config_declares_every_required_setting():
    """The committed file satisfies the loader, whatever the switches say."""
    settings = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for section, key in (
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
    ):
        assert key in settings.get(section, {}), f"[{section}] {key}"
    for key in ("routing_accuracy", "crisis_sentence", "faithfulness", "mrr"):
        assert key in settings["eval"]["gates"], f"[eval.gates] {key}"


def test_shipped_evaluation_settings_are_read():
    """The committed [eval] and [eval.gates] values (llm-access delta)."""
    settings = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert settings["eval"]["judge_provider"] == "openai"
    assert settings["eval"]["judge_model"] == "gpt-4o-mini"
    assert settings["eval"]["repetitions"] == 3
    assert settings["eval"]["gates"] == {
        "routing_accuracy": 0.95,
        "crisis_sentence": 1.0,
        "faithfulness": 0.7,
        "mrr": 0.8,
        "guardrail_false_positive": 1.0,
        "no_ssn": 1.0,
    }


def test_shipped_guardrail_settings_are_read():
    """The committed [guardrails] values (llm-access delta)."""
    settings = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert settings["guardrails"] == {
        "input_regex": True,
        "moderation": True,
        "injection_classifier": True,
        "classifier_provider": "openai",
        "classifier_model": "gpt-4o-mini",
    }


@pytest.mark.parametrize(
    "old, new, setting",
    [
        ('classifier_model = "gpt-4o-mini"\n', "", "[guardrails] classifier_model"),
        ("guardrail_false_positive = 1.0\n", "", "[eval.gates] guardrail_false_positive"),
        ("moderation = true", 'moderation = "yes"', "[guardrails] moderation"),
        ('classifier_provider = "openai"', 'classifier_provider = "anthropic"', "[guardrails] classifier_provider"),
    ],
)
def test_guardrail_settings_are_required_and_validated(tmp_path, monkeypatch, old, new, setting):
    path = write_config(tmp_path, monkeypatch, LOCAL_CONFIG.replace(old, new))
    with pytest.raises(KeyError) as info:
        get_settings()
    assert setting in str(info.value)
    assert str(path) in str(info.value)


def test_shipped_cost_settings_are_read():
    """The committed [cost] values and price entries (llm-access delta)."""
    import datetime

    settings = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cost = settings["cost"]
    # A developer switch like tracing: declared, initially committed as true.
    assert isinstance(cost["audit_log"], bool)
    assert cost["audit_log_path"] == "logs/audit_log.jsonl"
    assert cost["per_query_alert_usd"] == 0.01
    assert cost["daily_budget_usd"] == 1.0
    datetime.date.fromisoformat(cost["prices_as_of"])
    assert cost["prices"]["gpt-4o-mini"]["input_per_1m"] == 0.15
    assert cost["prices"]["gpt-4o-mini"]["output_per_1m"] == 0.60
    assert cost["prices"]["text-embedding-3-small"] == {"input_per_1m": 0.02}
    assert "reasoning" not in settings["ollama"] and "num_ctx" not in settings["ollama"]


def test_audit_log_directory_is_git_ignored():
    ignored = (CONFIG_PATH.parent / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "logs/" in ignored


@pytest.mark.parametrize(
    "old, new, setting",
    [
        ('prices_as_of = "2026-11-20"\n', "", "[cost] prices_as_of"),
        ('prices_as_of = "2026-11-20"', 'prices_as_of = "last week"', "[cost] prices_as_of"),
        ("output_per_1m = 0.60", "output_per_1m = -1", '[cost.prices."gpt-4o-mini"] output_per_1m'),
        ("output_per_1m = 0.60", 'output_per_1m = "cheap"', '[cost.prices."gpt-4o-mini"] output_per_1m'),
        ("input_per_1m = 0.02", "", '[cost.prices."text-embedding-3-small"] input_per_1m'),
        ("audit_log = true", 'audit_log = "on"', "[cost] audit_log"),
        ("per_query_alert_usd = 0.01", "per_query_alert_usd = 0", "[cost] per_query_alert_usd"),
        ("daily_budget_usd = 1.0", "daily_budget_usd = -5", "[cost] daily_budget_usd"),
        (
            'base_url = "http://127.0.0.1:11434"',
            'base_url = "http://127.0.0.1:11434"\nnum_ctx = 0',
            "[ollama] num_ctx",
        ),
        (
            'base_url = "http://127.0.0.1:11434"',
            'base_url = "http://127.0.0.1:11434"\nreasoning = "off"',
            "[ollama] reasoning",
        ),
    ],
)
def test_cost_settings_are_required_and_validated(tmp_path, monkeypatch, old, new, setting):
    assert old in LOCAL_CONFIG
    path = write_config(tmp_path, monkeypatch, LOCAL_CONFIG.replace(old, new))
    with pytest.raises(KeyError) as info:
        get_settings()
    assert setting in str(info.value)
    assert str(path) in str(info.value)


def test_prices_as_of_may_be_a_toml_date(tmp_path, monkeypatch):
    write_config(
        tmp_path, monkeypatch, LOCAL_CONFIG.replace('prices_as_of = "2026-11-20"', "prices_as_of = 2026-11-20")
    )
    assert str(get_settings()["cost"]["prices_as_of"]) == "2026-11-20"


def test_ollama_tuning_unset_builds_the_same_model(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    model = get_llm()
    assert model.reasoning is None and model.num_ctx is None
    assert "reasoning" not in model.model_fields_set and "num_ctx" not in model.model_fields_set


def test_ollama_tuning_reaches_the_model(tmp_path, monkeypatch):
    body = LOCAL_CONFIG.replace(
        'base_url = "http://127.0.0.1:11434"',
        'base_url = "http://127.0.0.1:11434"\nreasoning = false\nnum_ctx = 8192',
    )
    write_config(tmp_path, monkeypatch, body)
    model = get_llm()
    assert model.reasoning is False and model.num_ctx == 8192


def test_overrides_parse_the_tuning_values():
    from finos.evaluation.runner import parse_override

    reasoning = parse_override("ollama.reasoning=false")
    num_ctx = parse_override("ollama.num_ctx=8192")
    assert reasoning.value is False
    assert num_ctx.value == 8192 and isinstance(num_ctx.value, int)


def test_a_variant_can_set_the_unset_tuning_keys(policy_env):
    from finos import config
    from finos.evaluation.runner import OverrideError, variant

    policy_env.set_local_provider(True)

    with variant(["ollama.reasoning=false", "ollama.num_ctx=8192"]):
        assert config.get_settings()["ollama"]["reasoning"] is False
        assert config.get_settings()["ollama"]["num_ctx"] == 8192
        assert get_llm().reasoning is False and get_llm().num_ctx == 8192
    assert "reasoning" not in config.get_settings()["ollama"]
    with pytest.raises(OverrideError):
        with variant(["ollama.not_a_setting=1"]):
            pass


def test_shipped_sampling_rate_is_read():
    """The committed config traces every request."""
    settings = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert settings["langsmith"]["sampling_rate"] == 1.0


def test_committed_config_builds_the_provider_it_selects(monkeypatch):
    """The real config.toml works set either way.

    This is the test that would have caught the brittleness: it exercises
    whichever provider is actually configured, rather than assuming one.
    """
    from langchain_core.language_models import BaseChatModel
    from langchain_ollama import ChatOllama
    from langchain_openai import ChatOpenAI

    # Needed only on the OpenAI branch; harmless on the Ollama branch.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    get_settings.cache_clear()
    get_llm.cache_clear()

    settings = get_settings()
    llm = get_llm()

    assert isinstance(llm, BaseChatModel)
    if settings["llm"]["use_local_ollama_model"]:
        assert isinstance(llm, ChatOllama)
        assert llm.model == settings["ollama"]["model"]
        assert llm.base_url == settings["ollama"]["base_url"]
    else:
        assert isinstance(llm, ChatOpenAI)
        assert llm.model_name == settings["openai"]["model"]
    assert llm.temperature == settings["llm"]["temperature"]


def test_ollama_base_url_has_no_v1_suffix():
    """ChatOllama calls the native API, which has no /v1 prefix."""
    settings = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert not settings["ollama"]["base_url"].rstrip("/").endswith("/v1")


# --- Requirement: Secrets stay out of committed configuration -------------


def test_committed_config_holds_no_secrets():
    """No api keys in the committed settings file."""
    text = CONFIG_PATH.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in text
    assert "LANGCHAIN_API_KEY" not in text
    assert "sk-" not in text


def test_env_example_lists_secrets_only():
    """.env.example names the two secrets and no settings."""
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assigned = {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    assert assigned == {"OPENAI_API_KEY", "LANGCHAIN_API_KEY"}


def test_local_provider_needs_no_key(tmp_path, monkeypatch):
    """Ollama works with no OPENAI_API_KEY set."""
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    assert "OPENAI_API_KEY" not in __import__("os").environ
    assert get_llm() is not None


def test_openai_without_key_names_the_variable(tmp_path, monkeypatch):
    """The failure tells the developer which variable to set."""
    write_config(tmp_path, monkeypatch, OPENAI_CONFIG)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        get_llm()


# --- Requirement: Chat model is provider-neutral and shared ---------------


def test_repeated_requests_share_an_instance(tmp_path, monkeypatch):
    """The helper hands back one shared model."""
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    assert get_llm() is get_llm()


def test_model_override(tmp_path, monkeypatch):
    """An explicit name overrides the configured model."""
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    from langchain_ollama import ChatOllama

    llm = get_llm("some-other-model")
    assert isinstance(llm, ChatOllama)
    assert llm.model == "some-other-model"
    assert llm is not get_llm()


def test_result_is_provider_neutral(tmp_path, monkeypatch):
    """Callers can rely on the shared chat model interface."""
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    from langchain_core.language_models import BaseChatModel

    assert isinstance(get_llm(), BaseChatModel)


# --- Requirement: Tracing is controlled by committed configuration --------


def test_tracing_enabled(tmp_path, monkeypatch):
    """tracing = true with a key reaches LangSmith as enabled, under the project."""
    import os

    monkeypatch.setenv("LANGCHAIN_API_KEY", FAKE_LANGSMITH_KEY)
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    get_settings()
    get_env_var.cache_clear()
    assert tracing_is_enabled() is True
    assert os.environ["LANGCHAIN_PROJECT"] == "finos"


@pytest.mark.parametrize("key_var", ["LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"])
def test_tracing_stays_on_with_a_key(tmp_path, monkeypatch, key_var):
    """Either key variable keeps tracing on, and no reason is recorded."""
    monkeypatch.setenv(key_var, FAKE_LANGSMITH_KEY)
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    status = config_module.tracing_status()
    get_env_var.cache_clear()
    assert tracing_is_enabled() is True
    assert status.enabled is True
    assert status.off_reason is None
    assert status.project == "finos"


def test_tracing_turns_off_without_a_key(tmp_path, monkeypatch):
    """tracing = true and no key: off for the process, with the reason."""
    import os

    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    status = config_module.tracing_status()
    get_env_var.cache_clear()
    assert tracing_is_enabled() is False
    for name in ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING_V2", "LANGSMITH_TRACING"):
        assert os.environ[name] == "false"
    assert status.enabled is False
    assert status.off_reason == config_module.NO_API_KEY == "no-api-key"


def test_tracing_disabled_records_its_reason(tmp_path, monkeypatch):
    """tracing = false is off whether or not a key is set, and says so."""
    monkeypatch.setenv("LANGCHAIN_API_KEY", FAKE_LANGSMITH_KEY)
    write_config(
        tmp_path, monkeypatch, LOCAL_CONFIG.replace("tracing = true", "tracing = false")
    )
    status = config_module.tracing_status()
    assert status.enabled is False
    assert status.off_reason == config_module.DISABLED_IN_CONFIG


def test_observability_reexports_tracing_status():
    """finos.observability.tracing_status is the config accessor."""
    from finos import observability

    assert observability.tracing_status is config_module.tracing_status


def test_sampling_rate_is_applied_over_the_environment(tmp_path, monkeypatch):
    """[langsmith] sampling_rate wins over a conflicting environment value."""
    import os

    monkeypatch.setenv("LANGSMITH_TRACING_SAMPLING_RATE", "0.9")
    monkeypatch.setenv("LANGCHAIN_TRACING_SAMPLING_RATE", "0.9")
    write_config(
        tmp_path,
        monkeypatch,
        LOCAL_CONFIG.replace("sampling_rate = 1.0", "sampling_rate = 0.25"),
    )
    status = config_module.tracing_status()
    get_env_var.cache_clear()
    assert os.environ["LANGSMITH_TRACING_SAMPLING_RATE"] == "0.25"
    assert os.environ["LANGCHAIN_TRACING_SAMPLING_RATE"] == "0.25"
    assert status.sampling_rate == 0.25

    from langsmith import utils as ls_utils

    assert float(ls_utils.get_env_var("TRACING_SAMPLING_RATE")) == 0.25


def test_tracing_disabled(tmp_path, monkeypatch):
    """tracing = false reaches LangSmith as disabled."""
    write_config(
        tmp_path, monkeypatch, LOCAL_CONFIG.replace("tracing = true", "tracing = false")
    )
    get_settings()
    get_env_var.cache_clear()
    assert tracing_is_enabled() is False


def test_config_overrides_a_conflicting_environment_value(tmp_path, monkeypatch):
    """A pre-set LANGCHAIN_TRACING_V2 loses to config.toml."""
    import os

    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "some-other-project")
    get_env_var.cache_clear()
    write_config(
        tmp_path, monkeypatch, LOCAL_CONFIG.replace("tracing = true", "tracing = false")
    )
    get_settings()
    get_env_var.cache_clear()
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert os.environ["LANGCHAIN_PROJECT"] == "finos"
    assert tracing_is_enabled() is False


def test_loading_settings_makes_no_network_call(tmp_path, monkeypatch):
    """Settings load with tracing on and no LangSmith key, offline."""
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("settings loading must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    settings = get_settings()
    assert settings["langsmith"]["tracing"] is True


# --- Requirement: Missing configuration fails clearly ---------------------


def test_missing_config_file_names_the_path(tmp_path, monkeypatch):
    """The error points at the file that should exist."""
    missing = tmp_path / "nowhere" / "config.toml"
    monkeypatch.setattr(config_module, "CONFIG_PATH", missing)
    get_settings.cache_clear()
    get_llm.cache_clear()
    with pytest.raises(FileNotFoundError, match=str(missing)):
        get_llm()


def test_missing_setting_names_the_file_and_setting(tmp_path, monkeypatch):
    """A truncated config fails with both the setting and the file named."""
    path = write_config(
        tmp_path,
        monkeypatch,
        LOCAL_CONFIG.replace('base_url = "http://127.0.0.1:11434"', ""),
    )
    with pytest.raises(KeyError, match="base_url"):
        get_settings()
    get_settings.cache_clear()
    with pytest.raises(KeyError, match=str(path).replace("\\", "\\\\")):
        get_settings()


def test_missing_retrieval_setting_names_the_file_and_setting(tmp_path, monkeypatch):
    """A config without [policy] top_k fails naming that setting and the file."""
    path = write_config(tmp_path, monkeypatch, LOCAL_CONFIG.replace("top_k = 3\n", ""))
    with pytest.raises(KeyError) as info:
        get_settings()
    assert "[policy] top_k" in str(info.value)
    assert str(path) in str(info.value)


def test_missing_sampling_rate_names_the_file_and_setting(tmp_path, monkeypatch):
    """A config without [langsmith] sampling_rate fails naming it and the file."""
    path = write_config(
        tmp_path, monkeypatch, LOCAL_CONFIG.replace("sampling_rate = 1.0\n", "")
    )
    with pytest.raises(KeyError) as info:
        get_settings()
    assert "[langsmith] sampling_rate" in str(info.value)
    assert str(path) in str(info.value)


@pytest.mark.parametrize("value", ["1.5", "-0.1", '"0.5"', "true"])
def test_invalid_sampling_rate_names_the_file_and_setting(tmp_path, monkeypatch, value):
    """A sampling_rate that is not a number from 0.0 to 1.0 is rejected."""
    path = write_config(
        tmp_path,
        monkeypatch,
        LOCAL_CONFIG.replace("sampling_rate = 1.0", f"sampling_rate = {value}"),
    )
    with pytest.raises(KeyError) as info:
        get_settings()
    assert "[langsmith] sampling_rate" in str(info.value)
    assert str(path) in str(info.value)


@pytest.mark.parametrize(
    "line, setting",
    [
        ('judge_model = "gpt-4o-mini"\n', "[eval] judge_model"),
        ('judge_provider = "openai"\n', "[eval] judge_provider"),
        ("repetitions = 3\n", "[eval] repetitions"),
        ("faithfulness = 0.7\n", "[eval.gates] faithfulness"),
        ("mrr = 0.8\n", "[eval.gates] mrr"),
    ],
)
def test_missing_evaluation_setting_names_it(tmp_path, monkeypatch, line, setting):
    """Every [eval] and [eval.gates] setting is required."""
    path = write_config(tmp_path, monkeypatch, LOCAL_CONFIG.replace(line, ""))
    with pytest.raises(KeyError) as info:
        get_settings()
    assert setting in str(info.value)
    assert str(path) in str(info.value)


@pytest.mark.parametrize(
    "old, new, setting",
    [
        ("faithfulness = 0.7", "faithfulness = 7", "[eval.gates] faithfulness"),
        ("mrr = 0.8", "mrr = -0.1", "[eval.gates] mrr"),
        ("routing_accuracy = 0.95", 'routing_accuracy = "high"', "[eval.gates] routing_accuracy"),
        ("repetitions = 3", "repetitions = 0", "[eval] repetitions"),
        ("repetitions = 3", "repetitions = 1.5", "[eval] repetitions"),
        ('judge_provider = "openai"', 'judge_provider = "anthropic"', "[eval] judge_provider"),
    ],
)
def test_invalid_evaluation_setting_names_it(tmp_path, monkeypatch, old, new, setting):
    """Out-of-range thresholds, repetitions, and unknown judge providers fail."""
    path = write_config(tmp_path, monkeypatch, LOCAL_CONFIG.replace(old, new))
    with pytest.raises(KeyError) as info:
        get_settings()
    assert setting in str(info.value)
    assert str(path) in str(info.value)


@pytest.mark.parametrize("value", ["0", "0.0", "1", "0.5"])
def test_sampling_rate_bounds_are_accepted(tmp_path, monkeypatch, value):
    write_config(
        tmp_path,
        monkeypatch,
        LOCAL_CONFIG.replace("sampling_rate = 1.0", f"sampling_rate = {value}"),
    )
    assert config_module.tracing_status().sampling_rate == float(value)


@pytest.mark.parametrize(
    "section, line",
    [
        ("ollama", 'embedding_model = "test-local-embedding"\n'),
        ("openai", 'embedding_model = "text-embedding-3-small"\n'),
    ],
)
def test_missing_embedding_model_names_the_setting(tmp_path, monkeypatch, section, line):
    """The embedding model settings are required under both providers."""
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG.replace(line, ""))
    with pytest.raises(KeyError, match=rf"\[{section}\] embedding_model"):
        get_settings()


# --- Requirement: Judge model follows its own configuration ---------------


def test_openai_judge_with_a_local_generator(tmp_path, monkeypatch):
    """The judge ignores use_local_ollama_model."""
    from langchain_ollama import ChatOllama
    from langchain_openai import ChatOpenAI

    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    assert isinstance(get_llm(), ChatOllama)
    judge = get_judge_llm()
    assert isinstance(judge, ChatOpenAI)
    assert judge.model_name == "gpt-4o-mini"
    assert judge.temperature == 0
    assert get_judge_llm() is judge


def test_local_judge_needs_no_openai_key(tmp_path, monkeypatch):
    """An Ollama judge at the configured base URL, with no OpenAI key."""
    from langchain_ollama import ChatOllama

    write_config(
        tmp_path,
        monkeypatch,
        OPENAI_CONFIG.replace('judge_provider = "openai"', 'judge_provider = "ollama"').replace(
            'judge_model = "gpt-4o-mini"', 'judge_model = "local-judge"'
        ),
    )
    judge = get_judge_llm()
    assert isinstance(judge, ChatOllama)
    assert judge.model == "local-judge"
    assert judge.base_url == "http://127.0.0.1:11434"
    assert judge.temperature == 0


def test_openai_judge_without_key_names_the_variable(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        get_judge_llm()


def test_creating_the_judge_makes_no_network_call(tmp_path, monkeypatch):
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("creating the judge must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    assert get_judge_llm() is not None


# --- Requirement: Classifier model follows its own configuration ----------


def test_openai_classifier_with_a_local_generator(tmp_path, monkeypatch):
    from langchain_ollama import ChatOllama
    from langchain_openai import ChatOpenAI

    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    get_classifier_llm.cache_clear()
    assert isinstance(get_llm(), ChatOllama)
    classifier = get_classifier_llm()
    assert isinstance(classifier, ChatOpenAI)
    assert classifier.model_name == "gpt-4o-mini" and classifier.temperature == 0
    assert get_classifier_llm() is classifier


def test_local_classifier_needs_no_openai_key(tmp_path, monkeypatch):
    from langchain_ollama import ChatOllama

    write_config(
        tmp_path,
        monkeypatch,
        LOCAL_CONFIG.replace('classifier_provider = "openai"', 'classifier_provider = "ollama"').replace(
            'classifier_model = "gpt-4o-mini"', 'classifier_model = "local-classifier"'
        ),
    )
    get_classifier_llm.cache_clear()
    classifier = get_classifier_llm()
    assert isinstance(classifier, ChatOllama) and classifier.model == "local-classifier"


def test_openai_classifier_without_key_names_the_variable(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    get_classifier_llm.cache_clear()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        get_classifier_llm()


# --- Requirement: Embedding model follows the provider switch -------------


def test_local_embeddings_selected(tmp_path, monkeypatch):
    """Ollama embeddings at the configured base URL, with no OpenAI key."""
    write_config(tmp_path, monkeypatch, LOCAL_CONFIG)
    from langchain_ollama import OllamaEmbeddings

    embeddings = get_embeddings()
    assert isinstance(embeddings, OllamaEmbeddings)
    assert embeddings.model == "test-local-embedding"
    assert embeddings.base_url == "http://127.0.0.1:11434"
    assert embedding_identity() == ("ollama", "test-local-embedding")


def test_openai_embeddings_selected(tmp_path, monkeypatch):
    """OpenAI embeddings when the switch is false and a key is present."""
    write_config(tmp_path, monkeypatch, OPENAI_CONFIG)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    from langchain_openai import OpenAIEmbeddings

    embeddings = get_embeddings()
    assert isinstance(embeddings, OpenAIEmbeddings)
    assert embeddings.model == "text-embedding-3-small"
    assert embedding_identity() == ("openai", "text-embedding-3-small")


def test_openai_embeddings_without_key_names_the_variable(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, OPENAI_CONFIG)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        get_embeddings()


@pytest.mark.parametrize("config_body", [LOCAL_CONFIG, OPENAI_CONFIG])
def test_embeddings_share_an_instance(tmp_path, monkeypatch, config_body):
    write_config(tmp_path, monkeypatch, config_body)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    assert get_embeddings() is get_embeddings()


@pytest.mark.parametrize("config_body", [LOCAL_CONFIG, OPENAI_CONFIG])
def test_creating_embeddings_makes_no_network_call(tmp_path, monkeypatch, config_body):
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("creating embeddings must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    write_config(tmp_path, monkeypatch, config_body)
    assert get_embeddings() is not None


def test_committed_config_builds_the_embeddings_it_selects(monkeypatch):
    """The real config.toml builds matching embeddings, set either way."""
    from langchain_ollama import OllamaEmbeddings
    from langchain_openai import OpenAIEmbeddings

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    settings = get_settings()
    embeddings = get_embeddings()
    if settings["llm"]["use_local_ollama_model"]:
        assert isinstance(embeddings, OllamaEmbeddings)
        assert embeddings.model == settings["ollama"]["embedding_model"]
    else:
        assert isinstance(embeddings, OpenAIEmbeddings)
        assert embeddings.model == settings["openai"]["embedding_model"]


# --- Path constants -------------------------------------------------------


def test_path_constants_point_into_the_repository():
    """Later steps read data through these constants, not hardcoded paths."""
    from finos.config import MOCK_ACCOUNTS_PATH, POLICY_DOCS_DIR

    assert (PROJECT_ROOT / "pyproject.toml").is_file()
    assert POLICY_DOCS_DIR == PROJECT_ROOT / "data" / "policy-docs"
    assert MOCK_ACCOUNTS_PATH == PROJECT_ROOT / "data" / "mock_accounts.json"


def test_chroma_dir_is_the_ignored_index_directory():
    """The on-disk index lives in git-ignored data/chroma/."""
    from finos.config import CHROMA_DIR

    assert CHROMA_DIR == PROJECT_ROOT / "data" / "chroma"
    assert "data/chroma/" in (PROJECT_ROOT / ".gitignore").read_text("utf-8")
