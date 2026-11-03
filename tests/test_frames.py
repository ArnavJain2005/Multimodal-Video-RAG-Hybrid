"""Frame tests use generated video bytes, not benchmark media or model output."""

import json
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from test_ingestion import make_clip
from videorag import (FrameExtractionError, FrameManifest, register_video,
                      sample_frames)


class FrameSamplingTests(unittest.TestCase):
    def test_two_videos_real_pts_and_rebuild(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media_manifest = root / "media_manifest.json"
            results = []
            for name, color in (("red", "red"), ("blue", "blue")):
                clip = root / f"{name}.mp4"
                make_clip(clip, color)
                registration = register_video(clip, media_manifest)
                result = sample_frames(media_manifest, registration.record.asset.video_id,
                                       root / "frames", gap_s=0.4)
                self.assertFalse(result.reused)
                self.assertEqual([f.timestamp_s for f in result.manifest.frames],
                                 [0.0, 0.4, 0.8])
                self.assertEqual(result.manifest.source_sha256,
                                 registration.record.asset.sha256)
                self.assertEqual(result.manifest,
                                 FrameManifest.model_validate_json(
                                     (result.directory / "manifest.json").read_bytes()))
                for frame in result.manifest.frames:
                    self.assertTrue((result.directory / frame.relative_path).read_bytes().startswith(
                        b"\x89PNG\r\n\x1a\n"))
                    self.assertEqual(frame.video_id, registration.record.asset.video_id)
                    self.assertFalse(hasattr(frame, "text"))
                original_bytes = (result.directory / "manifest.json").read_bytes()
                again = sample_frames(media_manifest, registration.record.asset.video_id,
                                      root / "frames", gap_s=0.4)
                self.assertTrue(again.reused)
                self.assertEqual(again.manifest, result.manifest)
                self.assertEqual((again.directory / "manifest.json").read_bytes(), original_bytes)
                results.append(result)
            self.assertNotEqual(results[0].manifest.frames[0].frame_id,
                                results[1].manifest.frames[0].frame_id)

    def test_changed_source_is_rejected_before_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clip, replacement = root / "source.mp4", root / "replacement.mp4"
            make_clip(clip, "green")
            make_clip(replacement, "yellow")
            manifest = root / "media_manifest.json"
            video_id = register_video(clip, manifest).record.asset.video_id
            shutil.copyfile(replacement, clip)
            with self.assertRaisesRegex(FrameExtractionError, "bytes changed"):
                sample_frames(manifest, video_id, root / "frames")
            self.assertFalse((root / "frames").exists())

    def test_first_frame_uses_decoded_pts_not_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clip = root / "offset.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-f", "lavfi", "-i", "color=c=red:s=32x32:r=5", "-t", "1",
                            "-vf", "setpts=PTS+0.4/TB", "-an", "-c:v", "mpeg4",
                            str(clip)], check=True, capture_output=True, timeout=30)
            manifest = root / "media_manifest.json"
            video_id = register_video(clip, manifest).record.asset.video_id
            result = sample_frames(manifest, video_id, root / "frames", gap_s=0.4)
            self.assertEqual(result.manifest.stream_start_pts_s, 0.4)
            self.assertEqual(result.manifest.frames[0].source_pts_s, 0.4)
            self.assertEqual(result.manifest.frames[0].timestamp_s, 0.0)

    def test_corrupt_artifact_and_manifest_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clip = root / "source.mp4"
            make_clip(clip, "red")
            media_manifest = root / "media_manifest.json"
            video_id = register_video(clip, media_manifest).record.asset.video_id
            result = sample_frames(media_manifest, video_id, root / "frames")
            frame_path = result.directory / result.manifest.frames[0].relative_path
            frame_path.write_bytes(b"invalid image")
            with self.assertRaisesRegex(FrameExtractionError, "hash mismatch"):
                sample_frames(media_manifest, video_id, root / "frames")
            frame_path.unlink()
            with self.assertRaisesRegex(FrameExtractionError, "missing or unreadable"):
                sample_frames(media_manifest, video_id, root / "frames")
            manifest_path = result.directory / "manifest.json"
            data = json.loads(manifest_path.read_text())
            data["frames"][0]["timestamp_s"] = 2.0
            manifest_path.write_text(json.dumps(data))
            with self.assertRaises(ValidationError):
                sample_frames(media_manifest, video_id, root / "frames")

    def test_invalid_gap_and_existing_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clip = root / "source.mp4"
            make_clip(clip, "red")
            media_manifest = root / "media_manifest.json"
            video_id = register_video(clip, media_manifest).record.asset.video_id
            for gap in (0, -1, math.nan, math.inf, 0.4000001):
                with self.subTest(gap=gap), self.assertRaises(ValueError):
                    sample_frames(media_manifest, video_id, root / "frames", gap_s=gap)
            result = sample_frames(media_manifest, video_id, root / "frames")
            (result.directory / "manifest.json").unlink()
            with self.assertRaisesRegex(FrameExtractionError, "no valid manifest"):
                sample_frames(media_manifest, video_id, root / "frames")


if __name__ == "__main__":
    unittest.main()
