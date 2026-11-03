# BM25 lexical retrieval (standalone slice)

`videorag.bm25.BM25Index` is a deterministic, in-memory lexical channel over retrieval units of
validated `CanonicalVideo` records. It is rebuilt from canonical snapshots on demand; no index file,
service, model, Neo4j, API or UI is involved. **Retrieval quality has not been evaluated**; the
parameters below are provisional defaults, not tuned values.

```python
from videorag import load_canonical_video
from videorag.bm25 import BM25Index

records = [load_canonical_video(p) for p in snapshot_paths]
index = BM25Index(records)                  # rejects duplicate unit IDs and evidence gaps
for c in index.search("blue robot", top_k=5):
    print(c.rank, c.unit_id, c.score)       # RetrievalCandidate(channel="bm25", ...)
```

## Definition

- **Document** = one `RetrievalUnit`, keyed by `unit_id`; its text is `unit.text`.
- **Tokenizer** (`tokenize`): Unicode NFKC, `casefold()`, then maximal runs of Unicode letters/digits
  (`[^\W_]+`). Underscores and punctuation separate tokens. No stemming, stop words or synonyms.
- **Score**: for each distinct query term `t` present in the corpus,
  `idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))`, with
  `idf = ln(1 + (N - df + 0.5) / (df + 0.5))` (always positive). Defaults `k1 = 1.2`, `b = 0.75`.
  The equivalent ratio divided through by `k1` is used when `k1 >= 1` to prevent
  intermediate overflow for large finite parameters.
- **Ranking**: score descending, ties by `unit_id` ascending; ranks are contiguous from 1. Internal
  iteration is in sorted order, so results do not depend on input record order or rebuilds.
  Scores are diagnostic and comparable only within this channel.

## Edge cases

- Only units with a positive score are returned; non-matching units are omitted. `top_k` (positive
  int or `None`) truncates.
- Repeated query terms are de-duplicated (no query-side boost). Empty, whitespace or
  punctuation-only queries, unseen terms, and empty corpora return `()`.
- A unit whose text yields no tokens (e.g. `"?!"`) is a zero-length document: it stays in the
  corpus (it counts toward `N` and, with length 0, toward `avgdl`) but is never returned.
- Duplicate `unit_id` across supplied records (including the same record twice) raises
  `DuplicateUnitError`. Any record with an observation lacking evidence raises
  `IncompleteEvidenceError`. Records are re-validated before indexing.

## Not included

Index persistence, incremental updates, per-video filtering, phrase/fuzzy matching, language-specific
analysis, fusion (RRF), and evaluation.
