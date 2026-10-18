"""judge.py - how two pieces of reasoning are compared.

A judge is any function judge(reference_text, candidate_text) -> {"similarity": 0..1, "contradiction": 0..1}. Real deployments plug in an embedding similarity plus an entailment model
(cosine alone is blind to negation: 'do NOT delete' scores close to 'delete'). This module supplies:
  lexical_judge        an offline stand-in: word overlap plus a negation check. Labelled lexical in every verdict; it is a floor for tests and for machines with no model, not a measure of meaning
  grade(...)           applies the bars to a trace comparison AND an answer comparison. combined_verified needs BOTH: a right answer reached by wrong reasoning does not count"""
import re

_WORD = re.compile(r"[a-z0-9']+")
_NEG = frozenset(["not", "no", "never", "cannot", "dont", "don't", "doesnt", "doesn't", "without", "avoid", "stop", "refuse", "refused", "reject", "rejected", "wont", "won't", "shouldnt", "shouldn't"])
_STOP = frozenset("a an the and or of to in is it that this for on with as be are was were by at from".split())
SIM_BAR = 0.45
CONTRA_BAR = 0.5


class JudgeRefused(ValueError):
    pass


def _tokens(text):
    return [w for w in _WORD.findall(text.casefold())]


def lexical_judge(reference, candidate):
    if not isinstance(reference, str) or not isinstance(candidate, str):
        raise JudgeRefused("judge compares two texts")
    a, b = _tokens(reference), _tokens(candidate)
    ca = {w for w in a if w not in _STOP and w not in _NEG}
    cb = {w for w in b if w not in _STOP and w not in _NEG}
    union = ca | cb
    sim = len(ca & cb) / len(union) if union else 0.0
    neg_a, neg_b = sum(1 for w in a if w in _NEG), sum(1 for w in b if w in _NEG)
    contradiction = 0.0
    if sim >= 0.3 and (neg_a % 2) != (neg_b % 2):                     # same topic, one negated: a contradiction signal
        contradiction = 0.9
    return {"similarity": round(sim, 4), "contradiction": contradiction, "judge": "lexical"}


def _side(verdict, sim_bar, contra_bar):
    if not isinstance(verdict, dict):
        raise JudgeRefused("a judge returns a dict")
    sim, con = verdict.get("similarity"), verdict.get("contradiction")
    for v in (sim, con):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
            raise JudgeRefused("similarity and contradiction are numbers in 0..1")
    return {"similarity": float(sim), "contradiction": float(con), "verified": bool(sim >= sim_bar and con < contra_bar), "judge": verdict.get("judge", "unnamed")}


def grade(reference_trace, reference_answer, candidate_trace, candidate_answer, judge=lexical_judge, sim_bar=SIM_BAR, contra_bar=CONTRA_BAR):
    trace = _side(judge(reference_trace, candidate_trace), sim_bar, contra_bar)
    answer = _side(judge(reference_answer, candidate_answer), sim_bar, contra_bar)
    return {"trace": trace, "answer": answer, "combined_verified": bool(trace["verified"] and answer["verified"])}
