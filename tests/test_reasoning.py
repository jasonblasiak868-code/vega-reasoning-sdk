"""Functional tests for the reasoning SDK."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import fixture_reasoning as fx  # noqa: E402
from vega_reasoning import aquire, fidelity, judge, lyra, morna, overseer, predict, records, stats, vitals  # noqa: E402


class Stats(unittest.TestCase):
    def test_wilson(self):
        self.assertEqual(stats.wilson_lower(0, 0), 0.0)
        self.assertLess(stats.wilson_lower(5, 5), 0.6)                       # five for five is not skill
        self.assertGreater(stats.wilson_lower(95, 100), 0.88)

    def test_cusum_flags_late_drift_only(self):
        self.assertFalse(stats.cusum([0] * 40)["alarm"])
        self.assertTrue(stats.cusum([0] * 30 + [1] * 12)["alarm"])

    def test_brier_and_entropy(self):
        self.assertEqual(stats.brier([(1.0, 1), (0.0, 0)]), 0.0)
        self.assertAlmostEqual(stats.entropy([1, 1]), 1.0)


class Judge(unittest.TestCase):
    def test_negation_is_a_contradiction(self):
        v = judge.lexical_judge("delete the old database now", "do not delete the old database now")
        self.assertGreaterEqual(v["contradiction"], 0.5)

    def test_both_trace_and_answer_must_pass(self):
        g = judge.grade("restart the pool then clear cache", "answer is restart", "restart the pool then clear cache", "something else entirely unrelated words")
        self.assertTrue(g["trace"]["verified"])
        self.assertFalse(g["answer"]["verified"])
        self.assertFalse(g["combined_verified"])


class LogAndGate(unittest.TestCase):
    def test_records_hold_hashes_not_text(self):
        log, dag, t = fx.new_log()
        log.add(fx.app_row(1, True))
        with open(t / "c.jsonl", encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn("trace 1", raw)
        self.assertIn("trace_sha256", raw)

    def test_regrade_supersedes_not_inflates(self):
        log, _, _ = fx.new_log()
        for _ in range(5):
            log.add(fx.app_row(1, True, query="same"))
        log.add(fx.app_row(2, False, query="same"))
        rows = log.history(role="apprentice")
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["combined_verified"])

    def test_promotion_needs_enough_good_unbroken_records(self):
        log, _, _ = fx.new_log()
        fx.fill(log, [True] * 29)
        self.assertFalse(fidelity.status(log.history(), "code")["promoted"])        # n < 30
        fx.fill(log, [True] * 29 + [True] * 10)
        self.assertTrue(fidelity.status(log.history(), "code")["promoted"])

    def test_a_lucky_streak_on_a_bad_record_does_not_promote(self):
        log, _, _ = fx.new_log()
        fx.fill(log, [False, True] * 20)
        self.assertFalse(fidelity.status(log.history(), "code")["promoted"])

    def test_drift_after_promotion_demotes(self):
        log, _, _ = fx.new_log()
        fx.fill(log, [True] * 60)
        self.assertTrue(fidelity.status(log.history(), "code")["promoted"])
        for i in range(60, 75):
            log.add(fx.app_row(i, False))
        st = fidelity.status(log.history(), "code")
        self.assertTrue(st["cusum_alarm"])
        self.assertFalse(st["promoted"])
        self.assertEqual(fidelity.route(st), "reference_required")


class Vitals(unittest.TestCase):
    def test_colours(self):
        log, _, _ = fx.new_log()
        fx.fill(log, [True] * 40)
        self.assertEqual(vitals.vitals(log.history(), "small")["health"], "GREEN")
        log2, _, _ = fx.new_log()
        fx.fill(log2, [True] * 5)
        self.assertEqual(vitals.vitals(log2.history(), "small")["health"], "AMBER")
        log3, _, _ = fx.new_log()
        fx.fill(log3, [True] * 30 + [False] * 14)
        self.assertEqual(vitals.vitals(log3.history(), "small")["health"], "RED")


class Lyra(unittest.TestCase):
    def test_governor_rises_fast_and_falls_slow(self):
        g = lyra.Governor()
        up = g.step(1.0)["level"]
        self.assertGreater(up, 0.5)
        down = g.step(0.0)["level"]
        self.assertGreater(down, up * 0.7)

    def test_depth_never_passes_the_ceiling(self):
        g = lyra.Governor(max_depth=5)
        for _ in range(20):
            self.assertLessEqual(g.step(1.0)["depth"], 5)

    def test_mri_attribution_finds_the_feature_behind_the_flag(self):
        _, dag, _ = fx.new_log()
        m = lyra.MRI(dag)
        for i in range(30):
            code = i % 2
            m.observe("small", "q%d" % i, "o%d" % i, {"has_code": code, "long": i % 3 == 0 and 1 or 0}, {"wrong": code})
        top = m.attribute("small", "wrong")[0]
        self.assertEqual(top["feature"], "has_code")
        self.assertTrue(top["clear"])


class Aquire(unittest.TestCase):
    G = {"start": {"a": 3, "b": 1}, "a": {"win": 1}, "b": {"lose": 1}, "win": {}, "lose": {}}

    def test_distribution_and_best_path(self):
        f = aquire.forecast(self.G, "start")
        self.assertAlmostEqual(f["outcomes"]["win"], 0.75)
        self.assertEqual(f["best_path"]["path"], ["start", "a", "win"])
        self.assertEqual(f["soft_landing"][0], "win")
        self.assertEqual(f["mass_dropped"], 0.0)

    def test_a_narrow_beam_reports_what_it_dropped(self):
        f = aquire.forecast(self.G, "start", beam=1)
        self.assertGreater(f["mass_dropped"], 0.2)

    def test_collapse_only_when_requirements_leave_one(self):
        f = aquire.forecast(self.G, "start")["outcomes"]
        self.assertEqual(aquire.collapse(f, [lambda n: n == "win"])["status"], "COLLAPSED")
        self.assertEqual(aquire.collapse(f, [])["status"], "AMBIGUOUS")
        self.assertEqual(aquire.collapse(f, [lambda n: False])["status"], "NONE")


class Overseer(unittest.TestCase):
    def test_states(self):
        ok = overseer.digest({"x": 1}, lambda c: c, lambda a: {"passed": True})
        self.assertEqual(ok["state"], "NOURISHING")
        self.assertEqual(overseer.digest({}, lambda c: 1 / 0, lambda a: {"passed": True})["state"], "SICK")
        self.assertEqual(overseer.digest({}, lambda c: c, lambda a: {"passed": False, "missing": ["db"]})["state"], "HUNGRY")

    def test_nothing_promotes_itself(self):
        v = overseer.digest({"x": 1}, lambda c: c, lambda a: {"passed": True})
        self.assertEqual(overseer.promote(v, None)["status"], "PROPOSED")
        self.assertEqual(overseer.promote(v, lambda h: True)["status"], "PROMOTED")


class Morna(unittest.TestCase):
    def router(self, rows, **kw):
        log, dag, _ = fx.new_log()
        calls = []
        lanes = [morna.Lane("ref_free", lambda q: calls.append("ref_free") or "ref answer", "free", "reference", ["code"]),
                 morna.Lane("ref_paid", lambda q: calls.append("ref_paid") or "paid answer", "paid", "reference", ["code"]),
                 morna.Lane("app_local", lambda q: calls.append("app_local") or "app answer", "local", "apprentice", ["code"])]
        return morna.Router(lanes, lambda: rows, dag, **kw), calls

    def test_unpromoted_class_uses_a_reference_lane_cheapest_first(self):
        r, calls = self.router([])
        out = r.route("code", "q")
        self.assertEqual((out["lane"], out["gate"]), ("ref_free", "reference"))
        self.assertEqual(calls, ["ref_free"])

    def test_promoted_class_uses_the_apprentice(self):
        log, _, _ = fx.new_log()
        fx.fill(log, [True] * 60)
        r, calls = self.router(log.history())
        self.assertEqual(r.route("code", "q")["lane"], "app_local")

    def test_second_ask_is_recalled_not_recomputed(self):
        r, calls = self.router([])
        r.route("code", "q")
        out = r.route("code", "q")
        self.assertTrue(out["recalled"])
        self.assertEqual(calls, ["ref_free"])


class Predict(unittest.TestCase):
    def history(self):
        log, _, _ = fx.new_log()
        for i in range(60):
            log.add(fx.app_row(i, True, correct=(i % 4 != 0), model="small", difficulty=0.1 if i % 2 else 0.9))
            log.add(fx.frontier_row(i, True))
        return log.history()

    def test_no_basis_without_records(self):
        self.assertEqual(predict.Lattice([]).predict("code", "small")["basis"], "NO BASIS")

    def test_thin_cell_borrows_from_its_parent(self):
        p = predict.Lattice(self.history(), "correct").predict("code", "never-seen-model")
        self.assertIsNotNone(p["probability"])
        self.assertLessEqual(p["level"], 1)

    def test_backtest_scores_against_the_naive_baseline(self):
        b = predict.backtest(self.history(), "correct", warmup=20)
        self.assertGreater(b["n"], 50)
        self.assertIsNotNone(b["brier"])

    def test_accuracy_report_keeps_fidelity_and_correctness_apart_and_pairs_queries(self):
        r = predict.accuracy_report(self.history())["code"]
        self.assertEqual(r["apprentice_fidelity"]["n"], 60)
        self.assertGreater(r["paired_on_shared_queries"]["n"], 0)
        self.assertIn("not combined", r["honesty"])

    def test_training_gate(self):
        rows = [records.make("reference", "big", "code", "q", "t", "a", correct=True)]
        self.assertFalse(predict.training_gate(rows, "sellable_model")["allowed"])
        self.assertTrue(predict.training_gate(rows, "personal_research")["allowed"])


if __name__ == "__main__":
    unittest.main()
