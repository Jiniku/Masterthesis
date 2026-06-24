"""Deterministic offline stand-in for :class:`~quizgen.llm_client.LLMClient`.

No public LLM endpoint is guaranteed in every environment (CI, a student
laptop with no API key, the thesis defence machine).  ``MockLLMClient`` lets
the *entire* pipeline — generation, controlled generation, assembly,
validation — run end-to-end without a network call, producing schema-valid,
grounded-looking questions that honour the requested Bloom level, difficulty
and qtype.

It is **not** a quality model: it stitches questions from words found in the
prompt's source passages.  Its job is to exercise and demonstrate the code
paths (and to back the deterministic tests), not to write good exams.  Swap in
the real :class:`LLMClient` by changing ``.env`` — nothing else changes.
"""

from __future__ import annotations

import re
import zlib

from quizgen.llm_client import LLMClient

_SPEC_RE = re.compile(
    r"#SPEC\s+\d+\s*\|\s*bloom=(\w+)\s*\|\s*difficulty=(\w+)\s*\|\s*qtype=(\w+)"
)
_CHUNK_ID_RE = re.compile(r"\[([a-zA-Z0-9_.\-]+)\]")
_N_RE = re.compile(r"[Gg]enerate exactly (\d+)")
_CHAPTER_RE = re.compile(r"Chapter (\d+)")
_SECTION_RE = re.compile(r"[Ss]ection[:\s]+([0-9]+\.[0-9]+)")
_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z\-]{4,}\b")

_STOP = {
    "questions", "question", "chapter", "section", "source", "passage",
    "passages", "answer", "options", "explanation", "based", "exactly",
    "generate", "following", "should", "which", "their", "about", "these",
    "those", "there", "where", "would", "could", "every", "using", "given",
}

_TYPE_ROTATION = ["mcq", "true_false", "short_answer", "cloze"]
_BLOOM_ROTATION = ["remember", "understand", "apply", "analyze", "evaluate", "create"]
_DIFF_ROTATION = ["easy", "medium", "hard"]


class MockLLMClient(LLMClient):
    """A drop-in, network-free LLMClient that fabricates valid questions."""

    def __init__(self, model: str = "mock-model") -> None:  # noqa: D401
        # Deliberately skip the OpenAI client construction in the parent.
        self.base_url = "mock://local"
        self.api_key = "mock"
        self.model = model
        self._client = None

    # ── overridden transport ────────────────────────────────────────

    def chat(self, messages, *, temperature=None, max_tokens=2048, **kwargs):
        import json

        return json.dumps(self._build_payload(messages))

    def chat_json(self, messages, *, temperature=None, max_tokens=4096, **kwargs):
        return self._build_payload(messages)

    def chat_schema(self, messages, json_schema, *, schema_name="response",
                    temperature=None, max_tokens=4096, **kwargs):
        return self._build_payload(messages)

    # ── payload construction ────────────────────────────────────────

    def _build_payload(self, messages) -> dict:
        user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        chapter = int(_CHAPTER_RE.search(user).group(1)) if _CHAPTER_RE.search(user) else 1
        sec_match = _SECTION_RE.search(user)
        section = sec_match.group(1) if sec_match else f"{chapter}.0"
        chunk_ids = _CHUNK_ID_RE.findall(user) or [f"ch{chapter}_chunk_001"]
        keywords = self._keywords(user)

        specs = _SPEC_RE.findall(user)
        questions: list[dict] = []

        if specs:  # Phase 3 controlled mode — one question per spec.
            for i, (bloom, diff, qtype) in enumerate(specs):
                qt = qtype if qtype in _TYPE_ROTATION else _TYPE_ROTATION[i % 4]
                questions.append(
                    self._make_question(chapter, section, qt, bloom, diff,
                                        keywords, chunk_ids, i)
                )
        else:  # Phase 1/2 free generation — N varied questions.
            n_match = _N_RE.search(user)
            n = int(n_match.group(1)) if n_match else 2
            for i in range(n):
                questions.append(
                    self._make_question(
                        chapter, section,
                        _TYPE_ROTATION[i % 4],
                        _BLOOM_ROTATION[i % 6],
                        _DIFF_ROTATION[i % 3],
                        keywords, chunk_ids, i,
                    )
                )

        return {"questions": questions}

    @staticmethod
    def _passage_region(user: str) -> str:
        """Slice out just the source-passage text from the prompt.

        Keywords must come from the chapter's *own* passages, not the shared
        prompt scaffolding (Bloom descriptions, few-shot examples) which is
        identical across chapters — otherwise questions from different chapters
        look like near-duplicates.
        """
        for marker in ("SOURCE PASSAGES:", "TEXT PASSAGE:", "Retrieved passages"):
            pos = user.find(marker)
            if pos != -1:
                tail = user[pos + len(marker):]
                # Stop at the spec/instruction block that follows the passages.
                for end in ("\nSPECIFICATIONS", "\n---", "\nRespond with"):
                    epos = tail.find(end)
                    if epos != -1:
                        tail = tail[:epos]
                return tail
        return user

    def _keywords(self, text: str) -> list[str]:
        """Extract distinctive content words from the source passages."""
        text = self._passage_region(text)
        seen: list[str] = []
        for w in _WORD_RE.findall(text):
            lw = w.lower()
            if lw not in _STOP and w not in seen:
                seen.append(w)
            if len(seen) >= 40:
                break
        return seen or ["concept", "method", "system", "model", "rule"]

    # Several stem templates per type so successive questions are lexically
    # distinct (otherwise the dedup pass would collapse the whole pool).
    _MCQ_TEMPLATES = [
        "Which term best matches the description of '{kw}' in {kw2}?",
        "In the context of {kw3}, what does '{kw}' most directly refer to?",
        "Selecting from the passage, which concept is the counterpart of '{kw}'?",
        "Regarding {kw2} and {kw3}, which option correctly characterises '{kw}'?",
    ]
    _SA_TEMPLATES = [
        "Briefly explain the role of '{kw}' and how it relates to {kw2}.",
        "Describe how '{kw}' interacts with {kw3} according to the passage.",
        "Summarise what the passage says about '{kw}' in relation to {kw2}.",
        "Explain why '{kw}' matters when reasoning about {kw3}.",
    ]
    _TF_TEMPLATES = [
        "True or False: the passage links '{kw}' with {kw2}.",
        "True or False: according to the text, '{kw}' depends on {kw3}.",
        "True or False: '{kw}' and {kw2} are described as unrelated.",
        "True or False: the passage treats '{kw}' as a form of {kw3}.",
    ]
    _CLOZE_TEMPLATES = [
        "Fill in the blank: the concept relating {kw2} to {kw3} is ____.",
        "Complete: when discussing {kw2}, the passage introduces ____.",
        "Fill in the blank: ____ is the term the passage pairs with {kw3}.",
        "Complete the sentence: the key idea connecting {kw2} and {kw3} is ____.",
    ]

    def _make_question(self, chapter, section, qtype, bloom, difficulty,
                       keywords, chunk_ids, i) -> dict:
        k = len(keywords)
        # Fold bloom/difficulty into the variation so questions from different
        # generation batches don't collide (which would let dedup collapse the
        # whole pool). `g` is an effective global-ish index.
        salt = (zlib.crc32(f"{bloom}|{difficulty}".encode()) & 0xFFFF) % max(k, 7)
        g = i + salt
        # Spread keyword picks far apart so token overlap between questions stays low.
        kw = keywords[g % k]
        kw2 = keywords[(g * 3 + 5) % k]
        kw3 = keywords[(g * 7 + 11) % k]
        kw4 = keywords[(g * 5 + 2) % k]
        source_ref = chunk_ids[i % len(chunk_ids)]
        t = g % 4

        if qtype == "mcq":
            return {
                "chapter": chapter, "section": section, "qtype": "mcq",
                "bloom_level": bloom, "difficulty": difficulty,
                "stem": self._MCQ_TEMPLATES[t].format(kw=kw, kw2=kw2, kw3=kw3),
                "options": [f"A) {kw}", f"B) {kw2}", f"C) {kw3}", f"D) {kw4}"],
                "answer": "A",
                "explanation": f"The passage associates '{kw}' with {kw2}, so option A is correct here.",
                "source_ref": source_ref,
            }
        if qtype == "true_false":
            return {
                "chapter": chapter, "section": section, "qtype": "true_false",
                "bloom_level": bloom, "difficulty": difficulty,
                "stem": self._TF_TEMPLATES[t].format(kw=kw, kw2=kw2, kw3=kw3),
                "options": None, "answer": "True" if t % 2 == 0 else "False",
                "explanation": f"The relationship between '{kw}' and {kw2} in the passage settles this.",
                "source_ref": source_ref,
            }
        if qtype == "cloze":
            return {
                "chapter": chapter, "section": section, "qtype": "cloze",
                "bloom_level": bloom, "difficulty": difficulty,
                "stem": self._CLOZE_TEMPLATES[t].format(kw2=kw2, kw3=kw3),
                "options": None, "answer": kw,
                "explanation": f"'{kw}' is the term the passage uses when connecting {kw2} and {kw3}.",
                "source_ref": source_ref,
            }
        # short_answer
        return {
            "chapter": chapter, "section": section, "qtype": "short_answer",
            "bloom_level": bloom, "difficulty": difficulty,
            "stem": self._SA_TEMPLATES[t].format(kw=kw, kw2=kw2, kw3=kw3),
            "options": None,
            "answer": f"{kw} is described in the passage as relating to {kw2} and {kw3}.",
            "explanation": f"A correct answer references how '{kw}' connects to {kw2} in the source text.",
            "source_ref": source_ref,
        }
