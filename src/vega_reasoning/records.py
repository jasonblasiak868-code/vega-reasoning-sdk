"""records.py - the history of recorded reasoning: one hash-only record per graded exchange, on a custody chain.

A record never holds the reasoning text, the prompt or the answer: only their hashes, the scores and the labels needed to judge the model later. Roles:
  reference   the teacher whose reasoning is the yardstick (a frontier model's recorded trace)
  apprentice  a smaller or local model being measured against the reference
  frontier    a frontier model measured on its own account (against ground truth, not against itself)
`correct` is ground truth when it is known (a test passed, a human confirmed) and None when it is not: fidelity (matches the reference) and correctness (is right) are different
columns and are never mixed. Records are append-only; a regrade is a new record, and history() reads the LATEST per (query, model, role) so re-running a batch cannot inflate counts."""
import hashlib
import re

from vega_custody.dag.dag import RecordRefused

ROLES = ("reference", "apprentice", "frontier")
KIND = "REASONING_RECORD"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}")
_HEX = re.compile(r"[0-9a-f]{64}")
RESTRICTION_DEFAULT = "PERSONAL_RESEARCH_ONLY__NOT_FOR_COMPETING_OR_SELLABLE_MODEL"


class RecordRefusedError(ValueError):
    pass


def sha(text):
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _score(x, what):
    if x is None:
        return None
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 1:
        raise RecordRefusedError("%s must be a number in 0..1 or None" % what)
    return round(float(x), 4)


def make(role, model, task_class, query, trace, answer, verdict=None, correct=None, latency_ms=None, tokens=None, source="unspecified", reference_provenance=None, training_restriction=None,
         difficulty=None):
    """Build a record from the TEXTS (they are hashed and dropped). verdict is judge.grade(...) output for apprentice/frontier rows measured against a reference."""
    if role not in ROLES:
        raise RecordRefusedError("role must be one of %s" % (ROLES,))
    for v, w in ((model, "model"), (task_class, "task_class"), (source, "source")):
        if not isinstance(v, str) or not _ID.fullmatch(v):
            raise RecordRefusedError("%s must be a plain id" % w)
    for t, w in ((query, "query"), (trace, "trace"), (answer, "answer")):
        if not isinstance(t, str):
            raise RecordRefusedError("%s must be text" % w)
    if correct is not True and correct is not False and correct is not None:                # 1 and 0 equal True and False in Python; ground truth must be a real boolean
        raise RecordRefusedError("correct is True, False or None (unknown)")
    for v, w in ((latency_ms, "latency_ms"), (tokens, "tokens")):
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or v != v or v == float("inf")):
            raise RecordRefusedError("%s must be a non-negative number or None" % w)
    rec = {"role": role, "model": model, "task_class": task_class, "query_sha256": sha(query), "trace_sha256": sha(trace), "answer_sha256": sha(answer), "source": source,
           "correct": correct, "latency_ms": latency_ms, "tokens": tokens, "difficulty": _score(difficulty, "difficulty"),
           "reference_provenance": reference_provenance, "training_restriction": training_restriction or (RESTRICTION_DEFAULT if role == "reference" else None)}
    if verdict is not None:
        if not isinstance(verdict, dict) or "combined_verified" not in verdict:
            raise RecordRefusedError("verdict is the output of judge.grade")
        rec.update(trace_similarity=_score(verdict["trace"]["similarity"], "trace similarity"), trace_contradiction=_score(verdict["trace"]["contradiction"], "trace contradiction"),
                   answer_similarity=_score(verdict["answer"]["similarity"], "answer similarity"), answer_contradiction=_score(verdict["answer"]["contradiction"], "answer contradiction"),
                   combined_verified=bool(verdict["combined_verified"]), judge=str(verdict["trace"].get("judge", "unnamed"))[:64])
    else:
        rec["combined_verified"] = None
    return rec


class ReasoningLog:
    def __init__(self, dag):
        self.dag = dag

    def add(self, rec):
        if not isinstance(rec, dict) or rec.get("role") not in ROLES:
            raise RecordRefusedError("add() takes a record built by make()")
        for k in ("query_sha256", "trace_sha256", "answer_sha256"):
            if not isinstance(rec.get(k), str) or not _HEX.fullmatch(rec[k]):
                raise RecordRefusedError("%s must be a sha256 hex digest" % k)
        try:
            return self.dag.record(KIND, rec)
        except RecordRefused as exc:
            raise RecordRefusedError(str(exc))

    def history(self, task_class=None, model=None, role=None, latest_only=True):
        rows = [e["payload"] for e in self.dag.content.entries() if e["kind"] == KIND]
        if latest_only:
            latest = {}
            for r in rows:
                latest[(r["query_sha256"], r["model"], r["role"])] = r
            rows = list(latest.values())
        return [r for r in rows if (task_class is None or r["task_class"] == task_class) and (model is None or r["model"] == model) and (role is None or r["role"] == role)]

    def verify(self):
        return self.dag.verify()
