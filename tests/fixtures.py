"""Invented contract examples, not media or benchmark annotations."""

import hashlib

from videorag import (CanonicalVideo, Evidence, FrameDescription, OCRObservation,
                      Provenance, RetrievalUnit, TemporalSpan, TranscriptSpan,
                      VideoAsset, make_observation)


def synthetic_videos() -> tuple[CanonicalVideo, CanonicalVideo]:
    records = []
    for n in (1, 2):
        asset = VideoAsset.build(hashlib.sha256(f"synthetic-video-{n}".encode()).hexdigest(),
                                 f"synthetic://video-{n}", 30.0)
        speech = make_observation(TranscriptSpan, video_id=asset.video_id,
            span=TemporalSpan(start_s=1.0, end_s=2.5),
            text=("The blue robot begins moving" if n == 1 else "The sensor test starts"),
            provenance=Provenance(method="synthetic", version="1", source_locator="audio-track"),
            language="en")
        ocr = make_observation(OCRObservation, video_id=asset.video_id,
            span=TemporalSpan(start_s=8.0, end_s=8.0),
            text=("READY" if n == 1 else "42 C"),
            provenance=Provenance(method="synthetic", version="1", source_locator="frame-8"),
            frame_ref=f"synthetic-frame-{n}-8")
        visual = make_observation(FrameDescription, video_id=asset.video_id,
            span=TemporalSpan(start_s=12.0, end_s=12.0),
            text=("A blue robot crosses a line" if n == 1 else "A gauge is visible"),
            provenance=Provenance(method="synthetic", version="1", source_locator="frame-12"),
            frame_ref=f"synthetic-frame-{n}-12")
        observations = (speech, ocr, visual)
        units = tuple(RetrievalUnit.build(asset.video_id, obs.span, obs.text,
                                          (obs.observation_id,)) for obs in observations)
        evidence = tuple(Evidence.build(unit, obs) for unit, obs in zip(units, observations))
        records.append(CanonicalVideo(asset=asset, observations=observations,
                                      units=units, evidence=evidence))
    return tuple(records)
