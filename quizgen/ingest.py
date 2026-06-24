"""Ingest a textbook PDF (or .tex/.md) into chapter → section → chunk tree.

The pipeline:
1. Extract raw text from the PDF using PyMuPDF.
2. Parse the PDF's built-in Table of Contents to find chapter/section boundaries.
3. Split each section's text into overlapping chunks of ~500–800 tokens.
4. Attach metadata (chapter number, section label, chunk ID) to every chunk.

Usage::

    from quizgen.ingest import ingest_textbook
    chapters = ingest_textbook("data/textbook.pdf", chapter_nums=[1, 2, 3])
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tiktoken
import yaml

logger = logging.getLogger(__name__)


# ── Tokenizer (with offline fallback) ───────────────────────────────


class _WordTokenizer:
    """Lightweight offline fallback for tiktoken.

    ``tiktoken`` downloads its BPE vocabulary on first use; on an air-gapped
    machine (or behind a restrictive proxy) that fails.  This shim approximates
    token counts from whitespace words (~1.3 tokens/word for English prose),
    which is accurate enough to drive chunk-size targets.  It exposes the only
    method the chunker needs: :meth:`encode`.
    """

    _WORD = re.compile(r"\S+")

    def encode(self, text: str) -> list[int]:
        # ~1.3 subword tokens per whitespace word; return a list of that length.
        n_words = len(self._WORD.findall(text))
        return [0] * max(n_words, int(n_words * 1.3))


def _get_encoder(name: str):
    """Return a tiktoken encoding, falling back to :class:`_WordTokenizer`."""
    try:
        return tiktoken.get_encoding(name)
    except Exception as exc:  # network unavailable, unknown encoding, etc.
        logger.warning(
            "tiktoken encoding '%s' unavailable (%s); using offline word "
            "tokenizer for chunk sizing.", name, exc,
        )
        return _WordTokenizer()


# ── Data structures ─────────────────────────────────────────────────


@dataclass
class Chunk:
    """A passage of text with provenance metadata."""

    chunk_id: str
    chapter_num: int
    section_label: str | None
    text: str
    token_count: int
    page_start: int  # 1-indexed
    page_end: int


@dataclass
class Section:
    """A section within a chapter."""

    label: str  # e.g. "3.2"
    title: str
    page_start: int
    page_end: int
    text: str = ""
    chunks: list[Chunk] = field(default_factory=list)


@dataclass
class Chapter:
    """A chapter of the textbook."""

    number: int
    title: str
    page_start: int
    page_end: int
    sections: list[Section] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)  # all chunks across sections

    @property
    def total_chunks(self) -> int:
        return len(self.chunks)


# ── Chunking defaults ───────────────────────────────────────────────

DEFAULT_CHUNK_CONFIG = {
    "target_tokens": 600,
    "max_tokens": 800,
    "min_tokens": 100,
    "overlap_tokens": 100,
    "tokenizer": "cl100k_base",
}


# ── Main entry point ───────────────────────────────────────────────


def ingest_textbook(
    path: str | Path,
    chapter_nums: list[int] | None = None,
    config_path: str | Path | None = None,
) -> list[Chapter]:
    """Ingest a textbook and return a list of Chapter objects with chunks.

    Parameters
    ----------
    path
        Path to the textbook file (.pdf, .tex, or .md).
    chapter_nums
        Which chapters to process (by number). ``None`` = all.
    config_path
        Path to chapter_config.yaml for overrides.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Textbook not found: {path}")

    # Load optional config
    config = _load_config(config_path) if config_path else {}
    chunk_cfg = {**DEFAULT_CHUNK_CONFIG, **(config.get("chunking", {}) or {})}

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        chapters = _ingest_pdf(path, chapter_nums, chunk_cfg)
    elif suffix in (".tex", ".md", ".txt"):
        chapters = _ingest_text(path, chapter_nums, config, chunk_cfg)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    # Summary
    total_chunks = sum(ch.total_chunks for ch in chapters)
    logger.info(
        "Ingested %d chapter(s), %d section(s), %d chunk(s)",
        len(chapters),
        sum(len(ch.sections) for ch in chapters),
        total_chunks,
    )
    return chapters


# ── PDF ingestion ───────────────────────────────────────────────────


def _ingest_pdf(
    path: Path,
    chapter_nums: list[int] | None,
    chunk_cfg: dict[str, Any],
) -> list[Chapter]:
    """Extract chapters from a PDF using its built-in TOC."""
    import fitz  # PyMuPDF

    doc = fitz.open(str(path))
    toc = doc.get_toc()  # list of [level, title, page_num]

    if not toc:
        raise ValueError(
            "PDF has no Table of Contents. Provide chapter boundaries in chapter_config.yaml."
        )

    # Parse TOC into chapter/section structure
    chapters = _parse_toc(toc, doc.page_count)

    # Filter to requested chapters
    if chapter_nums is not None:
        chapters = [ch for ch in chapters if ch.number in chapter_nums]

    if not chapters:
        raise ValueError(f"No chapters found matching {chapter_nums}")

    # Extract text for each chapter/section
    enc = _get_encoder(chunk_cfg["tokenizer"])

    for chapter in chapters:
        _extract_chapter_text(doc, chapter)
        _chunk_chapter(chapter, enc, chunk_cfg)
        logger.info(
            "  Ch %d (%s): %d sections, %d chunks",
            chapter.number,
            chapter.title[:40],
            len(chapter.sections),
            chapter.total_chunks,
        )

    doc.close()
    return chapters


def _parse_toc(
    toc: list[list],
    total_pages: int,
) -> list[Chapter]:
    """Parse a PyMuPDF TOC into Chapter/Section objects.

    The TOC entries are [level, title, page].  We look for numbered
    chapters (e.g. "3 Logic Programming") and their sub-sections.
    """
    chapters: list[Chapter] = []
    chapter_pattern = re.compile(r"^(\d+)\s+(.+)$")

    # First pass: find all numbered chapters in the TOC
    chapter_entries: list[dict] = []
    for level, title, page in toc:
        m = chapter_pattern.match(title.strip())
        if m:
            chapter_entries.append({
                "number": int(m.group(1)),
                "title": m.group(2).strip(),
                "page": page,
                "level": level,
            })

    # Compute page ranges (each chapter runs until the next chapter starts)
    for i, entry in enumerate(chapter_entries):
        if i + 1 < len(chapter_entries):
            page_end = chapter_entries[i + 1]["page"] - 1
        else:
            page_end = total_pages
        entry["page_end"] = page_end

    # Second pass: find sections belonging to each chapter
    section_pattern = re.compile(r"^(\d+\.\d+(?:\.\d+)?)\s+(.+)$")

    for entry in chapter_entries:
        ch = Chapter(
            number=entry["number"],
            title=entry["title"],
            page_start=entry["page"],
            page_end=entry["page_end"],
        )

        # Find TOC entries that are sections of this chapter
        for level, title, page in toc:
            m = section_pattern.match(title.strip())
            if m:
                sec_label = m.group(1)
                # Check if this section belongs to this chapter
                sec_chapter_num = int(sec_label.split(".")[0])
                if sec_chapter_num == ch.number:
                    ch.sections.append(Section(
                        label=sec_label,
                        title=m.group(2).strip(),
                        page_start=page,
                        page_end=ch.page_end,  # will be refined below
                    ))

        # Refine section page ranges
        for i, sec in enumerate(ch.sections):
            if i + 1 < len(ch.sections):
                sec.page_end = ch.sections[i + 1].page_start - 1
            else:
                sec.page_end = ch.page_end

        chapters.append(ch)

    return chapters


def _extract_chapter_text(doc: Any, chapter: Chapter) -> None:
    """Extract text from the PDF for each section of a chapter."""
    if chapter.sections:
        for sec in chapter.sections:
            pages_text = []
            for page_idx in range(sec.page_start - 1, min(sec.page_end, doc.page_count)):
                pages_text.append(doc[page_idx].get_text())
            sec.text = "\n".join(pages_text).strip()
    else:
        # No sections found — treat the whole chapter as one section
        pages_text = []
        for page_idx in range(chapter.page_start - 1, min(chapter.page_end, doc.page_count)):
            pages_text.append(doc[page_idx].get_text())
        chapter.sections.append(Section(
            label=f"{chapter.number}.0",
            title=chapter.title,
            page_start=chapter.page_start,
            page_end=chapter.page_end,
            text="\n".join(pages_text).strip(),
        ))


# ── Chunking ────────────────────────────────────────────────────────


def _chunk_chapter(
    chapter: Chapter,
    enc: tiktoken.Encoding,
    cfg: dict[str, Any],
) -> None:
    """Split each section's text into overlapping token-based chunks."""
    chunk_counter = 0

    for sec in chapter.sections:
        if not sec.text.strip():
            continue

        text_chunks = _split_text_into_chunks(
            sec.text,
            enc,
            target=cfg["target_tokens"],
            maximum=cfg["max_tokens"],
            minimum=cfg["min_tokens"],
            overlap=cfg["overlap_tokens"],
        )

        for chunk_text, token_count in text_chunks:
            chunk_counter += 1
            chunk = Chunk(
                chunk_id=f"ch{chapter.number}_s{sec.label}_chunk_{chunk_counter:03d}",
                chapter_num=chapter.number,
                section_label=sec.label,
                text=chunk_text,
                token_count=token_count,
                page_start=sec.page_start,
                page_end=sec.page_end,
            )
            sec.chunks.append(chunk)
            chapter.chunks.append(chunk)


def _split_text_into_chunks(
    text: str,
    enc: tiktoken.Encoding,
    target: int = 600,
    maximum: int = 800,
    minimum: int = 100,
    overlap: int = 100,
) -> list[tuple[str, int]]:
    """Split text into chunks of approximately *target* tokens.

    Strategy: split on paragraph boundaries (double newline), then
    greedily merge paragraphs until reaching the target. If a single
    paragraph exceeds the maximum, split it on sentence boundaries.

    Returns a list of (chunk_text, token_count) tuples.
    """
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    # Pre-tokenize each paragraph
    para_tokens = [(p, len(enc.encode(p))) for p in paragraphs]

    chunks: list[tuple[str, int]] = []
    current_parts: list[str] = []
    current_tokens = 0

    for para, ptokens in para_tokens:
        # If a single paragraph is too large, split it by sentences
        if ptokens > maximum:
            # Flush current buffer first
            if current_parts:
                chunk_text = "\n\n".join(current_parts)
                chunks.append((chunk_text, current_tokens))
                current_parts, current_tokens = _apply_overlap(
                    current_parts, enc, overlap
                )

            sentence_chunks = _split_long_paragraph(para, enc, target, maximum)
            for sc, sc_tokens in sentence_chunks:
                chunks.append((sc, sc_tokens))
            continue

        # Would adding this paragraph exceed the target?
        if current_tokens + ptokens > target and current_parts:
            chunk_text = "\n\n".join(current_parts)
            if current_tokens >= minimum:
                chunks.append((chunk_text, current_tokens))
            current_parts, current_tokens = _apply_overlap(
                current_parts, enc, overlap
            )

        current_parts.append(para)
        current_tokens += ptokens

    # Flush remaining
    if current_parts:
        chunk_text = "\n\n".join(current_parts)
        tokens = len(enc.encode(chunk_text))
        if tokens >= minimum:
            chunks.append((chunk_text, tokens))

    return chunks


def _apply_overlap(
    parts: list[str],
    enc: tiktoken.Encoding,
    overlap_tokens: int,
) -> tuple[list[str], int]:
    """Keep the tail of *parts* that fits within *overlap_tokens*."""
    if overlap_tokens <= 0:
        return [], 0

    kept: list[str] = []
    kept_tokens = 0
    for p in reversed(parts):
        ptokens = len(enc.encode(p))
        if kept_tokens + ptokens > overlap_tokens:
            break
        kept.insert(0, p)
        kept_tokens += ptokens

    return kept, kept_tokens


def _split_paragraphs(text: str) -> list[str]:
    """Split text on blank lines, stripping empties."""
    paras = re.split(r"\n\s*\n", text)
    return [p.strip() for p in paras if p.strip()]


def _split_long_paragraph(
    text: str,
    enc: tiktoken.Encoding,
    target: int,
    maximum: int,
) -> list[tuple[str, int]]:
    """Split a long paragraph into sentence-level chunks."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[tuple[str, int]] = []
    current: list[str] = []
    current_tokens = 0

    for sent in sentences:
        stokens = len(enc.encode(sent))
        if current_tokens + stokens > target and current:
            chunk_text = " ".join(current)
            chunks.append((chunk_text, current_tokens))
            current = []
            current_tokens = 0
        current.append(sent)
        current_tokens += stokens

    if current:
        chunk_text = " ".join(current)
        chunks.append((chunk_text, current_tokens))

    return chunks


# ── Text file ingestion (fallback for .tex/.md) ────────────────────


def _ingest_text(
    path: Path,
    chapter_nums: list[int] | None,
    config: dict[str, Any],
    chunk_cfg: dict[str, Any],
) -> list[Chapter]:
    """Ingest a plain text / Markdown / LaTeX file using heading regexes."""
    text = path.read_text(encoding="utf-8")
    patterns = config.get("heading_patterns", {})
    chapter_re = re.compile(patterns.get("chapter", r"^#+\s+Chapter\s+(\d+)[:\s]+(.+)"), re.M)
    section_re = re.compile(patterns.get("section", r"^##+\s+(\d+\.\d+)\s+(.+)"), re.M)

    enc = _get_encoder(chunk_cfg["tokenizer"])

    # Find chapter boundaries
    chapter_matches = list(chapter_re.finditer(text))
    if not chapter_matches:
        raise ValueError("No chapter headings found. Check heading_patterns in config.")

    chapters: list[Chapter] = []
    for i, m in enumerate(chapter_matches):
        ch_num = int(m.group(1))
        if chapter_nums and ch_num not in chapter_nums:
            continue

        start = m.end()
        end = chapter_matches[i + 1].start() if i + 1 < len(chapter_matches) else len(text)
        ch_text = text[start:end]

        ch = Chapter(number=ch_num, title=m.group(2).strip(), page_start=0, page_end=0)

        # Find sections within this chapter's text
        sec_matches = list(section_re.finditer(ch_text))
        if sec_matches:
            for j, sm in enumerate(sec_matches):
                sec_start = sm.end()
                sec_end = sec_matches[j + 1].start() if j + 1 < len(sec_matches) else len(ch_text)
                ch.sections.append(Section(
                    label=sm.group(1),
                    title=sm.group(2).strip(),
                    page_start=0,
                    page_end=0,
                    text=ch_text[sec_start:sec_end].strip(),
                ))
        else:
            ch.sections.append(Section(
                label=f"{ch_num}.0",
                title=ch.title,
                page_start=0,
                page_end=0,
                text=ch_text.strip(),
            ))

        _chunk_chapter(ch, enc, chunk_cfg)
        chapters.append(ch)

    return chapters


# ── Config loading ──────────────────────────────────────────────────


def _load_config(path: str | Path) -> dict[str, Any]:
    """Load chapter_config.yaml."""
    path = Path(path)
    if not path.exists():
        logger.warning("Config file not found: %s — using defaults", path)
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}
