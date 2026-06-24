"""Generate candidate exam questions from textbook chunks via LLM.

Each chunk is sent to the LLM with a prompt that instructs it to generate
N questions grounded *only* in the provided text.  Every response is
validated against the ``Question`` Pydantic schema — invalid items are
logged and discarded.

Usage::

    from quizgen.generate import generate_questions
    from quizgen.ingest import ingest_textbook

    chapters = ingest_textbook("data/textbook.pdf", chapter_nums=[1, 2, 3])
    questions = generate_questions(chapters, per_chunk=2)

RAG mode::

    from quizgen.index import ChunkIndex
    index = ChunkIndex()
    index.build(chapters)
    questions = generate_questions(chapters, per_chunk=2, use_rag=True, index=index)
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from pydantic import ValidationError

from quizgen.ingest import Chapter, Chunk
from quizgen.llm_client import LLMClient
from quizgen.schema import Question, Quiz

logger = logging.getLogger(__name__)

# ── Prompt templates ────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an expert exam question writer for a university-level Artificial Intelligence course.
You create high-quality, schema-valid questions that are grounded ONLY in the provided source text.

Rules:
1. Every question MUST be answerable using ONLY the provided text passage.
2. Do NOT use any knowledge beyond the passage.
3. Vary question types: mcq, true_false, short_answer, cloze.
4. Vary Bloom's taxonomy levels: remember, understand, apply, analyze, evaluate, create.
5. Vary difficulty: easy, medium, hard.
6. For MCQ questions, provide exactly 4 options (A, B, C, D) and set answer to the correct letter.
7. For true_false, set answer to "True" or "False".
8. Set source_ref to the chunk_id provided.
9. Respond with valid JSON only — a JSON object with a "questions" key containing an array.
"""

USER_PROMPT_TEMPLATE = """\
Generate exactly {n} exam questions based ONLY on the following text passage.

**Source chunk ID**: {chunk_id}
**Chapter**: {chapter_num}
**Section**: {section_label}

---
TEXT PASSAGE:
{text}
---

Respond with a JSON object:
{{
  "questions": [
    {{
      "chapter": {chapter_num},
      "section": "{section_label}",
      "qtype": "mcq|true_false|short_answer|cloze",
      "bloom_level": "remember|understand|apply|analyze|evaluate|create",
      "difficulty": "easy|medium|hard",
      "stem": "The question text...",
      "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
      "answer": "B",
      "explanation": "Why this is correct (≥10 chars)...",
      "source_ref": "{chunk_id}"
    }}
  ]
}}

For non-MCQ questions, set "options" to null.
Generate exactly {n} questions with varied types, Bloom levels, and difficulties.
"""

# ── RAG-specific prompts ────────────────────────────────────────────

SYSTEM_PROMPT_RAG = """\
You are an expert exam question writer for a university-level Artificial Intelligence course.
You create high-quality, schema-valid questions that are grounded ONLY in the provided source text.

Rules:
1. Every question MUST be answerable using ONLY the provided text passages.
2. Do NOT use any knowledge beyond the passages.
3. Vary question types: mcq, true_false, short_answer, cloze.
4. Vary Bloom's taxonomy levels: remember, understand, apply, analyze, evaluate, create.
5. Vary difficulty: easy, medium, hard.
6. For MCQ questions, provide exactly 4 options (A, B, C, D) and set answer to the correct letter.
7. For true_false, set answer to "True" or "False".
8. Set source_ref to the chunk_id(s) of the passage(s) you use.
9. Respond with valid JSON only — a JSON object with a "questions" key containing an array.
"""

USER_PROMPT_TEMPLATE_RAG = """\
Generate exactly {n} exam questions based ONLY on the following text passages retrieved for Chapter {chapter_num}, Section {section_label}.

**Target Chapter**: {chapter_num}
**Target Section**: {section_label}
**Retrieved passages** (use these as grounding):

{context}

---

Respond with a JSON object:
{{
  "questions": [
    {{
      "chapter": {chapter_num},
      "section": "{section_label}",
      "qtype": "mcq|true_false|short_answer|cloze",
      "bloom_level": "remember|understand|apply|analyze|evaluate|create",
      "difficulty": "easy|medium|hard",
      "stem": "The question text...",
      "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
      "answer": "B",
      "explanation": "Why this is correct (≥10 chars)...",
      "source_ref": "chunk_id_used_from_above"
    }}
  ]
}}

For non-MCQ questions, set "options" to null.
Generate exactly {n} questions with varied types, Bloom levels, and difficulties.
Base EVERY question strictly on the retrieved passages above.
"""


# ── Generation logic ────────────────────────────────────────────────


def generate_questions(
    chapters: list[Chapter],
    per_chunk: int = 2,
    client: LLMClient | None = None,
    max_retries: int = 2,
    use_rag: bool = False,
    index: "ChunkIndex | None" = None,
    rag_top_k: int = 5,
    check_grounding: bool = True,
) -> list[Question]:
    """Generate candidate questions for all chunks across the given chapters.

    Parameters
    ----------
    chapters
        Chapters (with chunks) from the ingestion pipeline.
    per_chunk
        Number of questions to request per chunk.
    client
        LLM client instance. Created from settings if ``None``.
    max_retries
        Number of retries on LLM/validation failure per chunk.
    use_rag
        If True, use RAG mode (retrieve top-k chunks for each chapter/section).
        If False, use Phase 1 single-chunk mode.
    index
        ChunkIndex instance for RAG retrieval. Required if ``use_rag=True``.
    rag_top_k
        Number of chunks to retrieve for RAG grounding.
    check_grounding
        If True, run grounding checks on generated questions in RAG mode.

    Returns
    -------
    list[Question]
        All valid, schema-conforming questions.
    """
    if client is None:
        client = LLMClient()

    if use_rag:
        if index is None:
            raise ValueError("index must be provided when use_rag=True")
        return _generate_questions_rag(
            chapters,
            per_chunk,
            client,
            max_retries,
            index,
            rag_top_k,
            check_grounding,
        )
    else:
        return _generate_questions_single_chunk(
            chapters, per_chunk, client, max_retries
        )


def _generate_questions_single_chunk(
    chapters: list[Chapter],
    per_chunk: int,
    client: LLMClient,
    max_retries: int,
) -> list[Question]:
    """Phase 1 generation: one chunk at a time."""
    all_questions: list[Question] = []
    total_chunks = sum(ch.total_chunks for ch in chapters)
    processed = 0
    failed_chunks = 0

    for chapter in chapters:
        for chunk in chapter.chunks:
            processed += 1
            logger.info(
                "  [%d/%d] Generating %d question(s) from %s ...",
                processed,
                total_chunks,
                per_chunk,
                chunk.chunk_id,
            )

            questions = _generate_from_chunk(
                chunk, per_chunk, client, max_retries
            )
            if questions:
                all_questions.extend(questions)
                logger.info(
                    "    ✓ %d valid question(s) from %s",
                    len(questions),
                    chunk.chunk_id,
                )
            else:
                failed_chunks += 1
                logger.warning(
                    "    ✗ No valid questions from %s",
                    chunk.chunk_id,
                )

    logger.info(
        "Generation complete: %d questions from %d chunks (%d failed)",
        len(all_questions),
        total_chunks,
        failed_chunks,
    )
    return all_questions


def _generate_from_chunk(
    chunk: Chunk,
    n: int,
    client: LLMClient,
    max_retries: int,
) -> list[Question]:
    """Call the LLM for a single chunk and return validated Questions."""
    user_msg = USER_PROMPT_TEMPLATE.format(
        n=n,
        chunk_id=chunk.chunk_id,
        chapter_num=chunk.chapter_num,
        section_label=chunk.section_label or "N/A",
        text=chunk.text[:3000],  # cap to avoid token overflow
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    for attempt in range(1, max_retries + 1):
        try:
            data = client.chat_json(messages, temperature=0.7, max_tokens=4096)

            # Handle both {"questions": [...]} and bare [...]
            if isinstance(data, dict):
                raw_questions = data.get("questions", [])
            elif isinstance(data, list):
                raw_questions = data
            else:
                logger.warning("Unexpected response type: %s", type(data))
                continue

            # Validate each question against Pydantic schema
            valid: list[Question] = []
            for i, raw_q in enumerate(raw_questions):
                try:
                    # Ensure required fields are present
                    if isinstance(raw_q, dict):
                        raw_q.setdefault("source_ref", chunk.chunk_id)
                        raw_q.setdefault("chapter", chunk.chapter_num)
                        if chunk.section_label:
                            raw_q.setdefault("section", chunk.section_label)
                    q = Question.model_validate(raw_q)
                    valid.append(q)
                except ValidationError as e:
                    logger.debug(
                        "    Question %d failed validation: %s", i + 1, e.error_count()
                    )

            if valid:
                return valid

            logger.warning(
                "  Attempt %d: all %d questions failed validation, retrying...",
                attempt,
                len(raw_questions),
            )

        except Exception as e:
            logger.warning("  Attempt %d failed: %s", attempt, e)
            if attempt < max_retries:
                time.sleep(1)  # brief backoff

    return []


# ── RAG-based generation ────────────────────────────────────────────


def _generate_questions_rag(
    chapters: list[Chapter],
    per_chunk: int,
    client: LLMClient,
    max_retries: int,
    index: "ChunkIndex",
    top_k: int,
    check_grounding: bool,
) -> list[Question]:
    """Phase 2 generation: RAG-grounded using vector retrieval.

    For each chapter/section, retrieve the top-k most relevant chunks
    and pass them as grounding context to the LLM.
    """
    from quizgen.index import ChunkIndex

    all_questions: list[Question] = []
    failed_targets = 0
    grounding_failures = 0

    # Group chunks by chapter/section
    targets = _build_chapter_section_targets(chapters)
    total_targets = len(targets)

    for idx, (chapter_num, section_label, target_chunks) in enumerate(targets, 1):
        logger.info(
            "  [%d/%d] RAG generation for Ch.%d §%s (%d chunk(s) in section) ...",
            idx,
            total_targets,
            chapter_num,
            section_label or "N/A",
            len(target_chunks),
        )

        # Retrieve top-k most relevant chunks for this chapter/section
        # Use a general query that covers the chapter/section content
        query = f"Chapter {chapter_num} Section {section_label or ''}"

        retrieved = index.query(
            query,
            chapter=chapter_num,
            section=section_label,
            top_k=top_k,
        )

        if not retrieved:
            logger.warning("    ✗ No chunks retrieved for Ch.%d §%s", chapter_num, section_label)
            failed_targets += 1
            continue

        # Generate questions from the retrieved context
        questions = _generate_from_retrieved_chunks(
            chapter_num,
            section_label,
            retrieved,
            per_chunk,
            client,
            max_retries,
        )

        if questions:
            # Run grounding check if enabled
            if check_grounding:
                for q in questions:
                    is_grounded, overlap = index.check_grounding(
                        q.stem, q.answer, retrieved
                    )
                    if not is_grounded:
                        logger.warning(
                            "    ⚠ Question %s has low grounding (%.1f%% overlap): %s",
                            q.id,
                            overlap * 100,
                            q.stem[:60],
                        )
                        grounding_failures += 1

            all_questions.extend(questions)
            logger.info(
                "    ✓ %d valid question(s) from Ch.%d §%s",
                len(questions),
                chapter_num,
                section_label,
            )
        else:
            failed_targets += 1
            logger.warning(
                "    ✗ No valid questions from Ch.%d §%s",
                chapter_num,
                section_label,
            )

    logger.info(
        "RAG generation complete: %d questions from %d targets (%d failed, %d grounding warnings)",
        len(all_questions),
        total_targets,
        failed_targets,
        grounding_failures,
    )
    return all_questions


def _build_chapter_section_targets(
    chapters: list[Chapter],
) -> list[tuple[int, str | None, list[Chunk]]]:
    """Group chunks by (chapter_num, section_label) for RAG retrieval."""
    targets: dict[tuple[int, str | None], list[Chunk]] = {}

    for chapter in chapters:
        for chunk in chapter.chunks:
            key = (chunk.chapter_num, chunk.section_label)
            if key not in targets:
                targets[key] = []
            targets[key].append(chunk)

    return [(ch, sec, chunks) for (ch, sec), chunks in sorted(targets.items())]


def _generate_from_retrieved_chunks(
    chapter_num: int,
    section_label: str | None,
    retrieved: list["RetrievedChunk"],
    n: int,
    client: LLMClient,
    max_retries: int,
) -> list[Question]:
    """Call the LLM with retrieved chunks as grounding context."""
    from quizgen.index import RetrievedChunk

    # Build context from retrieved chunks
    context_parts = []
    for i, rc in enumerate(retrieved, 1):
        context_parts.append(
            f"[Passage {i} — {rc.chunk_id}]\n{rc.text[:2000]}"
        )
    context = "\n\n".join(context_parts)

    user_msg = USER_PROMPT_TEMPLATE_RAG.format(
        n=n,
        chapter_num=chapter_num,
        section_label=section_label or "N/A",
        context=context,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_RAG},
        {"role": "user", "content": user_msg},
    ]

    for attempt in range(1, max_retries + 1):
        try:
            data = client.chat_json(messages, temperature=0.7, max_tokens=4096)

            # Handle both {"questions": [...]} and bare [...]
            if isinstance(data, dict):
                raw_questions = data.get("questions", [])
            elif isinstance(data, list):
                raw_questions = data
            else:
                logger.warning("Unexpected response type: %s", type(data))
                continue

            # Validate each question against Pydantic schema
            valid: list[Question] = []
            for i, raw_q in enumerate(raw_questions):
                try:
                    # Ensure required fields are present
                    if isinstance(raw_q, dict):
                        raw_q.setdefault("chapter", chapter_num)
                        if section_label:
                            raw_q.setdefault("section", section_label)
                        # Default source_ref if not provided
                        if "source_ref" not in raw_q and retrieved:
                            raw_q["source_ref"] = retrieved[0].chunk_id
                    q = Question.model_validate(raw_q)
                    valid.append(q)
                except ValidationError as e:
                    logger.debug(
                        "    Question %d failed validation: %s", i + 1, e.error_count()
                    )

            if valid:
                return valid

            logger.warning(
                "  Attempt %d: all %d questions failed validation, retrying...",
                attempt,
                len(raw_questions),
            )

        except Exception as e:
            logger.warning("  Attempt %d failed: %s", attempt, e)
            if attempt < max_retries:
                time.sleep(1)  # brief backoff

    return []


# ── Quiz assembly helper ────────────────────────────────────────────


def questions_to_quiz(
    questions: list[Question],
    title: str = "Generated Quiz",
    blueprint: dict | None = None,
) -> Quiz:
    """Wrap a list of questions into a Quiz object."""
    return Quiz(
        title=title,
        blueprint=blueprint or {},
        questions=questions,
    )


# ── Summary / reporting ────────────────────────────────────────────


def print_summary(questions: list[Question]) -> None:
    """Print a distribution summary of generated questions."""
    from collections import Counter

    print(f"\n{'='*60}")
    print(f"  GENERATION SUMMARY — {len(questions)} questions")
    print(f"{'='*60}")

    # Per chapter
    by_chapter = Counter(q.chapter for q in questions)
    print("\n  Per chapter:")
    for ch in sorted(by_chapter):
        print(f"    Chapter {ch}: {by_chapter[ch]}")

    # Per question type
    by_qtype = Counter(q.qtype.value for q in questions)
    print("\n  Per question type:")
    for qt in sorted(by_qtype):
        print(f"    {qt}: {by_qtype[qt]}")

    # Per difficulty
    by_diff = Counter(q.difficulty.value for q in questions)
    print("\n  Per difficulty:")
    for d in ["easy", "medium", "hard"]:
        print(f"    {d}: {by_diff.get(d, 0)}")

    # Per Bloom level
    by_bloom = Counter(q.bloom_level.value for q in questions)
    print("\n  Per Bloom level:")
    for bl in ["remember", "understand", "apply", "analyze", "evaluate", "create"]:
        print(f"    {bl}: {by_bloom.get(bl, 0)}")

    print(f"\n{'='*60}\n")


def print_questions(questions: list[Question], n: int = 5) -> None:
    """Pretty-print the first *n* questions."""
    print(f"\n{'─'*60}")
    print(f"  FIRST {min(n, len(questions))} GENERATED QUESTIONS")
    print(f"{'─'*60}")

    for i, q in enumerate(questions[:n], 1):
        print(f"\n  [{i}] {q.qtype.value.upper()} | Ch.{q.chapter} §{q.section or '–'}")
        print(f"      Bloom: {q.bloom_level.value} | Difficulty: {q.difficulty.value}")
        print(f"      Stem: {q.stem}")
        if q.options:
            for opt in q.options:
                print(f"        {opt}")
        print(f"      Answer: {q.answer}")
        print(f"      Explanation: {q.explanation[:80]}...")
        print(f"      Source: {q.source_ref}")

    print(f"\n{'─'*60}\n")
