"""fidelity.py - the autonomy gate: an apprentice is trusted for a task class only when its record says so, and loses that trust when the record turns.

  status(rows, ...)     per task class: n, successes, Wilson lower bound, drift alarm, promoted or not, and an honest note when n is too small to claim anything
  route(status)         'apprentice' only when promoted; otherwise 'reference_required'
Promotion needs ALL of: n >= min_n, Wilson lower bound >= bar, no drift alarm. A rolling average is not used: a lucky streak cannot promote and drift after promotion demotes.
Promoted means 'matches the reference on the tested distribution'. It does not mean frontier quality, and the reference's own mistakes are inherited."""
from vega_reasoning.stats import cusum, wilson_lower

MIN_N = 30
WILSON_BAR = 0.80
CUSUM_K = 0.05
CUSUM_H = 4.0


def status(rows, task_class, min_n=MIN_N, bar=WILSON_BAR, k=CUSUM_K, h=CUSUM_H):
    """rows: records (apprentice role, with combined_verified True/False) in time order, already de-duplicated (ReasoningLog.history)."""
    mine = [r for r in rows if r.get("task_class") == task_class and r.get("role") == "apprentice" and (r.get("combined_verified") is True or r.get("combined_verified") is False)]
    n = len(mine)
    succ = sum(1 for r in mine if r["combined_verified"])
    wl = wilson_lower(succ, n) if n else 0.0
    drift = cusum([0 if r["combined_verified"] else 1 for r in mine], k=k, h=h) if n >= 10 else {"alarm": False, "max": 0.0, "at": None}
    promoted = n >= min_n and wl >= bar and not drift["alarm"]
    return {"task_class": task_class, "n": n, "successes": succ, "wilson_lower": round(wl, 4), "cusum_alarm": drift["alarm"], "promoted": promoted,
            "honesty": ("n<%d: not a claim" % min_n) if n < min_n else "sample ok"}


def route(st):
    return "apprentice" if st["promoted"] else "reference_required"


def all_status(rows, **kw):
    classes = sorted({r["task_class"] for r in rows if r.get("role") == "apprentice"})
    return {c: status(rows, c, **kw) for c in classes}
