# quizgen — build an exam from a question bank

Master's thesis project — KWARC group, FAU Erlangen-Nürnberg

## What this tool does (in one sentence)

You already have a **collection of exam questions** (in a JSON file). You tell
quizgen **what the exam should look like** — how many questions, how many per
chapter, how hard, how many versions — and it **picks the questions for you**,
exactly matching your specification.

That's it. It does **not** write questions and it does **not** read a textbook.
It only *selects* from questions you already have. No AI / LLM is involved.

**A small example.** You have 180 questions. You want a 20-question exam: half
from Chapter 1, and an easy/medium/hard mix of 8/8/4 — in **two different
versions** that share no questions (so students next to each other get
different papers). quizgen does the picking and guarantees the counts are
exactly right.

Three words used throughout this README:

- **Pool** = your question bank (the input JSON file).
- **Blueprint** = your specification of the exam (counts, difficulty, versions).
- **Version** = one assembled exam paper. You can ask for several at once.

---

## 1. Set up (do this once)

You need **Python 3.11 or newer**.

> **macOS / Linux note:** on a Mac the command is `python3`, not `python`.
> After you create and *activate* the virtual environment below, `python`
> works inside it. If you ever see `zsh: command not found: python`, it just
> means the environment is not activated — run the `source` line again.

```bash
# from inside the project folder:
python3 -m venv .venv            # create a private environment (once)
source .venv/bin/activate        # activate it — your prompt now shows (.venv)
pip install -e .                 # install quizgen + its 3 dependencies
```

On **Windows (PowerShell)**:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

That installs only three small libraries: `pydantic`, `pyyaml`, `pulp`
(the optimisation solver). No AI models, no internet needed.

Optional extras:

```bash
pip install -e ".[dev]"          # tools to run the tests (pytest, ruff)
pip install -e ".[embeddings]"   # smarter duplicate detection (optional)
```

---

## 2. Run your first exam (3 steps)

Make sure the environment is active (you see `(.venv)` in your prompt). Then:

```bash
python -m quizgen --pool questions.example.json --blueprint blueprint.yaml --out-dir out
```

- `--pool questions.example.json` → the question bank to pick from (an example
  with 180 questions is included).
- `--blueprint blueprint.yaml` → the exam specification (an example is included).
- `--out-dir out` → put the finished exams in a folder called `out/`.

You will see output like this:

```
📋 Blueprint: AI-1 Midterm Exam
   Total/version: 20
   Per chapter:   {1: 10, 2: 6, 3: 4}
   Difficulty:    {'easy': 8, 'medium': 8, 'hard': 4}
   Versions:      2   Selector: mip
   Pool size:     180

   ── Version A (20 questions) ──
      Per chapter: {1: 10, 2: 6, 3: 4}
      Difficulty:  {'easy': 8, 'medium': 8, 'hard': 4}
   💾 Saved version A -> out/exam_v1.json

   ── Version B (20 questions) ──
      Per chapter: {1: 10, 2: 6, 3: 4}
      Difficulty:  {'easy': 8, 'medium': 8, 'hard': 4}
   💾 Saved version B -> out/exam_v2.json

✅ All versions blueprint-compliant
```

Look in the `out/` folder: `exam_v1.json` and `exam_v2.json` are your two
finished exams (each a list of the chosen questions).

**Add a quality report** by also passing `--validate`:

```bash
python -m quizgen --pool questions.example.json --blueprint blueprint.yaml \
    --validate --out-dir out
```

This writes an extra `exam_v1.report.md` / `exam_v2.report.md` next to each
exam, confirming it matches the blueprint, has no duplicates, etc.

---

## 3. The input file (your question bank)

A JSON file containing a list of questions. Each question needs these fields
(the exact rules are in `schemas/question.schema.json`):

```json
{
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

quizgen uses the **metadata** to decide what to pick:

| Field | Why quizgen needs it |
|-------|----------------------|
| `chapter` | to hit the per-chapter counts |
| `difficulty` | `easy` / `medium` / `hard` — to hit the difficulty mix |
| `qtype` | `mcq` / `true_false` / `short_answer` / `cloze` — for type filtering |
| `bloom_level` | `remember … create` — slightly favours higher-order questions |
| `stem`, `answer`, `options` | to detect near-duplicate questions |
| `source_ref` | a free-text note of where the question came from |

To use **your own** questions, make a file in this same shape and pass it with
`--pool your_questions.json`. (The included `questions.example.json` is just a
sample so the tool works out of the box.)

---

## 4. The blueprint (your exam specification)

A short YAML file you edit (`blueprint.yaml`):

```yaml
title: "AI-1 Midterm Exam"
total_questions: 20
chapters: { 1: "50%", 2: "30%", 3: "20%" }      # how to split across chapters
difficulty_mix: { easy: 0.4, medium: 0.4, hard: 0.2 }
allowed_qtypes: [mcq, true_false, short_answer, cloze]
versions: 2                # how many parallel papers
selector: mip              # "mip" (exact) or "greedy" (fast) — see below
dedup_similarity: 0.85     # how similar counts as a "duplicate" (0–1)
```

- Chapter and difficulty amounts can be **exact counts** (`10`), **fractions**
  (`0.5`), or **percentages** (`"50%"`). quizgen converts them to whole numbers
  that add up to `total_questions` exactly.
- `versions: 2` produces two papers that **share no questions**.

---

## 5. Setting the exam without editing the file (command-line flags)

You don't have to edit the YAML every time. Any setting can be given as a
**flag on the command line**, and **flags override the YAML file**. You can even
skip the blueprint file entirely:

```bash
# No YAML at all — specify everything on the command line:
python -m quizgen --pool questions.example.json \
    --total 20 --chapters 1:10,2:6,3:4 \
    --difficulty 0.4,0.4,0.2 --versions 2 --selector mip
```

| Flag | Sets | Example |
|------|------|---------|
| `--pool` | the question bank (**required**) | `--pool questions.example.json` |
| `--blueprint` | a YAML file of defaults | `--blueprint blueprint.yaml` |
| `--total` | total questions per version | `--total 20` |
| `--chapters` | per-chapter split | `--chapters 1:10,2:6,3:4` or `1:50%,2:30%,3:20%` |
| `--difficulty` | easy/medium/hard mix | `--difficulty 0.4,0.4,0.2` |
| `--qtypes` | allowed question types | `--qtypes mcq,short_answer` |
| `--versions` | number of papers | `--versions 2` |
| `--selector` | `greedy` or `mip` | `--selector mip` |
| `--dedup` | remove duplicate questions first | *(on/off)* |
| `--validate` | also write a quality report | *(on/off)* |
| `--out` / `--out-dir` | where to save | `--out-dir out` |

If you give neither `--total` nor a blueprint with a total, quizgen stops and
tells you a total is required.

---

## 6. How it picks: `greedy` vs `mip`

| `selector` | What it is | When to use |
|-----------|------------|-------------|
| `greedy` | A fast, simple "fill the quotas" method | quick drafts; very large pools |
| `mip` | An **exact optimiser** (Mixed-Integer Program, solved by PuLP/CBC) | the real exam — guarantees the counts are exactly right, versions don't overlap, and no duplicates appear |

**Recommended: `mip`.** It treats the selection as a math problem and finds a
solution that meets *every* constraint exactly while preferring higher-quality
questions. If your pool is too small to satisfy everything (e.g. not enough
hard questions in a chapter), it relaxes the difficulty target, tells you it did
so, and still keeps the per-chapter counts correct.

---

## 7. Troubleshooting

**`zsh: command not found: python`**
The virtual environment isn't active. Run `source .venv/bin/activate` (you
should then see `(.venv)` in your prompt), and use `python` again. Outside the
environment, use `python3`.

**`MIP assembly failed: Infeasible` / "pool too small"**
Your question bank doesn't have enough questions to satisfy the blueprint
(e.g. you asked for 2 versions × 10 Chapter-1 questions = 20, but the pool only
has 12 from Chapter 1). Add more questions, ask for fewer, or reduce `versions`.

**`total number of questions is required`**
Pass `--total N`, or put `total_questions:` in your blueprint YAML.

---

## 8. Other commands

```bash
# Run the test suite (needs the [dev] extra installed):
pytest

# The assemble and validate steps as standalone tools:
python -m quizgen.assemble --pool questions.example.json --blueprint blueprint.yaml --out exam.json
python -m quizgen.validate --exam exam.json --blueprint blueprint.yaml --out report.md
```

Everything runs offline — no internet, no API keys, no AI models.

---

## Project layout

```
quizgen/
├── quizgen/
│   ├── __main__.py     # the command you run: pool + blueprint/flags → exam(s)
│   ├── schema.py       # the Question / Quiz data definitions
│   ├── blueprint.py    # reads the blueprint, turns %/fractions into exact counts
│   ├── assemble.py     # the selection logic (greedy + MIP)
│   ├── similarity.py   # finds near-duplicate questions
│   ├── dedup.py        # removes duplicates from the pool
│   ├── validate.py     # checks a finished exam against the blueprint
│   ├── textmatch.py    # small text helper
│   └── config.py       # one optional setting (embedding model)
├── blueprint.yaml          # example exam specification
├── questions.example.json  # example question bank
├── schemas/                # the JSON rules for a Question / Quiz
├── docs/                   # implementation report (LaTeX) + slides
└── tests/                  # automated tests
```

---

## License

MIT License — Author: Jinikuhayashi — Advisor: Prof. Michael Kohlhase
(KWARC, FAU Erlangen-Nürnberg)
