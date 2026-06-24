#!/usr/bin/env python3
"""Build quizgen_slides.pptx — a 'how it works' deck for the quizgen project.

Run:  python build_slides.py  (writes docs/quizgen_slides.pptx)
"""
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.dml.color import RGBColor

# ── palette ───────────────────────────────────────────────────────────
NAVY   = RGBColor(0x1F, 0x2D, 0x3D)
BLUE   = RGBColor(0x31, 0x82, 0xBD)
BLUEL  = RGBColor(0xDE, 0xEB, 0xF7)
GREEN  = RGBColor(0x31, 0xA3, 0x54)
GREENL = RGBColor(0xE5, 0xF5, 0xE0)
RED    = RGBColor(0xDE, 0x2D, 0x26)
REDL   = RGBColor(0xFD, 0xE0, 0xDD)
GREY   = RGBColor(0x63, 0x63, 0x63)
GREYL  = RGBColor(0xF0, 0xF0, 0xF2)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
DARK   = RGBColor(0x33, 0x33, 0x33)

FONT = "Calibri"
MONO = "Consolas"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
SW, SH = prs.slide_width, prs.slide_height
BLANK = prs.slide_layouts[6]


# ── helpers ───────────────────────────────────────────────────────────
def slide():
    return prs.slides.add_slide(BLANK)


def _set(frame, size, color, bold=False, align=PP_ALIGN.LEFT, font=FONT, italic=False):
    for p in frame.paragraphs:
        p.alignment = align
        for r in p.runs:
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.italic = italic
            r.font.name = font
            r.font.color.rgb = color


def textbox(s, x, y, w, h, text, size=18, color=DARK, bold=False,
            align=PP_ALIGN.LEFT, font=FONT, italic=False, anchor=MSO_ANCHOR.TOP):
    tb = s.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.text = text
    _set(tf, size, color, bold, align, font, italic)
    return tb


def box(s, x, y, w, h, text, fill, line, txtcolor=DARK, size=14, bold=True,
        shape=MSO_SHAPE.ROUNDED_RECTANGLE, font=FONT, line_w=1.25):
    sp = s.shapes.add_shape(shape, x, y, w, h)
    sp.fill.solid(); sp.fill.fore_color.rgb = fill
    sp.line.color.rgb = line; sp.line.width = Pt(line_w)
    sp.shadow.inherit = False
    tf = sp.text_frame; tf.word_wrap = True
    tf.margin_left = Inches(0.05); tf.margin_right = Inches(0.05)
    tf.margin_top = Inches(0.03); tf.margin_bottom = Inches(0.03)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.text = text
    _set(tf, size, txtcolor, bold, PP_ALIGN.CENTER, font)
    return sp


def arrow(s, x1, y1, x2, y2, color=GREY, w=2.0, dash=False):
    cn = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x1, y1, x2, y2)
    cn.line.color.rgb = color; cn.line.width = Pt(w)
    le = cn.line._get_or_add_ln()
    from pptx.oxml.ns import qn
    tail = le.makeelement(qn('a:tailEnd'),
                          {'type': 'triangle', 'w': 'med', 'len': 'med'})
    le.append(tail)
    if dash:
        d = le.makeelement(qn('a:prstDash'), {'val': 'dash'})
        le.insert(0, d)
    return cn


def header(s, title, kicker=None):
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, Inches(1.15))
    bar.fill.solid(); bar.fill.fore_color.rgb = NAVY; bar.line.fill.background()
    bar.shadow.inherit = False
    textbox(s, Inches(0.55), Inches(0.18), Inches(12.2), Inches(0.8),
            title, size=30, color=WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    if kicker:
        textbox(s, Inches(0.58), Inches(0.02), Inches(12), Inches(0.3),
                kicker, size=12, color=BLUEL, bold=True)


def bullets(s, x, y, w, h, items, size=18, gap=6):
    tb = s.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame; tf.word_wrap = True
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        lvl = 0
        if isinstance(it, tuple):
            it, lvl = it
        p.level = lvl
        run = p.add_run(); run.text = ("• " if lvl == 0 else "– ") + it
        run.font.size = Pt(size - lvl * 2)
        run.font.name = FONT
        run.font.color.rgb = DARK if lvl == 0 else GREY
        p.space_after = Pt(gap)
    return tb


def chip(s, x, y, w, text, fill, line, txt=DARK, size=11):
    return box(s, x, y, w, Inches(0.42), text, fill, line, txt, size=size,
               shape=MSO_SHAPE.ROUNDED_RECTANGLE)


# ══════════════════════════════════════════════════════════════════════
# 1 — TITLE
# ══════════════════════════════════════════════════════════════════════
s = slide()
bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH)
bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background()
bg.shadow.inherit = False
band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(4.7), SW, Inches(0.12))
band.fill.solid(); band.fill.fore_color.rgb = BLUE; band.line.fill.background()
band.shadow.inherit = False
textbox(s, Inches(0.8), Inches(2.0), Inches(11.7), Inches(1.2),
        "quizgen", size=66, color=WHITE, bold=True)
textbox(s, Inches(0.85), Inches(3.25), Inches(11.7), Inches(1.3),
        "Automated exam & quiz generation from a textbook\n"
        "A generate-then-select pipeline", size=26, color=BLUEL)
textbox(s, Inches(0.85), Inches(5.0), Inches(11.7), Inches(1.4),
        "RAG grounding   •   Bloom-controlled generation   •   "
        "Automated Test Assembly (MIP)\nMaster's Thesis — KWARC Group, FAU "
        "Erlangen-Nürnberg", size=16, color=WHITE)

# ══════════════════════════════════════════════════════════════════════
# 2 — THE IDEA
# ══════════════════════════════════════════════════════════════════════
s = slide()
header(s, "The core idea: generate, then select", "WHY THIS ARCHITECTURE")
textbox(s, Inches(0.55), Inches(1.35), Inches(12.2), Inches(0.7),
        "Don't ask one prompt to write \"the exam\". Split the job into two "
        "stages with very different failure modes.", size=18, italic=True, color=GREY)

box(s, Inches(0.7), Inches(2.3), Inches(5.5), Inches(1.0),
    "GENERATE  →  over-produce a large, tagged, source-grounded POOL of candidates",
    BLUEL, BLUE, DARK, size=15)
box(s, Inches(7.1), Inches(2.3), Inches(5.5), Inches(1.0),
    "SELECT  →  pick the optimal subset matching the professor's BLUEPRINT",
    GREENL, GREEN, DARK, size=15)
arrow(s, Inches(6.2), Inches(2.8), Inches(7.1), Inches(2.8), GREY, 2.5)

bullets(s, Inches(0.7), Inches(3.7), Inches(12), Inches(3.2), [
    "Creative & stochastic generation is decoupled from exact constraint satisfaction.",
    "Auditability — every question traces to a source chunk; every exam traces to a blueprint.",
    "Exact constraints — selection is solved with a Mixed-Integer Program, not coaxed from a prompt.",
    "Reusability — one pool yields many exams and parallel versions.",
    "Separable evaluation — grounding, dedup, schema validation & LLM-judge act on finished artifacts.",
], size=18, gap=10)

# ══════════════════════════════════════════════════════════════════════
# 3 — ARCHITECTURE / PIPELINE DIAGRAM
# ══════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Architecture: the pipeline at a glance", "FIVE STAGES, ONE FLOW")

stages = [
    ("1\nIngest", BLUEL, BLUE),
    ("2\nIndex\n(RAG)", BLUEL, BLUE),
    ("3\nGenerate\npool", BLUEL, BLUE),
    ("4a\nDedup", BLUEL, BLUE),
    ("4b\nAssemble\n(MIP)", BLUEL, BLUE),
    ("5\nValidate", BLUEL, BLUE),
    ("5\nJudge", BLUEL, BLUE),
]
n = len(stages)
bw, bh = Inches(1.5), Inches(1.15)
gap = Inches(0.22)
total = bw * n + gap * (n - 1)
x0 = (SW - total) // 2
y0 = Inches(2.7)
centers = []
for i, (label, fill, line) in enumerate(stages):
    x = x0 + i * (bw + gap)
    box(s, x, y0, bw, bh, label, fill, line, DARK, size=13)
    centers.append((x, x + bw))
    if i < n - 1:
        arrow(s, x + bw, y0 + bh // 2, x + bw + gap, y0 + bh // 2, GREY, 1.8)

# data artifacts above
box(s, centers[0][0], Inches(1.55), bw, Inches(0.6), "textbook.pdf",
    GREENL, GREEN, DARK, size=11, shape=MSO_SHAPE.RECTANGLE)
arrow(s, centers[0][0] + bw // 2, Inches(2.15), centers[0][0] + bw // 2, y0, GREEN, 1.6)
box(s, centers[2][0], Inches(1.55), bw, Inches(0.6), "tagged pool",
    GREENL, GREEN, DARK, size=11, shape=MSO_SHAPE.RECTANGLE)
arrow(s, centers[2][0] + bw // 2, y0, centers[2][0] + bw // 2, Inches(2.15), GREEN, 1.6, dash=True)
# blueprint feeds assemble (red)
box(s, centers[4][0], Inches(1.55), bw, Inches(0.6), "blueprint.yaml",
    REDL, RED, DARK, size=11, shape=MSO_SHAPE.RECTANGLE)
arrow(s, centers[4][0] + bw // 2, Inches(2.15), centers[4][0] + bw // 2, y0, RED, 1.6)
# exams out
box(s, centers[5][0], Inches(4.2), bw, Inches(0.6), "exam versions\n+ reports",
    GREENL, GREEN, DARK, size=10, shape=MSO_SHAPE.RECTANGLE)
arrow(s, centers[5][0] + bw // 2, y0 + bh, centers[5][0] + bw // 2, Inches(4.2), GREEN, 1.6)

# legend
chip(s, Inches(0.7), Inches(5.6), Inches(2.0), "processing stage", BLUEL, BLUE)
chip(s, Inches(2.9), Inches(5.6), Inches(2.0), "data artifact", GREENL, GREEN)
chip(s, Inches(5.1), Inches(5.6), Inches(2.4), "professor input", REDL, RED)
textbox(s, Inches(0.7), Inches(6.2), Inches(12), Inches(1.0),
        "Stages 1–3 PRODUCE candidate questions (grounded in retrieved text). "
        "Stages 4–5 SELECT and VERIFY them. Each stage = one module in the "
        "quizgen package.", size=15, color=GREY, italic=True)

# ══════════════════════════════════════════════════════════════════════
# 4 — DATA MODEL
# ══════════════════════════════════════════════════════════════════════
s = slide()
header(s, "The data contract: one schema, exported not written", "schema.py — Pydantic v2")
bullets(s, Inches(0.7), Inches(1.45), Inches(5.7), Inches(5), [
    "Every artifact is a Pydantic v2 model — the single source of truth.",
    "JSON Schema is EXPORTED from the models, so they can never drift.",
    "Three enums reused everywhere: a tag can't be a free-text typo.",
    ("qtype: mcq | true_false | short_answer | cloze", 1),
    ("bloom_level: remember … create (revised Bloom)", 1),
    ("difficulty: easy | medium | hard", 1),
    "source_ref links each question to the chunk(s) it was grounded in — the audit trail.",
], size=17, gap=8)

code = (
    "class Question(BaseModel):\n"
    "    id: str            # uuid4 hex[:12]\n"
    "    chapter: int\n"
    "    section: str | None\n"
    "    qtype: QuestionType\n"
    "    bloom_level: BloomLevel\n"
    "    difficulty: Difficulty\n"
    "    stem: str          # >= 10 chars\n"
    "    options: list[str] | None\n"
    "    answer: str\n"
    "    explanation: str   # >= 10 chars\n"
    "    source_ref: str    # grounding"
)
cb = box(s, Inches(6.7), Inches(1.45), Inches(6.0), Inches(4.0), code,
         GREYL, GREY, DARK, size=14, bold=False, shape=MSO_SHAPE.RECTANGLE, font=MONO)
cb.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT
for p in cb.text_frame.paragraphs:
    p.alignment = PP_ALIGN.LEFT

# ══════════════════════════════════════════════════════════════════════
# 5 — STAGE 1 & 2
# ══════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Stages 1–2: ingest & ground", "ingest.py  •  index.py")
textbox(s, Inches(0.7), Inches(1.3), Inches(6), Inches(0.4),
        "① INGEST", size=18, color=BLUE, bold=True)
bullets(s, Inches(0.7), Inches(1.75), Inches(5.8), Inches(3), [
    "PyMuPDF extracts text; the PDF table of contents gives chapter/section structure.",
    "Sections split into overlapping ~500–800 token chunks with provenance metadata.",
    "Offline fallback: a word-tokenizer shim replaces tiktoken when its vocab can't download.",
], size=16, gap=8)
textbox(s, Inches(7.0), Inches(1.3), Inches(6), Inches(0.4),
        "② INDEX (RAG)", size=18, color=BLUE, bold=True)
bullets(s, Inches(7.0), Inches(1.75), Inches(5.7), Inches(3.2), [
    "Chunks embedded with sentence-transformers (all-MiniLM-L6-v2) into a local ChromaDB.",
    "Top-k retrieval (filterable by chapter) supplies grounding CONTEXT to the generator.",
    "= Retrieval-Augmented Generation: model writes only about retrieved text.",
    "A word-overlap heuristic flags answers that don't match their context.",
], size=16, gap=8)
box(s, Inches(0.7), Inches(5.3), Inches(12), Inches(1.1),
    "Why it matters:  grounding makes source_ref meaningful, keeps questions factual & "
    "on-topic, and gives the whole pipeline a traceable audit trail.",
    GREENL, GREEN, DARK, size=16, bold=False, shape=MSO_SHAPE.ROUNDED_RECTANGLE)

# ══════════════════════════════════════════════════════════════════════
# 6 — STAGE 3 CONTROLLED GENERATION
# ══════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Stage 3: controlled, grounded generation", "bloom.py • generate.py • llm_client.py")
# three columns
col_y = Inches(1.5)
box(s, Inches(0.6), col_y, Inches(3.9), Inches(0.55), "WHAT to ask  (bloom.py)",
    BLUE, BLUE, WHITE, size=14)
bullets(s, Inches(0.65), Inches(2.15), Inches(3.9), Inches(3.4), [
    "Single source of truth for prompt-craft.",
    "Per-level Bloom + difficulty descriptions.",
    "One few-shot example per Bloom level.",
    "build_balanced_plan → ordered QuestionSpecs.",
    "Largest-remainder makes counts EXACT.",
], size=14, gap=6)

box(s, Inches(4.7), col_y, Inches(3.9), Inches(0.55), "HOW to ask  (generate.py)",
    BLUE, BLUE, WHITE, size=14)
bullets(s, Inches(4.75), Inches(2.15), Inches(3.9), Inches(3.4), [
    "Batched by Bloom level per LLM call.",
    "Explicit numbered #SPEC directives.",
    "Tag COERCION: returned questions are re-tagged to the requested level.",
    "→ pool distribution matches the plan by construction.",
], size=14, gap=6)

box(s, Inches(8.8), col_y, Inches(3.9), Inches(0.55), "VALID JSON  (llm_client)",
    BLUE, BLUE, WHITE, size=14)
bullets(s, Inches(8.85), Inches(2.15), Inches(3.9), Inches(3.4), [
    "Swappable OpenAI-compatible client (GLM / Ollama / vLLM / OpenAI).",
    "chat_schema: strict json_schema → json_object → outlines.",
    "Pydantic re-validates every item.",
    "Shape guaranteed, never facts.",
], size=14, gap=6)

box(s, Inches(0.6), Inches(5.75), Inches(12.1), Inches(0.9),
    "#SPEC 1 | bloom=apply | difficulty=medium | qtype=mcq        "
    "#SPEC 2 | bloom=apply | difficulty=hard | qtype=short_answer",
    GREYL, GREY, DARK, size=13, bold=False, font=MONO, shape=MSO_SHAPE.RECTANGLE)

# ══════════════════════════════════════════════════════════════════════
# 7 — STAGE 4 BLUEPRINT + ATA + MIP
# ══════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Stage 4: blueprint → Automated Test Assembly", "blueprint.py • assemble.py")
bp = (
    "total_questions: 20\n"
    "chapters: {1: 50%, 2: 30%, 3: 20%}\n"
    "difficulty_mix: {easy:.4, medium:.4, hard:.2}\n"
    "versions: 2\n"
    "selector: mip\n"
    "dedup_similarity: 0.85"
)
box(s, Inches(0.6), Inches(1.45), Inches(4.6), Inches(2.5), bp,
    REDL, RED, DARK, size=14, bold=False, font=MONO, shape=MSO_SHAPE.RECTANGLE)
textbox(s, Inches(0.6), Inches(4.05), Inches(4.7), Inches(2.6),
        "The professor edits one small YAML.\nCounts may be ints, fractions or "
        "\"NN%\"; resolve() turns them into exact integer counts (largest-remainder).",
        size=14, color=GREY, italic=True)

textbox(s, Inches(5.5), Inches(1.4), Inches(7.2), Inches(0.5),
        "Selection = optimisation.  0–1 Mixed-Integer Program (PuLP/CBC):",
        size=15, color=DARK, bold=True)
mip = (
    "maximise   Σ  q_i · x_iv            (total quality)\n"
    "s.t.   Σ_{chap(i)=c}  x_iv  =  n_c    (exact per-chapter)\n"
    "       Σ_{diff(i)=d}  x_iv  =  m_d    (exact difficulty)\n"
    "       Σ_v  x_iv  ≤  1               (versions disjoint)\n"
    "       Σ_v x_iv + Σ_v x_jv ≤ 1       (forbid dup pairs)\n"
    "       x_iv ∈ {0, 1}"
)
box(s, Inches(5.5), Inches(2.0), Inches(7.2), Inches(2.5), mip,
    GREYL, GREY, DARK, size=14, bold=False, font=MONO, shape=MSO_SHAPE.RECTANGLE)
bullets(s, Inches(5.5), Inches(4.7), Inches(7.3), Inches(2.4), [
    "One solve produces all parallel versions, disjoint & individually compliant.",
    "Infeasible? difficulty equalities relax (logged); per-chapter counts never violated.",
    "GreedySelector = fast baseline behind the same interface (config switch).",
], size=14, gap=6)

# ══════════════════════════════════════════════════════════════════════
# 8 — DEDUP
# ══════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Deduplication: keep versions distinct", "similarity.py • dedup.py")
bullets(s, Inches(0.7), Inches(1.5), Inches(6.0), Inches(4), [
    "Near-duplicates waste blueprint slots and make versions predictable.",
    "One API, two backends:",
    ("Token-Jaccard over stem+answer(+options) — always available, offline.", 1),
    ("Embedding cosine via the RAG encoder — catches paraphrases.", 1),
    "Dedup drops the later of each pair BEFORE assembly…",
    "…and the MIP additionally forbids any surviving dup pair across versions.",
    "Degrades gracefully: no encoder ⇒ token backend automatically.",
], size=16, gap=8)
box(s, Inches(7.1), Inches(1.7), Inches(5.5), Inches(1.3),
    "sim(q₁,q₂) = |T(q₁) ∩ T(q₂)|\n               ────────────────\n"
    "               |T(q₁) ∪ T(q₂)|",
    GREYL, GREY, DARK, size=15, bold=False, font=MONO, shape=MSO_SHAPE.RECTANGLE)
box(s, Inches(7.1), Inches(3.3), Inches(5.5), Inches(2.4),
    "Two layers of protection:\n\n1.  remove dups from the POOL (dedup.py)\n"
    "2.  forbid dup PAIRS across versions (MIP constraint)",
    GREENL, GREEN, DARK, size=15, bold=False, shape=MSO_SHAPE.ROUNDED_RECTANGLE)

# ══════════════════════════════════════════════════════════════════════
# 9 — STAGE 5 VALIDATION + JUDGE
# ══════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Stage 5: validate & (optionally) judge", "validate.py • judge.py")
textbox(s, Inches(0.7), Inches(1.3), Inches(12), Inches(0.4),
        "Four-dimension validation report (the overall gate = PASS/FAIL):",
        size=17, bold=True, color=DARK)
quad = [
    ("Schema validity", "every question round-trips through the Question model", BLUEL, BLUE),
    ("Blueprint compliance", "per-chapter, difficulty, total & qtypes match EXACTLY", GREENL, GREEN),
    ("Grounding coverage", "share traceable to source; answer words overlap passage", BLUEL, BLUE),
    ("Duplicate rate", "share of questions involved in a near-duplicate pair", GREENL, GREEN),
]
for i, (t, d, f, l) in enumerate(quad):
    x = Inches(0.7) + (i % 2) * Inches(6.2)
    y = Inches(1.85) + (i // 2) * Inches(1.45)
    sp = box(s, x, y, Inches(5.9), Inches(1.25), "", f, l, DARK,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    tf = sp.text_frame; tf.word_wrap = True
    tf.paragraphs[0].text = t
    _set(tf, 16, DARK, True, PP_ALIGN.CENTER)
    p = tf.add_paragraph(); p.text = d; p.alignment = PP_ALIGN.CENTER
    for r in p.runs:
        r.font.size = Pt(12); r.font.name = FONT; r.font.color.rgb = GREY
box(s, Inches(0.7), Inches(5.0), Inches(12.0), Inches(1.6),
    "LLM-as-JUDGE (opt-in):  a SEPARATE model call rates each finished question 1–5 on "
    "answerability, correctness, clarity & Bloom-match, and flags weak items for human "
    "review. It only reads questions — never rewrites them — so generate & judge stay "
    "cleanly separable.",
    REDL, RED, DARK, size=15, bold=False, shape=MSO_SHAPE.ROUNDED_RECTANGLE)

# ══════════════════════════════════════════════════════════════════════
# 10 — OFFLINE / ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Orchestration & fully-offline operation", "pipeline.py • mock_client.py")
bullets(s, Inches(0.7), Inches(1.5), Inches(12), Inches(2.6), [
    "pipeline.py sequences every stage; each stage is imported from its own module.",
    "MockLLMClient parses #SPEC/#JUDGE directives and synthesises deterministic, "
    "schema-valid output — no network needed (--mock).",
    "Index build is best-effort: no embeddings ⇒ generate without RAG, dedup/validate "
    "fall back to token backend.",
    "Swapping the real LLM provider is a one-line .env change.",
], size=17, gap=10)
box(s, Inches(0.7), Inches(4.7), Inches(12.0), Inches(1.0),
    "python -m quizgen.pipeline --chapters 1-3 --blueprint blueprint.yaml --mock --judge",
    NAVY, NAVY, WHITE, size=16, bold=False, font=MONO, shape=MSO_SHAPE.RECTANGLE)
textbox(s, Inches(0.7), Inches(5.9), Inches(12), Inches(0.8),
        "ingest → index → generate → dedup → assemble → validate → judge", size=18,
        color=BLUE, bold=True, align=PP_ALIGN.CENTER)

# ══════════════════════════════════════════════════════════════════════
# 11 — SOURCE ATTRIBUTION
# ══════════════════════════════════════════════════════════════════════
s = slide()
header(s, "Where each technique comes from", "TECHNIQUE → SOURCE LINEAGE")
rows = [
    ("Generate-then-select pipeline", "over-generate & select pattern (NLG / QG)"),
    ("RAG grounding (index.py)", "Lewis et al. 2020 — retrieval-augmented generation"),
    ("Bloom levels + aligned prompting", "Anderson & Krathwohl 2001 (revised Bloom)"),
    ("Structured / constrained decoding", "JSON-Schema decoding; Outlines (Willard & Louf 2023)"),
    ("Test assembly as 0–1 MIP", "van der Linden 2005 — optimal test design"),
    ("Semantic dedup (embeddings)", "Sentence-BERT (Reimers & Gurevych 2019)"),
    ("LLM-as-judge (judge.py)", "Zheng et al. 2023 — judging LLM-as-a-judge"),
    ("Test blueprint", "classical table-of-specifications assessment design"),
]
ty = Inches(1.45)
rh = Inches(0.52)
box(s, Inches(0.7), ty, Inches(5.4), rh, "Implemented in code", BLUE, BLUE, WHITE, size=14)
box(s, Inches(6.2), ty, Inches(6.5), rh, "Source lineage", BLUE, BLUE, WHITE, size=14)
for i, (a, b) in enumerate(rows):
    y = ty + rh * (i + 1)
    f = WHITE if i % 2 else GREYL
    box(s, Inches(0.7), y, Inches(5.4), rh, a, f, GREY, DARK, size=12, bold=False,
        shape=MSO_SHAPE.RECTANGLE)
    box(s, Inches(6.2), y, Inches(6.5), rh, b, f, GREY, DARK, size=12, bold=False,
        shape=MSO_SHAPE.RECTANGLE)
textbox(s, Inches(0.7), Inches(6.95), Inches(12.4), Inches(0.5),
        "Note: the cited papers are not in the repo — replace these keys with the "
        "thesis's exact bibliography. Engineering (apportionment, greedy baseline, "
        "mock client) is project-specific.", size=11, color=RED, italic=True)

# ══════════════════════════════════════════════════════════════════════
# 12 — TAKEAWAYS
# ══════════════════════════════════════════════════════════════════════
s = slide()
bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH)
bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background()
bg.shadow.inherit = False
textbox(s, Inches(0.8), Inches(0.7), Inches(12), Inches(0.9),
        "Takeaways", size=40, color=WHITE, bold=True)
band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.85), Inches(1.65),
                          Inches(3.2), Inches(0.08))
band.fill.solid(); band.fill.fore_color.rgb = BLUE; band.line.fill.background()
band.shadow.inherit = False
items = [
    "Separate GENERATION from SELECTION — creativity vs. exact constraints.",
    "RAG keeps questions grounded & traceable (source_ref).",
    "Bloom-aligned prompting + tag coercion = exact pedagogical control.",
    "A 0–1 MIP gives exact, auditable, multi-version assembly.",
    "Layered checks: schema, blueprint, grounding, dedup, LLM-judge.",
    "Runs fully offline; swap the LLM provider with one .env line.",
]
tb = s.shapes.add_textbox(Inches(0.9), Inches(2.1), Inches(11.6), Inches(4.8))
tf = tb.text_frame; tf.word_wrap = True
for i, it in enumerate(items):
    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
    r = p.add_run(); r.text = "→  " + it
    r.font.size = Pt(22); r.font.name = FONT; r.font.color.rgb = WHITE
    p.space_after = Pt(16)

out = "docs/quizgen_slides.pptx"
prs.save(out)
print("saved", out, "with", len(prs.slides._sldIdLst), "slides")
