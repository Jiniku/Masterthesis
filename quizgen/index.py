"""Vector index for RAG-grounded question generation.

Embeds all textbook chunks using a local sentence-transformers model and
stores them in a ChromaDB persistent collection.  At query time, retrieves
the top-k most relevant chunks for a given chapter/section, providing
grounding context to the LLM.

**Why ChromaDB?**  It runs fully locally (no server needed), persists to
disk, supports metadata filtering (chapter, section), and integrates well
with sentence-transformers embeddings.  FAISS would also work but lacks
built-in metadata filtering and persistence.

Usage::

    from quizgen.index import ChunkIndex
    from quizgen.ingest import ingest_textbook

    chapters = ingest_textbook("data/textbook.pdf", chapter_nums=[1, 2, 3])
    idx = ChunkIndex(persist_dir="data/chroma_db")
    idx.build(chapters)
    results = idx.query("What is backtracking in Prolog?", chapter=3, top_k=5)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer

from quizgen.config import settings
from quizgen.ingest import Chapter, Chunk

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """A chunk retrieved from the vector index with its similarity score."""

    chunk_id: str
    chapter_num: int
    section_label: str | None
    text: str
    distance: float  # lower = more similar (L2 distance in Chroma)

    @property
    def similarity(self) -> float:
        """Convert L2 distance to a 0–1 similarity score."""
        return 1.0 / (1.0 + self.distance)


class ChunkIndex:
    """Manages the vector index for RAG retrieval.

    Parameters
    ----------
    persist_dir
        Directory for ChromaDB's persistent storage.
    embedding_model
        Name of the sentence-transformers model to use.
    collection_name
        Name of the ChromaDB collection.
    """

    def __init__(
        self,
        persist_dir: str | Path = "data/chroma_db",
        embedding_model: str | None = None,
        collection_name: str = "textbook_chunks",
    ) -> None:
        self.persist_dir = Path(persist_dir)
        self.model_name = embedding_model or settings.embedding_model
        self.collection_name = collection_name

        # Lazy-load the embedding model (heavy import)
        self._encoder: SentenceTransformer | None = None
        self._client: chromadb.ClientAPI | None = None
        self._collection: chromadb.Collection | None = None

    @property
    def encoder(self) -> SentenceTransformer:
        if self._encoder is None:
            logger.info("Loading embedding model: %s", self.model_name)
            self._encoder = SentenceTransformer(self.model_name)
        return self._encoder

    @property
    def client(self) -> chromadb.ClientAPI:
        if self._client is None:
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self.persist_dir)
            )
        return self._client

    @property
    def collection(self) -> chromadb.Collection:
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "l2"},  # L2 distance
            )
        return self._collection

    # ── Build index ─────────────────────────────────────────────────

    def build(self, chapters: list[Chapter], force_rebuild: bool = False) -> int:
        """Embed all chunks and store them in the vector index.

        Parameters
        ----------
        chapters
            Chapters with chunks from the ingestion pipeline.
        force_rebuild
            If True, drops and recreates the collection.

        Returns
        -------
        int
            Number of chunks indexed.
        """
        if force_rebuild:
            try:
                self.client.delete_collection(self.collection_name)
                self._collection = None
                logger.info("Dropped existing collection '%s'", self.collection_name)
            except Exception:
                pass

        all_chunks: list[Chunk] = []
        for ch in chapters:
            all_chunks.extend(ch.chunks)

        if not all_chunks:
            logger.warning("No chunks to index")
            return 0

        # Check if already indexed
        existing = self.collection.count()
        if existing > 0 and not force_rebuild:
            logger.info(
                "Collection already has %d items. Use force_rebuild=True to rebuild.",
                existing,
            )
            return existing

        # Embed in batches
        batch_size = 64
        total_indexed = 0

        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i : i + batch_size]

            texts = [c.text for c in batch]
            ids = [c.chunk_id for c in batch]
            metadatas = [
                {
                    "chapter_num": c.chapter_num,
                    "section_label": c.section_label or "",
                    "token_count": c.token_count,
                    "page_start": c.page_start,
                    "page_end": c.page_end,
                }
                for c in batch
            ]

            # Compute embeddings
            embeddings = self.encoder.encode(texts, show_progress_bar=False)

            self.collection.add(
                ids=ids,
                embeddings=embeddings.tolist(),
                documents=texts,
                metadatas=metadatas,
            )
            total_indexed += len(batch)

            logger.info(
                "  Indexed %d/%d chunks",
                total_indexed,
                len(all_chunks),
            )

        logger.info(
            "Index built: %d chunks in collection '%s'",
            total_indexed,
            self.collection_name,
        )
        return total_indexed

    # ── Query index ─────────────────────────────────────────────────

    def query(
        self,
        query_text: str,
        *,
        chapter: int | None = None,
        section: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        """Retrieve the most relevant chunks for a query.

        Parameters
        ----------
        query_text
            The query to search for.
        chapter
            Filter by chapter number (optional).
        section
            Filter by section label (optional).
        top_k
            Number of results to return.
        """
        # Build metadata filter
        where: dict[str, Any] | None = None
        if chapter is not None and section is not None:
            where = {
                "$and": [
                    {"chapter_num": {"$eq": chapter}},
                    {"section_label": {"$eq": section}},
                ]
            }
        elif chapter is not None:
            where = {"chapter_num": {"$eq": chapter}}
        elif section is not None:
            where = {"section_label": {"$eq": section}}

        # Embed the query
        query_embedding = self.encoder.encode([query_text]).tolist()

        # Query ChromaDB
        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        # Parse results
        retrieved: list[RetrievedChunk] = []
        if results and results["ids"] and results["ids"][0]:
            for idx in range(len(results["ids"][0])):
                retrieved.append(RetrievedChunk(
                    chunk_id=results["ids"][0][idx],
                    chapter_num=results["metadatas"][0][idx]["chapter_num"],
                    section_label=results["metadatas"][0][idx].get("section_label") or None,
                    text=results["documents"][0][idx],
                    distance=results["distances"][0][idx],
                ))

        return retrieved

    # ── Grounding check ─────────────────────────────────────────────

    @staticmethod
    def check_grounding(
        question_text: str,
        answer_text: str,
        context_chunks: list[RetrievedChunk],
        min_overlap_ratio: float = 0.3,
    ) -> tuple[bool, float]:
        """Check if a question/answer is supported by the retrieved context.

        Uses a simple word-overlap heuristic: what fraction of the
        answer's content words appear in the context?

        Parameters
        ----------
        question_text
            The question stem.
        answer_text
            The keyed answer.
        context_chunks
            Retrieved chunks used as grounding.
        min_overlap_ratio
            Minimum fraction of answer words found in context.

        Returns
        -------
        (is_grounded, overlap_ratio)
        """
        # Build context word set
        context_text = " ".join(c.text for c in context_chunks)
        context_words = _extract_content_words(context_text)

        # Check answer overlap
        answer_words = _extract_content_words(answer_text)
        if not answer_words:
            return True, 1.0  # trivial answer (e.g. "True", "B")

        overlap = answer_words & context_words
        ratio = len(overlap) / len(answer_words) if answer_words else 1.0

        return ratio >= min_overlap_ratio, ratio


# Re-exported for backward compatibility; the implementation now lives in the
# dependency-free quizgen.textmatch module so other code can use it without
# importing the heavy vector-index stack.
from quizgen.textmatch import extract_content_words as _extract_content_words  # noqa: E402
