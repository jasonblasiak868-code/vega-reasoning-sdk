"""RED TEAM 2 - reasoning SDK: the router's paid lanes, lane failures, the overseer's self-promotion, the forecaster's inputs, Lyra's inputs.

Run:  . SDK_FAMILY/env_family.sh ; python -m unittest discover -s SDK_FAMILY/vega-reasoning-sdk/tests -p "redteam_2_*.py"
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import fixture_reasoning as fx  # noqa: E402
from vega_reasoning import aquire, lyra, morna, overseer  # noqa: E402


def mk(lanes, rows=None, **kw):
    _, dag, t = fx.new_log()
    return morna.Router(lanes, lambda: rows or [], dag, **kw), dag, t


class A_PaidLanes(unittest.TestCase):
    def lanes(self, calls):
        return [morna.Lane("paid_ref", lambda q: calls.append("paid") or "paid text", "paid", "reference", ["c"])]

    def test_a_paid_lane_never_runs_without_a_commitment_check(self):
        calls = []
        r, dag, t = mk(self.lanes(calls))
        out = r.route("c", "q")
        self.assertFalse(out["ok"])
        self.assertEqual(calls, [])

    def test_only_exactly_true_opens_a_paid_lane(self):
        for answer in ("yes", 1, [1], {"ok": 1}, None, "True"):
            calls = []
            r, _, _ = mk(self.lanes(calls), paid_ok=lambda n, q, a=answer: a)
            self.assertFalse(r.route("c", "q")["ok"], repr(answer))
            self.assertEqual(calls, [])

    def test_a_crashing_commitment_check_means_no(self):
        calls = []

        def boom(n, q):
            raise RuntimeError("verifier down")
        r, _, _ = mk(self.lanes(calls), paid_ok=boom)
        self.assertFalse(r.route("c", "q")["ok"])
        self.assertEqual(calls, [])

    def test_the_commitment_is_asked_per_query_hash(self):
        asked = []
        calls = []
        r, _, _ = mk(self.lanes(calls), paid_ok=lambda n, q: asked.append(q) or True)
        r.route("c", "one")
        r.route("c", "two")
        self.assertEqual(len(set(asked)), 2)

    def test_skips_are_recorded(self):
        calls = []
        r, dag, _ = mk(self.lanes(calls))
        r.route("c", "q")
        self.assertIn("MORNA_SKIP", [e["kind"] for e in dag.content.entries()])

    def test_a_free_lane_is_used_before_a_paid_one_and_paid_is_not_touched(self):
        calls = []
        lanes = self.lanes(calls) + [morna.Lane("free_ref", lambda q: calls.append("free") or "free text", "free", "reference", ["c"])]
        r, _, _ = mk(lanes, paid_ok=lambda n, q: True)
        self.assertEqual(r.route("c", "q")["lane"], "free_ref")
        self.assertEqual(calls, ["free"])


class B_LaneFailures(unittest.TestCase):
    def test_a_failing_lane_falls_through_to_the_next(self):
        def bad(q):
            raise RuntimeError("down")
        lanes = [morna.Lane("a", bad, "free", "reference", ["c"]), morna.Lane("b", lambda q: "fine", "local", "reference", ["c"])]
        r, dag, _ = mk(lanes)
        out = r.route("c", "q")
        self.assertEqual(out["lane"], "b")
        self.assertEqual(out["attempts"][0]["failed"], "RuntimeError")

    def test_non_text_results_are_failures_not_results(self):
        lanes = [morna.Lane("a", lambda q: {"x": 1}, "free", "reference", ["c"]), morna.Lane("b", lambda q: None, "free", "reference", ["c"])]
        r, _, _ = mk(lanes)
        self.assertFalse(r.route("c", "q")["ok"])

    def test_nothing_is_frozen_from_a_failed_call(self):
        n = [0]

        def flaky(q):
            n[0] += 1
            if n[0] == 1:
                raise RuntimeError("once")
            return "ok now"
        r, _, _ = mk([morna.Lane("a", flaky, "free", "reference", ["c"])])
        self.assertFalse(r.route("c", "q")["ok"])
        self.assertEqual(r.route("c", "q")["result"], "ok now")

    def test_the_chain_holds_hashes_not_results(self):
        r, dag, t = mk([morna.Lane("a", lambda q: "CONFIDENTIAL RESULT", "free", "reference", ["c"])])
        r.route("c", "CONFIDENTIAL QUERY")
        raw = open(t / "c.jsonl", encoding="utf-8").read()
        self.assertNotIn("CONFIDENTIAL", raw)

    def test_bad_lane_definitions_are_refused(self):
        for kw in (dict(name="", call=len, cost="free", role="reference", task_classes=["c"]), dict(name="a", call=None, cost="free", role="reference", task_classes=["c"]),
                   dict(name="a", call=len, cost="gratis", role="reference", task_classes=["c"]), dict(name="a", call=len, cost="free", role="boss", task_classes=["c"]),
                   dict(name="a", call=len, cost="free", role="reference", task_classes=[]), dict(name="a", call=len, cost="free", role="reference", task_classes="code")):
            with self.assertRaises(morna.MornaRefused, msg=repr(kw)):
                morna.Lane(**kw)
        with self.assertRaises(morna.MornaRefused):
            mk([morna.Lane("a", len, "free", "reference", ["c"]), morna.Lane("a", len, "free", "reference", ["c"])])

    def test_idle_lanes_collapse_back_to_dormant(self):
        events = []
        lane = morna.Lane("a", lambda q: "x", "free", "reference", ["c"], load=lambda: events.append("load"), unload=lambda: events.append("unload"))
        r, _, _ = mk([lane], clock=lambda: 100.0)
        r.route("c", "q")
        self.assertEqual(r.collapse_idle(110.0, 60), [])
        self.assertEqual(r.collapse_idle(200.0, 60), ["a"])
        self.assertEqual(events, ["load", "unload"])


class C_Overseer(unittest.TestCase):
    def nourishing(self):
        return overseer.digest({"x": 1}, lambda c: c, lambda a: {"passed": True})

    def test_only_exactly_true_passes(self):
        for res in ({"passed": "yes"}, {"passed": 1}, {"passed": None}, {}, "ok", None, 5, [True]):
            self.assertEqual(overseer.digest({}, lambda c: c, lambda a, r=res: r)["state"], "SICK", repr(res))

    def test_cosign_must_return_exactly_true(self):
        v = self.nourishing()
        for sig in ("yes", 1, [1], {"ok": True}, None, "True"):
            self.assertEqual(overseer.promote(v, lambda h, s=sig: s)["status"], "PROPOSED", repr(sig))

    def test_a_crashing_cosign_does_not_promote(self):
        def boom(h):
            raise RuntimeError("signer down")
        self.assertEqual(overseer.promote(self.nourishing(), boom)["status"], "PROPOSED")

    def test_the_cosign_is_asked_about_this_verdict_only(self):
        seen = []
        v = self.nourishing()
        overseer.promote(v, lambda h: seen.append(h) or True)
        self.assertEqual(seen, [overseer.verdict_hash(v)])

    def test_sick_and_hungry_candidates_never_promote_whatever_the_cosign_says(self):
        sick = overseer.digest({}, lambda c: 1 / 0, lambda a: {"passed": True})
        hungry = overseer.digest({}, lambda c: c, lambda a: {"passed": False, "missing": ["x"]})
        for v in (sick, hungry):
            self.assertNotEqual(overseer.promote(v, lambda h: True)["status"], "PROMOTED")

    def test_a_forged_verdict_shape_is_refused(self):
        for bad in ({}, {"state": "PROMOTED"}, {"state": "NOURISHING-ish"}, None, "x"):
            with self.assertRaises(overseer.OverseerRefused):
                overseer.promote(bad, lambda h: True)

    def test_a_test_that_crashes_is_sick_and_a_build_that_crashes_is_sick(self):
        self.assertEqual(overseer.digest({}, lambda c: c, lambda a: 1 / 0)["state"], "SICK")
        self.assertEqual(overseer.digest({}, lambda c: 1 / 0, lambda a: {"passed": True})["state"], "SICK")


class D_Aquire(unittest.TestCase):
    def test_bad_graphs_are_refused(self):
        for g in (None, {}, [], {"a": []}, {"a": {"b": 1}}, {"a": {"a": 0}}, {"a": {"a": -1}}, {"a": {"a": float("nan")}}, {"a": {"a": float("inf")}}, {"a": {"a": True}}, {"a": {"a": "1"}},
                  {1: {}}):
            with self.assertRaises(aquire.AquireRefused, msg=repr(g)):
                aquire.forecast(g, "a")

    def test_bad_parameters_are_refused(self):
        g = {"a": {}}
        for kw in ({"beam": 0}, {"beam": True}, {"beam": 10 ** 6}, {"depth": 0}, {"depth": 10 ** 6}, {"depth": 2.5}):
            with self.assertRaises(aquire.AquireRefused, msg=repr(kw)):
                aquire.forecast(g, "a", **kw)
        with self.assertRaises(aquire.AquireRefused):
            aquire.forecast(g, "missing")

    def test_cycles_terminate_and_probabilities_sum_to_one(self):
        g = {"a": {"b": 1}, "b": {"a": 1, "end": 1}, "end": {}}
        f = aquire.forecast(g, "a", beam=4, depth=10)
        self.assertAlmostEqual(sum(f["outcomes"].values()), 1.0, places=5)

    def test_a_requirement_must_return_exactly_true_to_count(self):
        out = {"x": 0.5, "y": 0.5}
        self.assertEqual(aquire.collapse(out, [lambda n: "yes"])["status"], "NONE")
        self.assertEqual(aquire.collapse(out, [lambda n: n == "x"])["choice"], "x")

    def test_bad_collapse_arguments(self):
        for out, req in (({}, []), (None, []), ({"x": 1}, None), ({"x": 1}, ["notcallable"])):
            with self.assertRaises(aquire.AquireRefused):
                aquire.collapse(out, req)

    def test_a_wide_graph_is_bounded_by_the_beam(self):
        g = {"s": {("n%d" % i): 1 for i in range(500)}}
        g.update({("n%d" % i): {} for i in range(500)})
        f = aquire.forecast(g, "s", beam=5, depth=3)
        self.assertGreater(f["mass_dropped"], 0.9)


class E_Lyra(unittest.TestCase):
    def test_governor_inputs_are_checked(self):
        g = lyra.Governor()
        for bad in (-0.1, 1.1, True, None, "0.5", float("nan")):
            with self.assertRaises(lyra.LyraRefused, msg=repr(bad)):
                g.step(bad)
        for bad in ({"uncertainty": 2}, {"unknown_signal": 0.5}, {"uncertainty": True}, None, [], {"retries": float("nan")}):
            with self.assertRaises(lyra.LyraRefused, msg=repr(bad)):
                lyra.Governor.difficulty(bad)
        for kw in (dict(rise=0), dict(fall=2), dict(min_depth=0), dict(min_depth=5, max_depth=2), dict(max_depth=1000)):
            with self.assertRaises(lyra.LyraRefused, msg=repr(kw)):
                lyra.Governor(**kw)

    def test_missing_signals_are_reported_not_guessed(self):
        d = lyra.Governor.difficulty({"uncertainty": 1.0})
        self.assertIn("novelty", d["missing"])
        self.assertAlmostEqual(d["difficulty"], 0.35)

    def test_mri_input_is_checked(self):
        _, dag, _ = fx.new_log()
        m = lyra.MRI(dag)
        for model, q, o, f, oc in (("", "q", "o", {}, {}), ("m", 5, "o", {}, {}), ("m", "q", None, {}, {}), ("m", "q", "o", {"a": 2}, {}), ("m", "q", "o", {"a b": 1}, {}), ("m", "q", "o", {}, {"x": True}),
                                   ("m", "q", "o", {("k%d" % i): 1 for i in range(100)}, {})):
            with self.assertRaises(lyra.LyraRefused):
                m.observe(model, q, o, f, oc)

    def test_the_mri_stores_hashes_only(self):
        _, dag, t = fx.new_log()
        lyra.MRI(dag).observe("m", "TOP SECRET PROMPT", "TOP SECRET OUTPUT", {"f": 1}, {"x": 0})
        self.assertNotIn("TOP SECRET", open(t / "c.jsonl", encoding="utf-8").read())

    def test_a_chance_pattern_is_not_called_clear(self):
        _, dag, _ = fx.new_log()
        m = lyra.MRI(dag)
        import random
        rnd = random.Random(7)
        for i in range(60):
            m.observe("m", "q%d" % i, "o", {"f%d" % (i % 5): 1, "g": rnd.randint(0, 1)}, {"x": rnd.randint(0, 1)})
        clear = [a for a in m.attribute("m", "x") if a["clear"]]
        self.assertLessEqual(len(clear), 1)

    def test_small_samples_are_not_attributed(self):
        _, dag, _ = fx.new_log()
        m = lyra.MRI(dag)
        for i in range(6):
            m.observe("m", "q%d" % i, "o", {"f": i % 2}, {"x": i % 2})
        self.assertEqual(m.attribute("m", "x", min_n=5), [])
        self.assertIsNone(m.shift("m", "x"))


if __name__ == "__main__":
    unittest.main()
