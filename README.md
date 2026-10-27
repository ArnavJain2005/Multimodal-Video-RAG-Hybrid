# Multimodal Video RAG using Hybrid Vector and Knowledge Graph Retrieval

An independent, domain-agnostic foundation for video evidence retrieval. **Current status:** typed canonical records, deterministic one-observation retrieval units, validated JSON snapshots, local video registration with probed duration and streamed SHA-256, a media manifest, explicit evidence-gap reporting, and tests using generated clips. No ASR/vision extraction, retriever, live database, API, UI, inference, or evaluated quality is implemented yet.

## Run the milestone

Python 3.11+ is required. From this directory:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

Media tests need `ffmpeg` and `ffprobe` on `PATH` and create small clips in a temporary directory. The other tests construct two invented video records in memory; `synthetic://` locators do not point to media. Neither fixture is benchmark ground truth. GitHub Actions runs the suite on Python 3.11 and 3.12.

## Register local video media

```python
from videorag import register_video, load_media_manifest

result = register_video("/path/to/authorized-video.mp4", "data/media_manifest.json")
print(result.record.asset.video_id, result.record.asset.duration_s, result.duplicate)
print(load_media_manifest("data/media_manifest.json").records)
```

Registration verifies a real video stream and duration with `ffprobe`, streams the file's SHA-256, and atomically records the asset, source URIs, technical metadata and `registered` processing status. The same bytes retain one video ID across file paths. When bytes change at a previously registered path, that path is marked `superseded` on the old identity and `verified` on the new one. `set_processing_status` records subsequent processing/failure states. This is a single-writer local manifest; sources are checked at registration time and must be revalidated before later processing if files may have moved or changed. Media and manifest files are ignored by git.

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
- `src/videorag/ingestion.py`: local video verification, identity registration and status manifest.
- `tests/`: synthetic two-video examples and validation checks.
- `docs/PRD.md`: scope and acceptance boundaries.
- `docs/SYSTEM_ARCHITECTURE.md`: offline and online responsibilities.
- `docs/DATA_ARCHITECTURE.md`: identity, time, provenance and Neo4j projection schema.
- `docs/adr/0001-retrieval-persistence.md`: accepted boundaries and provisional choices.

This project is independently written. The cooking-video reference at revision `7cd5c83cd6eb9f008f6c742405045ad2dc3acfbd` informed failure cases; its code and media are not included. The draft internship report describes a different state from the checked-in reference artifacts, so neither supplies ground truth for this implementation. The optional RAG-Anything video/audio processors can be evaluated as a future ingestion adapter; they do not define our canonical or retrieval contracts.
