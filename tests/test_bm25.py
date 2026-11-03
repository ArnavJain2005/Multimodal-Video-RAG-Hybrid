import itertools
import unittest

from fixtures import synthetic_videos
from videorag import CanonicalVideo, IncompleteEvidenceError, TemporalSpan
from videorag.bm25 import BM25Index, DuplicateUnitError, tokenize


def unit_for(record: CanonicalVideo, fragment: str) -> str:
    return next(u.unit_id for u in record.units if fragment in u.text)


def with_text(record: CanonicalVideo, text: str) -> CanonicalVideo:
    """Record whose first observation/unit is replaced by `text`-bearing one (via builder)."""
    from videorag import FrameDescription, Provenance, build_canonical_video, make_observation
    obs = make_observation(FrameDescription, video_id=record.asset.video_id,
                           span=TemporalSpan(start_s=3.0, end_s=3.0), text=text,
                           provenance=Provenance(method="synthetic", version="1",
                                                 source_locator="f"), frame_ref="x")
    return build_canonical_video(record.asset, (obs,))


class TokenizerTests(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(("the", "blue", "robot", "42", "c", "a", "b"),
                         tokenize("The BLUE robot, 42°C! a_b"))
        self.assertEqual(("fine",), tokenize("\ufb01ne"))  # NFKC ligature expansion
        self.assertEqual(("strasse",), tokenize("STRA\u00dfE"))  # casefold
        self.assertEqual((), tokenize("  ?!..._ "))


class BM25Tests(unittest.TestCase):
    def setUp(self):
        self.v1, self.v2 = synthetic_videos()

    def test_expected_lexical_matches(self):
        index = BM25Index([self.v1, self.v2])
        self.assertEqual(6, len(index))
        hits = index.search("blue robot")
        self.assertEqual([unit_for(self.v1, "begins moving"), unit_for(self.v1, "crosses")],
                         [h.unit_id for h in hits])
        self.assertEqual([1, 2], [h.rank for h in hits])
        self.assertTrue(all(h.channel == "bm25" for h in hits))
        self.assertGreater(hits[0].score, hits[1].score)
        self.assertEqual([unit_for(self.v2, "gauge")], [h.unit_id for h in index.search("Gauge")])
        self.assertEqual([unit_for(self.v1, "READY")], [h.unit_id for h in index.search("ready")])
        self.assertEqual((), index.search("nonexistent"))

    def test_top_k_and_validation(self):
        index = BM25Index([self.v1, self.v2])
        self.assertEqual(1, len(index.search("blue robot", top_k=1)))
        for bad in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                index.search("blue", top_k=bad)
        with self.assertRaises(TypeError):
            index.search(None)

    def test_deterministic_across_input_order_and_rebuilds(self):
        reference = None
        for order in itertools.permutations([self.v1, self.v2]):
            for _ in range(2):
                result = BM25Index(order).search("blue robot sensor gauge test is the")
                reference = reference or result
                self.assertEqual(reference, result)

    def test_ties_break_by_unit_id_with_contiguous_ranks(self):
        # Same text in both videos -> identical scores; distinct unit_ids.
        a, b = with_text(self.v1, "alpha beta"), with_text(self.v2, "alpha beta")
        hits = BM25Index([b, a]).search("alpha")
        self.assertEqual(hits[0].score, hits[1].score)
        self.assertEqual(sorted(h.unit_id for h in hits), [h.unit_id for h in hits])
        self.assertEqual([1, 2], [h.rank for h in hits])

    def test_scores_finite_and_repeated_terms_do_not_boost(self):
        index = BM25Index([self.v1, self.v2])
        once, many = index.search("robot"), index.search("robot robot robot")
        self.assertEqual(once, many)
        self.assertTrue(all(h.score is not None and h.score > 0 for h in once))

    def test_term_frequency_and_length_normalisation(self):
        a = with_text(self.v1, "robot robot robot")
        b = with_text(self.v2, "robot lamp table chair")
        hits = BM25Index([a, b]).search("robot")
        self.assertEqual(a.units[0].unit_id, hits[0].unit_id)

    def test_empty_inputs(self):
        self.assertEqual((), BM25Index([]).search("robot"))
        self.assertEqual(0, len(BM25Index([])))
        index = BM25Index([self.v1])
        for q in ("", "   ", "?!._", "___"):
            self.assertEqual((), index.search(q))

    def test_zero_length_document_is_indexed_but_unmatchable(self):
        blank = with_text(self.v2, "?!...")
        index = BM25Index([blank])
        self.assertEqual(1, len(index))
        self.assertEqual((), index.search("anything"))
        self.assertEqual((), index.search("?!..."))
        mixed = BM25Index([blank, self.v1])
        self.assertEqual(2, len(mixed.search("blue robot")))

    def test_duplicate_unit_ids_rejected(self):
        with self.assertRaises(DuplicateUnitError) as raised:
            BM25Index([self.v1, self.v2, self.v1])
        self.assertEqual(tuple(sorted(u.unit_id for u in self.v1.units)),
                         raised.exception.unit_ids)

    def test_incomplete_evidence_rejected(self):
        incomplete = CanonicalVideo(asset=self.v1.asset, observations=self.v1.observations,
                                    units=self.v1.units, evidence=self.v1.evidence[:1])
        with self.assertRaises(IncompleteEvidenceError):
            BM25Index([self.v2, incomplete])
        unlinked = CanonicalVideo(asset=self.v1.asset, observations=self.v1.observations,
                                  units=self.v1.units, evidence=())
        with self.assertRaises(IncompleteEvidenceError):
            BM25Index(unlinked)

    def test_bad_inputs_and_parameters(self):
        with self.assertRaises(TypeError):
            BM25Index(["not a record"])
        for k1, b in ((-1, 0.5), (float("nan"), 0.5), (1.2, 1.5), (1.2, -0.1)):
            with self.assertRaises(ValueError):
                BM25Index([], k1=k1, b=b)
        self.assertEqual(3, len(BM25Index(self.v1)))  # a single record is accepted


if __name__ == "__main__":
    unittest.main()
