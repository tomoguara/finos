"""The single place in the system that knows about model providers.

Agents call :func:`get_llm` and use the result through the LangChain chat
model interface; the policy index calls :func:`get_embeddings`. Which
provider backs both is decided by one switch in ``config.toml``, so chat and
embedding models never come from different providers.

The evaluation judge (:func:`get_judge_llm`) is the one exception: it comes
from ``[eval] judge_provider`` and ``judge_model``, so a local generator can
be judged by a different, independent model.
"""

from __future__ import annotations

import os
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from finos.config import get_settings


@lru_cache
def get_llm(model: str | None = None) -> BaseChatModel:
    """Return the shared chat model for the configured provider.

    Loading settings first also applies the ``[langsmith]`` tracing settings
    to the environment, which has to happen before any traced call.

    Constructing a chat model makes no network call, so an unreachable
    Ollama host or an invalid key surfaces on the first ``invoke``, not
    here.

    Args:
        model: Override the configured model name for the selected
            provider. ``None`` uses the configured model.

    Returns:
        A provider-neutral chat model. Repeated calls with the same
        argument return the same instance; tests call
        ``get_llm.cache_clear()``.

    Raises:
        FileNotFoundError: If ``config.toml`` is missing.
        KeyError: If a required setting is missing.
        RuntimeError: If OpenAI is selected and ``OPENAI_API_KEY`` is unset.
    """
    settings = get_settings()
    provider = "ollama" if settings["llm"]["use_local_ollama_model"] else "openai"
    return _chat_model(
        provider,
        model or settings[provider]["model"],
        temperature=settings["llm"]["temperature"],
    )


@lru_cache
def get_judge_llm() -> BaseChatModel:
    """Return the evaluation judge: ``[eval] judge_provider`` and ``judge_model``.

    Independent of ``[llm] use_local_ollama_model``, so an OpenAI judge can
    score a local generator (and the reverse). Temperature is always 0, so
    the judge is as repeatable as the provider allows. Construction makes no
    network call; tests call ``get_judge_llm.cache_clear()``.

    Raises:
        FileNotFoundError: If ``config.toml`` is missing.
        KeyError: If a required setting is missing or invalid.
        RuntimeError: If the judge is OpenAI and ``OPENAI_API_KEY`` is unset.
    """
    settings = get_settings()
    evaluation = settings["eval"]
    return _chat_model(
        str(evaluation["judge_provider"]), str(evaluation["judge_model"]), temperature=0
    )


@lru_cache
def get_classifier_llm() -> BaseChatModel:
    """Return the injection classifier: ``[guardrails] classifier_provider`` and model.

    Like the judge, independent of ``[llm] use_local_ollama_model``, at
    temperature 0, with no network call on construction; tests call
    ``get_classifier_llm.cache_clear()``.

    Raises:
        RuntimeError: If the classifier is OpenAI and ``OPENAI_API_KEY`` is unset.
    """
    guardrails = get_settings()["guardrails"]
    return _chat_model(
        str(guardrails["classifier_provider"]), str(guardrails["classifier_model"]), temperature=0
    )


def judge_identity() -> tuple[str, str]:
    """Return the configured judge ``(provider, model)`` without building it."""
    evaluation = get_settings()["eval"]
    return str(evaluation["judge_provider"]), str(evaluation["judge_model"])


def chat_identity() -> tuple[str, str]:
    """Return the configured chat ``(provider, model)`` without building it."""
    settings = get_settings()
    provider = "ollama" if settings["llm"]["use_local_ollama_model"] else "openai"
    return provider, str(settings[provider]["model"])


def _chat_model(provider: str, model: str, *, temperature: float) -> BaseChatModel:
    """Construct a chat model for ``provider``; no network call is made."""
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        ollama = get_settings()["ollama"]
        # The optional tuning keys are passed only when set, so an unset
        # config builds exactly the model it always did (llm-access delta).
        tuning = {key: ollama[key] for key in ("reasoning", "num_ctx") if key in ollama}
        return ChatOllama(
            model=model,
            base_url=ollama["base_url"],
            temperature=temperature,
            **tuning,
        )

    _require_openai_key()

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model, temperature=temperature)


@lru_cache
def get_embeddings() -> Embeddings:
    """Return the shared embedding model for the configured provider.

    Follows the same ``[llm] use_local_ollama_model`` switch as
    :func:`get_llm`: ``[ollama] embedding_model`` at the configured base URL
    when true, ``[openai] embedding_model`` when false. A local run therefore
    never needs an OpenAI key.

    Constructing the model makes no network call; an unreachable host, a
    model that is not pulled, or an invalid key surfaces on the first embed.

    Returns:
        A provider-neutral embedding model. Repeated calls return the same
        instance; tests call ``get_embeddings.cache_clear()``.

    Raises:
        FileNotFoundError: If ``config.toml`` is missing.
        KeyError: If a required setting is missing.
        RuntimeError: If OpenAI is selected and ``OPENAI_API_KEY`` is unset.
    """
    settings = get_settings()

    if settings["llm"]["use_local_ollama_model"]:
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            model=settings["ollama"]["embedding_model"],
            base_url=settings["ollama"]["base_url"],
        )

    _require_openai_key()

    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=settings["openai"]["embedding_model"])


def embedding_identity() -> tuple[str, str]:
    """Return the configured embedding ``(provider, model)`` without building it.

    The policy index records this pair in its fingerprint, so switching
    provider or model forces a rebuild.
    """
    settings = get_settings()
    if settings["llm"]["use_local_ollama_model"]:
        return "ollama", str(settings["ollama"]["embedding_model"])
    return "openai", str(settings["openai"]["embedding_model"])


def _require_openai_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to .env (see .env.example), "
            "or set [llm] use_local_ollama_model = true in config.toml."
        )
