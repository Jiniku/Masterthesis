# quizgen — Automated Test Assembly from a Question Bank

Master's thesis project — KWARC group, FAU Erlangen-Nürnberg

`quizgen` takes an existing **question bank** (a JSON list of questions with
metadata) and **selects** a blueprint-compliant exam from it — the right number
of questions per chapter, the target difficulty mix, allowed question types, and
one or more **parallel, non-overlapping versions**. Selection is solved exactly
with **Automated Test Assembly** (a greedy selector or a Mixed-Integer Program),
not coaxed from a prompt.

> There is **no LLM and no PDF ingestion** here. You bring the questions;
> quizgen picks the exam. Constraints come from a blueprint YAML and/or
> command-line flags (**flags override the YAML**).

---

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # core: pydantic, pyyaml, pulp
pip install -e ".[dev]"     # + pytest, ruff   (for tests)
pip install -e ".[embeddings]"   # optional: semantic dedup (sentence-transformers)
```

Requires Python 3.11+.

---

## Quick start

```bash
# Pick 20 questions from the example bank using the example blueprint,
# de-duplicate first, and write a validation report per version:
python -m quizgen --pool questions.example.json --blueprint blueprint.yaml \
    --dedup --validate --out-dir out
```

This reads `questions.example.json` (72 sample questions), assembles two
disjoint 20-question versions matching `blueprint.yaml`, and writes
`out/exam_v1.json`, `out/exam_v2.json` and their `.report.md` files.

Pure command line, no YAML at all:

```bash
python -m quizgen --pool questions.example.json \
    --total 20 --chapters 1:10,2:6,3:4 \
    --difficulty 0.4,0.4,0.2 --versions 2 --selector mip
```

---

## The question bank (input)

A JSON file: either a `Quiz` object with a `questions` array, or a bare list of
questions. Each question follows the `Question` schema (`schemas/question.schema.json`):

```json
{
  "id": "q001",
  "chapter": 1,
  "section": "1.2",
  "qtype": "mcq",
  "bloom_level": "understand",
  "difficulty": "medium",
  "stem": "Explain how A* uses an admissible heuristic.",
  "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
  "answer": "A",
  "explanation": "A* is optimal when h never overestimates the true cost.",
  "source_ref": "ch1_sec2_q1"
}
```

The metadata fields are what selection reasons over:

| Field | Used for |
|-------|----------|
| `chapter` | per-chapter quotas |
| `difficulty` | `easy` / `medium` / `hard` mix |
| `qtype` | `mcq` / `true_false` / `short_answer` / `cloze` filtering |
| `bloom_level` | `remember … create` (informs the quality objective) |
| `stem` / `answer` / `options` | near-duplicate detection |
| `source_ref` | provenance / audit trail (free-form; optional in practice) |

---

## The blueprint

A small YAML the professor edits (see `blueprint.yaml`):

```yaml
title: "AI-1 Midterm Exam"
total_questions: 20
chapters: { 1: "50%", 2: "30%", 3: "20%" }   # counts, fractions, or "NN%"
difficulty_mix: { easy: 0.4, medium: 0.4, hard: 0.2 }
allowed_qtypes: [mcq, true_false, short_answer, cloze]
versions: 2
selector: mip            # greedy | mip
dedup_similarity: 0.85
```

Chapter and difficulty amounts may be integer counts, fractions, or `"NN%"`
strings; they are resolved to exact integer counts (largest-remainder method)
that sum to `total_questions`.

---

## Constraints: YAML and/or flags (flags win)

Every blueprint field can be overridden on the command line, so you can keep a
base `blueprint.yaml` and tweak a single run:

```bash
# Load the YAML, but override just the version count and selector:
python -m quizgen --pool questions.example.json --blueprint blueprint.yaml \
    --versions 3 --selector greedy
```

| Flag | Overrides | Example |
|------|-----------|---------|
| `--pool` | (required) question-bank JSON | `--pool questions.json` |
| `--blueprint` | blueprint YAML (defaults) | `--blueprint blueprint.yaml` |
| `--total` | `total_questions` | `--total 20` |
| `--chapters` | `chapters` | `--chapters 1:10,2:6,3:4` or `1:50%,2:30%,3:20%` |
| `--difficulty` | `difficulty_mix` | `--difficulty 0.4,0.4,0.2` or `easy:0.4,hard:0.6` |
| `--qtypes` | `allowed_qtypes` | `--qtypes mcq,short_answer` |
| `--versions` | `versions` | `--versions 2` |
| `--selector` | `selector` | `--selector mip` |
| `--dedup-similarity` | `dedup_similarity` | `--dedup-similarity 0.9` |
| `--dedup` | drop near-duplicates from the pool first | |
| `--embeddings` | use embeddings for `--dedup` (else token overlap) | |
| `--validate` | write a Markdown validation report per version | |
| `--out` / `--out-dir` | output path(s) | `--out-dir out` |

If neither the YAML nor `--total` provides a question count, the run errors out.

---

## The two selectors

| Selector | Method | Guarantees |
|----------|--------|-----------|
| `greedy` | Greedy/random with content balancing | Fast; meets per-chapter counts, respects the difficulty marginal, skips duplicates |
| `mip` | Mixed-Integer Program (PuLP/CBC) | Meets per-chapter **and** difficulty counts exactly, maximises a quality objective, keeps versions disjoint, forbids near-duplicate pairs across versions |

The MIP is a 0–1 program: a binary `x[i,v]` decides whether question `i` goes
into version `v`, subject to exact per-chapter and per-difficulty equalities,
at-most-one-version-per-question (disjointness), and a forbid-near-duplicate
constraint, maximising total question quality. If the exact program is
infeasible for the given pool, the difficulty equalities are relaxed (and the
relaxation is reported) while per-chapter counts are never violated.

---

## What the pipeline does

```
question bank (JSON)
        │
        ├─►  (optional) deduplicate the pool        quizgen/dedup.py, similarity.py
        │
        ├─►  assemble  (greedy | MIP)               quizgen/assemble.py, blueprint.py
        │      → one or more disjoint versions
        │
        └─►  (optional) validate each version        quizgen/validate.py
               → schema, blueprint compliance,
                 grounding, duplicate rate
```

---

## Project structure

```
quizgen/
├── quizgen/
│   ├── __main__.py     # CLI: pool + blueprint/flags → exam version(s)
│   ├── schema.py       # Pydantic models (Question, Quiz) + JSON-Schema export
│   ├── blueprint.py    # Blueprint model, count resolution (largest-remainder)
│   ├── assemble.py     # Automated Test Assembly: GreedySelector, MIPSelector
│   ├── similarity.py   # Near-duplicate detection (token-Jaccard / embedding)
│   ├── dedup.py        # Pool deduplication pass
│   ├── validate.py     # Validation & quality report
│   ├── textmatch.py    # Dependency-free content-word overlap helper
│   └── config.py       # Optional embedding-model setting (semantic dedup)
├── blueprint.yaml          # Example blueprint
├── questions.example.json  # Example question bank (72 questions)
├── schemas/                # Exported JSON Schemas (Question, Quiz)
└── tests/                  # test_schema, test_blueprint+assemble, test_dedup,
                            # test_validate, test_cli
```

---

## Standalone tools

The assembly and validation steps also have their own entry points:

```bash
# Assemble from a blueprint file only:
python -m quizgen.assemble --pool questions.example.json --blueprint blueprint.yaml --out exam.json

# Validate an assembled exam against a blueprint:
python -m quizgen.validate --exam exam.json --blueprint blueprint.yaml --out report.md
```

---

## Tests

```bash
source .venv/bin/activate
pytest
```

Everything runs offline with no external services.

---

## License

MIT License — Author: Jinikuhayashi — Advisor: Prof. Michael Kohlhase (KWARC, FAU Erlangen-Nürnberg)
