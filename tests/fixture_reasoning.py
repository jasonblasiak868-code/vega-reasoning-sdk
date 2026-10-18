"""Shared helpers for the reasoning SDK tests (not a test file)."""
import pathlib
import tempfile

from vega_custody.dag.dag import Dag
from vega_reasoning import judge, records


def new_log():
    t = pathlib.Path(tempfile.mkdtemp())
    dag = Dag([t / "c.jsonl"], [t / "l.jsonl"])
    return records.ReasoningLog(dag), dag, t


def verdict(ok):
    s = 0.9 if ok else 0.1
    return {"trace": {"similarity": s, "contradiction": 0.0, "verified": ok, "judge": "test"}, "answer": {"similarity": s, "contradiction": 0.0, "verified": ok, "judge": "test"}, "combined_verified": ok}


def app_row(i, ok, task_class="code", model="small", correct=None, difficulty=None, query=None):
    return records.make("apprentice", model, task_class, query or "q%d" % i, "trace %d" % i, "answer %d" % i, verdict=verdict(ok), correct=correct, latency_ms=100 + i, difficulty=difficulty)


def frontier_row(i, correct, task_class="code", model="big", query=None, role="frontier"):
    return records.make(role, model, task_class, query or "q%d" % i, "ftrace %d" % i, "fanswer %d" % i, correct=correct, latency_ms=900)


def fill(log, flags, **kw):
    for i, ok in enumerate(flags):
        log.add(app_row(i, ok, **kw))
