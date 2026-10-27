"""Canonical, storage-independent video evidence contracts (schema version 1)."""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Text = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def stable_id(prefix: str, payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{prefix}_{hashlib.sha256((prefix + ':v1:' + encoded).encode('utf-8')).hexdigest()}"


def _micros(value: float) -> int:
    if not math.isfinite(value) or value < 0:
        raise ValueError("time must be finite and nonnegative")
    micros = round(value * 1_000_000)
    if not math.isclose(value, micros / 1_000_000, rel_tol=0, abs_tol=1e-10):
        raise ValueError("time precision must be at most one microsecond")
    return micros


class TemporalSpan(Contract):
    """Seconds on the source timeline; equal bounds denote an observed instant."""

    start_s: float
    end_s: float

    @model_validator(mode="after")
    def ordered(self) -> TemporalSpan:
        if _micros(self.start_s) > _micros(self.end_s):
            raise ValueError("start must not exceed end")
        return self

    def within(self, duration_s: float | None) -> bool:
        return duration_s is None or _micros(self.end_s) <= _micros(duration_s)

    def key(self) -> list[int]:
        return [_micros(self.start_s), _micros(self.end_s)]


class VideoAsset(Contract):
    video_id: str
    sha256: Digest
    source_uri: Text
    duration_s: float | None = None

    @model_validator(mode="after")
    def valid(self) -> VideoAsset:
        if self.duration_s is not None and _micros(self.duration_s) <= 0:
            raise ValueError("known duration must be positive")
        if self.video_id != stable_id("vid", {"sha256": self.sha256}):
            raise ValueError("video_id does not match source digest")
        return self

    @classmethod
    def build(cls, sha256: str, source_uri: str, duration_s: float | None) -> VideoAsset:
        return cls(video_id=stable_id("vid", {"sha256": sha256}), sha256=sha256,
                   source_uri=source_uri, duration_s=duration_s)


class Provenance(Contract):
    method: Text
    version: Text
    source_locator: Text  # e.g. source media + track or frame artifact identifier


class Modality(StrEnum):
    SPEECH = "speech"
    OCR = "ocr"
    FRAME_DESCRIPTION = "frame_description"


class Observation(Contract):
    observation_id: str
    video_id: Text
    span: TemporalSpan
    text: Text
    provenance: Provenance

    @property
    def modality(self) -> Modality:
        raise NotImplementedError

    @model_validator(mode="after")
    def identity(self) -> Observation:
        expected = stable_id("obs", observation_identity(self.modality, self.video_id,
            self.span, self.text, self.provenance, self._qualifier()))
        if self.observation_id != expected:
            raise ValueError("observation_id does not match content")
        return self

    def _qualifier(self) -> dict[str, str]:
        raise NotImplementedError


class TranscriptSpan(Observation):
    kind: Literal["transcript"] = "transcript"
    language: Text

    @property
    def modality(self) -> Modality:
        return Modality.SPEECH

    def _qualifier(self) -> dict[str, str]:
        return {"language": self.language}


class OCRObservation(Observation):
    kind: Literal["ocr"] = "ocr"
    frame_ref: Text  # identifier of an actually extracted source frame

    @property
    def modality(self) -> Modality:
        return Modality.OCR

    def _qualifier(self) -> dict[str, str]:
        return {"frame_ref": self.frame_ref}


class FrameDescription(Observation):
    kind: Literal["frame_description"] = "frame_description"
    frame_ref: Text

    @property
    def modality(self) -> Modality:
        return Modality.FRAME_DESCRIPTION

    def _qualifier(self) -> dict[str, str]:
        return {"frame_ref": self.frame_ref}


ObservationType = Annotated[TranscriptSpan | OCRObservation | FrameDescription,
                            Field(discriminator="kind")]


def observation_identity(modality: Modality, video_id: str, span: TemporalSpan,
                         text: str, provenance: Provenance, qualifier: dict[str, str]) -> dict:
    return {"video_id": video_id, "modality": modality.value, "span_us": span.key(),
            "text": text, "provenance": provenance.model_dump(), **qualifier}


def make_observation(cls: type[Observation], *, video_id: str, span: TemporalSpan,
                     text: str, provenance: Provenance, **fields: str) -> Observation:
    modality = {TranscriptSpan: Modality.SPEECH, OCRObservation: Modality.OCR,
                FrameDescription: Modality.FRAME_DESCRIPTION}[cls]
    observation_id = stable_id("obs", observation_identity(modality, video_id, span,
                                                            text, provenance, fields))
    return cls(observation_id=observation_id, video_id=video_id, span=span,
               text=text, provenance=provenance, **fields)


class RetrievalUnit(Contract):
    unit_id: str
    video_id: Text
    span: TemporalSpan
    text: Text
    observation_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def identity(self) -> RetrievalUnit:
        if len(set(self.observation_ids)) != len(self.observation_ids):
            raise ValueError("duplicate observation references")
        expected = stable_id("unit", {"video_id": self.video_id, "span_us": self.span.key(),
            "text": self.text, "observation_ids": sorted(self.observation_ids)})
        if self.unit_id != expected:
            raise ValueError("unit_id does not match content")
        return self

    @classmethod
    def build(cls, video_id: str, span: TemporalSpan, text: str,
              observation_ids: tuple[str, ...]) -> RetrievalUnit:
        unit_id = stable_id("unit", {"video_id": video_id, "span_us": span.key(),
            "text": text, "observation_ids": sorted(observation_ids)})
        return cls(unit_id=unit_id, video_id=video_id, span=span, text=text,
                   observation_ids=observation_ids)


class Evidence(Contract):
    evidence_id: str
    unit_id: Text
    observation_id: Text
    video_id: Text
    span: TemporalSpan
    modality: Modality

    @model_validator(mode="after")
    def identity(self) -> Evidence:
        if self.evidence_id != stable_id("ev", {"unit_id": self.unit_id,
                                             "observation_id": self.observation_id}):
            raise ValueError("evidence_id does not match references")
        return self

    @classmethod
    def build(cls, unit: RetrievalUnit, observation: Observation) -> Evidence:
        return cls(evidence_id=stable_id("ev", {"unit_id": unit.unit_id,
                                               "observation_id": observation.observation_id}),
                   unit_id=unit.unit_id, observation_id=observation.observation_id,
                   video_id=observation.video_id, span=observation.span,
                   modality=observation.modality)


class EvidenceResolution(Contract):
    status: Literal["present", "missing"]
    evidence: Evidence | None = None
    observation_id: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def consistent(self) -> EvidenceResolution:
        if (self.status == "present") != (self.evidence is not None):
            raise ValueError("present status requires evidence")
        if (self.status == "missing") != (self.reason is not None):
            raise ValueError("missing status requires a reason")
        if self.evidence is not None and self.observation_id != self.evidence.observation_id:
            raise ValueError("resolved observation ID must match evidence")
        return self


class CanonicalVideo(Contract):
    schema_version: Literal[1] = 1
    asset: VideoAsset
    observations: tuple[ObservationType, ...]
    units: tuple[RetrievalUnit, ...]
    evidence: tuple[Evidence, ...]

    @model_validator(mode="after")
    def references(self) -> CanonicalVideo:
        obs = {o.observation_id: o for o in self.observations}
        units = {u.unit_id: u for u in self.units}
        evs = {e.evidence_id: e for e in self.evidence}
        if len(obs) != len(self.observations) or len(units) != len(self.units) or len(evs) != len(self.evidence):
            raise ValueError("duplicate canonical IDs")
        for item in (*self.observations, *self.units, *self.evidence):
            if item.video_id != self.asset.video_id or not item.span.within(self.asset.duration_s):
                raise ValueError("foreign video or out-of-bounds span")
        for unit in self.units:
            for oid in unit.observation_ids:
                observation = obs.get(oid)
                if observation is None or unit.span.start_s > observation.span.start_s or unit.span.end_s < observation.span.end_s:
                    raise ValueError("unit does not contain a referenced observation")
        for ev in self.evidence:
            unit, observation = units.get(ev.unit_id), obs.get(ev.observation_id)
            if unit is None or observation is None or ev.observation_id not in unit.observation_ids:
                raise ValueError("evidence references an unrelated or missing record")
            if ev.span != observation.span or ev.modality != observation.modality:
                raise ValueError("evidence must mirror its observation")
        return self

    def resolve(self, unit_id: str) -> tuple[EvidenceResolution, ...]:
        unit = next((u for u in self.units if u.unit_id == unit_id), None)
        if unit is None:
            return (EvidenceResolution(status="missing", reason="unknown retrieval unit"),)
        by_observation = {e.observation_id: e for e in self.evidence if e.unit_id == unit_id}
        return tuple(EvidenceResolution(status="present", evidence=by_observation[oid],
                                       observation_id=oid) if oid in by_observation else
                     EvidenceResolution(status="missing", observation_id=oid,
                                        reason="no linked evidence") for oid in unit.observation_ids)


class RetrievalCandidate(Contract):
    """Shared channel output; scores are only comparable within a channel."""

    channel: Literal["dense", "bm25", "graph"]
    unit_id: Text
    rank: Annotated[int, Field(ge=1)]
    score: float | None = None

    @model_validator(mode="after")
    def finite_score(self) -> RetrievalCandidate:
        if self.score is not None and not math.isfinite(self.score):
            raise ValueError("score must be finite")
        return self
