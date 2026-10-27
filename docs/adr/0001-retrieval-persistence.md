# ADR 0001: retrieval and persistence boundaries

**Status:** Accepted architecture; index technology and ranking parameters provisional. **Date:** 2026-10-27.

## Decision

Canonical Pydantic/JSON video records own media identity, timeline, observations, units and evidence. Offline builders independently project the same stable `unit_id` set into a dense index, BM25 corpus and persistent Neo4j graph. Online channels return ranked `RetrievalCandidate` records; orchestration deduplicates, applies RRF and resolves canonical evidence before generation. FastAPI is the backend boundary; Streamlit uses the API. Neo4j, not NetworkX, is the persistent graph design.

## Why and consequences

The cooking reference mixes video-level BM25, frame/text dense chunks and graph triples without shared evidence IDs. A common unit/evidence contract makes retrieval and citation auditable, and reindexing possible without changing source records. This adds explicit schema versioning, transactional graph projection and migration work. Rank fusion avoids treating unlike channel scores as probabilities. Any answer lacking valid evidence must abstain.

## Provisional implementation choices

Sentence Transformers/FAISS and BM25 are candidates. Initial RRF `k=60` and graph maximum two hops are defaults to measure, not tuned results. RAG-Anything processors may be tested later behind extraction adapters; no code/media is copied from the unlicensed cooking reference. Runtime model versions, resource needs, license and quality/cost measurements remain a pilot decision.
