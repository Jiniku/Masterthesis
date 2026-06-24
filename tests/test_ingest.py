"""Tests for the ingestion pipeline — Phase 1.

These verify that the PDF is correctly split into chapters, sections,
and chunks with proper metadata.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quizgen.ingest import ingest_textbook

TEXTBOOK = Path("data/textbook.pdf")


@pytest.mark.skipif(not TEXTBOOK.exists(), reason="Textbook PDF not available")
class TestIngestion:
    """Integration tests against the real textbook PDF."""

    def test_ingest_chapters_1_to_3(self):
        """Chapters 1–3 are extracted with correct structure."""
        chapters = ingest_textbook(TEXTBOOK, chapter_nums=[1, 2, 3])
        assert len(chapters) == 3
        assert [ch.number for ch in chapters] == [1, 2, 3]

    def test_chapters_have_sections(self):
        """Each chapter has at least one section."""
        chapters = ingest_textbook(TEXTBOOK, chapter_nums=[1, 2, 3])
        for ch in chapters:
            assert len(ch.sections) > 0, f"Chapter {ch.number} has no sections"

    def test_chapters_have_chunks(self):
        """Each chapter has chunks after ingestion."""
        chapters = ingest_textbook(TEXTBOOK, chapter_nums=[1, 2, 3])
        for ch in chapters:
            assert ch.total_chunks > 0, f"Chapter {ch.number} has no chunks"

    def test_chunk_metadata(self):
        """Every chunk has correct chapter/section metadata."""
        chapters = ingest_textbook(TEXTBOOK, chapter_nums=[2])
        for chunk in chapters[0].chunks:
            assert chunk.chapter_num == 2
            assert chunk.section_label is not None
            assert chunk.section_label.startswith("2.")
            assert chunk.chunk_id.startswith("ch2_")
            assert chunk.token_count > 0
            assert len(chunk.text) > 0

    def test_chunk_token_sizes(self):
        """Chunks are within the expected token range."""
        chapters = ingest_textbook(TEXTBOOK, chapter_nums=[3])
        for chunk in chapters[0].chunks:
            # Allow some flexibility — min is 100, max is 800
            assert chunk.token_count >= 50, (
                f"{chunk.chunk_id} has only {chunk.token_count} tokens"
            )
            assert chunk.token_count <= 1000, (
                f"{chunk.chunk_id} has {chunk.token_count} tokens (exceeds max)"
            )

    def test_chunk_ids_unique(self):
        """All chunk IDs within a chapter are unique."""
        chapters = ingest_textbook(TEXTBOOK, chapter_nums=[1, 2, 3])
        all_ids = [c.chunk_id for ch in chapters for c in ch.chunks]
        assert len(all_ids) == len(set(all_ids)), "Duplicate chunk IDs found"

    def test_single_chapter(self):
        """Requesting a single chapter works."""
        chapters = ingest_textbook(TEXTBOOK, chapter_nums=[3])
        assert len(chapters) == 1
        assert chapters[0].number == 3
        assert "Logic Programming" in chapters[0].title

    def test_config_path_works(self):
        """Optional config path does not crash."""
        chapters = ingest_textbook(
            TEXTBOOK,
            chapter_nums=[1],
            config_path="data/chapter_config.yaml",
        )
        assert len(chapters) == 1
