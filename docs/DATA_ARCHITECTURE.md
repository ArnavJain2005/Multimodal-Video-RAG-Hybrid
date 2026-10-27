# Canonical data and graph projection

## Source of truth and identity (implemented)

`CanonicalVideo(schema_version=1)` holds a `VideoAsset`, typed transcript/OCR/frame-description observations, retrieval units and evidence. JSON snapshots are saved atomically with validation under `<video_id>.json`; later storage can use a manifest plus one validated record per video. Saving a changed snapshot requires `replace=True`. Incomplete evidence raises `IncompleteEvidenceError` before writing by default; explicit `allow_incomplete=True` permits inspection, and `evidence_gaps` lists each missing link. Such records must not be indexed. Observations carry a provenance method, version and source locator. OCR and frame descriptions require a `frame_ref`; the fixture uses deliberately synthetic frame identifiers, while future ingestion must verify artifacts exist.

`video_id = vid_ + SHA256(domain-tagged canonical JSON of source media SHA256)`. Source URI changes alone do not change video identity. Observation ID hashes video ID, modality, microsecond span, text, provenance and language/frame reference. Unit ID hashes video ID, microsecond span, text and sorted observation IDs. Evidence ID hashes unit and observation IDs. All IDs include a versioned domain tag; changing content, model provenance or unit grouping changes its ID. Canonical JSON uses sorted keys, UTF-8 and compact separators for hashing. Duplicate IDs are rejected in one video. IDs are deterministic, content-based, and do not encode file paths as index row numbers.

Times are finite nonnegative seconds on the source timeline, with at most microsecond precision. `start_s <= end_s`; equal bounds represent an observed instant. Every span is checked against a known asset duration; if duration is unknown, a bound cannot yet be verified and media probing must occur before publish/index. A unit contains all referenced observation spans. Evidence mirrors its observation span and modality exactly; unit/observation/video references must resolve. A missing unit or a unit with an unlinked observation yields `EvidenceResolution(status="missing", reason=..., evidence=None)`; it has no fabricated time or frame. Resolution reports each referenced observation independently; future context construction must reject incomplete support.

### Important current limitations

The P0/P1 record validates in-video references. The builder requires a known duration and makes one unit per observation; composite windows and any rewriting policy remain unevaluated. Global registry checks across video records, source digest verification against actual bytes, observation truthfulness, frame artifact existence, and extraction coverage require ingestion. Unknown duration remains allowed in the contract for unprobed assets but cannot be built/indexed. IDs are version 1; migration must explicitly rebuild indexes and record the old/new mapping.

## Neo4j projection (accepted persistent graph, implementation pending)

| Node | Unique key | Source |
| --- | --- | --- |
| `Video` | `video_id` | canonical asset |
| `Observation` | `observation_id` | canonical typed observation |
| `RetrievalUnit` | `unit_id` | canonical unit |
| `Evidence` | `evidence_id` | canonical evidence |
| `Entity` | `(ontology_version, normalized_type, normalized_name)` | future extracted candidate, never assumed globally identical without normalization |

Structure: `(Video)-[:HAS_OBSERVATION]->(Observation)`, `(Video)-[:HAS_UNIT]->(RetrievalUnit)`, `(RetrievalUnit)-[:GROUNDED_IN]->(Evidence)`, `(Evidence)-[:FROM_OBSERVATION]->(Observation)`. `Observation` stores `start_us`, `end_us`, `modality`, source locator and provenance version; `Evidence` carries the canonical time and modality. A semantic `(Entity)-[:OBSERVED_IN {claim_id, extractor_version}]->(Observation)` edge requires a separately recorded extraction claim and an evidence link. Edge `claim_id` is a versioned hash of type, endpoints and provenance; duplicate claims merge by ID rather than multiplying on rebuild. No domain-specific recipes, unsupported event chronology, or ungrounded entity facts are implied.

Apply Neo4j uniqueness constraints to node keys and use transactional `MERGE` per canonical ID; rebuild a projection into a new generation from validated canonical snapshots, then switch query generation. Graph retrieval must traverse through `Evidence` and return a `unit_id`. This document defines the schema; no Neo4j process or Cypher has been run.

Dense and lexical indexes likewise store `unit_id` mappings rather than owning content. Their model/tokenizer and snapshot versions belong in rebuild manifests, not in `VideoAsset`. Scores across channels are not calibrated; fusion uses ranks.
