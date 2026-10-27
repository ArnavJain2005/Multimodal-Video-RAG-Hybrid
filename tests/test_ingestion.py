"""Media ingestion checks use generated clips, never redistributed source footage."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from videorag import (MediaValidationError, load_media_manifest, register_video,
                      set_processing_status)


def make_clip(path: Path, color: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"color=c={color}:s=32x32:r=5",
                    "-t", "1", "-an", "-c:v", "mpeg4", "-q:v", "5", str(path)],
                   check=True, capture_output=True, timeout=30)


class IngestionTests(unittest.TestCase):
    def test_reproducible_duplicate_and_changed_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, copy, replacement = (root / "one.mp4", root / "copy.mp4", root / "blue.mp4")
            manifest = root / "media_manifest.json"
            make_clip(first, "red")
            make_clip(replacement, "blue")
            shutil.copyfile(first, copy)

            original = register_video(first, manifest)
            self.assertFalse(original.duplicate)
            self.assertEqual(original.record.processing_status, "registered")
            self.assertEqual(original.record.asset.duration_s, 1.0)
            self.assertEqual(original.record.width, 32)
            saved = manifest.read_bytes()
            repeated = register_video(first, manifest)
            self.assertTrue(repeated.duplicate)
            self.assertEqual(saved, manifest.read_bytes())

            duplicate = register_video(copy, manifest)
            self.assertTrue(duplicate.duplicate)
            self.assertEqual(duplicate.record.asset.video_id, original.record.asset.video_id)
            self.assertEqual(len(duplicate.record.sources), 2)

            # Replacing bytes at a path creates a new ID and supersedes just
            # that source association; the other valid copy remains registered.
            shutil.copyfile(replacement, first)
            changed = register_video(first, manifest)
            self.assertFalse(changed.duplicate)
            self.assertNotEqual(changed.record.asset.video_id, original.record.asset.video_id)
            records = {row.asset.video_id: row for row in load_media_manifest(manifest).records}
            previous = records[original.record.asset.video_id]
            self.assertEqual({source.uri: source.status for source in previous.sources},
                             {first.resolve().as_uri(): "superseded",
                              copy.resolve().as_uri(): "verified"})
            self.assertEqual(len(records), 2)

    def test_invalid_media_does_not_create_an_asset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "media_manifest.json"
            with self.assertRaises(FileNotFoundError):
                register_video(root / "missing.mp4", manifest)
            corrupt = root / "corrupt.mp4"
            corrupt.write_bytes(b"not a video")
            with self.assertRaises(MediaValidationError):
                register_video(corrupt, manifest)
            audio = root / "only.wav"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                            "-c:a", "pcm_s16le", str(audio)], check=True,
                           capture_output=True, timeout=30)
            with self.assertRaises(MediaValidationError):
                register_video(audio, manifest)
            self.assertFalse(manifest.exists())

    def test_status_and_corrupt_manifest_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clip, manifest = root / "clip.mp4", root / "media_manifest.json"
            make_clip(clip, "green")
            record = register_video(clip, manifest).record
            with self.assertRaises(KeyError):
                set_processing_status(manifest, "unknown", "processing")
            with self.assertRaises(ValueError):
                set_processing_status(manifest, record.asset.video_id, "failed")
            self.assertEqual(set_processing_status(manifest, record.asset.video_id,
                                                   "processing").processing_status, "processing")
            failed = set_processing_status(manifest, record.asset.video_id,
                                           "failed", error="extraction failed")
            self.assertEqual(failed.processing_error, "extraction failed")
            self.assertEqual(load_media_manifest(manifest).records[0].processing_status, "failed")
            set_processing_status(manifest, record.asset.video_id, "processing")
            self.assertIsNone(load_media_manifest(manifest).records[0].processing_error)
            saved = manifest.read_bytes()
            manifest.write_text("{}")
            with self.assertRaises(ValidationError):
                register_video(clip, manifest)
            self.assertEqual(manifest.read_text(), "{}")
            manifest.write_bytes(saved)
            self.assertEqual(load_media_manifest(manifest).records[0].asset.video_id,
                             record.asset.video_id)


if __name__ == "__main__":
    unittest.main()
