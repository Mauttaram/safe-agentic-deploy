"""
RAG vector store for failed fix events.

Uses ChromaDB (local, open source, no API key) for storage.
Embeddings: sentence-transformers (offline) → Anthropic API fallback.

Each document stored = one FailureEvent, embedded as:
  "{ticket_title} | {root_cause} | {error_output[:500]}"

This lets semantic search find similar bugs, similar errors,
or similar root causes — whichever is most relevant.
"""
from __future__ import annotations
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from feedback.capture import FailureEvent

COLLECTION_NAME = "fix_failures"
EMBED_MODEL     = "all-MiniLM-L6-v2"   # fast, 80MB, runs offline


class RAGStore:
    _write_lock = threading.Lock()  # shared across all instances; ChromaDB SQLite can't handle concurrent writes

    def __init__(self, store_dir: str = "feedback/store"):
        self._store_dir = store_dir
        self._client    = None
        self._collection = None
        self._embedder   = None
        self._init()

    def _init(self):
        try:
            import chromadb
            db_path = str(Path(self._store_dir) / "chroma")
            self._client     = chromadb.PersistentClient(path=db_path)
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            print(f"[rag_store] ChromaDB ready at {db_path} "
                  f"({self._collection.count()} documents)")
        except ImportError:
            print("[rag_store] chromadb not installed — run: pip install chromadb")

    # ── Write ─────────────────────────────────────────────────────────────────

    def add(self, event: "FailureEvent") -> None:
        if self._collection is None:
            return
        text      = self._event_to_text(event)
        embedding = self._embed(text)

        with RAGStore._write_lock:
            self._collection.add(
                ids        = [event.event_id],
                embeddings = [embedding],
                documents  = [text],
                metadatas  = [{
                    "event_type":   event.event_type,
                    "ticket_id":    event.ticket_id,
                    "ticket_title": event.ticket_title,
                    "repo":         event.repo,
                    "root_cause":   event.root_cause,
                    "timestamp":    event.timestamp,
                    "diff_snippet": event.diff[:500],
                }],
            )

    # ── Read ──────────────────────────────────────────────────────────────────

    def query(self, text: str, n_results: int = 3) -> list[dict]:
        """
        Return the n most similar past failures to the given query text.
        Each result has: ticket_id, ticket_title, root_cause, diff_snippet,
                         event_type, repo, similarity_score.
        """
        if self._collection is None or self._collection.count() == 0:
            return []

        embedding = self._embed(text)
        results   = self._collection.query(
            query_embeddings = [embedding],
            n_results        = min(n_results, self._collection.count()),
            include          = ["metadatas", "distances", "documents"],
        )

        out = []
        for i, meta in enumerate(results["metadatas"][0]):
            out.append({
                **meta,
                "similarity": round(1 - results["distances"][0][i], 3),
                "full_text":  results["documents"][0][i],
            })
        return out

    def count(self) -> int:
        return self._collection.count() if self._collection else 0

    # ── Embedding ─────────────────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        return self._embed_sentence_transformers(text) \
            or self._embed_anthropic(text)             \
            or self._embed_tfidf_fallback(text)

    def _embed_sentence_transformers(self, text: str) -> list[float] | None:
        try:
            from sentence_transformers import SentenceTransformer
            if self._embedder is None:
                self._embedder = SentenceTransformer(EMBED_MODEL)
            return self._embedder.encode(text, normalize_embeddings=True).tolist()
        except Exception:
            return None

    def _embed_anthropic(self, text: str) -> list[float] | None:
        """Anthropic doesn't expose an embeddings API — skip."""
        return None

    def _embed_tfidf_fallback(self, text: str) -> list[float]:
        """
        Last resort: hash-based pseudo-embedding (no dependencies).
        Not semantically meaningful but prevents a crash.
        """
        import hashlib, math
        tokens = text.lower().split()
        vec    = [0.0] * 128
        for token in tokens:
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            vec[h % 128] += 1.0
        norm = math.sqrt(sum(x ** 2 for x in vec)) or 1.0
        return [x / norm for x in vec]

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _event_to_text(event: "FailureEvent") -> str:
        return (
            f"Ticket: {event.ticket_title}\n"
            f"Type: {event.event_type}\n"
            f"Repo: {event.repo}\n"
            f"Root cause: {event.root_cause}\n"
            f"Error: {event.error_output[:500]}\n"
            f"Diff snippet: {event.diff[:500]}"
        )
