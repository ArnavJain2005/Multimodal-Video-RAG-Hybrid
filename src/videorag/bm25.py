"""Deterministic in-memory BM25 channel over validated canonical retrieval units.

The index is rebuilt from loaded ``CanonicalVideo`` records; nothing is persisted. See
``docs/BM25_RETRIEVAL.md`` for the tokenizer and scoring definition.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from .contracts import CanonicalVideo, RetrievalCandidate
from .persistence import IncompleteEvidenceError, evidence_gaps

K1 = 1.2
B = 0.75
_TOKEN = re.compile(r"[^\W_]+")


def tokenize(text: str) -> tuple[str, ...]:
    """NFKC-normalise, casefold, then take maximal runs of Unicode letters/digits.

    Underscores and all punctuation/whitespace separate tokens. No stemming or stop words.
    """
    return tuple(_TOKEN.findall(unicodedata.normalize("NFKC", text).casefold()))


class DuplicateUnitError(ValueError):
    def __init__(self, unit_ids: tuple[str, ...]):
        self.unit_ids = unit_ids
        super().__init__("duplicate retrieval unit IDs: " + ", ".join(unit_ids))


@dataclass(frozen=True)
class _Document:
    unit_id: str
    length: int
    frequencies: dict[str, int]


class BM25Index:
    """Immutable BM25 index keyed by ``unit_id`` (Lucene-style non-negative IDF)."""

    def __init__(self, records: Iterable[CanonicalVideo] | CanonicalVideo, *,
                 k1: float = K1, b: float = B):
        if not (math.isfinite(k1) and k1 >= 0) or not (math.isfinite(b) and 0 <= b <= 1):
            raise ValueError("require finite k1 >= 0 and 0 <= b <= 1")
        self.k1, self.b = float(k1), float(b)
        if isinstance(records, CanonicalVideo):
            records = (records,)
        units, seen, duplicates = [], set(), set()
        for record in records:
            if not isinstance(record, CanonicalVideo):
                raise TypeError("records must be CanonicalVideo instances")
            # Re-validate: model_copy(update=...) can bypass field/reference validation.
            checked = CanonicalVideo.model_validate_json(record.model_dump_json())
            gaps = evidence_gaps(checked)
            if gaps:
                raise IncompleteEvidenceError(gaps)
            for unit in checked.units:
                if unit.unit_id in seen:
                    duplicates.add(unit.unit_id)
                seen.add(unit.unit_id)
                units.append(unit)
        if duplicates:
            raise DuplicateUnitError(tuple(sorted(duplicates)))
        documents = []
        for unit in sorted(units, key=lambda u: u.unit_id):  # input order never matters
            tokens = tokenize(unit.text)
            documents.append(_Document(unit.unit_id, len(tokens), dict(Counter(tokens))))
        self._documents = tuple(documents)
        self._avg_length = (sum(d.length for d in documents) / len(documents)
                            if documents else 0.0)
        frequency = Counter(term for d in documents for term in d.frequencies)
        n = len(documents)
        self._idf = {term: math.log(1.0 + (n - df + 0.5) / (df + 0.5))
                     for term, df in frequency.items()}

    def __len__(self) -> int:
        return len(self._documents)

    def search(self, query: str, top_k: int | None = None) -> tuple[RetrievalCandidate, ...]:
        """Rank units matching at least one query term; others are not returned.

        Query terms are de-duplicated (repetition does not boost). Empty or token-free
        queries, empty corpora and zero-length documents yield no candidates.
        """
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if top_k is not None and (isinstance(top_k, bool) or not isinstance(top_k, int)
                                  or top_k < 1):
            raise ValueError("top_k must be a positive integer or None")
        terms = sorted({t for t in tokenize(query) if t in self._idf})
        scored = []
        for doc in self._documents:
            if doc.length == 0:
                continue
            norm = 1.0 - self.b + self.b * doc.length / self._avg_length
            score = 0.0
            for term in terms:
                tf = doc.frequencies.get(term, 0)
                if tf:
                    score += self._idf[term] * tf * (self.k1 + 1.0) / (tf + self.k1 * norm)
            if score > 0.0:
                scored.append((-score, doc.unit_id))
        scored.sort()
        return tuple(RetrievalCandidate(channel="bm25", unit_id=unit_id, rank=rank,
                                        score=-negative)
                     for rank, (negative, unit_id) in enumerate(scored[:top_k], 1))
