"""Domain-independent contracts for multimodal video retrieval."""

from .contracts import (CanonicalVideo, Evidence, EvidenceResolution, FrameDescription,
                        Modality, OCRObservation, Provenance, RetrievalCandidate,
                        RetrievalUnit, TemporalSpan, TranscriptSpan, VideoAsset,
                        make_observation)
from .build import build_canonical_video
from .persistence import (EvidenceGap, IncompleteEvidenceError, evidence_gaps,
                          load_canonical_video, save_canonical_video)
from .ingestion import (MediaManifest, MediaRecord, MediaSource, MediaValidationError,
                        RegistrationResult, load_media_manifest, register_video,
                        set_processing_status)

__all__ = ["CanonicalVideo", "Evidence", "EvidenceResolution", "FrameDescription",
           "Modality", "OCRObservation", "Provenance", "RetrievalCandidate",
           "RetrievalUnit", "TemporalSpan", "TranscriptSpan", "VideoAsset",
           "make_observation"]
__all__ += ["build_canonical_video", "EvidenceGap", "IncompleteEvidenceError",
            "evidence_gaps", "load_canonical_video", "save_canonical_video"]
__all__ += ["MediaManifest", "MediaRecord", "MediaSource", "MediaValidationError",
            "RegistrationResult", "load_media_manifest", "register_video",
            "set_processing_status"]
