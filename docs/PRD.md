# Product requirements (P0/P1 baseline)

## Objective and status

Answer questions about heterogeneous videos with auditable, source-linked evidence. The research question is whether dense + BM25 + graph retrieval improves evidence retrieval and grounded answering over each channel alone. Improvement remains **unmeasured**.

**Accepted V1 architecture:** canonical domain-neutral Pydantic records; independent offline extraction/indexing; online dense, BM25 and persistent Neo4j graph channels converging on retrieval-unit IDs; deduplication and RRF; evidence validation and explicit insufficient-evidence answers; FastAPI backend and initial Streamlit UI. Media and source records are the authority; every index is rebuildable.

**Delivered foundation:** validated asset, temporal span, speech/OCR/frame observations, unit, evidence and candidate types; deterministic one-observation unit/evidence building; canonical JSON snapshots, explicit incomplete-evidence diagnostics and synthetic tests. This is deliberately smaller than the V1 product.

## V1 user path and acceptance targets

1. Register authorized video media, validate duration and source metadata, record extraction provenance.
2. Extract speech and sampled visual observations offline, persist canonical versioned records, derive units and build independent indexes.
3. Ask a question through FastAPI/Streamlit; each channel returns ranked `RetrievalCandidate` records, or an explicit channel failure.
4. Deduplicate by `unit_id`; use RRF over per-channel rank (initial `k=60`, provisional); resolve evidence before constructing answer context.
5. Return source-linked spans and only actually extracted frame references. When support is missing, say evidence is insufficient; do not invent times, imagery or confidence.

Acceptance for the later end-to-end pilot: two **authorized real videos** process repeatably; three independent retrieval channels yield resolvable unit IDs; answer responses identify actual evidence or abstain; comparative evaluation measures retrieval and answer grounding. The synthetic fixture here is not this pilot.

## Evaluation and decisions pending

Plan approximately 24 authorized English videos across six categories, about four per category and 3–15 minutes each, after a two-video pilot. Curate independently checked questions and evidence annotations before claiming performance. Compare dense, BM25, graph, pairwise and three-channel retrieval with fixed data, queries and metrics (Recall@k, MRR/nDCG, citation correctness, abstention and latency/cost). Report uncertainty and failed channel rates.

**Provisional choices:** Sentence Transformers + FAISS, BM25 implementation, model family, text unit granularity, RRF parameter, and sampled frame cadence. Freeze runtime ASR/vision/embedding models only after recording exact versions, licenses, hardware, cost and pilot measurements. ChatGPT reasoning settings are unrelated to these runtime choices.

**Open questions:** media authorization and licenses; final transcript segmentation; initial entity/event ontology; pilot hardware and deployment budget; answer-generation provider and acceptable latency. No open question blocks the current contracts.
