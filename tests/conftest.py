"""Shared offline fixtures and fakes (Steps 2 and 3).

``live_test_tracing`` (autouse) runs every ``live``-marked test under
``observe("live-test")``, with its node ID as ``test_id`` in the root
metadata, so live traces can be found by tag (hardening 1, design D8).

``policy_env`` gives a test a private, offline world: a copy of the
committed ``config.toml`` with tracing off, ``CHROMA_DIR`` under
``tmp_path``, and deterministic fake embeddings in place of the real
provider. Nothing is written under the real ``data/chroma/``.

:class:`RecordingChatModel` is the shared fake chat model: it records every
prompt and replies with fixed text. The ``recording_chat`` fixture installs
one as ``finos.llm.get_llm`` for any agent's tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from typing import Any

from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from finos.config import get_settings as _get_settings
from finos.llm import get_embeddings as _get_embeddings
from finos.llm import get_classifier_llm as _get_classifier_llm
from finos.llm import get_judge_llm as _get_judge_llm
from finos.llm import get_llm as _get_llm
from finos.vectorstore import get_store as _get_store

@pytest.fixture(autouse=True)
def live_test_tracing(request: pytest.FixtureRequest):
    """Trace live tests under ``entry:live-test`` with their ``test_id``."""
    if request.node.get_closest_marker("live") is None:
        yield None
        return
    from finos.observability import observe

    with observe("live-test", metadata={"test_id": request.node.nodeid}) as observation:
        yield observation


class RecordingChatModel(BaseChatModel):
    """A fake chat model that records every prompt and replies with fixed text."""

    reply: str = "The overdraft fee is $35 per transaction."
    calls: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "recording-fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        self.calls.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(self.reply))])


REAL_AUDIT_LOG = Path(__file__).resolve().parents[1] / "logs" / "audit_log.jsonl"


def _audit_log_state() -> tuple[int, int] | None:
    try:
        stat = REAL_AUDIT_LOG.stat()
    except FileNotFoundError:
        return None
    return stat.st_size, stat.st_mtime_ns


@pytest.fixture(autouse=True)
def no_real_audit_log(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Keep offline tests out of the real ``logs/audit_log.jsonl``.

    ``policy_env``'s private config already points the audit log into
    ``tmp_path``. A test that answers a query on the shipped config would
    otherwise append to the developer's log, so the real path is redirected
    into this test's ``tmp_path``, and the test fails if the real file
    changes anyway. Live tests write the real log: that is real traffic,
    tagged ``live-test``.
    """
    if request.node.get_closest_marker("live") is not None:
        yield
        return
    from finos import cost

    configured = cost.audit_log_path
    redirected = tmp_path / "shipped-config-audit-log.jsonl"

    def audit_log_path():
        path = configured()
        return redirected if path.resolve() == REAL_AUDIT_LOG else path

    monkeypatch.setattr(cost, "audit_log_path", audit_log_path)
    before = _audit_log_state()
    yield
    assert _audit_log_state() == before, (
        f"{request.node.nodeid} wrote to {REAL_AUDIT_LOG}; use policy_env or a tmp audit path"
    )


@pytest.fixture(autouse=True)
def offline_guard_layers(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Keep the OpenAI-backed input guards offline in every non-live test.

    The shipped ``config.toml`` enables moderation and the injection
    classifier, so a test that reads it (rather than ``policy_env``'s private
    copy) would call OpenAI whenever ``OPENAI_API_KEY`` is set, and a real
    verdict could block the test's query. Moderation flags nothing and the
    classifier answers ``safe`` here; guardrail tests install their own fakes
    on top. Live tests keep the real layers.
    """
    if request.node.get_closest_marker("live") is not None:
        return
    from finos import llm
    from finos.guardrails import input as guard_in

    monkeypatch.setattr(guard_in, "moderate", lambda query: set())
    monkeypatch.setattr(
        llm, "get_classifier_llm", lambda: RecordingChatModel(calls=[], reply="safe")
    )


@pytest.fixture
def recording_chat(monkeypatch: pytest.MonkeyPatch) -> RecordingChatModel:
    """Install a fresh RecordingChatModel as ``finos.llm.get_llm``."""
    from finos import llm

    model = RecordingChatModel(calls=[])
    monkeypatch.setattr(llm, "get_llm", lambda *a, **k: model)
    return model


FAKE_PROVIDER = "fake"
FAKE_MODEL = "deterministic-64"


class CountingEmbeddings(Embeddings):
    """Wraps deterministic fake embeddings and counts what it embeds.

    ``fail_after`` makes document embedding raise once that many documents
    have been embedded in total, to simulate a provider dying mid-build.
    """

    def __init__(self, size: int = 64, fail_after: int | None = None) -> None:
        self.inner = DeterministicFakeEmbedding(size=size)
        self.documents_embedded = 0
        self.queries_embedded = 0
        self.fail_after = fail_after

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            if self.fail_after is not None and self.documents_embedded >= self.fail_after:
                raise ConnectionError("fake embedding provider went away")
            vectors.append(self.inner.embed_query(text))
            self.documents_embedded += 1
        return vectors

    def embed_query(self, text: str) -> list[float]:
        self.queries_embedded += 1
        return self.inner.embed_query(text)


@dataclass
class PolicyEnv:
    """Handles a test uses to steer the offline policy world."""

    monkeypatch: pytest.MonkeyPatch
    chroma_dir: Path
    config_path: Path
    embeddings: CountingEmbeddings
    identity: list[str] = field(default_factory=lambda: [FAKE_PROVIDER, FAKE_MODEL])

    def use_embeddings(self, embeddings: CountingEmbeddings, model: str | None = None):
        """Swap the embedder (and optionally the model name in the fingerprint)."""
        self.embeddings = embeddings
        if model is not None:
            self.identity[1] = model
        self.clear_caches()

    def set_config(self, old: str, new: str) -> None:
        """Edit the private config.toml and reload settings."""
        text = self.config_path.read_text(encoding="utf-8")
        assert old in text, old
        self.config_path.write_text(text.replace(old, new), encoding="utf-8")
        self.clear_caches()

    def set_local_provider(self, local: bool) -> None:
        """Set ``use_local_ollama_model``, whatever the shipped value is."""
        import re

        text = self.config_path.read_text(encoding="utf-8")
        value = "true" if local else "false"
        text, count = re.subn(
            r"(?m)^use_local_ollama_model = \w+$", f"use_local_ollama_model = {value}", text
        )
        assert count == 1
        self.config_path.write_text(text, encoding="utf-8")
        self.clear_caches()

    @staticmethod
    def clear_caches() -> None:
        _get_settings.cache_clear()
        _get_llm.cache_clear()
        _get_judge_llm.cache_clear()
        _get_classifier_llm.cache_clear()
        _get_embeddings.cache_clear()
        _get_store.cache_clear()


@pytest.fixture
def policy_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PolicyEnv:
    from finos import config, llm

    source = config.CONFIG_PATH.read_text(encoding="utf-8")
    config_path = tmp_path / "config.toml"
    # Tracing off, and the OpenAI-backed input guards off, so no test can
    # reach LangSmith or OpenAI; guardrail tests turn the layers on with fakes.
    config_path.write_text(
        source.replace("tracing = true", "tracing = false")
        .replace("moderation = true", "moderation = false")
        .replace("injection_classifier = true", "injection_classifier = false")
        # The audit log is on (a developer may have switched it off) and
        # goes to this test's directory, never to logs/.
        .replace("audit_log = false", "audit_log = true")
        .replace(
            'audit_log_path = "logs/audit_log.jsonl"',
            f"audit_log_path = {json.dumps(str(tmp_path / 'logs' / 'audit_log.jsonl'))}",
        ),
        encoding="utf-8",
    )
    chroma_dir = tmp_path / "chroma"

    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config, "CHROMA_DIR", chroma_dir)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    env = PolicyEnv(
        monkeypatch=monkeypatch,
        chroma_dir=chroma_dir,
        config_path=config_path,
        embeddings=CountingEmbeddings(),
    )
    monkeypatch.setattr(llm, "get_embeddings", lambda: env.embeddings)
    monkeypatch.setattr(llm, "embedding_identity", lambda: tuple(env.identity))
    env.clear_caches()
    yield env
    env.clear_caches()
