# Multimodal Video RAG using Hybrid Vector and Knowledge Graph Retrieval

An independent, domain-agnostic foundation for video evidence retrieval. **Current status:** typed canonical records, deterministic one-observation retrieval units, validated JSON snapshots, stable identities, explicit evidence-gap reporting, a two-video synthetic fixture, and tests work locally. No media processing, retriever, live database, API, UI, inference, or evaluated quality is implemented yet.

## Run the milestone

Python 3.11+ is required. From this directory:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

The tests construct two invented video records in memory; `synthetic://` locators do not point to media. The fixture is a contract check, not benchmark ground truth.

## Canonical snapshot example

```python
from videorag import build_canonical_video, save_canonical_video, load_canonical_video

# asset: a VideoAsset with a known duration; observations: validated source observations
record = build_canonical_video(asset, observations)
path = save_canonical_video("data/canonical", record)
assert load_canonical_video(path) == record
```

The builder makes one unit and evidence link per observation, sorted by time and ID. Saving rejects missing links by default and will not overwrite a changed snapshot unless `replace=True`. For inspecting partial records, use `allow_incomplete=True` explicitly and call `evidence_gaps(record)`; such records are not ready for indexing.

## Source map

- `src/videorag/contracts.py`: Pydantic video, observations, retrieval units, evidence and candidate contract.
- `src/videorag/build.py`, `persistence.py`: deterministic projection and atomic, validated JSON snapshots.
- `tests/`: synthetic two-video examples and validation checks.
- `docs/PRD.md`: scope and acceptance boundaries.
- `docs/SYSTEM_ARCHITECTURE.md`: offline and online responsibilities.
- `docs/DATA_ARCHITECTURE.md`: identity, time, provenance and Neo4j projection schema.
- `docs/adr/0001-retrieval-persistence.md`: accepted boundaries and provisional choices.

This project is independently written. The cooking-video reference at revision `7cd5c83cd6eb9f008f6c742405045ad2dc3acfbd` informed failure cases; its code and media are not included. The draft internship report describes a different state from the checked-in reference artifacts, so neither supplies ground truth for this implementation. The optional RAG-Anything video/audio processors can be evaluated as a future ingestion adapter; they do not define our canonical or retrieval contracts.
