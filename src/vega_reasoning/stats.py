"""stats.py - the small statistics the autonomy gate stands on. Standard formulas, no third-party code.

  wilson_lower(successes, n, z)   lower bound of the Wilson score interval: a lucky streak on few trials cannot look like skill
  cusum(seq, k, h)                one-sided CUSUM on a 0/1 failure sequence: alarms when failures run above the sequence's own earlier rate
  brier(pairs)                    mean squared error of probability forecasts, 0 is perfect, 0.25 is a coin flip
  entropy(probs)                  Shannon entropy in bits of a probability distribution"""
import math

Z95 = 1.959963984540054


def wilson_lower(successes, n, z=Z95):
    if not (isinstance(successes, int) and isinstance(n, int)) or isinstance(successes, bool) or isinstance(n, bool) or n < 0 or not 0 <= successes <= n:
        raise ValueError("successes and n must be integers with 0 <= successes <= n")
    if n == 0:
        return 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def cusum(seq, k=0.05, h=4.0, baseline=None):
    """seq: failure indicators (1 = failure), oldest first. The reference rate is the rate over the first half of the sequence unless baseline is given, so drift AFTER a good stretch
    is what trips it. Returns {"alarm": bool, "max": float, "at": index of first alarm or None}."""
    if any(x not in (0, 1) or isinstance(x, bool) for x in seq):
        raise ValueError("seq holds 0 and 1 only")
    if len(seq) < 4:
        return {"alarm": False, "max": 0.0, "at": None}
    ref = baseline if baseline is not None else sum(seq[: len(seq) // 2]) / (len(seq) // 2)
    s, peak, at = 0.0, 0.0, None
    for i, x in enumerate(seq):
        s = max(0.0, s + (x - ref - k))
        peak = max(peak, s)
        if at is None and s > h:
            at = i
    return {"alarm": s > h, "max": round(peak, 4), "at": at, "current": round(s, 4)}      # alarm = drifting NOW (the statistic is still above the bar at the end); a past episode that has since recovered does not keep a class demoted forever


def brier(pairs):
    """pairs: [(forecast probability 0..1, outcome 0 or 1)]."""
    if not pairs:
        return None
    tot = 0.0
    for p, o in pairs:
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1 or o not in (0, 1):
            raise ValueError("each pair is (probability in 0..1, outcome 0 or 1)")
        tot += (p - o) ** 2
    return tot / len(pairs)


def entropy(probs):
    if not probs or any(p < 0 or not math.isfinite(p) for p in probs):
        raise ValueError("probabilities must be finite and non-negative")
    s = sum(probs)
    if s <= 0:
        raise ValueError("probabilities sum to zero")
    return -sum((p / s) * math.log2(p / s) for p in probs if p > 0)
