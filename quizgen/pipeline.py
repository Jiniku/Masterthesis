"""End-to-end pipeline orchestration (Phase 5).

Wires the whole generate-then-select architecture into one runnable flow:

    ingest → index → generate pool → deduplicate → assemble → validate → judge

Every stage is reused from its own module; this file only sequences them and
reports.  Run it as a module::

    python -m quizgen.pipeline --chapters 1-3 --blueprint blueprint.yaml --mock

``--mock`` uses the offline :class:`~quizgen.mock_client.MockLLMClient` so the
full pipeline runs with no network; drop it to use the model configured in
``.env`` (GLM-5.2, Ollama, …).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from quizgen.assemble import assemble
from quizgen.blueprint import Blueprint, load_blueprint
from quizgen.dedup import DedupResult, deduplicate
from quizgen.generate import generate_controlled
from quizgen.ingest import Chapter, ingest_textbook
from quizgen.llm_client import LLMClient
from quizgen.schema import Question
from quizgen.validate import ValidationReport, report_to_markdown, validate_exam

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Everything produced by a full pipeline run."""

    pool: list[Question]
    dedup: DedupResult
    exams: list  # list[Quiz]
    reports: list[ValidationReport] = field(default_factory=list)
    used_rag: bool = False


def _source_chunk_map(chapters: list[Chapter]) -> dict[str, str]:
    return {c.chunk_id: c.text for ch in chapters for c in ch.chunks}


def _try_build_index(chapters, index_dir):
    """Best-effort vector index; returns ``None`` if embeddings are unavailable."""
    try:
        from quizgen.index import ChunkIndex

        index = ChunkIndex(persist_dir=index_dir)
        index.build(chapters, force_rebuild=False)
        # Touch the encoder so an offline failure surfaces here, not mid-run.
        _ = index.encoder
        return index
    except Exception as exc:
        logger.warning("Vector index unavailable (%s); generating without RAG.", exc)
        return None


def run_pipeline(
    textbook: str,
    chapters_to_process: list[int],
    blueprint: Blueprint,
    *,
    client: LLMClient | None = None,
    per_chapter_pool: int = 24,
    use_rag: bool = True,
    config_path: str | None = "data/chapter_config.yaml",
    index_dir: str = "data/chroma_db",
    dedup_threshold: float = 0.92,
) -> PipelineResult:
    """Run ingest → index → generate → dedup → assemble → validate."""
    if client is None:
        client = LLMClient()

    # 1. Ingest.
    logger.info("① Ingesting %s, chapters %s", textbook, chapters_to_process)
    chapters = ingest_textbook(textbook, chapter_nums=chapters_to_process, config_path=config_path)

    # 2. Index (best-effort; degrades to non-RAG offline).
    index = _try_build_index(chapters, index_dir) if use_rag else None
    used_rag = index is not None

    # 3. Generate pool (controlled Bloom/difficulty, Phase 3).
    logger.info("③ Generating candidate pool (%d/chapter)...", per_chapter_pool)
    pool = generate_controlled(
        chapters,
        total_per_chapter=per_chapter_pool,
        client=client,
        difficulty_mix=blueprint.difficulty_mix or None,
        index=index,
    )

    # 4. Deduplicate the pool. Reuse the index's encoder when RAG is available;
    #    otherwise use the offline token backend (avoids a failed model load).
    dedup = deduplicate(
        pool,
        threshold=dedup_threshold,
        encoder=index.encoder if used_rag else None,
        use_embeddings=used_rag,
    )

    # 5. Assemble exam version(s).
    result = assemble(dedup.kept, blueprint)
    exams = result.to_quizzes()

    # 6. Validate each version (with grounding via the source chunk map).
    source_map = _source_chunk_map(chapters)
    reports = [
        validate_exam(quiz, blueprint, source_chunks=source_map, duplicate_threshold=dedup_threshold)
        for quiz in exams
    ]

    return PipelineResult(
        pool=dedup.kept, dedup=dedup, exams=exams, reports=reports, used_rag=used_rag,
    )


# ── CLI ─────────────────────────────────────────────────────────────


def main() -> None:
    import argparse
    from pathlib import Path

    from quizgen.__main__ import parse_chapters
    from quizgen.judge import judge_questions, judge_summary

    parser = argparse.ArgumentParser(
        prog="quizgen.pipeline",
        description="Run the full generate-then-select pipeline end to end.",
    )
    parser.add_argument("--textbook", default="data/textbook.pdf")
    parser.add_argument("--chapters", default="1-3")
    parser.add_argument("--blueprint", default="blueprint.yaml")
    parser.add_argument("--pool-per-chapter", type=int, default=24)
    parser.add_argument("--mock", action="store_true", help="Use the offline MockLLMClient")
    parser.add_argument("--no-rag", action="store_true", help="Skip the vector index step")
    parser.add_argument("--judge", action="store_true", help="Run the LLM-as-judge pass")
    parser.add_argument("--out-dir", default="out", help="Directory for exams + reports")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(name)s  %(message)s",
    )

    client = None
    if args.mock:
        from quizgen.mock_client import MockLLMClient

        client = MockLLMClient()

    blueprint = load_blueprint(args.blueprint)
    chapters = parse_chapters(args.chapters)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n🚀 Full pipeline — chapters {chapters}, blueprint '{blueprint.title}'")
    result = run_pipeline(
        args.textbook, chapters, blueprint,
        client=client,
        per_chapter_pool=args.pool_per_chapter,
        use_rag=not args.no_rag,
    )

    print(f"\n   Pool after dedup: {result.dedup.n_kept} kept, "
          f"{result.dedup.n_removed} removed ({result.dedup.method}, "
          f"t={result.dedup.threshold})")
    print(f"   RAG grounding: {'on' if result.used_rag else 'off (offline fallback)'}")
    print(f"   Assembled {len(result.exams)} exam version(s)")

    for i, (quiz, report) in enumerate(zip(result.exams, result.reports), 1):
        exam_path = out_dir / f"exam_v{i}.json"
        report_path = out_dir / f"report_v{i}.md"
        exam_path.write_text(quiz.model_dump_json(indent=2))
        md = report_to_markdown(report, title=f"Validation — {quiz.title}")
        report_path.write_text(md)
        print("\n" + md)
        print(f"   💾 {exam_path}   💾 {report_path}")

        if args.judge:
            judgements = judge_questions(quiz.questions, client=client)
            summary = judge_summary(judgements)
            print(f"   ⚖ Judge: mean {summary['mean_overall']}/5, "
                  f"{summary['flagged']} flagged for review")


if __name__ == "__main__":
    main()
