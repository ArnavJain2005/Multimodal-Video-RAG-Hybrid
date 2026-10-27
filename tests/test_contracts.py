import math
import unittest

from pydantic import ValidationError

from fixtures import synthetic_videos
from videorag import (CanonicalVideo, Evidence, RetrievalCandidate, RetrievalUnit,
                      TemporalSpan)


class ContractTests(unittest.TestCase):
    def test_round_trip_two_videos(self):
        for record in synthetic_videos():
            self.assertEqual(record, CanonicalVideo.model_validate_json(record.model_dump_json()))
            self.assertEqual(len(record.observations), 3)
            self.assertNotEqual(record.observations[0].span, record.observations[1].span)

    def test_stable_ids_and_evidence_resolution(self):
        a, b = synthetic_videos()
        self.assertNotEqual(a.asset.video_id, b.asset.video_id)
        self.assertEqual(a.units[0].unit_id, synthetic_videos()[0].units[0].unit_id)
        self.assertEqual(a.resolve(a.units[0].unit_id)[0].evidence, a.evidence[0])
        self.assertEqual(a.evidence[0].observation_id, a.observations[0].observation_id)
        self.assertEqual(a.resolve(a.units[2].unit_id)[0].evidence.span.start_s, 12.0)

    def test_missing_evidence_is_explicit(self):
        a, _ = synthetic_videos()
        without_evidence = CanonicalVideo(asset=a.asset, observations=a.observations,
                                          units=a.units, evidence=())
        self.assertEqual(without_evidence.resolve(a.units[0].unit_id)[0].status, "missing")
        self.assertIsNone(without_evidence.resolve(a.units[0].unit_id)[0].evidence)
        self.assertEqual(without_evidence.resolve(a.units[0].unit_id)[0].observation_id,
                         a.observations[0].observation_id)
        self.assertEqual(a.resolve("nonexistent")[0].reason, "unknown retrieval unit")
        combined = RetrievalUnit.build(a.asset.video_id, TemporalSpan(start_s=1, end_s=8),
                                       "speech and on-screen text",
                                       (a.observations[0].observation_id,
                                        a.observations[1].observation_id))
        partial = CanonicalVideo(asset=a.asset, observations=a.observations,
                                 units=a.units + (combined,),
                                 evidence=a.evidence + (Evidence.build(combined, a.observations[0]),))
        self.assertEqual([r.status for r in partial.resolve(combined.unit_id)],
                         ["present", "missing"])

    def test_invalid_time_and_bound(self):
        for start, end in [(-1, 1), (2, 1), (math.nan, 1), (0, math.inf), (0, 1.0000004)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValidationError):
                TemporalSpan(start_s=start, end_s=end)
        a, _ = synthetic_videos()
        far = a.observations[0].model_copy(update={"span": TemporalSpan(start_s=31, end_s=32)})
        with self.assertRaises(ValidationError):
            CanonicalVideo(asset=a.asset, observations=(far,), units=(), evidence=())
        with self.assertRaises(ValidationError):
            CanonicalVideo(asset=a.asset, observations=a.observations, units=a.units,
                           evidence=(a.evidence[0].model_copy(update={"span": TemporalSpan(start_s=0, end_s=0)}),))

    def test_identity_and_cross_refs(self):
        a, b = synthetic_videos()
        with self.assertRaises(ValidationError):
            RetrievalUnit(unit_id="wrong", video_id=a.asset.video_id,
                          span=a.units[0].span, text=a.units[0].text,
                          observation_ids=a.units[0].observation_ids)
        with self.assertRaises(ValidationError):
            CanonicalVideo(asset=a.asset, observations=a.observations,
                           units=(b.units[0],), evidence=())
        with self.assertRaises(ValidationError):
            Evidence(evidence_id="wrong", unit_id=a.units[0].unit_id,
                     observation_id=a.observations[0].observation_id,
                     video_id=a.asset.video_id, span=a.observations[0].span, modality="speech")

    def test_candidate_interface(self):
        a, _ = synthetic_videos()
        for channel in ("dense", "bm25", "graph"):
            candidate = RetrievalCandidate(channel=channel, unit_id=a.units[0].unit_id, rank=1)
            self.assertEqual(candidate.unit_id, a.units[0].unit_id)
        with self.assertRaises(ValidationError):
            RetrievalCandidate(channel="graph", unit_id=a.units[0].unit_id, rank=0)


if __name__ == "__main__":
    unittest.main()
