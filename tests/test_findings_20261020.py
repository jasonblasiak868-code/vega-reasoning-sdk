"""Regression test (2026-10-20): the promotion gate and the vital signs counted a record whose verdict was the number 1 or 0 as a real True/False (1 == True in Python)."""
import unittest

from vega_reasoning import fidelity, vitals


def rows(verdicts, role="apprentice"):
    return [{"task_class": "t", "role": role, "model": "m", "combined_verified": v, "correct": v, "latency_ms": 10} for v in verdicts]


class VerdictsMustBeRealBooleans(unittest.TestCase):
    def test_numbers_do_not_count_toward_promotion(self):
        st = fidelity.status(rows([1] * 60), "t")
        self.assertEqual((st["n"], st["promoted"]), (0, False))

    def test_real_booleans_still_promote(self):
        st = fidelity.status(rows([True] * 60), "t")
        self.assertEqual((st["n"], st["promoted"]), (60, True))

    def test_numbers_do_not_count_as_observations_in_the_vital_signs(self):
        v = vitals.vitals(rows([1, 0, 1, 1] * 10), "m")
        self.assertEqual((v["fidelity"]["n"], v["correctness"]["n"]), (0, 0))


class PredictAndOverseer(unittest.TestCase):
    def test_predict_counts_only_real_booleans(self):
        from vega_reasoning import predict
        self.assertIsNone(predict._outcome({"correct": 1}, "correct"))
        self.assertIsNone(predict._outcome({"combined_verified": 0}, "combined"))
        self.assertIs(predict._outcome({"correct": True}, "correct"), True)

    def test_the_overseer_refuses_a_candidate_it_would_hash_by_memory_address(self):
        from vega_reasoning import overseer
        with self.assertRaises(overseer.OverseerRefused):
            overseer.digest({"build": object()}, lambda c: c, lambda a: {"passed": True})
        a = overseer.digest({"x": 1}, lambda c: c, lambda a: {"passed": True})
        b = overseer.digest({"x": 1}, lambda c: c, lambda a: {"passed": True})
        self.assertEqual(a["candidate_sha256"], b["candidate_sha256"])


if __name__ == "__main__":
    unittest.main()
