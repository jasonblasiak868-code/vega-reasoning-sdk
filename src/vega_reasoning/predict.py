"""predict.py - the lattice's forecast of how a model will do, scored against what actually happened, and the history of how its reasoning compared with a frontier model.

LATTICE: cells are nested from specific to general: (task class, model, difficulty bucket) -> (task class, model) -> (task class) -> everything. A forecast uses the most specific cell that
has enough records (min_n) and is shrunk toward its parent cell, so a thin cell borrows from the layer above instead of trusting five samples. With no records at all the answer is
NO BASIS, not a guess.
  Lattice(rows, outcome='correct'|'fidelity').predict(task_class, model, difficulty)
  backtest(rows, outcome)         walk forward through the history: predict each row from only the rows before it; Brier score against 'always the overall rate so far'
  accuracy_report(rows)           per task class: frontier/reference correctness, apprentice fidelity and correctness, the paired comparison on shared queries
  training_gate(rows, purpose)    refuses to hand restricted (frontier-derived) records to a non-personal-research purpose"""
import math

from vega_reasoning.stats import brier, wilson_lower

SHRINK = 5.0
MIN_N = 10


class PredictRefused(ValueError):
    pass


def bucket(d):
    if d is None:
        return "unknown"
    if isinstance(d, bool) or not isinstance(d, (int, float)) or not 0 <= d <= 1:
        raise PredictRefused("difficulty is a number in 0..1 or None")
    return str(min(3, int(d * 4)))


def _outcome(r, outcome):
    v = r.get("correct") if outcome == "correct" else r.get("combined_verified")
    return v if v in (True, False) else None


class Lattice:
    def __init__(self, rows, outcome="correct", min_n=MIN_N):
        if outcome not in ("correct", "fidelity"):
            raise PredictRefused("outcome is 'correct' or 'fidelity'")
        self.outcome, self.min_n = outcome, min_n
        self.cells = {}
        for r in rows:
            o = _outcome(r, outcome)
            if o is None or r.get("role") == "reference" and outcome == "fidelity":
                continue
            for key in self._keys(r.get("task_class"), r.get("model"), r.get("difficulty")):
                n, s = self.cells.get(key, (0, 0))
                self.cells[key] = (n + 1, s + (1 if o else 0))

    @staticmethod
    def _keys(task_class, model, difficulty):
        return [(task_class, model, bucket(difficulty)), (task_class, model), (task_class,), ()]

    def predict(self, task_class, model, difficulty=None):
        keys = self._keys(task_class, model, difficulty)
        chain = [(k, self.cells.get(k, (0, 0))) for k in keys]
        if chain[-1][1][0] == 0:
            return {"probability": None, "basis": "NO BASIS", "level": None, "n": 0, "wilson_lower": None}
        p = None
        used = None
        for k, (n, s) in reversed(chain):                                    # general first, so each finer cell is shrunk toward the one above it
            if n == 0:
                continue
            p = s / n if p is None else (s + SHRINK * p) / (n + SHRINK)
            if used is None or n >= self.min_n:                              # the most specific cell with enough records; failing that, the most general one there is
                used = (k, n, s, p)
        k, n, s, pr = used
        return {"probability": round(pr, 4), "basis": "cell", "level": len(k), "n": n, "wilson_lower": round(wilson_lower(s, n), 4), "enough": n >= self.min_n}


def backtest(rows, outcome="correct", warmup=10):
    seq = [r for r in rows if _outcome(r, outcome) is not None and not (r.get("role") == "reference" and outcome == "fidelity")]
    pairs, base_pairs = [], []
    for i in range(warmup, len(seq)):
        past, now = seq[:i], seq[i]
        p = Lattice(past, outcome).predict(now.get("task_class"), now.get("model"), now.get("difficulty"))["probability"]
        o = 1 if _outcome(now, outcome) else 0
        overall = sum(1 for r in past if _outcome(r, outcome)) / len(past)
        if p is not None:
            pairs.append((p, o))
            base_pairs.append((overall, o))
    if not pairs:
        return {"n": 0, "brier": None, "baseline_brier": None, "skill": None, "note": "not enough history to score"}
    b, bb = brier(pairs), brier(base_pairs)
    skill = None if bb == 0 else round(1 - b / bb, 4)
    bins = {}
    for p, o in pairs:
        k = min(9, int(p * 10))
        n, s, ps = bins.get(k, (0, 0, 0.0))
        bins[k] = (n + 1, s + o, ps + p)
    reliability = [{"bin": "%.1f-%.1f" % (k / 10, (k + 1) / 10), "n": n, "forecast": round(ps / n, 3), "observed": round(s / n, 3)} for k, (n, s, ps) in sorted(bins.items())]
    return {"n": len(pairs), "brier": round(b, 4), "baseline_brier": round(bb, 4), "skill": skill, "reliability": reliability}


def _rate(vals):
    n = len(vals)
    s = sum(1 for v in vals if v)
    return {"n": n, "rate": round(s / n, 4) if n else None, "wilson_lower": round(wilson_lower(s, n), 4) if n else None}


def accuracy_report(rows):
    out = {}
    for c in sorted({r["task_class"] for r in rows}):
        mine = [r for r in rows if r["task_class"] == c]
        frontier = [r for r in mine if r["role"] in ("frontier", "reference") and r.get("correct") in (True, False)]
        app = [r for r in mine if r["role"] == "apprentice"]
        fid = [r["combined_verified"] for r in app if r.get("combined_verified") in (True, False)]
        app_cor = [r for r in app if r.get("correct") in (True, False)]
        fq = {r["query_sha256"]: r["correct"] for r in frontier}
        paired = [(fq[r["query_sha256"]], r["correct"]) for r in app_cor if r["query_sha256"] in fq]
        both = sum(1 for f, a in paired if f and a)
        only_f = sum(1 for f, a in paired if f and not a)
        only_a = sum(1 for f, a in paired if a and not f)
        neither = sum(1 for f, a in paired if not f and not a)
        out[c] = {"frontier_correctness": _rate([r["correct"] for r in frontier]), "apprentice_fidelity": _rate(fid), "apprentice_correctness": _rate([r["correct"] for r in app_cor]),
                  "paired_on_shared_queries": {"n": len(paired), "both_right": both, "only_frontier_right": only_f, "only_apprentice_right": only_a, "neither_right": neither},
                  "honesty": "fidelity = matches the reference trace and answer; correctness = ground truth known right. The two are not the same and are not combined."}
    return out


def training_gate(rows, purpose):
    if purpose not in ("personal_research", "commercial", "competing_model", "sellable_model", "public_release"):
        raise PredictRefused("purpose must be one of personal_research, commercial, competing_model, sellable_model, public_release")
    restricted = [r for r in rows if r.get("training_restriction")]
    if purpose != "personal_research" and restricted:
        return {"allowed": False, "restricted_rows": len(restricted), "why": "rows carry a personal-research-only restriction (frontier-derived reasoning)"}
    return {"allowed": True, "restricted_rows": len(restricted), "why": "no restricted rows" if not restricted else "personal research only"}
