# System architecture

## Offline path (accepted boundaries; implementation pending)

```text
authorized media + manifest
  → validate/hash/probe → speech, OCR, frame extraction + provenance
  → canonical JSON (asset, observations, spans)
  → deterministic retrieval units + evidence links
  → independent dense / BM25 / Neo4j index builders
```

The implemented builder sorts observations by start, end and ID, then derives one unit and evidence link per observation. It requires a known duration. `save_canonical_video` validates the complete record, rejects gaps by default, and writes an atomic JSON snapshot at `<video_id>.json`; changed snapshots require explicit replacement. Extraction itself is pending. A frame sample is a point observation; it must not be widened to assert a continuous action. Index builders must be idempotent and recoverable from canonical snapshots, with configuration/model versions recorded in manifests. Canonical types import no index, web or UI packages.

## Online path (accepted boundaries; implementation pending)

```text
Streamlit → FastAPI → query orchestration
                        ├→ dense candidates
                        ├→ BM25 candidates
                        └→ Neo4j evidence-linked candidates
                     → deduplicate unit IDs → RRF → resolve evidence
                     → bounded context → grounded generation / abstention
                     → API answer + source references → Streamlit
```

Every channel returns `RetrievalCandidate(channel, unit_id, rank, score?)`. Rank starts at 1; score is diagnostic and never added across channels. The orchestrator rejects unknown IDs and unlinked evidence. For RRF, sum `1/(k+rank)` once per unique `(channel, unit_id)`; ties use `unit_id` for reproducibility. A failed channel is logged and reported, not silently treated as a successful empty result. Future graph traversal must be bounded (provisional maximum two hops) and return a linked unit, not an unsupported triple. Generation receives resolved evidence rather than database objects.

The backend will own ingestion/status/query endpoints; the UI calls that boundary. No API/UI or orchestration code is in this milestone. The hypothesis that hybrid retrieval helps remains for controlled evaluation.
