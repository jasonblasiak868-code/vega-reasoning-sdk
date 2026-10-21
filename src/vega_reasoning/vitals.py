"""vitals.py - a model's vital signs, read from its record: how often it is right, how fast it answers, whether it is getting worse, and a plain GREEN / AMBER / RED.

  vitals(rows, model, now_epoch=None, last_epoch=None)

Sources are the records of ReasoningLog (hash-only). Two accuracy columns are kept apart: `fidelity` (matches the reference trace AND answer) and `correctness` (ground truth known to be right).
A column with fewer than MIN_N observations is reported as unknown and caps the colour at AMBER: no vital sign is claimed from a handful of samples."""
from vega_reasoning.stats import cusum, wilson_lower

MIN_N = 20
STALE_SECONDS = 14 * 24 * 3600


def _pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def _column(vals):
    n = len(vals)
    s = sum(1 for v in vals if v)
    return {"n": n, "successes": s, "rate": round(s / n, 4) if n else None, "wilson_lower": round(wilson_lower(s, n), 4) if n else None,
            "drift_alarm": bool(cusum([0 if v else 1 for v in vals])["alarm"]) if n >= 10 else False}


def vitals(rows, model, now_epoch=None, last_epoch=None):
    mine = [r for r in rows if r.get("model") == model]
    fid = _column([r["combined_verified"] for r in mine if r.get("combined_verified") is True or r.get("combined_verified") is False])
    cor = _column([r["correct"] for r in mine if r.get("correct") is True or r.get("correct") is False])
    lat = [r["latency_ms"] for r in mine if isinstance(r.get("latency_ms"), (int, float))]
    out = {"model": model, "records": len(mine), "fidelity": fid, "correctness": cor, "latency_ms": {"n": len(lat), "p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95)}, "reasons": []}
    stale = now_epoch is not None and last_epoch is not None and now_epoch - last_epoch > STALE_SECONDS
    colour = "GREEN"
    for name, col in (("fidelity", fid), ("correctness", cor)):
        if col["n"] == 0:
            continue
        if col["drift_alarm"]:
            colour = "RED"
            out["reasons"].append("%s is drifting (more failures lately than its own earlier record)" % name)
        elif col["n"] < MIN_N:
            colour = colour if colour == "RED" else "AMBER"
            out["reasons"].append("%s has only %d observations: unknown, not good" % (name, col["n"]))
        elif col["wilson_lower"] < 0.5:
            colour = "RED"
            out["reasons"].append("%s lower bound %.2f is below 0.5" % (name, col["wilson_lower"]))
        elif col["wilson_lower"] < 0.8:
            colour = colour if colour == "RED" else "AMBER"
            out["reasons"].append("%s lower bound %.2f is below 0.8" % (name, col["wilson_lower"]))
    if fid["n"] == 0 and cor["n"] == 0:
        colour = "AMBER"
        out["reasons"].append("no graded or ground-truthed observations yet")
    if stale:
        colour = colour if colour == "RED" else "AMBER"
        out["reasons"].append("no new record for over 14 days")
    out["health"] = colour
    return out
