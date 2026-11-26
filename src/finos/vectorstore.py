"""The on-disk policy index: load, chunk, fingerprint, build, open, and search.

This module knows nothing about the policy agent or its prompt, so
``finos policy search`` and later retrieval experiments can use it without
generating an answer.

Importing it has no side effects: no settings are loaded, no index is
opened, and ``chromadb`` and the LangChain integrations are imported only
when an index is actually built or opened.

Lifecycle (design D3)::

    open → read data/chroma/finos_index.json → fingerprint matches? ── yes → reuse
                       │ no / missing / unreadable
                       ▼
    remove marker → delete collection → create → add all chunks → write marker

The marker is written last, so a build that fails partway leaves no
matching marker and the next open rebuilds from scratch.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from finos import config, llm
from finos.observability import step

if TYPE_CHECKING:
    from langchain_chroma import Chroma
    from langchain_core.documents import Document

FINGERPRINT_SCHEMA_VERSION = 1
"""Bumped when the fingerprint's inputs change shape, forcing a rebuild."""

SPLITTER_NAME = "RecursiveCharacterTextSplitter"
"""The splitter recorded in the fingerprint."""

MARKER_NAME = "finos_index.json"
"""The marker file, inside :data:`finos.config.CHROMA_DIR`."""


@dataclass(frozen=True)
class PolicyDocument:
    """One policy document: its bare filename and its full text."""

    name: str
    text: str


@dataclass(frozen=True)
class IndexInfo:
    """What an open or build did, and what the index holds."""

    status: str
    """``"built"`` or ``"up_to_date"``."""
    documents: int
    chunks: int
    provider: str
    model: str
    collection: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchHit:
    """One retrieved chunk, ranked from 1, with a relevance score (higher is better)."""

    rank: int
    score: float
    source: str
    chunk_index: int
    text: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Settings ---------------------------------------------------------------


def policy_settings() -> dict[str, Any]:
    """Return the ``[policy]`` section of ``config.toml``."""
    return dict(config.get_settings()["policy"])


def marker_path() -> Path:
    """Return the marker file path under the current ``CHROMA_DIR``."""
    return config.CHROMA_DIR / MARKER_NAME


# --- Loading and chunking (design D4) ---------------------------------------


def load_documents(directory: Path | None = None) -> list[PolicyDocument]:
    """Load every Markdown file directly in the policy documents directory.

    Files are read as UTF-8 in sorted filename order. ``name`` comes from
    ``Path.name``, so it is always a bare filename.

    Raises:
        FileNotFoundError: If the directory is missing or holds no ``.md``
            files; the message names the directory.
    """
    directory = config.POLICY_DOCS_DIR if directory is None else directory
    if not directory.is_dir():
        raise FileNotFoundError(f"Policy documents directory not found: {directory}")
    paths = sorted(
        path
        for path in directory.glob("*.md")
        if path.is_file() and not path.name.startswith(".")
    )
    if not paths:
        raise FileNotFoundError(f"No Markdown policy documents in {directory}")
    return [PolicyDocument(path.name, path.read_text(encoding="utf-8")) for path in paths]


def chunk_documents(
    documents: Sequence[PolicyDocument], chunk_size: int, chunk_overlap: int
) -> list[Document]:
    """Split each document separately so no chunk spans two documents.

    Each chunk's metadata holds ``source`` (bare filename) and
    ``chunk_index`` (0-based within its file), and its ``id`` is
    ``"{source}:{chunk_index}"``.
    """
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    chunks: list[Document] = []
    for document in documents:
        for index, text in enumerate(splitter.split_text(document.text)):
            chunks.append(
                Document(
                    id=f"{document.name}:{index}",
                    page_content=text,
                    metadata={"source": document.name, "chunk_index": index},
                )
            )
    return chunks


# --- Fingerprint and marker (design D3) -------------------------------------


def compute_fingerprint(
    documents: Sequence[PolicyDocument],
    *,
    collection: str,
    chunk_size: int,
    chunk_overlap: int,
    provider: str,
    model: str,
) -> str:
    """Return a SHA-256 over everything that shapes the index.

    ``top_k`` is deliberately not an input: it changes retrieval, not the
    index. Documents are sorted by name, so file order does not matter.
    """
    payload = {
        "schema": FINGERPRINT_SCHEMA_VERSION,
        "collection": collection,
        "splitter": SPLITTER_NAME,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "embedding": {"provider": provider, "model": model},
        "documents": sorted(
            (
                {
                    "name": document.name,
                    "sha256": hashlib.sha256(document.text.encode("utf-8")).hexdigest(),
                }
                for document in documents
            ),
            key=lambda entry: entry["name"],
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_marker() -> dict[str, Any] | None:
    """Return the marker's contents, or ``None`` if it is missing or unreadable."""
    try:
        value = json.loads(marker_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_marker(fingerprint: str, info: IndexInfo) -> None:
    marker = {
        "fingerprint": fingerprint,
        "collection": info.collection,
        "documents": info.documents,
        "chunks": info.chunks,
        "provider": info.provider,
        "model": info.model,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    marker_path().write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")


def _remove_marker() -> None:
    marker_path().unlink(missing_ok=True)


# --- Build and open (design D3) ---------------------------------------------


TELEMETRY_IMPL = "finos._chroma_telemetry.NoProductTelemetry"
"""Chroma's product-telemetry client: one that drops every event."""


def _client():
    """Return a persistent Chroma client with telemetry off.

    ``anonymized_telemetry=False`` is Chroma's switch; the no-op client also
    stops Chroma's ``posthog`` integration from logging failures to stderr.
    """
    import chromadb
    from chromadb.config import Settings

    config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(config.CHROMA_DIR),
        settings=Settings(
            anonymized_telemetry=False, chroma_product_telemetry_impl=TELEMETRY_IMPL
        ),
    )


def _store(client, collection: str) -> Chroma:
    from langchain_chroma import Chroma

    return Chroma(
        client=client,
        collection_name=collection,
        embedding_function=llm.get_embeddings(),
        collection_metadata={"hnsw:space": "cosine"},
    )


def _open_or_build(*, rebuild: bool) -> tuple[Chroma, IndexInfo]:
    """Open the index, rebuilding it when forced or when it is stale."""
    settings = policy_settings()
    collection = str(settings["collection"])
    chunk_size = int(settings["chunk_size"])
    chunk_overlap = int(settings["chunk_overlap"])
    provider, model = llm.embedding_identity()

    documents = load_documents()
    fingerprint = compute_fingerprint(
        documents,
        collection=collection,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        provider=provider,
        model=model,
    )
    marker = read_marker()
    client = _client()

    if not rebuild and marker is not None and marker.get("fingerprint") == fingerprint:
        info = IndexInfo(
            status="up_to_date",
            documents=int(marker.get("documents", len(documents))),
            chunks=int(marker.get("chunks", 0)),
            provider=provider,
            model=model,
            collection=collection,
        )
        return _store(client, collection), info

    # Remove the marker first, so a failed build can never leave a matching one.
    _remove_marker()
    stale = {collection}
    if marker is not None and isinstance(marker.get("collection"), str):
        stale.add(marker["collection"])
    existing = set(client.list_collections())
    for name in stale & existing:
        client.delete_collection(name)

    chunks = chunk_documents(documents, chunk_size, chunk_overlap)
    store = _store(client, collection)
    store.add_documents(chunks, ids=[chunk.id for chunk in chunks])

    info = IndexInfo(
        status="built",
        documents=len(documents),
        chunks=len(chunks),
        provider=provider,
        model=model,
        collection=collection,
    )
    _write_marker(fingerprint, info)
    return store, info


_index_lock = threading.RLock()
"""Serializes opening and building the index.

Chroma's persistent client is not safe to create from two threads at once on
a fresh directory ("no such table: tenants"), and evaluation experiments run
agents concurrently (Hardening 2). Opening is quick once the index exists.
"""


@lru_cache(maxsize=1)
def get_store() -> Chroma:
    """Return the policy index for this process, building it if missing or stale.

    The result is cached per process; :func:`ensure_index` clears the cache,
    and tests call ``get_store.cache_clear()`` after pointing ``CHROMA_DIR``
    elsewhere. Safe to call from several threads.
    """
    with _index_lock:
        store, _info = _open_or_build(rebuild=False)
    return store


def ensure_index(*, rebuild: bool = False) -> IndexInfo:
    """Build the index if it is stale (or always, with ``rebuild``) and report.

    This always checks afresh rather than reusing the process cache, and it
    clears that cache so the next :func:`get_store` sees the result.
    """
    get_store.cache_clear()
    try:
        with _index_lock:
            _store, info = _open_or_build(rebuild=rebuild)
    finally:
        get_store.cache_clear()
    return info


# --- Retrieval and formatting (design D5) -----------------------------------


def search(query: str, k: int | None = None) -> list[SearchHit]:
    """Return the ``k`` most relevant chunks, best first.

    ``k`` defaults to ``[policy] top_k``. Scores are cosine relevance
    (``1 - distance``), so higher is more relevant.
    """
    if k is None:
        k = int(policy_settings()["top_k"])
    store = get_store()
    _record_query_embedding(query)
    results = store.similarity_search_with_relevance_scores(query, k=k)
    results = sorted(results, key=lambda pair: pair[1], reverse=True)
    return [
        SearchHit(
            rank=rank,
            score=float(score),
            source=str(document.metadata["source"]),
            chunk_index=int(document.metadata["chunk_index"]),
            text=document.page_content,
        )
        for rank, (document, score) in enumerate(results, start=1)
    ]


def hits_as_documents(hits: Sequence[SearchHit]) -> dict[str, Any]:
    """Shape ranked hits as the documents a retriever run records, in rank order."""
    return {
        "documents": [
            {
                "type": "Document",
                "page_content": hit.text,
                "metadata": {
                    "source": hit.source,
                    "chunk_index": hit.chunk_index,
                    "score": hit.score,
                },
            }
            for hit in hits
        ]
    }


@step(
    "policy_retrieval",
    "retriever",
    inputs=lambda query, k=None: {"query": query},
    outputs=hits_as_documents,
)
def traced_search(query: str, k: int | None = None) -> list[SearchHit]:
    """:func:`search` as the ``policy_retrieval`` retriever run.

    Looks ``search`` up at call time, so tests can replace it. Opening or
    building the index inside is not traced: embedding runs are not
    LangChain runs, and :func:`ensure_index` is never wrapped.
    """
    import finos.vectorstore as module

    return module.search(query, k)


def format_docs(hits: Sequence[SearchHit]) -> str:
    """Format ranked chunks into the numbered context string.

    One block per chunk, numbered from 1, each starting with
    ``[n] (Source: <filename>)``; blocks are separated by a blank line.
    No hits format as ``""``.
    """
    return "\n\n".join(
        f"[{number}] (Source: {hit.source})\n{hit.text}"
        for number, hit in enumerate(hits, start=1)
    )


def distinct_sources(hits: Sequence[SearchHit]) -> list[str]:
    """Return the distinct sources of ``hits`` in rank order."""
    return list(dict.fromkeys(hit.source for hit in hits))


def _record_query_embedding(query: str) -> None:
    """Record the query embedding for cost: one call, tokens estimated as characters / 4.

    Embedding models report no usage, so the count is an estimate and is
    marked so. The index build is setup, not query cost, and is not recorded.
    """
    import math

    from finos import llm
    from finos.observability import record_call

    try:
        provider, model = llm.embedding_identity()
    except Exception:  # noqa: BLE001 - recording must never fail a search
        return
    record_call("embedding", provider, model, math.ceil(len(query) / 4), 0, estimated=True)
