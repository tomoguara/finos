"""Tests for the policy index (Step 2, policy-retrieval).

Every test here runs offline: ``policy_env`` (see ``conftest.py``) points
``CHROMA_DIR`` at ``tmp_path`` and replaces the embedding model with
deterministic fakes, so no model is called and nothing is written under the
real ``data/chroma/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finos import config, vectorstore
from finos.vectorstore import (
    PolicyDocument,
    SearchHit,
    chunk_documents,
    compute_fingerprint,
    distinct_sources,
    ensure_index,
    format_docs,
    get_store,
    load_documents,
    read_marker,
    search,
)
from tests.conftest import CountingEmbeddings

REAL_CHROMA_DIR = config.PROJECT_ROOT / "data" / "chroma"
CORPUS_NAMES = sorted(p.name for p in config.POLICY_DOCS_DIR.glob("*.md"))


def _real_chroma_snapshot() -> set[str]:
    if not REAL_CHROMA_DIR.exists():
        return set()
    return {str(p.relative_to(REAL_CHROMA_DIR)) for p in REAL_CHROMA_DIR.rglob("*")}


@pytest.fixture(autouse=True, scope="module")
def real_chroma_untouched():
    """No test in this module may write under the real data/chroma/."""
    before = _real_chroma_snapshot()
    yield
    assert _real_chroma_snapshot() == before


# --- Requirement: The corpus is chunked per document with traceable metadata


def test_shipped_settings_chunking():
    """At 1000/100 every chunk fits, every document yields chunks, indexes run 0.."""
    chunks = chunk_documents(load_documents(), 1000, 100)
    assert all(len(chunk.page_content) <= 1000 for chunk in chunks)
    by_source: dict[str, list[int]] = {}
    for chunk in chunks:
        by_source.setdefault(chunk.metadata["source"], []).append(
            chunk.metadata["chunk_index"]
        )
    assert sorted(by_source) == CORPUS_NAMES
    assert len(CORPUS_NAMES) == 4
    for indexes in by_source.values():
        assert indexes == list(range(len(indexes)))


def test_sources_are_bare_filenames():
    for chunk in chunk_documents(load_documents(), 1000, 100):
        source = chunk.metadata["source"]
        assert "/" not in source and "\\" not in source
        assert (config.POLICY_DOCS_DIR / source).is_file()


def test_chunk_ids_are_deterministic():
    first = chunk_documents(load_documents(), 1000, 100)
    second = chunk_documents(load_documents(), 1000, 100)
    ids = [chunk.id for chunk in first]
    assert ids == [chunk.id for chunk in second]
    assert len(set(ids)) == len(ids)
    for chunk in first:
        assert chunk.id == f"{chunk.metadata['source']}:{chunk.metadata['chunk_index']}"


def test_no_chunk_spans_two_documents():
    documents = load_documents()
    texts = {document.name: document.text for document in documents}
    for chunk in chunk_documents(documents, 1000, 100):
        assert chunk.page_content in texts[chunk.metadata["source"]]


def test_documents_load_in_sorted_order():
    assert [document.name for document in load_documents()] == CORPUS_NAMES


def test_missing_directory_names_it(tmp_path: Path):
    missing = tmp_path / "nowhere"
    with pytest.raises(FileNotFoundError, match=str(missing)):
        load_documents(missing)


def test_directory_without_markdown_names_it(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("not markdown", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match=str(tmp_path)):
        load_documents(tmp_path)


# --- Fingerprint ------------------------------------------------------------

BASE_DOCS = [PolicyDocument("a.md", "alpha"), PolicyDocument("b.md", "beta")]
BASE_ARGS = dict(
    collection="finos_policy_docs",
    chunk_size=1000,
    chunk_overlap=100,
    provider="ollama",
    model="qwen3-embedding:latest",
)


def _fingerprint(docs=BASE_DOCS, **overrides) -> str:
    return compute_fingerprint(docs, **{**BASE_ARGS, **overrides})


@pytest.mark.parametrize(
    "overrides",
    [
        {"collection": "other"},
        {"chunk_size": 800},
        {"chunk_overlap": 50},
        {"provider": "openai"},
        {"model": "other-embedding"},
    ],
)
def test_each_setting_changes_the_fingerprint(overrides):
    assert _fingerprint(**overrides) != _fingerprint()


def test_document_content_changes_the_fingerprint():
    changed = [PolicyDocument("a.md", "alpha!"), BASE_DOCS[1]]
    assert _fingerprint(changed) != _fingerprint()


def test_document_name_changes_the_fingerprint():
    renamed = [PolicyDocument("c.md", "alpha"), BASE_DOCS[1]]
    assert _fingerprint(renamed) != _fingerprint()


def test_added_document_changes_the_fingerprint():
    assert _fingerprint([*BASE_DOCS, PolicyDocument("c.md", "gamma")]) != _fingerprint()


def test_file_order_does_not_change_the_fingerprint():
    assert _fingerprint(list(reversed(BASE_DOCS))) == _fingerprint()


def test_top_k_is_not_a_fingerprint_input():
    """top_k changes retrieval, not the index, so it cannot be passed at all."""
    with pytest.raises(TypeError):
        compute_fingerprint(BASE_DOCS, top_k=5, **BASE_ARGS)


def test_top_k_change_reuses_the_index(policy_env):
    ensure_index()
    policy_env.set_config("top_k = 3", "top_k = 5")
    assert ensure_index().status == "up_to_date"


# --- Requirement: The index persists on disk and is rebuilt when stale ------


def test_first_open_builds_and_writes_the_marker(policy_env):
    assert not policy_env.chroma_dir.exists()
    info = ensure_index()
    assert info.status == "built"
    assert info.documents == 4
    assert info.chunks > 4
    assert (info.provider, info.model) == ("fake", "deterministic-64")
    assert info.collection == "finos_policy_docs"
    assert policy_env.embeddings.documents_embedded == info.chunks

    marker = read_marker()
    assert marker is not None
    assert marker["chunks"] == info.chunks
    assert marker["documents"] == 4
    assert marker["collection"] == "finos_policy_docs"
    assert marker["provider"] == "fake"
    assert marker["model"] == "deterministic-64"
    assert set(marker) >= {"fingerprint", "built_at"}


def test_unchanged_inputs_reuse_the_index(policy_env):
    ensure_index()
    counter = CountingEmbeddings()
    policy_env.use_embeddings(counter)
    get_store()
    info = ensure_index()
    assert info.status == "up_to_date"
    assert counter.documents_embedded == 0


def test_get_store_is_cached_per_process(policy_env):
    assert get_store() is get_store()
    assert policy_env.embeddings.documents_embedded > 0


def test_stale_marker_rebuilds(policy_env):
    first = ensure_index()
    marker = read_marker()
    marker["fingerprint"] = "stale"
    vectorstore.marker_path().write_text(json.dumps(marker), encoding="utf-8")
    counter = CountingEmbeddings()
    policy_env.use_embeddings(counter)
    assert ensure_index().status == "built"
    assert counter.documents_embedded == first.chunks


@pytest.mark.parametrize("content", [None, "{not json", "[]"])
def test_missing_or_unreadable_marker_rebuilds(policy_env, content):
    ensure_index()
    if content is None:
        vectorstore.marker_path().unlink()
    else:
        vectorstore.marker_path().write_text(content, encoding="utf-8")
    assert ensure_index().status == "built"


@pytest.mark.parametrize(
    "old, new",
    [
        ("chunk_size = 1000", "chunk_size = 800"),
        ("chunk_overlap = 100", "chunk_overlap = 50"),
        ('collection = "finos_policy_docs"', 'collection = "renamed_docs"'),
    ],
)
def test_setting_change_rebuilds(policy_env, old, new):
    ensure_index()
    policy_env.set_config(old, new)
    assert ensure_index().status == "built"
    assert ensure_index().status == "up_to_date"


def test_collection_rename_removes_the_old_collection(policy_env):
    ensure_index()
    policy_env.set_config('collection = "finos_policy_docs"', 'collection = "renamed"')
    ensure_index()
    names = set(vectorstore._client().list_collections())
    assert names == {"renamed"}


def test_document_change_rebuilds(policy_env, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    for path in config.POLICY_DOCS_DIR.glob("*.md"):
        (docs / path.name).write_text(path.read_text("utf-8"), encoding="utf-8")
    policy_env.monkeypatch.setattr(config, "POLICY_DOCS_DIR", docs)
    ensure_index()
    target = docs / "account_fees.md"
    target.write_text(target.read_text("utf-8") + "\nNew paragraph.\n", "utf-8")
    assert ensure_index().status == "built"


def test_forced_rebuild_rebuilds(policy_env):
    ensure_index()
    assert ensure_index(rebuild=True).status == "built"
    assert ensure_index().status == "up_to_date"


def test_embedding_size_change_rebuilds_cleanly(policy_env):
    """A new model with a different vector size replaces the old collection."""
    ensure_index()
    policy_env.use_embeddings(CountingEmbeddings(size=32), model="other-32")
    info = ensure_index()
    assert info.status == "built"
    assert info.model == "other-32"
    hits = search("overdraft fee")
    assert hits
    collection = vectorstore._client().get_collection("finos_policy_docs")
    assert collection.count() == info.chunks


def test_failed_build_leaves_no_matching_marker(policy_env):
    ensure_index()
    policy_env.use_embeddings(CountingEmbeddings(fail_after=3), model="new-model")
    with pytest.raises(ConnectionError):
        ensure_index()
    assert read_marker() is None

    counter = CountingEmbeddings()
    policy_env.use_embeddings(counter)
    info = ensure_index()
    assert info.status == "built"
    assert counter.documents_embedded == info.chunks


def test_failed_forced_rebuild_leaves_no_matching_marker(policy_env):
    ensure_index()
    policy_env.use_embeddings(CountingEmbeddings(fail_after=1))
    with pytest.raises(ConnectionError):
        ensure_index(rebuild=True)
    assert read_marker() is None


def test_client_has_telemetry_disabled(policy_env):
    client = vectorstore._client()
    settings = client.get_settings()
    assert settings.anonymized_telemetry is False
    assert settings.chroma_product_telemetry_impl == vectorstore.TELEMETRY_IMPL


def test_collection_uses_cosine_space(policy_env):
    ensure_index()
    collection = vectorstore._client().get_collection("finos_policy_docs")
    assert collection.metadata["hnsw:space"] == "cosine"


# --- Requirement: Search returns ranked chunks with scores ------------------


def test_default_depth_is_top_k(policy_env):
    hits = search("What is the overdraft fee?")
    assert 0 < len(hits) <= 3
    assert [hit.rank for hit in hits] == list(range(1, len(hits) + 1))
    scores = [hit.score for hit in hits]
    assert scores == sorted(scores, reverse=True)
    for hit in hits:
        assert hit.source in CORPUS_NAMES
        assert isinstance(hit.chunk_index, int)
        assert hit.text


def test_default_depth_follows_config(policy_env):
    policy_env.set_config("top_k = 3", "top_k = 5")
    assert len(search("overdraft")) == 5


def test_explicit_depth(policy_env):
    assert len(search("overdraft", k=2)) == 2


# --- Requirement: Retrieved chunks are formatted into a numbered context ----


def _hit(rank: int, source: str, text: str) -> SearchHit:
    return SearchHit(rank=rank, score=0.5, source=source, chunk_index=0, text=text)


def test_two_chunks_format():
    context = format_docs(
        [_hit(1, "account_fees.md", "Fee text."), _hit(2, "fraud_policy.md", "Fraud text.")]
    )
    assert context == (
        "[1] (Source: account_fees.md)\nFee text.\n\n"
        "[2] (Source: fraud_policy.md)\nFraud text."
    )
    assert context.startswith("[1] (Source: account_fees.md)")
    assert "[2] (Source: fraud_policy.md)" in context


def test_empty_results_format_as_empty_string():
    assert format_docs([]) == ""


def test_distinct_sources_keep_rank_order():
    hits = [
        _hit(1, "account_fees.md", "a"),
        _hit(2, "account_fees.md", "b"),
        _hit(3, "fraud_policy.md", "c"),
    ]
    assert distinct_sources(hits) == ["account_fees.md", "fraud_policy.md"]


# --- Failure-mode baseline (offline): where the overdraft facts land --------

OVERDRAFT_FACTS = {
    "fee_35": "overdraft fee of $35 per transaction",
    "cap_105": "maximum of 3 overdraft fees per day ($105)",
    "protection_fee_12": "carries a fee of $12,",
    "protection_description": "enrolled in overdraft protection has a linked savings account",
}


def _chunks_holding(fact: str) -> set[int]:
    chunks = chunk_documents(load_documents(), 1000, 100)
    return {
        chunk.metadata["chunk_index"]
        for chunk in chunks
        if chunk.metadata["source"] == "account_fees.md"
        and fact in " ".join(chunk.page_content.split())
    }


def test_baseline_overdraft_chunk_layout():
    """Record where the overdraft facts land at the 1000/100 baseline.

    This documents the baseline for the evaluation phase; it is not a
    quality bar. If chunk settings or the corpus change, update the
    expected layout deliberately and note it in the evaluation record.

    Observed at 1000/100: the $35 fee and the $105 daily cap share one
    chunk, and the $12 overdraft protection fee shares the next chunk with
    its description. The $35 fee and the $12 protection fee are in
    different chunks, so a question comparing them ("how much does
    overdraft protection save?") needs both chunks retrieved: the
    split-fact failure mode.
    """
    placement = {name: _chunks_holding(fact) for name, fact in OVERDRAFT_FACTS.items()}
    for name, chunks in placement.items():
        assert chunks, f"{name} not found whole in any chunk"

    assert placement["fee_35"] & placement["cap_105"], "$35 and $105 share a chunk"
    assert placement["protection_fee_12"] & placement["protection_description"], (
        "the $12 fee and its description share a chunk"
    )
    assert placement == {
        "fee_35": {1},
        "cap_105": {1},
        "protection_fee_12": {2},
        "protection_description": {2},
    }
    assert not placement["fee_35"] & placement["protection_fee_12"]


def test_concurrent_first_use_opens_the_index_once(policy_env):
    """Several threads searching a fresh index don't race Chroma (Hardening 2)."""
    from concurrent.futures import ThreadPoolExecutor

    from finos.vectorstore import search

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: search("overdraft fee"), range(8)))
    assert all(results)
