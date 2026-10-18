"""Tests added after the mutation check found fixes no earlier test noticed."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import fixture_reasoning as fx  # noqa: E402
from vega_reasoning import aquire, predict, stats, vitals  # noqa: E402


class Sharpened(unittest.TestCase):
    def test_improvement_is_not_drift(self):
        """Bad early, good late: failures are FALLING, so the drift alarm stays quiet (the reference rate is the first half's own rate)."""
        self.assertFalse(stats.cusum([1] * 10 + [0] * 30)["alarm"])

    def test_sixteen_perfect_answers_are_still_too_few_to_be_green(self):
        log, _, _ = fx.new_log()
        fx.fill(log, [True] * 16)
        v = vitals.vitals(log.history(), "small")
        self.assertEqual(v["health"], "AMBER")
        self.assertTrue(any("observations" in r for r in v["reasons"]))

    def test_an_ambiguous_collapse_chooses_nothing(self):
        out = aquire.collapse({"x": 0.6, "y": 0.4}, [])
        self.assertEqual((out["status"], out["choice"]), ("AMBIGUOUS", None))

    def test_a_thin_cell_is_pulled_toward_its_parent(self):
        log, _, _ = fx.new_log()
        for i in range(12):
            log.add(fx.app_row(i, False, model="weak", correct=False))
        for i in range(200):
            log.add(fx.app_row(1000 + i, True, model="strong", correct=True))
        p = predict.Lattice(log.history(), "correct", min_n=10).predict("code", "weak")
        self.assertGreater(p["probability"], 0.05)                             # raw rate is 0.0; the class above it is almost all successes
        self.assertLess(p["probability"], 0.6)


if __name__ == "__main__":
    unittest.main()
