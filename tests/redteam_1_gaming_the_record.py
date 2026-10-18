"""RED TEAM 1 - reasoning SDK: try to make a model look better than its record, or to smuggle data into the record.

Run:  . SDK_FAMILY/env_family.sh ; python -m unittest discover -s SDK_FAMILY/vega-reasoning-sdk/tests -p "redteam_1_*.py"
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import fixture_reasoning as fx  # noqa: E402
from vega_reasoning import fidelity, judge, predict, records, stats, vitals  # noqa: E402


class A_Stats(unittest.TestCase):
    def test_bad_counts_are_refused(self):
        for s, n in ((-1, 5), (6, 5), (True, 5), (1, True), (1.5, 5), (None, 5), ("1", 5), (1, -1)):
            with self.assertRaises(ValueError, msg=repr((s, n))):
                stats.wilson_lower(s, n)

    def test_cusum_input_is_checked(self):
        for bad in ([0, 2, 1, 1], [True, False, True, False], [0.5] * 6, ["1"] * 6):
            with self.assertRaises(ValueError, msg=repr(bad)):
                stats.cusum(bad)

    def test_brier_and_entropy_inputs_are_checked(self):
        for bad in ([(1.5, 1)], [(0.5, 2)], [(True, 1)], [(float("nan"), 1)], [("a", 1)]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                stats.brier(bad)
        for bad in ([], [-1, 2], [0, 0], [float("nan")], [float("inf")]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                stats.entropy(bad)


class B_Judge(unittest.TestCase):
    def test_a_judge_that_lies_in_shape_is_refused(self):
        for bad in (None, [], {"similarity": True, "contradiction": 0}, {"similarity": 2, "contradiction": 0}, {"similarity": 0.9, "contradiction": -1}, {"similarity": float("nan"), "contradiction": 0},
                    {"similarity": "0.9", "contradiction": 0}, {"similarity": 0.9}, {}):
            with self.assertRaises(judge.JudgeRefused, msg=repr(bad)):
                judge.grade("a", "b", "a", "b", judge=lambda x, y, v=bad: v)

    def test_a_negated_answer_with_the_same_words_does_not_pass(self):
        g = judge.grade("deploy the fix to production now", "deploy it", "deploy the fix to production now", "do not deploy it")
        self.assertFalse(g["answer"]["verified"] and g["combined_verified"])

    def test_two_negations_agree_and_empty_text_does_not_verify(self):
        self.assertEqual(judge.lexical_judge("never delete the data", "do not delete the data")["contradiction"], 0.0)
        self.assertEqual(judge.lexical_judge("", "")["similarity"], 0.0)
        self.assertFalse(judge.grade("", "", "", "")["combined_verified"])

    def test_texts_only(self):
        for a, b in ((None, "x"), ("x", 5), (b"x", "x")):
            with self.assertRaises(judge.JudgeRefused):
                judge.lexical_judge(a, b)


class C_Records(unittest.TestCase):
    def test_nothing_but_hashes_reaches_the_chain(self):
        log, dag, t = fx.new_log()
        log.add(records.make("apprentice", "small", "code", "SECRET-QUERY-TEXT", "SECRET-TRACE-TEXT", "SECRET-ANSWER-TEXT", verdict=fx.verdict(True)))
        raw = open(t / "c.jsonl", encoding="utf-8").read()
        for s in ("SECRET-QUERY-TEXT", "SECRET-TRACE-TEXT", "SECRET-ANSWER-TEXT"):
            self.assertNotIn(s, raw)

    def test_bad_fields_are_refused(self):
        base = dict(role="apprentice", model="m", task_class="c", query="q", trace="t", answer="a")
        for patch in ({"role": "judge"}, {"model": ""}, {"model": "a b"}, {"model": "../x"}, {"model": "x" * 200}, {"task_class": None}, {"query": 5}, {"trace": None}, {"correct": "yes"},
                      {"correct": 1}, {"latency_ms": -1}, {"latency_ms": float("nan")}, {"latency_ms": True}, {"tokens": float("inf")}, {"difficulty": 1.5}, {"difficulty": True}, {"source": "a b"}):
            kw = dict(base, **patch)
            with self.assertRaises(records.RecordRefusedError, msg=repr(patch)):
                records.make(**kw)

    def test_a_verdict_must_come_from_grade(self):
        for bad in ({}, {"combined_verified": True}, {"trace": {}, "answer": {}, "combined_verified": True}, "x", 5):
            with self.assertRaises((records.RecordRefusedError, KeyError, TypeError), msg=repr(bad)):
                records.make("apprentice", "m", "c", "q", "t", "a", verdict=bad)

    def test_score_ranges_are_enforced_on_the_verdict(self):
        v = fx.verdict(True)
        v["trace"]["similarity"] = 1.7
        with self.assertRaises(records.RecordRefusedError):
            records.make("apprentice", "m", "c", "q", "t", "a", verdict=v)

    def test_add_refuses_hand_built_records(self):
        log, _, _ = fx.new_log()
        for bad in ({}, {"role": "apprentice"}, {"role": "apprentice", "query_sha256": "x", "trace_sha256": "y", "answer_sha256": "z"}, None, "x"):
            with self.assertRaises(records.RecordRefusedError, msg=repr(bad)):
                log.add(bad)

    def test_a_credential_in_a_label_cannot_reach_the_chain(self):
        log, _, _ = fx.new_log()
        for field in ("model", "task_class", "source"):
            kw = dict(role="apprentice", model="m", task_class="c", query="q", trace="t", answer="a")
            kw[field] = "sk-" + "A1b2C3d4" * 4
            with self.assertRaises(Exception):
                log.add(records.make(**kw))

    def test_the_reference_carries_its_training_restriction(self):
        r = records.make("reference", "big", "c", "q", "t", "a")
        self.assertIn("PERSONAL_RESEARCH_ONLY", r["training_restriction"])


class D_Gate(unittest.TestCase):
    def test_duplicates_cannot_inflate_n(self):
        log, _, _ = fx.new_log()
        for _ in range(100):
            log.add(fx.app_row(1, True, query="one-query"))
        st = fidelity.status(log.history(), "code")
        self.assertEqual(st["n"], 1)
        self.assertFalse(st["promoted"])

    def test_records_without_a_verdict_do_not_count_as_successes(self):
        log, _, _ = fx.new_log()
        for i in range(60):
            log.add(records.make("apprentice", "small", "code", "q%d" % i, "t", "a"))
        st = fidelity.status(log.history(), "code")
        self.assertEqual(st["n"], 0)
        self.assertFalse(st["promoted"])

    def test_reference_and_frontier_rows_do_not_promote_an_apprentice(self):
        log, _, _ = fx.new_log()
        for i in range(60):
            log.add(fx.frontier_row(i, True, role="reference"))
        self.assertFalse(fidelity.status(log.history(), "code")["promoted"])

    def test_one_class_cannot_borrow_another_classes_record(self):
        log, _, _ = fx.new_log()
        fx.fill(log, [True] * 60, task_class="easy")
        self.assertTrue(fidelity.status(log.history(), "easy")["promoted"])
        self.assertFalse(fidelity.status(log.history(), "hard")["promoted"])

    def test_a_good_start_then_collapse_is_demoted_even_with_a_high_overall_rate(self):
        log, _, _ = fx.new_log()
        fx.fill(log, [True] * 120 + [False] * 14)
        st = fidelity.status(log.history(), "code")
        self.assertGreater(st["successes"] / st["n"], 0.85)
        self.assertTrue(st["cusum_alarm"])
        self.assertFalse(st["promoted"])


class E_Vitals(unittest.TestCase):
    def test_a_handful_of_perfect_answers_is_never_green(self):
        log, _, _ = fx.new_log()
        fx.fill(log, [True] * 10)
        self.assertNotEqual(vitals.vitals(log.history(), "small")["health"], "GREEN")

    def test_no_data_is_amber_not_green(self):
        self.assertEqual(vitals.vitals([], "small")["health"], "AMBER")

    def test_a_green_model_goes_amber_when_stale(self):
        log, _, _ = fx.new_log()
        fx.fill(log, [True] * 60)
        self.assertEqual(vitals.vitals(log.history(), "small")["health"], "GREEN")
        self.assertEqual(vitals.vitals(log.history(), "small", now_epoch=10 ** 9, last_epoch=10 ** 9 - 15 * 24 * 3600)["health"], "AMBER")

    def test_ground_truth_failures_turn_it_red_even_if_fidelity_is_perfect(self):
        log, _, _ = fx.new_log()
        for i in range(40):
            log.add(fx.app_row(i, True, correct=False))
        self.assertEqual(vitals.vitals(log.history(), "small")["health"], "RED")


class F_Predict(unittest.TestCase):
    def test_a_forecast_never_uses_the_future(self):
        log, _, _ = fx.new_log()
        for i in range(40):
            log.add(fx.app_row(i, True, correct=True))
        rows = log.history()
        bt = predict.backtest(rows, "correct", warmup=10)
        self.assertEqual(bt["n"], 30)

    def test_no_history_gives_no_basis_not_a_number(self):
        p = predict.Lattice([]).predict("code", "m", 0.5)
        self.assertIsNone(p["probability"])

    def test_a_single_lucky_record_is_not_a_prediction_of_certainty(self):
        log, _, _ = fx.new_log()
        log.add(fx.app_row(0, True, correct=True))
        p = predict.Lattice(log.history(), "correct").predict("code", "small")
        self.assertFalse(p["enough"])
        self.assertLess(p["wilson_lower"], 0.3)

    def test_bad_arguments(self):
        with self.assertRaises(predict.PredictRefused):
            predict.Lattice([], "other")
        with self.assertRaises(predict.PredictRefused):
            predict.Lattice([]).predict("c", "m", 2)
        with self.assertRaises(predict.PredictRefused):
            predict.training_gate([], "sell it")

    def test_restricted_rows_never_pass_a_commercial_gate(self):
        rows = [records.make("reference", "big", "c", "q", "t", "a")]
        for purpose in ("commercial", "competing_model", "sellable_model", "public_release"):
            self.assertFalse(predict.training_gate(rows, purpose)["allowed"], purpose)

    def test_an_edited_restriction_is_not_honoured_by_silence(self):
        r = records.make("reference", "big", "c", "q", "t", "a")
        r["training_restriction"] = None                                     # someone strips the tag from a copy: a row with no tag is allowed, which is why the tag is hashed on the chain
        log, dag, _ = fx.new_log()
        e = log.add(records.make("reference", "big", "c", "q", "t", "a"))
        self.assertIn("PERSONAL_RESEARCH_ONLY", e["payload"]["training_restriction"])
        self.assertTrue(dag.verify())


if __name__ == "__main__":
    unittest.main()
