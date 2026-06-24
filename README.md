# QuizGen — LLM-Powered Exam/Quiz Generator

Master's thesis project — KWARC group, FAU Erlangen-Nürnberg

An LLM-powered system that generates exam questions from textbooks using a **generate-then-select** approach with RAG (Retrieval-Augmented Generation) for improved grounding.

---

## 🚀 Quick Start (macOS)

### 1. **Activate the Virtual Environment**

```bash
cd "/Users/jinikuhayashi/Master thesis/quizgen"
source .venv/bin/activate
```

After activation, your terminal prompt will show `(.venv)`.

### 2. **Run Question Generation**

**Phase 1 — Single-chunk generation (no RAG):**
```bash
python -m quizgen --chapters 2 --per-chunk 2 --out quizzes_ch2.json
```

**Phase 2 — RAG-grounded generation:**
```bash
python -m quizgen --chapters 2 --per-chunk 2 --out quizzes_ch2_rag.json --rag
```

### 3. **View Generated Questions**

The output is saved as a JSON file. Preview the first 5 questions with:
```bash
python -m quizgen --chapters 2 --per-chunk 2 --out quizzes.json --rag --show 5
```

---

## 📋 Requirements

- **Python 3.11+**
- **Virtual environment** (already set up in `.venv/`)
- **Ollama** (for local LLM) or OpenAI-compatible API

---

## 🔧 Installation

The project is already set up with dependencies installed. If you need to reinstall:

```bash
# Activate venv
source .venv/bin/activate

# Install core dependencies
pip install -e .

# Install RAG dependencies (Phase 2+)
pip install -e ".[rag]"

# Install development tools
pip install -e ".[dev]"
```

---

## 🎯 Usage

### **Basic Command Structure**

```bash
python -m quizgen --chapters CHAPTERS --per-chunk N --out OUTPUT.json [OPTIONS]
```

### **Command-Line Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--chapters` | Chapters to process (e.g., `1-3` or `1,2,5`) | **Required** |
| `--per-chunk` | Questions per chunk | `2` |
| `--out` | Output JSON file path | `quizzes.json` |
| `--textbook` | Path to textbook PDF | `data/textbook.pdf` |
| `--config` | Chapter config YAML file | `data/chapter_config.yaml` |
| `--title` | Quiz title | Auto-generated |
| `--show` | Number of questions to preview | `5` |
| `--ingest-only` | Only run ingestion (no LLM calls) | `False` |
| `-v, --verbose` | Enable verbose logging | `False` |

### **RAG Options (Phase 2)**

| Option | Description | Default |
|--------|-------------|---------|
| `--rag` | Enable RAG mode (retrieve top-k chunks) | `False` |
| `--no-rag` | Disable RAG (Phase 1 mode) | `False` |
| `--rag-top-k` | Number of chunks to retrieve | `5` |
| `--no-grounding-check` | Disable grounding validation | `False` |
| `--index-dir` | ChromaDB storage directory | `data/chroma_db` |

---

## 📖 Examples

### **1. Generate Questions from Chapter 2 (No RAG)**

```bash
source .venv/bin/activate
python -m quizgen --chapters 2 --per-chunk 2 --out quizzes_ch2_no_rag.json
```

### **2. Generate RAG-Grounded Questions from Chapter 2**

```bash
source .venv/bin/activate
python -m quizgen --chapters 2 --per-chunk 2 --out quizzes_ch2_rag.json --rag --show 5
```

### **3. Generate Questions from Multiple Chapters**

```bash
source .venv/bin/activate
python -m quizgen --chapters 1-3 --per-chunk 3 --out quizzes_ch1-3.json --rag
```

### **4. Test Ingestion Pipeline Only**

```bash
source .venv/bin/activate
python -m quizgen --chapters 1 --ingest-only
```

### **5. Compare RAG vs Non-RAG Output**

```bash
source .venv/bin/activate

# Phase 1 (single-chunk)
python -m quizgen --chapters 2 --per-chunk 2 --out quizzes_no_rag.json --show 5

# Phase 2 (RAG)
python -m quizgen --chapters 2 --per-chunk 2 --out quizzes_rag.json --rag --show 5
```

---

## 🧪 The Full Pipeline (Phases 3–5)

The complete **generate-then-select** pipeline runs end to end with a single
command:

```
ingest → index → generate pool → deduplicate → assemble → validate → judge
```

```bash
source .venv/bin/activate

# Full pipeline against the configured LLM (.env), driven by a blueprint:
python -m quizgen.pipeline --chapters 1-3 --blueprint blueprint.yaml --judge

# Same thing fully offline (no API / no network), using the deterministic
# MockLLMClient — handy for demos, CI, and air-gapped machines:
python -m quizgen.pipeline --chapters 1-3 --blueprint blueprint.yaml --mock --no-rag
```

Outputs land in `out/`: one `exam_vN.json` plus a `report_vN.md` per version.

### Phase 3 — Bloom & difficulty control

Generate a controlled set with an explicit cognitive-level and difficulty
spread (Bloom-aligned prompting with per-level few-shot examples). The output
is **guaranteed schema-valid JSON** (strict structured-output mode, with a
loose-JSON fallback and an Outlines hook for local constrained decoding —
selected by `STRUCTURED_OUTPUT_MODE` in `.env`):

```bash
# 12 questions for chapter 3 across all Bloom levels, 40/40/20 difficulty,
# printing a Bloom × difficulty distribution table:
python -m quizgen.generate --chapters 3 --controlled --total 12 \
    --difficulty-mix "easy:0.4,medium:0.4,hard:0.2" --out quiz_ch3.json
```

> Schema validity guarantees the *container*, not the *facts* — the Pydantic
> and grounding checks still run on every item.

### Phase 4 — Blueprint & Automated Test Assembly

The professor edits **`blueprint.yaml`** (total questions, per-chapter share as
counts/fractions/percentages, difficulty mix, allowed types, parallel versions,
selector). Generation produces a large tagged *pool*; the **selector** picks the
subset that satisfies the blueprint:

```bash
# 1. Build a pool (reuse Phase 3 controlled generation)
python -m quizgen.generate --chapters 1-3 --controlled --total 30 --out pool.json

# 2. Assemble exam(s) from the pool per the blueprint
python -m quizgen.assemble --blueprint blueprint.yaml --pool pool.json --out exam.json
```

Two interchangeable selectors (set `selector:` in the blueprint, or override
with `--selector`):

| Selector | Method | Guarantees |
|----------|--------|-----------|
| `greedy` | Greedy/random with content balancing | Fast; meets per-chapter counts, balances difficulty |
| `mip` | Mixed-integer programming (PuLP/CBC) | Meets per-chapter **and** difficulty counts exactly, maximises a quality objective, keeps parallel versions disjoint, forbids near-duplicates |

Each version is written as `Quiz` JSON embedding the resolved blueprint and the
per-question chapter/Bloom/difficulty tags and `source_ref`.

### Phase 5 — Validation, deduplication, evaluation

```bash
# Standalone validation report (Markdown + JSON) for an assembled exam:
python -m quizgen.validate --exam exam.json --blueprint blueprint.yaml \
    --out report.md --json-out report.json
```

The report covers **schema validity**, **blueprint compliance** (counts per
chapter, difficulty mix), **grounding coverage** (share traceable to source
text), and **duplicate rate**. Deduplication (`quizgen/dedup.py`) drops
near-duplicate pool questions by embedding cosine similarity (token-Jaccard
fallback offline) and reports how many were removed. The optional
**LLM-as-judge** (`quizgen/judge.py`, enabled with `--judge`) rates each
question on answerability, answer correctness, clarity and Bloom-level match,
flagging weak items for human review — kept as a separate module from
generation.

---

## 🧩 Project Structure

```
quizgen/
├── quizgen/
│   ├── __init__.py
│   ├── __main__.py          # CLI entry point (generation)
│   ├── schema.py            # Pydantic models (Question, Quiz) + batch schema
│   ├── config.py            # Settings loaded from .env
│   ├── llm_client.py        # OpenAI-compatible LLM wrapper (+ structured output)
│   ├── mock_client.py       # Offline deterministic LLM stand-in (demos/CI)
│   ├── ingest.py            # PDF/TeX/MD → chapters → sections → chunks
│   ├── generate.py          # LLM question generation (+ Phase 3 controlled)
│   ├── bloom.py             # Phase 3: Bloom descriptions, few-shot, planners
│   ├── index.py             # RAG vector index (ChromaDB)
│   ├── blueprint.py         # Phase 4: professor blueprint model + loader
│   ├── assemble.py          # Phase 4: ATA selectors (greedy + MIP)
│   ├── similarity.py        # Near-duplicate detection (token / embedding)
│   ├── dedup.py             # Phase 5: pool deduplication
│   ├── validate.py          # Phase 5: validation/quality report
│   ├── judge.py             # Phase 5: LLM-as-judge evaluation
│   ├── textmatch.py         # Dependency-free content-word overlap helper
│   └── pipeline.py          # Phase 5: end-to-end orchestration + CLI
├── data/
│   ├── textbook.pdf         # AI-1 textbook
│   └── chapter_config.yaml  # Chapter parsing config
├── blueprint.yaml           # Example exam blueprint (Phase 4)
├── schemas/
│   ├── question.schema.json # JSON Schema for Question
│   └── quiz.schema.json     # JSON Schema for Quiz
├── tests/
│   ├── fixtures/tiny_textbook.md   # Hermetic e2e fixture
│   ├── test_schema.py              # Phase 0: schema
│   ├── test_ingest.py              # Phase 1: ingestion
│   ├── test_generate_controlled.py # Phase 3: Bloom/difficulty control
│   ├── test_assemble.py            # Phase 4: blueprint + selectors
│   ├── test_dedup.py               # Phase 5: deduplication
│   ├── test_validate.py            # Phase 5: validation report
│   ├── test_judge.py               # Phase 5: LLM-as-judge
│   └── test_pipeline.py            # Phase 5: end-to-end
├── .env.example             # Environment config template
├── pyproject.toml           # Project metadata & dependencies
└── README.md                # This file
```

---

## ⚙️ Configuration

### **1. LLM Provider Setup**

Copy `.env.example` to `.env` and configure your LLM provider:

```bash
cp .env.example .env
```

**Option A: Local Ollama (Default — No API key needed)**
```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:7b
```

Make sure Ollama is running:
```bash
ollama serve
ollama pull qwen2.5:7b
```

**Option B: GLM-5.2 via Z.ai (Zhipu AI)**
```env
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_API_KEY=your-zhipu-api-key-here
LLM_MODEL=glm-4-plus
```

**Option C: OpenAI**
```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-openai-api-key-here
LLM_MODEL=gpt-4
```

### **2. Embedding Model (Phase 2 — RAG)**

```env
EMBEDDING_MODEL=all-MiniLM-L6-v2
```

This model runs locally via `sentence-transformers`. No API needed.

### **3. Generation Defaults**

```env
DEFAULT_PER_CHUNK=2
DEFAULT_TEMPERATURE=0.7

# How schema-valid JSON is enforced (Phase 3):
#   auto        – try strict json_schema, fall back to json_object (default)
#   json_schema – provider-enforced strict structured output (GLM/OpenAI)
#   json_object – loose JSON mode (Pydantic still validates the container)
#   outlines    – local constrained decoding via the Outlines library
STRUCTURED_OUTPUT_MODE=auto
```

### **Switching models — change one config value**

Every model call goes through `LLMClient`, a thin wrapper over the
OpenAI-compatible `/v1/chat/completions` endpoint. **Switching providers is a
`.env` edit, no code changes**: point `LLM_BASE_URL` / `LLM_API_KEY` /
`LLM_MODEL` at GLM-5.2 (Z.ai), a local Ollama model, OpenAI, or any
OpenAI-compatible server (vLLM, etc.) using the blocks above. For offline runs
with no provider at all, pass `--mock` to any CLI to use the deterministic
`MockLLMClient`.

> **Thesis note:** GLM-5.2 is MIT-licensed with open weights and native
> structured output, but full-precision self-hosting needs ~1.5 TB of GPU
> memory (use the hosted API or a quantized GGUF build), and the hosted API
> routes data through China — relevant for data-protection considerations.

---

## 🐛 Troubleshooting (macOS)

### **Error: `command not found: python`**

**Problem:** macOS doesn't have a `python` command by default.

**Solution 1 — Activate the virtual environment:**
```bash
source .venv/bin/activate
python -m quizgen --chapters 2 --per-chunk 2 --out quiz.json
```

**Solution 2 — Use `python3` directly:**
```bash
python3 -m quizgen --chapters 2 --per-chunk 2 --out quiz.json
```

**Solution 3 — One-liner with venv:**
```bash
source .venv/bin/activate && python -m quizgen --chapters 2 --per-chunk 2 --out quiz.json
```

---

### **Error: `externally-managed-environment`**

**Problem:** Trying to install packages system-wide on macOS.

**Solution:** Always use the virtual environment:
```bash
source .venv/bin/activate
pip install chromadb sentence-transformers
```

---

### **Error: `No LLM endpoint configured`**

**Problem:** `.env` file is missing or incomplete.

**Solution:**
```bash
cp .env.example .env
# Edit .env with your LLM credentials
nano .env
```

---

### **Error: `Textbook PDF not found`**

**Problem:** The textbook is not in the expected location.

**Solution:** Specify the path:
```bash
python -m quizgen --textbook /path/to/your/textbook.pdf --chapters 1
```

Or copy the textbook to the default location:
```bash
cp /path/to/your/textbook.pdf data/textbook.pdf
```

---

## 📊 Output Format

Generated quizzes are saved as JSON files conforming to the `Quiz` schema:

```json
{
  "quiz_id": "9a40fb1cdd6f",
  "title": "Quiz — Chapters 2",
  "created_at": "2026-06-24T09:24:07.416734Z",
  "blueprint": {
    "chapters": [2],
    "per_chunk": 2,
    "total_chunks": 11,
    "generation_mode": "RAG",
    "rag_top_k": 5,
    "grounding_check": true
  },
  "questions": [
    {
      "id": "00e820ec6f50",
      "chapter": 2,
      "section": "2.1",
      "qtype": "short_answer",
      "bloom_level": "remember",
      "difficulty": "easy",
      "stem": "What is the first question that we have to ask ourselves according to the passage?",
      "options": null,
      "answer": "What is artificial intelligence?",
      "explanation": "The passage states, 'The first question we have to ask ourselves is \"What is artificial intelligence?\"'",
      "source_ref": "chunk_001"
    }
  ]
}
```

### **Question Types:**
- `mcq` — Multiple Choice (4 options)
- `true_false` — True/False
- `short_answer` — Free-text answer
- `cloze` — Fill-in-the-blank

### **Bloom's Taxonomy Levels:**
- `remember` — Recall facts
- `understand` — Explain concepts
- `apply` — Use knowledge in new situations
- `analyze` — Break down information
- `evaluate` — Make judgments
- `create` — Generate new ideas

### **Difficulty Levels:**
- `easy` — Basic recall/comprehension
- `medium` — Application/analysis
- `hard` — Evaluation/creation

---

## 🧪 Running Tests

```bash
source .venv/bin/activate
pytest
```

**Test coverage (72 tests):**
- `tests/test_schema.py` — Phase 0: Schema validation
- `tests/test_ingest.py` — Phase 1: Ingestion pipeline
- `tests/test_generate_controlled.py` — Phase 3: Bloom/difficulty control
- `tests/test_assemble.py` — Phase 4: Blueprint + selectors
- `tests/test_dedup.py` — Phase 5: Deduplication
- `tests/test_validate.py` — Phase 5: Validation report
- `tests/test_judge.py` — Phase 5: LLM-as-judge
- `tests/test_pipeline.py` — Phase 5: End-to-end (hermetic)

Most tests run fully offline via the `MockLLMClient`; no API key or network is
required.

---

## 🗺️ Development Roadmap

### **Phase 0 — Project Scaffolding** ✅ COMPLETE
- Pydantic v2 schemas (Question, Quiz)
- JSON Schema export
- Swappable LLM client
- Schema round-trip tests

### **Phase 1 — Ingest & Generate** ✅ COMPLETE
- PDF/TeX/Markdown ingestion
- Chapter/section/chunk parsing
- LLM-based question generation
- CLI with summary stats

### **Phase 2 — RAG Grounding** ✅ COMPLETE
- Vector index (ChromaDB)
- Local embeddings (sentence-transformers)
- RAG retrieval (top-k chunks)
- Grounding validation
- `--rag` and `--no-rag` flags

### **Phase 3 — Difficulty + Bloom Control** ✅ COMPLETE
- Bloom-aligned prompting (per-level few-shot examples)
- Difficulty spread control (e.g. 40% easy / 40% medium / 20% hard)
- Guaranteed-valid JSON (strict structured output + Outlines hook)
- Controlled generation CLI + Bloom × difficulty distribution table

### **Phase 4 — Automated Test Assembly** ✅ COMPLETE
- Blueprint YAML config (counts / fractions / percentages)
- Greedy/random selector with content balancing
- Mixed-integer programming optimizer (PuLP/CBC)
- Parallel, disjoint exam version generation

### **Phase 5 — Validation & Evaluation** ✅ COMPLETE
- Deduplication (embedding / token similarity) with removal report
- Validation report (schema, blueprint compliance, grounding, duplicates)
- LLM-as-judge quality evaluation (separate module)
- End-to-end pipeline + hermetic e2e test

---

## 📝 License

MIT License

---

## 🙋 Support

For issues or questions:
1. Check the **Troubleshooting** section above
2. Review `.env.example` for configuration
3. Run with `--verbose` for detailed logs:
   ```bash
   python -m quizgen --chapters 2 --per-chunk 2 --out quiz.json --rag --verbose
   ```

---

## 📚 Thesis Context

This project implements a **generate-then-select** approach for automated exam generation:

1. **Ingest** the textbook → split into chapters/sections/chunks
2. **Generate** a large pool of candidate questions (RAG-grounded, Bloom-tagged, difficulty-tagged)
3. **Select** a subset that matches the professor's blueprint (Automated Test Assembly)
4. **Validate** the final exam against schema and quality filters

This separation of generation and selection provides better control, reproducibility, and citability compared to monolithic LLM prompting.

---

**Last Updated:** June 24, 2026
**Author:** Jinikuhayashi
**Advisor:** Prof. Michael Kohlhase (KWARC, FAU Erlangen-Nürnberg)
