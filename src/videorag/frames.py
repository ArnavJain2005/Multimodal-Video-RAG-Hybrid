"""Verified offline frame sampling from registered media; no visual inference."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from pydantic import Field, model_validator

from .contracts import Contract, TemporalSpan, stable_id
from .ingestion import MediaRecord, _fingerprint, _sha256, load_media_manifest


SAMPLER_VERSION = "native-pts-min-gap-v1"
_PTS = re.compile(r"\bpts_time:([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")
_FRAME_NAME = re.compile(r"^frame-\d{6}\.png$")


class FrameExtractionError(ValueError):
    """Media or its extracted frame artifacts could not be verified."""


def _sha256_bytes(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _gap_us(gap_s: float) -> int:
    try:
        value = Decimal(str(gap_s))
        micros = value * 1_000_000
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("sampling gap must be a finite positive number of microseconds") from exc
    if not value.is_finite() or value <= 0 or micros != micros.to_integral_value():
        raise ValueError("sampling gap must be finite, positive and at most microsecond precision")
    return int(micros)


class FrameArtifact(Contract):
    frame_id: str
    video_id: str
    sampler_id: str
    timestamp_s: float
    source_pts_s: float  # Unshifted presentation timestamp from the source stream.
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    relative_path: str

    @model_validator(mode="after")
    def identity(self) -> FrameArtifact:
        span = TemporalSpan(start_s=self.timestamp_s, end_s=self.timestamp_s)
        if not math.isfinite(self.source_pts_s):
            raise ValueError("source PTS must be finite")
        if not _FRAME_NAME.fullmatch(self.relative_path) or PurePosixPath(self.relative_path).name != self.relative_path:
            raise ValueError("frame path must be a generated PNG basename")
        expected = stable_id("frame", {"video_id": self.video_id, "sampler_id": self.sampler_id,
                                       "timestamp_us": span.key()[0], "sha256": self.sha256})
        if self.frame_id != expected:
            raise ValueError("frame identity does not match source and extracted bytes")
        return self

    @classmethod
    def build(cls, video_id: str, sampler_id: str, timestamp_s: float,
              source_pts_s: float, sha256: str, relative_path: str) -> FrameArtifact:
        instant = TemporalSpan(start_s=timestamp_s, end_s=timestamp_s).key()[0]
        frame_id = stable_id("frame", {"video_id": video_id, "sampler_id": sampler_id,
                                       "timestamp_us": instant, "sha256": sha256})
        return cls(frame_id=frame_id, video_id=video_id, sampler_id=sampler_id,
                   timestamp_s=timestamp_s, source_pts_s=source_pts_s,
                   sha256=sha256, relative_path=relative_path)


class FrameManifest(Contract):
    schema_version: int = Field(default=1, ge=1, le=1)
    video_id: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_uri: str
    stream_start_pts_s: float
    sampler_id: str
    sampler_version: str
    gap_s: float
    ffmpeg_version: str
    frames: tuple[FrameArtifact, ...]

    @model_validator(mode="after")
    def consistent(self) -> FrameManifest:
        _gap_us(self.gap_s)
        if self.sampler_version != SAMPLER_VERSION or not self.source_uri or not self.ffmpeg_version:
            raise ValueError("unsupported sampler or missing provenance")
        expected = stable_id("sampler", {"version": SAMPLER_VERSION,
                                          "gap_us": _gap_us(self.gap_s),
                                          "ffmpeg_version": self.ffmpeg_version})
        if self.sampler_id != expected:
            raise ValueError("sampler identity does not match configuration")
        if not math.isfinite(self.stream_start_pts_s):
            raise ValueError("stream start PTS must be finite")
        times = [f.timestamp_s for f in self.frames]
        ids = [f.frame_id for f in self.frames]
        paths = [f.relative_path for f in self.frames]
        if not times or times != sorted(set(times)) or len(ids) != len(set(ids)):
            raise ValueError("frame timestamps and identities must be unique and ordered")
        if any((Decimal(str(later)) - Decimal(str(earlier))) * 1_000_000 < _gap_us(self.gap_s)
               for earlier, later in zip(times, times[1:])):
            raise ValueError("selected frames violate the minimum sampling gap")
        if paths != [f"frame-{n:06d}.png" for n in range(1, len(paths) + 1)]:
            raise ValueError("frame paths must match extraction order")
        if any(f.video_id != self.video_id or f.sampler_id != self.sampler_id for f in self.frames):
            raise ValueError("foreign frame in manifest")
        if any(abs((f.source_pts_s - self.stream_start_pts_s) - f.timestamp_s) > 1e-7
               for f in self.frames):
            raise ValueError("frame timeline does not match stream start PTS")
        return self


@dataclass(frozen=True)
class FrameExtractionResult:
    manifest: FrameManifest
    directory: Path
    reused: bool


def _verified_source(record: MediaRecord) -> Path:
    verified = [s.uri for s in record.sources if s.status == "verified"]
    if not verified:
        raise FrameExtractionError("no verified source for registered video")
    parsed = urlparse(verified[0])
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        raise FrameExtractionError("frame extraction requires a local file source")
    path = Path(unquote(parsed.path))
    try:
        before = _fingerprint(path)
        digest = _sha256(path)
        after = _fingerprint(path)
    except OSError as exc:
        raise FrameExtractionError("registered source is unavailable") from exc
    if before != after or digest != record.asset.sha256 or before[2] != record.size_bytes:
        raise FrameExtractionError("registered source bytes changed; register it again")
    return path


def _ffmpeg_version(ffmpeg_bin: str, timeout_s: float) -> str:
    try:
        result = subprocess.run([ffmpeg_bin, "-version"], capture_output=True,
                                text=True, timeout=timeout_s, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FrameExtractionError("ffmpeg unavailable or timed out") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise FrameExtractionError("ffmpeg version could not be determined")
    return result.stdout.splitlines()[0]


def _stream_start_pts(source: Path, stream_index: int,
                      ffprobe_bin: str, timeout_s: float) -> Decimal:
    try:
        result = subprocess.run([ffprobe_bin, "-v", "error", "-show_entries",
                                 "stream=index,start_time", "-of", "json", str(source)],
                                capture_output=True, text=True, timeout=timeout_s, check=False)
        if result.returncode != 0:
            raise FrameExtractionError("ffprobe could not read stream start time")
        streams = json.loads(result.stdout)["streams"]
        value = next(stream["start_time"] for stream in streams
                     if stream["index"] == stream_index)
        origin = Decimal(str(value))
    except (OSError, subprocess.TimeoutExpired, KeyError, StopIteration,
            ValueError, InvalidOperation, TypeError) as exc:
        raise FrameExtractionError("source stream start PTS is unavailable") from exc
    if not origin.is_finite() or origin * 1_000_000 != (origin * 1_000_000).to_integral_value():
        raise FrameExtractionError("source stream start PTS is not representable")
    return origin


def _validate_artifacts(directory: Path, manifest: FrameManifest, duration_s: float) -> None:
    for artifact in manifest.frames:
        if not TemporalSpan(start_s=artifact.timestamp_s,
                            end_s=artifact.timestamp_s).within(duration_s):
            raise FrameExtractionError("decoded frame timestamp exceeds video duration")
        path = directory / artifact.relative_path
        try:
            digest = _sha256_bytes(path)
        except OSError as exc:
            raise FrameExtractionError("frame artifact is missing or unreadable") from exc
        if digest != artifact.sha256:
            raise FrameExtractionError("frame artifact hash mismatch")


def sample_frames(manifest_path: Path | str, video_id: str, output_root: Path | str, *,
                  gap_s: float = 4.0, ffmpeg_bin: str = "ffmpeg",
                  ffprobe_bin: str = "ffprobe",
                  timeout_s: float = 600) -> FrameExtractionResult:
    """Select native frames at least `gap_s` apart and record their decoded PTS.

    Existing output is reused only after source and every artifact are revalidated.
    No transcript, OCR, caption or retrieval unit is inferred from a frame.
    """
    gap_us = _gap_us(gap_s)
    records = load_media_manifest(manifest_path).records
    record = next((r for r in records if r.asset.video_id == video_id), None)
    if record is None:
        raise KeyError(f"unknown registered video: {video_id}")
    source = _verified_source(record)
    if record.asset.duration_s is None:
        raise FrameExtractionError("registered video has no known duration")
    stream_start = _stream_start_pts(source, record.video_stream_index, ffprobe_bin, timeout_s)
    version = _ffmpeg_version(ffmpeg_bin, timeout_s)
    sampler_id = stable_id("sampler", {"version": SAMPLER_VERSION,
                                       "gap_us": gap_us, "ffmpeg_version": version})
    destination = Path(output_root) / video_id / sampler_id
    manifest_file = destination / "manifest.json"
    if destination.exists():
        if not manifest_file.is_file():
            raise FrameExtractionError("existing frame directory has no valid manifest")
        manifest = FrameManifest.model_validate_json(manifest_file.read_bytes())
        if (manifest.video_id != video_id or manifest.source_sha256 != record.asset.sha256
                or manifest.sampler_id != sampler_id):
            raise FrameExtractionError("existing frame manifest does not match registered source")
        _validate_artifacts(destination, manifest, record.asset.duration_s)
        return FrameExtractionResult(manifest, destination, reused=True)

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".frame-stage-", dir=destination.parent))
    try:
        gap_text = format(Decimal(gap_us) / 1_000_000, "f")
        filter_expression = ("select=isnan(prev_selected_t)+gte(t-prev_selected_t\\,"
                             + gap_text + "),showinfo")
        command = [ffmpeg_bin, "-hide_banner", "-nostdin", "-loglevel", "info", "-copyts",
                   "-i", str(source), "-map", f"0:{record.video_stream_index}", "-an",
                   "-vf", filter_expression, "-fps_mode", "vfr", "-c:v", "png",
                   str(staging / "frame-%06d.png")]
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=timeout_s, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FrameExtractionError("ffmpeg extraction unavailable or timed out") from exc
        if result.returncode != 0:
            raise FrameExtractionError(f"ffmpeg frame extraction failed: {result.stderr[-300:]}")
        timestamps: list[tuple[float, float]] = []
        for line in result.stderr.splitlines():
            if "Parsed_showinfo" not in line:
                continue
            match = _PTS.search(line)
            if match:
                try:
                    pts = Decimal(match.group(1))
                    micros = pts * 1_000_000
                    if not pts.is_finite() or micros != micros.to_integral_value():
                        raise InvalidOperation
                    relative = pts - stream_start
                    if relative * 1_000_000 != (relative * 1_000_000).to_integral_value():
                        raise InvalidOperation
                    timestamp, source_pts = float(relative), float(pts)
                    if not math.isfinite(timestamp) or not math.isfinite(source_pts):
                        raise InvalidOperation
                except (InvalidOperation, OverflowError) as exc:
                    raise FrameExtractionError("decoded frame PTS is not representable") from exc
                timestamps.append((timestamp, source_pts))
        files = sorted(staging.glob("frame-*.png"))
        if not files or len(files) != len(timestamps):
            raise FrameExtractionError("decoded frames and reported PTS do not match")
        frames = tuple(FrameArtifact.build(video_id, sampler_id, timestamp, source_pts,
                                           _sha256_bytes(path), path.name)
                       for (timestamp, source_pts), path in zip(timestamps, files))
        manifest = FrameManifest(video_id=video_id, source_sha256=record.asset.sha256,
                                 source_uri=source.as_uri(), stream_start_pts_s=float(stream_start),
                                 sampler_id=sampler_id,
                                 sampler_version=SAMPLER_VERSION, gap_s=float(Decimal(gap_us) / 1_000_000),
                                 ffmpeg_version=version, frames=frames)
        _validate_artifacts(staging, manifest, record.asset.duration_s)
        if _verified_source(record) != source:
            raise FrameExtractionError("registered source changed during frame extraction")
        payload = (json.dumps(manifest.model_dump(mode="json"), sort_keys=True,
                              ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        (staging / "manifest.json").write_bytes(payload)
        os.replace(staging, destination)
        return FrameExtractionResult(manifest, destination, reused=False)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
