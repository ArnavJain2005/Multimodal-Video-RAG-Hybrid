import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from fixtures import synthetic_videos
from videorag import (CanonicalVideo, IncompleteEvidenceError, VideoAsset,
                      build_canonical_video, evidence_gaps, load_canonical_video,
                      save_canonical_video)


class PersistenceTests(unittest.TestCase):
    def test_two_video_round_trip_and_rebuild(self):
        with tempfile.TemporaryDirectory() as temporary:
            for original in synthetic_videos():
                first = build_canonical_video(original.asset, reversed(original.observations))
                second = build_canonical_video(original.asset, original.observations)
                self.assertEqual(first, second)
                self.assertEqual([u.unit_id for u in first.units],
                                 [u.unit_id for u in original.units])
                self.assertEqual([e.evidence_id for e in first.evidence],
                                 [e.evidence_id for e in original.evidence])
                path = save_canonical_video(temporary, first)
                payload = path.read_bytes()
                self.assertEqual(path, save_canonical_video(temporary, second))
                self.assertEqual(payload, path.read_bytes())
                loaded = load_canonical_video(path)
                self.assertEqual(first, loaded)
                self.assertEqual((), evidence_gaps(loaded))
            self.assertEqual(len(tuple(Path(temporary).glob("*.json"))), 2)

    def test_incomplete_is_diagnosed_before_write_and_after_load(self):
        original, _ = synthetic_videos()
        incomplete = CanonicalVideo(asset=original.asset, observations=original.observations,
                                    units=original.units, evidence=original.evidence[:1])
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(IncompleteEvidenceError) as raised:
                save_canonical_video(temporary, incomplete)
            self.assertEqual(len(raised.exception.gaps), 2)
            self.assertEqual({g.observation_id for g in raised.exception.gaps},
                             {o.observation_id for o in original.observations[1:]})
            self.assertEqual(list(Path(temporary).iterdir()), [])
            path = save_canonical_video(temporary, incomplete, allow_incomplete=True)
            with self.assertRaises(IncompleteEvidenceError):
                load_canonical_video(path)
            self.assertEqual(evidence_gaps(load_canonical_video(path, allow_incomplete=True)),
                             raised.exception.gaps)

    def test_invalid_json_and_nested_id_are_rejected(self):
        original, _ = synthetic_videos()
        with tempfile.TemporaryDirectory() as temporary:
            path = save_canonical_video(temporary, original)
            data = json.loads(path.read_text())
            data["observations"][0]["observation_id"] = "tampered"
            path.write_text(json.dumps(data))
            with self.assertRaises(ValidationError):
                load_canonical_video(path)
            # Even a model_copy bypass cannot write corrupt nested data.
            bad = original.model_copy(update={"observations": (
                original.observations[0].model_copy(update={"observation_id": "tampered"}),
                *original.observations[1:])})
            with self.assertRaises(ValidationError):
                save_canonical_video(temporary, bad, replace=True)

    def test_explicit_replace_and_filename_check(self):
        original, _ = synthetic_videos()
        changed = CanonicalVideo(asset=original.asset, observations=original.observations,
                                 units=original.units, evidence=())
        with tempfile.TemporaryDirectory() as temporary:
            path = save_canonical_video(temporary, original)
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                save_canonical_video(temporary, changed, allow_incomplete=True)
            self.assertEqual(path.read_bytes(), before)
            save_canonical_video(temporary, changed, replace=True, allow_incomplete=True)
            self.assertNotEqual(path.read_bytes(), before)
            wrong_path = Path(temporary) / "wrong-name.json"
            wrong_path.write_bytes(path.read_bytes())
            with self.assertRaises(ValueError):
                load_canonical_video(wrong_path, allow_incomplete=True)

    def test_unprobed_asset_cannot_build(self):
        original, _ = synthetic_videos()
        unprobed = VideoAsset.build(original.asset.sha256, original.asset.source_uri, None)
        with self.assertRaisesRegex(ValueError, "known video duration"):
            build_canonical_video(unprobed, original.observations)


if __name__ == "__main__":
    unittest.main()
