"""Local media registration: verified bytes and probe data before canonical extraction."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, VideoAsset


class MediaValidationError(ValueError):
    """A file could not be validated as usable video media."""


class MediaSource(Contract):
    uri: str = Field(min_length=1)
    status: Literal["verified", "superseded"] = "verified"


class MediaRecord(Contract):
    asset: VideoAsset
    sources: tuple[MediaSource, ...]
    size_bytes: int = Field(gt=0)
    video_stream_index: int = Field(ge=0)
    codec_name: str | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    processing_status: Literal["registered", "processing", "processed", "failed"] = "registered"
    processing_error: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def consistent(self) -> MediaRecord:
        uris = [source.uri for source in self.sources]
        if not uris or len(uris) != len(set(uris)) or uris != sorted(uris):
            raise ValueError("sources must be nonempty, unique and ordered")
        if self.asset.source_uri not in uris:
            raise ValueError("original source must remain in the manifest")
        if (self.processing_status == "failed") != (self.processing_error is not None):
            raise ValueError("only failed processing may have a nonempty error")
        return self


class MediaManifest(Contract):
    schema_version: Literal[1]
    records: tuple[MediaRecord, ...]

    @model_validator(mode="after")
    def unique(self) -> MediaManifest:
        ids = [record.asset.video_id for record in self.records]
        if len(ids) != len(set(ids)) or ids != sorted(ids):
            raise ValueError("media records must have unique, ordered IDs")
        verified = [source.uri for record in self.records for source in record.sources
                    if source.status == "verified"]
        if len(verified) != len(set(verified)):
            raise ValueError("one verified source cannot point to two media identities")
        return self


@dataclass(frozen=True)
class RegistrationResult:
    record: MediaRecord
    manifest_path: Path
    duplicate: bool


def load_media_manifest(path: Path | str) -> MediaManifest:
    source = Path(path)
    return (MediaManifest.model_validate_json(source.read_bytes()) if source.exists()
            else MediaManifest(schema_version=1, records=()))


def _fingerprint(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positive_duration(value: object) -> float | None:
    try:
        duration = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not duration.is_finite() or duration <= 0:
        return None
    try:
        rounded = duration.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        seconds = float(rounded)
    except (InvalidOperation, OverflowError):
        return None
    return seconds if rounded > 0 and math.isfinite(seconds) else None


def _probe_video(path: Path, ffprobe_bin: str, timeout_s: float) -> tuple[float, int, str | None, int, int]:
    try:
        result = subprocess.run(
            [ffprobe_bin, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaValidationError(f"ffprobe unavailable or timed out: {exc}") from exc
    if result.returncode != 0:
        raise MediaValidationError(f"ffprobe rejected video: {result.stderr.strip()[:300]}")
    try:
        data = json.loads(result.stdout)
        streams = data["streams"]
        video = next(stream for stream in streams if stream.get("codec_type") == "video"
                     and not stream.get("disposition", {}).get("attached_pic"))
        width, height, index = int(video["width"]), int(video["height"]), int(video["index"])
        duration = _positive_duration(video.get("duration")) or _positive_duration(
            data.get("format", {}).get("duration"))
        if width <= 0 or height <= 0 or index < 0 or duration is None:
            raise ValueError("missing valid video dimensions, index or duration")
    except (KeyError, TypeError, ValueError, StopIteration, json.JSONDecodeError) as exc:
        raise MediaValidationError("no usable video stream with a known duration") from exc
    return duration, index, video.get("codec_name"), width, height


def _save_manifest(path: Path, manifest: MediaManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = MediaManifest.model_validate_json(manifest.model_dump_json())
    payload = (json.dumps(manifest.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
                          indent=2, allow_nan=False) + "\n").encode("utf-8")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".media-manifest-",
                                         suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def register_video(file_path: Path | str, manifest_path: Path | str, *,
                   ffprobe_bin: str = "ffprobe", timeout_s: float = 60) -> RegistrationResult:
    """Register local video bytes; repeat registration is idempotent.

    A reused path with different bytes supersedes its previous source association,
    while retaining both content identities for audit. Single-writer manifest v1.
    """
    path = Path(file_path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise MediaValidationError("source must be a nonempty local file")
    manifest_file = Path(manifest_path)
    manifest = load_media_manifest(manifest_file)  # Fail closed on corrupt existing data.
    before = _fingerprint(path)
    duration, index, codec, width, height = _probe_video(path, ffprobe_bin, timeout_s)
    digest = _sha256(path)
    if before != _fingerprint(path):
        raise MediaValidationError("source changed while it was being validated")
    uri = path.as_uri()
    asset = VideoAsset.build(digest, uri, duration)
    existing = next((record for record in manifest.records
                     if record.asset.video_id == asset.video_id), None)
    updated: list[MediaRecord] = []
    for record in manifest.records:
        if record.asset.video_id == asset.video_id:
            sources = {source.uri: source.status for source in record.sources}
            sources[uri] = "verified"
            updated.append(record.model_copy(update={"sources": tuple(
                MediaSource(uri=key, status=value) for key, value in sorted(sources.items()))}))
        else:
            sources = tuple(MediaSource(uri=source.uri, status="superseded")
                            if source.uri == uri else source for source in record.sources)
            updated.append(record.model_copy(update={"sources": sources}))
    if existing is None:
        updated.append(MediaRecord(asset=asset, sources=(MediaSource(uri=uri),),
                                   size_bytes=before[2], video_stream_index=index,
                                   codec_name=codec, width=width, height=height))
    checked = MediaManifest(schema_version=1,
                            records=tuple(sorted(updated, key=lambda row: row.asset.video_id)))
    if checked != manifest:
        _save_manifest(manifest_file, checked)
    record = next(row for row in checked.records if row.asset.video_id == asset.video_id)
    return RegistrationResult(record=record, manifest_path=manifest_file, duplicate=existing is not None)


def set_processing_status(manifest_path: Path | str, video_id: str,
                          status: Literal["processing", "processed", "failed"], *,
                          error: str | None = None) -> MediaRecord:
    """Record pipeline status; failures require a reason and never create a media identity."""
    path = Path(manifest_path)
    manifest = load_media_manifest(path)
    record = next((row for row in manifest.records if row.asset.video_id == video_id), None)
    if record is None:
        raise KeyError(f"unknown registered video: {video_id}")
    if status == "failed" and not error:
        raise ValueError("failed processing requires an error")
    if status != "failed" and error is not None:
        raise ValueError("only failed processing may have an error")
    updated = record.model_copy(update={"processing_status": status, "processing_error": error})
    checked = MediaManifest(schema_version=1,
                            records=tuple(updated if row.asset.video_id == video_id else row
                                          for row in manifest.records))
    if checked != manifest:
        _save_manifest(path, checked)
    return updated
