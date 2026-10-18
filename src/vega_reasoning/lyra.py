"""lyra.py - Lyra: the model MRI and the difficulty governor.

MRI: records, for every call, what went in and what came out as HASHES plus a small set of caller-supplied features (is there code, is it long, was a tool involved, did it refuse), and
then answers the question 'what in the prompts is associated with a change in this model's behaviour'. It sees associations in the record; it does not prove cause.
Governor: turns a difficulty signal into how much thinking to spend (how many echoes or branches), rising fast when things get hard and falling slowly when they ease, never past a ceiling.

  MRI(dag).observe(model, query, output, features, outcome)      one record: outcome is a dict of 0/1 behaviour flags, e.g. {"refused": 0, "wrong": 1}
  MRI.attribute(model, flag, min_n)                              features ranked by how much they raise (or lower) the flag's rate, with an interval
  Governor().difficulty(signals) / .step(d)                      difficulty 0..1 and the depth to spend"""
import hashlib
import math
import re

from vega_custody.dag.dag import RecordRefused

KIND = "LYRA_OBSERVATION"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}")
MAX_FEATURES = 64


class LyraRefused(ValueError):
    pass


def _h(t):
    return hashlib.sha256(t.encode("utf-8", "surrogatepass")).hexdigest()


class MRI:
    def __init__(self, dag):
        self.dag = dag

    def observe(self, model, query, output, features, outcome):
        if not isinstance(model, str) or not _ID.fullmatch(model):
            raise LyraRefused("model must be a plain id")
        if not isinstance(query, str) or not isinstance(output, str):
            raise LyraRefused("query and output are text (hashed and dropped)")
        for d, w in ((features, "features"), (outcome, "outcome")):
            if not isinstance(d, dict) or len(d) > MAX_FEATURES or any(not isinstance(k, str) or not _ID.fullmatch(k) or v not in (0, 1) or isinstance(v, bool) for k, v in d.items()):
                raise LyraRefused("%s is a dict of at most %d plain names to 0 or 1" % (w, MAX_FEATURES))
        try:
            return self.dag.record(KIND, {"model": model, "query_sha256": _h(query), "output_sha256": _h(output), "features": dict(sorted(features.items())), "outcome": dict(sorted(outcome.items()))})
        except RecordRefused as exc:
            raise LyraRefused(str(exc))

    def rows(self, model):
        return [e["payload"] for e in self.dag.content.entries() if e["kind"] == KIND and e["payload"]["model"] == model]

    def attribute(self, model, flag, min_n=5):
        """For each feature with at least min_n rows with it AND min_n without it: rate of `flag` with the feature, without it, and the difference with a 95% half-width.
        Ranked by absolute difference. An association in a record, not a cause."""
        rows = [r for r in self.rows(model) if flag in r["outcome"]]
        names = sorted({k for r in rows for k in r["features"]})
        out = []
        for f in names:
            a = [r["outcome"][flag] for r in rows if r["features"].get(f) == 1]
            b = [r["outcome"][flag] for r in rows if r["features"].get(f) != 1]
            if len(a) < min_n or len(b) < min_n:
                continue
            pa, pb = sum(a) / len(a), sum(b) / len(b)
            half = 1.96 * math.sqrt(pa * (1 - pa) / len(a) + pb * (1 - pb) / len(b))
            out.append({"feature": f, "with": round(pa, 4), "without": round(pb, 4), "difference": round(pa - pb, 4), "half_width": round(half, 4), "n_with": len(a), "n_without": len(b),
                        "clear": abs(pa - pb) > half})
        return sorted(out, key=lambda x: -abs(x["difference"]))

    def shift(self, model, flag, window=20):
        """Compare the flag's rate in the latest `window` rows with the rows before them. Returns None when there are not enough rows for both."""
        vals = [r["outcome"][flag] for r in self.rows(model) if flag in r["outcome"]]
        if len(vals) < 2 * window:
            return None
        new, old = vals[-window:], vals[:-window]
        pn, po = sum(new) / len(new), sum(old) / len(old)
        half = 1.96 * math.sqrt(pn * (1 - pn) / len(new) + po * (1 - po) / len(old))
        return {"old_rate": round(po, 4), "new_rate": round(pn, 4), "difference": round(pn - po, 4), "half_width": round(half, 4), "shifted": abs(pn - po) > half and half >= 0}


WEIGHTS = {"uncertainty": 0.35, "disagreement": 0.25, "retries": 0.15, "overrun": 0.15, "novelty": 0.10}


class Governor:
    """level is a smoothed difficulty: it moves up by `rise` of the gap when difficulty is above it and down by `fall` of the gap when below (fast up, slow down)."""

    def __init__(self, rise=0.6, fall=0.15, min_depth=1, max_depth=8):
        if not (0 < rise <= 1 and 0 < fall <= 1) or not (1 <= min_depth <= max_depth <= 64):
            raise LyraRefused("rise and fall are in (0,1]; depths are 1 <= min <= max <= 64")
        self.rise, self.fall, self.lo, self.hi = rise, fall, min_depth, max_depth
        self.level = 0.0

    @staticmethod
    def difficulty(signals):
        """signals: dict of any of uncertainty, disagreement, retries, overrun, novelty, each 0..1. Unknown names are refused; a missing one counts as 0 and is reported."""
        if not isinstance(signals, dict) or set(signals) - set(WEIGHTS):
            raise LyraRefused("signals may only be %s" % sorted(WEIGHTS))
        for k, v in signals.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1 or v != v:
                raise LyraRefused("%s must be a number in 0..1" % k)
        d = sum(WEIGHTS[k] * float(signals.get(k, 0.0)) for k in WEIGHTS)
        return {"difficulty": round(d, 4), "known": sorted(signals), "missing": sorted(set(WEIGHTS) - set(signals))}

    def step(self, difficulty):
        if isinstance(difficulty, bool) or not isinstance(difficulty, (int, float)) or not 0 <= difficulty <= 1:
            raise LyraRefused("difficulty is a number in 0..1")
        gain = self.rise if difficulty > self.level else self.fall
        self.level += gain * (difficulty - self.level)
        depth = self.lo + round((self.hi - self.lo) * self.level)
        return {"level": round(self.level, 4), "depth": max(self.lo, min(self.hi, depth))}
