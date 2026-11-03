"""Generated media only; no fixture footage is committed."""

import shutil
import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from videorag import MediaValidationError, register_video
from videorag.frames import (FrameExtractionError, load_frame_manifest,
                             sample_frames)

from test_ingestion import make_clip


class FrameTests(unittest.TestCase):
    def test_repeatable_samples_and_verified_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clip = root / "red.mp4"
            make_clip(clip, "red")
            record = register_video(clip, root / "media.json").record
            frames = sample_frames(record, clip, root / "artifacts", cadence_s=0.25)
            self.assertEqual([0, 0.25, 0.5, 0.75],
                             [a.span.start_s for a in frames.artifacts])
            self.assertEqual([a.span.end_s for a in frames.artifacts],
                             [a.span.start_s for a in frames.artifacts])
            saved = (root / "artifacts" / record.asset.video_id / "frames.json").read_bytes()
            self.assertEqual(frames, sample_frames(record, clip, root / "artifacts",
                                                   cadence_s=0.25))
            self.assertEqual(saved, (root / "artifacts" / record.asset.video_id /
                                     "frames.json").read_bytes())
            self.assertEqual(frames, load_frame_manifest(root / "artifacts" /
                                                          record.asset.video_id / "frames.json"))
            self.assertEqual(4, len({a.frame_ref for a in frames.artifacts}))

    def test_source_change_and_unregistered_source_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clip, other = root / "red.mp4", root / "other.mp4"
            make_clip(clip, "red")
            shutil.copyfile(clip, other)
            record = register_video(clip, root / "media.json").record
            with self.assertRaises(MediaValidationError):
                sample_frames(record, other, root / "artifacts")
            make_clip(clip, "blue")
            with self.assertRaises(MediaValidationError):
                sample_frames(record, clip, root / "artifacts")
            self.assertFalse((root / "artifacts" / record.asset.video_id /
                              "frames.json").exists())

    def test_failure_and_existing_manifest_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clip = root / "red.mp4"
            make_clip(clip, "red")
            record = register_video(clip, root / "media.json").record
            for cadence in (0, -1, 0.0000001, float("nan")):
                with self.assertRaises(ValueError):
                    sample_frames(record, clip, root / "artifacts", cadence_s=cadence)
            with self.assertRaises(FrameExtractionError):
                sample_frames(record, clip, root / "artifacts", cadence_s=0.1,
                              max_frames=2)
            with self.assertRaises(FrameExtractionError):
                sample_frames(record, clip, root / "artifacts", ffmpeg_bin="not-ffmpeg")
            frames = sample_frames(record, clip, root / "artifacts")
            manifest = root / "artifacts" / record.asset.video_id / "frames.json"
            original = manifest.read_bytes()
            with self.assertRaises(FrameExtractionError):
                sample_frames(record, clip, root / "artifacts", cadence_s=0.25)
            self.assertEqual(original, manifest.read_bytes())
            image = manifest.parent / frames.artifacts[0].filename
            image.write_bytes(b"corrupt")
            with self.assertRaises(FrameExtractionError):
                load_frame_manifest(manifest)
            with self.assertRaises(FrameExtractionError):
                sample_frames(record, clip, root / "artifacts")
            tampered = json.loads(original)
            tampered["artifacts"][0]["span"] = {"start_s": 0.1, "end_s": 0.1}
            manifest.write_text(json.dumps(tampered))
            with self.assertRaises(ValidationError):
                load_frame_manifest(manifest, verify_files=False)


if __name__ == "__main__":
    unittest.main()
