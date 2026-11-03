"""Sample verified source frames without making visual claims about their content."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Digest, TemporalSpan, Text, stable_id
from .ingestion import MediaRecord, MediaValidationError


class FrameExtractionError(ValueError):
    """The registered source could not produce the requested frames."""


class FrameArtifact(Contract):
    frame_ref: str
    video_id: str
    span: TemporalSpan
    sha256: Digest
    filename: str = Field(pattern=r"^frame_[0-9a-f]{64}\.png$")

    @model_validator(mode="after")
    def identity(self) -> FrameArtifact:
        expected = stable_id("frame", {"video_id": self.video_id,
                                       "span_us": self.span.key(), "sha256": self.sha256})
        if self.frame_ref != expected or self.filename != f"{expected}.png":
            raise ValueError("frame identity does not match content")
        if self.span.start_s != self.span.end_s:
            raise ValueError("a sampled frame must be an instant")
        return self


class FrameManifest(Contract):
    schema_version: Literal[1] = 1
    video_id: str
    source_sha256: Digest
    stream_index: int = Field(ge=0)
    cadence_us: int = Field(gt=0)
    ffmpeg_version: Text
    artifacts: tuple[FrameArtifact, ...]

    @model_validator(mode="after")
    def consistent(self) -> FrameManifest:
        if self.video_id != stable_id("vid", {"sha256": self.source_sha256}):
            raise ValueError("frame manifest video ID does not match source digest")
        if any(a.video_id != self.video_id for a in self.artifacts):
            raise ValueError("foreign frame in manifest")
        spans = [a.span.key()[0] for a in self.artifacts]
        if spans != [i * self.cadence_us for i in range(len(spans))]:
            raise ValueError("frame times must follow the declared cadence")
        return self


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_path(record: MediaRecord, file_path: Path | str) -> Path:
    path = Path(file_path).resolve(strict=True)
    uri = path.as_uri()
    if not path.is_file() or not any(source.uri == uri and source.status == "verified"
                                     for source in record.sources):
        raise MediaValidationError("source is not a verified file for this video")
    return path


def _cadence_us(cadence_s: float) -> int:
    if (isinstance(cadence_s, bool) or not isinstance(cadence_s, (float, int))
            or not math.isfinite(cadence_s)):
        raise ValueError("cadence must be a finite positive number")
    microseconds = Decimal(str(cadence_s)) * 1_000_000
    if microseconds <= 0 or microseconds != microseconds.to_integral_value():
        raise ValueError("cadence must be positive with at most microsecond precision")
    return int(microseconds)


def load_frame_manifest(path: Path | str, *, verify_files: bool = True) -> FrameManifest:
    """Load the manifest; optionally verify each referenced PNG is present and unchanged."""
    source = Path(path)
    manifest = FrameManifest.model_validate_json(source.read_bytes())
    if verify_files:
        for artifact in manifest.artifacts:
            image = source.parent / artifact.filename
            if not image.is_file() or _sha256(image) != artifact.sha256:
                raise FrameExtractionError(f"missing or changed frame: {artifact.frame_ref}")
    return manifest


def sample_frames(record: MediaRecord, file_path: Path | str, output_dir: Path | str,
                  *, cadence_s: float = 5.0, max_frames: int = 1000,
                  ffmpeg_bin: str = "ffmpeg", timeout_s: float = 60) -> FrameManifest:
    """Extract PNG instants at 0, cadence, ... strictly before the registered duration.

    The manifest is written last. Each invocation checks source bytes before and after
    extraction; an existing different manifest requires a separate output directory.
    """
    checked = MediaRecord.model_validate_json(record.model_dump_json())
    cadence = _cadence_us(cadence_s)
    if isinstance(max_frames, bool) or not isinstance(max_frames, int) or max_frames < 1:
        raise ValueError("max_frames must be a positive integer")
    duration = checked.asset.duration_s
    if duration is None:
        raise MediaValidationError("registered video needs a known duration")
    duration_us = round(duration * 1_000_000)
    count = (duration_us - 1) // cadence + 1
    if count > max_frames:
        raise FrameExtractionError(f"sample count {count} exceeds max_frames {max_frames}")
    path = _source_path(checked, file_path)
    before = path.stat()
    if _sha256(path) != checked.asset.sha256:
        raise MediaValidationError("registered source bytes have changed")
    try:
        version = subprocess.run([ffmpeg_bin, "-version"], capture_output=True,
                                 text=True, timeout=timeout_s, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FrameExtractionError("ffmpeg unavailable or timed out") from exc
    if version.returncode != 0 or not version.stdout.strip():
        raise FrameExtractionError("ffmpeg version could not be determined")
    ffmpeg_version = version.stdout.splitlines()[0]

    directory = Path(output_dir) / checked.asset.video_id
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "frames.json"
    artifacts: list[FrameArtifact] = []
    with tempfile.TemporaryDirectory(prefix=".frames-", dir=directory) as temporary:
        staging = Path(temporary)
        for tick in range(count):
            micros = tick * cadence
            image = staging / f"{tick:06d}.png"
            try:
                result = subprocess.run(
                    [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                     "-i", str(path), "-ss", f"{micros / 1_000_000:.6f}",
                     "-map", f"0:{checked.video_stream_index}", "-frames:v", "1",
                     "-f", "image2", str(image)],
                    capture_output=True, text=True, timeout=timeout_s, check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise FrameExtractionError(f"ffmpeg unavailable or timed out at {micros} us") from exc
            if result.returncode != 0 or not image.is_file() or image.stat().st_size == 0:
                raise FrameExtractionError(f"ffmpeg failed to extract frame at {micros} us: "
                                           f"{result.stderr.strip()[:200]}")
            seconds = micros / 1_000_000
            span = TemporalSpan(start_s=seconds, end_s=seconds)
            digest = _sha256(image)
            frame_ref = stable_id("frame", {"video_id": checked.asset.video_id,
                                            "span_us": span.key(), "sha256": digest})
            artifacts.append(FrameArtifact(frame_ref=frame_ref, video_id=checked.asset.video_id,
                                           span=span, sha256=digest,
                                           filename=f"{frame_ref}.png"))

        after = path.stat()
        fingerprint = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if fingerprint(before) != fingerprint(after) or _sha256(path) != checked.asset.sha256:
            raise MediaValidationError("source changed during frame extraction")
        manifest = FrameManifest(video_id=checked.asset.video_id,
                                 source_sha256=checked.asset.sha256,
                                 stream_index=checked.video_stream_index, cadence_us=cadence,
                                 ffmpeg_version=ffmpeg_version,
                                 artifacts=tuple(artifacts))
        payload = (json.dumps(manifest.model_dump(mode="json"), sort_keys=True,
                              ensure_ascii=False, indent=2) + "\n").encode()
        if manifest_path.exists() and manifest_path.read_bytes() != payload:
            raise FrameExtractionError("existing frame manifest differs; use a new output directory")
        for tick, artifact in enumerate(artifacts):
            target = directory / artifact.filename
            if target.exists():
                if _sha256(target) != artifact.sha256:
                    raise FrameExtractionError(f"existing frame changed: {artifact.frame_ref}")
            else:
                os.replace(staging / f"{tick:06d}.png", target)
        if not manifest_path.exists():
            temporary_manifest = staging / "frames.json"
            temporary_manifest.write_bytes(payload)
            os.replace(temporary_manifest, manifest_path)
    return manifest
