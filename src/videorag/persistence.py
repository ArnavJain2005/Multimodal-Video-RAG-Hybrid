"""Validated, atomic canonical JSON snapshots; no retrieval index is persisted here."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .contracts import CanonicalVideo


@dataclass(frozen=True)
class EvidenceGap:
    unit_id: str
    observation_id: str
    reason: str


class IncompleteEvidenceError(ValueError):
    def __init__(self, gaps: tuple[EvidenceGap, ...]):
        self.gaps = gaps
        super().__init__(f"incomplete evidence for {len(gaps)} observation link(s): "
                         + ", ".join(f"{g.unit_id}/{g.observation_id}" for g in gaps))


def evidence_gaps(record: CanonicalVideo) -> tuple[EvidenceGap, ...]:
    """Return every referenced observation lacking evidence, in unit order."""
    return tuple(EvidenceGap(unit.unit_id, result.observation_id, result.reason)
                 for unit in record.units for result in record.resolve(unit.unit_id)
                 if result.status == "missing"
                 and result.observation_id is not None and result.reason is not None)


def _validated(record: CanonicalVideo, allow_incomplete: bool) -> CanonicalVideo:
    # Pydantic model_copy(update=...) skips validation; round-trip through JSON to
    # validate every nested model and reference before any filesystem mutation.
    checked = CanonicalVideo.model_validate_json(record.model_dump_json())
    gaps = evidence_gaps(checked)
    if gaps and not allow_incomplete:
        raise IncompleteEvidenceError(gaps)
    return checked


def save_canonical_video(directory: Path | str, record: CanonicalVideo, *,
                         replace: bool = False, allow_incomplete: bool = False) -> Path:
    """Write `<video_id>.json` atomically; a changed snapshot needs explicit replace."""
    checked = _validated(record, allow_incomplete)
    payload = (json.dumps(checked.model_dump(mode="json"), sort_keys=True,
                          ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    destination = Path(directory)
    path = destination / f"{checked.asset.video_id}.json"
    if path.exists():
        if path.read_bytes() == payload:
            return path
        if not replace:
            raise FileExistsError(f"canonical snapshot already exists: {path}")
    destination.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=destination,
                                         prefix=".canonical-", suffix=".tmp",
                                         delete=False) as stream:
            temporary = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return path


def load_canonical_video(path: Path | str, *,
                         allow_incomplete: bool = False) -> CanonicalVideo:
    source = Path(path)
    checked = CanonicalVideo.model_validate_json(source.read_bytes())
    if source.name != f"{checked.asset.video_id}.json":
        raise ValueError("snapshot filename does not match video identity")
    return _validated(checked, allow_incomplete)
