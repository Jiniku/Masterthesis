"""CLI entry point — ``python -m quizgen.generate``.

Usage examples::

    # Generate 2 questions per chunk for chapters 1–3
    python -m quizgen.generate --chapters 1-3 --per-chunk 2 --out quizzes_ch1-3.json

    # Single chapter, more questions
    python -m quizgen.generate --chapters 3 --per-chunk 4 --out quiz_ch3.json

    # Custom textbook path and config
    python -m quizgen.generate --textbook data/other.pdf --config data/chapter_config.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from quizgen.generate import (
    generate_questions,
    print_questions,
    print_summary,
    questions_to_quiz,
)
from quizgen.ingest import ingest_textbook


def parse_chapters(spec: str) -> list[int]:
    """Parse a chapter specification like '1-3' or '1,2,5' into a list of ints."""
    chapters: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            chapters.extend(range(int(start), int(end) + 1))
        else:
            chapters.append(int(part))
    return sorted(set(chapters))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="quizgen.generate",
        description="Generate exam/quiz questions from a textbook using an LLM.",
    )
    parser.add_argument(
        "--textbook",
        default="data/textbook.pdf",
        help="Path to the textbook file (default: data/textbook.pdf)",
    )
    parser.add_argument(
        "--chapters",
        required=True,
        help="Chapters to process, e.g. '1-3' or '1,2,5'",
    )
    parser.add_argument(
        "--per-chunk",
        type=int,
        default=2,
        help="Number of questions to generate per chunk (default: 2)",
    )
    parser.add_argument(
        "--out",
        default="quizzes.json",
        help="Output JSON file path (default: quizzes.json)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to chapter_config.yaml (optional)",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Title for the generated quiz",
    )
    parser.add_argument(
        "--show",
        type=int,
        default=5,
        help="Number of questions to preview (default: 5)",
    )
    parser.add_argument(
        "--ingest-only",
        action="store_true",
        help="Only run ingestion (no LLM calls) — useful for testing chunking",
    )
    parser.add_argument(
        "--rag",
        action="store_true",
        help="Use RAG mode (Phase 2): retrieve top-k chunks for grounding",
    )
    parser.add_argument(
        "--no-rag",
        action="store_true",
        help="Disable RAG mode (Phase 1): generate from single chunks",
    )
    parser.add_argument(
        "--rag-top-k",
        type=int,
        default=5,
        help="Number of chunks to retrieve for RAG grounding (default: 5)",
    )
    parser.add_argument(
        "--no-grounding-check",
        action="store_true",
        help="Disable grounding checks in RAG mode",
    )
    parser.add_argument(
        "--index-dir",
        default="data/chroma_db",
        help="Directory for ChromaDB vector index (default: data/chroma_db)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(name)s  %(message)s",
    )

    chapter_nums = parse_chapters(args.chapters)
    print(f"\n📚 Processing chapters: {chapter_nums}")
    print(f"   Textbook: {args.textbook}")

    # ── Step 1: Ingest ──────────────────────────────────────────────
    print("\n⏳ Ingesting textbook...")
    chapters = ingest_textbook(
        args.textbook,
        chapter_nums=chapter_nums,
        config_path=args.config or "data/chapter_config.yaml",
    )

    total_chunks = sum(ch.total_chunks for ch in chapters)
    print(f"   ✓ {len(chapters)} chapter(s), {total_chunks} chunk(s)")

    for ch in chapters:
        print(f"     Ch {ch.number}: {ch.title[:50]} — {len(ch.sections)} sections, {ch.total_chunks} chunks")

    if args.ingest_only:
        print("\n✅ Ingestion complete (--ingest-only). No LLM calls made.")
        # Print some sample chunks for review
        for ch in chapters:
            if ch.chunks:
                c = ch.chunks[0]
                print(f"\n  Sample chunk from Ch {ch.number}:")
                print(f"    ID: {c.chunk_id}")
                print(f"    Tokens: {c.token_count}")
                print(f"    Text: {c.text[:200]}...")
        return

    # ── Step 2: Determine generation mode ──────────────────────────
    use_rag = args.rag and not args.no_rag  # --rag overrides, --no-rag disables

    if use_rag:
        print(f"\n🔍 RAG MODE — Building vector index from {total_chunks} chunks...")
        from quizgen.index import ChunkIndex

        index = ChunkIndex(persist_dir=args.index_dir)
        indexed_count = index.build(chapters, force_rebuild=False)
        print(f"   ✓ Vector index ready: {indexed_count} chunks indexed")

        print(f"\n⏳ Generating questions with RAG (top-{args.rag_top_k} retrieval)...")
        questions = generate_questions(
            chapters,
            per_chunk=args.per_chunk,
            use_rag=True,
            index=index,
            rag_top_k=args.rag_top_k,
            check_grounding=not args.no_grounding_check,
        )
    else:
        print(f"\n⏳ Generating {args.per_chunk} question(s) per chunk ({total_chunks} chunks)...")
        print(f"   Expected: ~{total_chunks * args.per_chunk} questions")
        print("   Mode: Phase 1 (single-chunk generation)")

        questions = generate_questions(chapters, per_chunk=args.per_chunk, use_rag=False)

    if not questions:
        print("\n❌ No valid questions generated. Check your LLM endpoint in .env")
        sys.exit(1)

    # ── Step 3: Output ──────────────────────────────────────────────
    title = args.title or f"Quiz — Chapters {args.chapters}"
    blueprint = {
        "chapters": chapter_nums,
        "per_chunk": args.per_chunk,
        "total_chunks": total_chunks,
        "generation_mode": "RAG" if use_rag else "single-chunk",
        "rag_top_k": args.rag_top_k if use_rag else None,
        "grounding_check": not args.no_grounding_check if use_rag else None,
    }
    quiz = questions_to_quiz(questions, title=title, blueprint=blueprint)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(quiz.model_dump_json(indent=2))
    print(f"\n💾 Saved {len(questions)} questions to {out_path}")

    # ── Step 4: Summary ─────────────────────────────────────────────
    print_questions(questions, n=args.show)
    print_summary(questions)


if __name__ == "__main__":
    main()
