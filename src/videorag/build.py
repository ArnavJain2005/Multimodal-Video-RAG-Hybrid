"""Deterministic P1 projection from validated observations to retrieval units."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import (CanonicalVideo, Evidence, Observation, RetrievalUnit,
                        VideoAsset)


def build_canonical_video(asset: VideoAsset,
                          observations: Iterable[Observation]) -> CanonicalVideo:
    """Build one independent unit per observation, ordered by source time and ID.

    Composite windows and text rewriting are deferred until an evaluated policy exists.
    The builder requires a known duration, because an unprobed timeline cannot be indexed.
    """
    if asset.duration_s is None:
        raise ValueError("a known video duration is required to build retrieval units")
    validated_asset = VideoAsset.model_validate(asset.model_dump())
    validated = tuple(type(obs).model_validate(obs.model_dump()) for obs in observations)
    ordered = tuple(sorted(validated, key=lambda obs: (
        obs.span.key()[0], obs.span.key()[1], obs.observation_id)))
    units = tuple(RetrievalUnit.build(validated_asset.video_id, obs.span, obs.text,
                                      (obs.observation_id,)) for obs in ordered)
    evidence = tuple(Evidence.build(unit, obs) for unit, obs in zip(units, ordered))
    # JSON validation rechecks nested fields, including identities and timeline bounds.
    draft = CanonicalVideo(asset=validated_asset, observations=ordered,
                           units=units, evidence=evidence)
    return CanonicalVideo.model_validate_json(draft.model_dump_json())
