# Sources matching the implemented solution

This list maps each part of the **current** `quizgen` codebase (selection-only
Automated Test Assembly from a question bank) to the literature it draws on.
Full BibTeX entries are in [`references.bib`](references.bib); every entry was
verified against the publisher / ACL Anthology / ERIC record.

> Scope reminder: the implemented tool **selects** an exam from a pre-existing
> question bank. It does **not** generate questions or ingest documents, so the
> sources below are about *test assembly, blueprints, item metadata, and
> duplicate detection* — not about LLM question generation.

## Code → technique → source

| Code | Technique | Primary source(s) | Why it matches |
|------|-----------|-------------------|----------------|
| `assemble.py` · `MIPSelector` | Test assembly as a 0–1 / mixed-integer program | van der Linden (2005); Theunissen (1985); van der Linden & Boekkooi-Timminga (1989) | Our `x[i,v] ∈ {0,1}` model with content-count equalities is exactly the 0–1 LP/MIP formulation these establish. |
| `assemble.py` · solver & practice | Solving ATA with free MIP solvers | Diao & van der Linden (2011); Luo (2020); Krohne et al. (2021, eatATA) | Same practical setting: MIP ATA via open-source solvers (we use PuLP/**CBC**). Luo specifically studies modelling choices and solvers incl. CBC. |
| `assemble.py` · `versions`, disjointness `Σ_v x_iv ≤ 1` | Maximum non-overlapping parallel forms | Belov (2008), *Uniform Test Assembly* | Directly about assembling **disjoint** parallel forms from one pool — our multi-version, no-shared-item feature. |
| `assemble.py` · `question_quality` objective | Objective-weighted item selection | van der Linden (2005, 1998) | The maximise-objective-subject-to-constraints pattern; our quality proxy stands in for IRT information. |
| `blueprint.py` | Test blueprint / table of specifications | Fives & DiDonato-Barnes (2013) | A content × cognitive-level specification that drives item selection — precisely what the blueprint encodes. |
| `blueprint.py` · `_largest_remainder` | Largest-remainder (Hamilton) apportionment | Balinski & Young (1982) | Resolves fractional/percentage blueprint shares into exact integer counts summing to the total. |
| `schema.py` · `bloom_level` | Revised Bloom's taxonomy | Anderson & Krathwohl (2001); Bloom (1956) | The `remember…create` levels used as item metadata and in the quality objective. |
| `similarity.py` · embedding cosine | Semantic near-duplicate detection | Reimers & Gurevych (2019), Sentence-BERT | `all-MiniLM-L6-v2` is an SBERT model; cosine over its embeddings is the optional dedup backend. |
| `similarity.py` · token backend | Jaccard set-overlap coefficient | Jaccard (1912) | The dependency-free token-overlap measure used offline. |
| `assemble.py` / `blueprint.py` · tooling | MILP modelling & solver software | PuLP (Mitchell et al. 2011); CBC (Forrest et al., COIN-OR) | The actual libraries the selector is built on. |

## Reference list (verified)

**Automated Test Assembly (MIP/LP):**
- van der Linden, W. J. (2005). *Linear Models for Optimal Test Design.* Springer. https://doi.org/10.1007/0-387-29054-0
- Theunissen, T. J. J. M. (1985). Binary Programming and Test Design. *Psychometrika, 50*(4), 411–420. https://doi.org/10.1007/BF02296260
- van der Linden, W. J., & Boekkooi-Timminga, E. (1989). A Maximin Model for IRT-Based Test Design with Practical Constraints. *Psychometrika, 54*(2), 237–247. https://doi.org/10.1007/BF02294518
- van der Linden, W. J. (1998). Optimal Assembly of Psychological and Educational Tests. *Applied Psychological Measurement, 22*(3), 195–211. https://doi.org/10.1177/01466216980223001
- Diao, Q., & van der Linden, W. J. (2011). Automated Test Assembly Using lp_Solve Version 5.5 in R. *Applied Psychological Measurement, 35*(5), 398–409. https://doi.org/10.1177/0146621610392211
- Luo, X. (2020). Automated Test Assembly with Mixed-Integer Programming: The Effects of Modeling Approaches and Solvers. *Journal of Educational Measurement, 57*(4). https://doi.org/10.1111/jedm.12262
- Krohne, U., et al. (2021). Automated Test Assembly in R: The eatATA Package. *Psych, 3*(2), 96–112. https://doi.org/10.3390/psych3020010

**Parallel / disjoint forms:**
- Belov, D. I. (2008). Uniform Test Assembly. *Psychometrika, 73*(1), 21–38. https://doi.org/10.1007/s11336-007-9025-0

**Blueprint / table of specifications:**
- Fives, H., & DiDonato-Barnes, N. (2013). Classroom Test Construction: The Power of a Table of Specifications. *Practical Assessment, Research, and Evaluation, 18*(3). https://openpublishing.library.umass.edu/pare/article/id/1430/

**Cognitive-level taxonomy (Bloom):**
- Bloom, B. S. (Ed.) (1956). *Taxonomy of Educational Objectives, Handbook I: The Cognitive Domain.* David McKay.
- Anderson, L. W., & Krathwohl, D. R. (Eds.) (2001). *A Taxonomy for Learning, Teaching, and Assessing: A Revision of Bloom's Taxonomy of Educational Objectives.* Longman.

**Near-duplicate detection:**
- Reimers, N., & Gurevych, I. (2019). Sentence-BERT: Sentence Embeddings Using Siamese BERT-Networks. *EMNLP-IJCNLP*, 3982–3992. https://aclanthology.org/D19-1410/
- Jaccard, P. (1912). The Distribution of the Flora in the Alpine Zone. *New Phytologist, 11*(2), 37–50. https://doi.org/10.1111/j.1469-8137.1912.tb05611.x

**Apportionment:**
- Balinski, M. L., & Young, H. P. (1982). *Fair Representation: Meeting the Ideal of One Man, One Vote.* Yale University Press.

**Software:**
- Mitchell, S., O'Sullivan, M., & Dunning, I. (2011). *PuLP: A Linear Programming Toolkit for Python.* https://github.com/coin-or/pulp
- Forrest, J., et al. *CBC (COIN-OR Branch and Cut) MILP solver.* https://github.com/coin-or/Cbc

## Notes on use

- **Core vs. supporting.** The van der Linden line (2005, 1989, 1998), Theunissen
  (1985), Belov (2008), and Fives & DiDonato-Barnes (2013) are the *core*
  matches — they describe the exact problem the code solves. The rest
  (Bloom, SBERT, Jaccard, Balinski–Young, PuLP/CBC) support individual
  components.
- **IRT caveat.** Classic ATA maximises a *test information function* from Item
  Response Theory. `quizgen` does **not** use IRT — it maximises a lightweight
  `question_quality` proxy. Cite the ATA sources for the *optimisation
  framing*, and state this difference explicitly in the thesis.
- Replace any author initials/issue numbers with your citation style's exact
  form before submission.
