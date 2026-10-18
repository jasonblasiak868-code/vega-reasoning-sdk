"""morna.py - MoRNA: many specialists dormant on disk, one transcribed into use per request, results frozen so the same reasoning is never paid for twice.

A lane is a function the caller supplies (a local model, a remote endpoint, a lookup): the SDK never opens a network connection and never calls a provider on its own.
  Lane(name, call, cost, role, task_classes, load=None, unload=None)    cost is 'free' | 'local' | 'paid'; role is 'apprentice' | 'reference'
  Router(lanes, rows_fn, dag, paid_ok=None)
      route(task_class, query):
        1. frozen result for this (lane, query)? return it, zero compute
        2. candidate lanes: an apprentice lane only if fidelity says the class is PROMOTED, else a reference lane; cheapest cost first
        3. a PAID lane runs only when paid_ok(lane_name, query_sha256) returns exactly True (a human-signed commitment check the caller wires in); with no paid_ok it never runs
        4. a lane that raises or returns a non-text result is skipped and the next one tried; every attempt is recorded (hashes only)
  collapse_idle(now, idle_seconds)   unload lanes unused for idle_seconds (back to dormant)"""
import hashlib
import re
import time

from vega_custody.dag.dag import RecordRefused
from vega_reasoning import fidelity

COSTS = ("free", "local", "paid")
ROLES = ("apprentice", "reference")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}")


class MornaRefused(ValueError):
    pass


def _h(t):
    return hashlib.sha256(t.encode("utf-8", "surrogatepass")).hexdigest()


class Lane:
    def __init__(self, name, call, cost, role, task_classes, load=None, unload=None):
        if not isinstance(name, str) or not _ID.fullmatch(name) or not callable(call) or cost not in COSTS or role not in ROLES:
            raise MornaRefused("a lane needs a plain name, a function, a cost in %s and a role in %s" % (COSTS, ROLES))
        if not isinstance(task_classes, (list, tuple, set, frozenset)) or not task_classes or any(not isinstance(t, str) or not _ID.fullmatch(t) for t in task_classes):
            raise MornaRefused("task_classes is a non-empty list of plain ids")
        self.name, self.call, self.cost, self.role, self.classes = name, call, cost, role, frozenset(task_classes)
        self.load, self.unload = load, unload
        self.active, self.last_used = False, 0.0

    def transcribe(self, now):
        if not self.active and self.load:
            self.load()
        self.active, self.last_used = True, now


class Router:
    def __init__(self, lanes, rows_fn, dag, paid_ok=None, clock=time.time):
        names = [l.name for l in lanes]
        if len(set(names)) != len(names):
            raise MornaRefused("two lanes share a name")
        self.lanes = {l.name: l for l in lanes}
        self.rows_fn, self.dag, self.paid_ok, self.clock = rows_fn, dag, paid_ok, clock
        self.frozen = {}

    def _record(self, kind, payload):
        try:
            self.dag.record(kind, payload)
        except RecordRefused as exc:
            raise MornaRefused("could not record: %s" % exc)

    def route(self, task_class, query):
        if not isinstance(query, str) or not isinstance(task_class, str) or not _ID.fullmatch(task_class):
            raise MornaRefused("task_class is a plain id and query is text")
        qh = _h(query)
        st = fidelity.status(self.rows_fn(), task_class)
        want = "apprentice" if st["promoted"] else "reference"
        cands = sorted((l for l in self.lanes.values() if task_class in l.classes and l.role == want), key=lambda l: (COSTS.index(l.cost), l.name))
        attempts = []
        for lane in cands:
            key = (lane.name, qh)
            if key in self.frozen:
                self._record("MORNA_RECALL", {"lane": lane.name, "query_sha256": qh, "result_sha256": self.frozen[key][1]})
                return {"ok": True, "lane": lane.name, "result": self.frozen[key][0], "recalled": True, "gate": want, "attempts": attempts}
            if lane.cost == "paid" and not (callable(self.paid_ok) and self._paid(lane, qh)):
                attempts.append({"lane": lane.name, "skipped": "paid lane without a verified commitment"})
                self._record("MORNA_SKIP", {"lane": lane.name, "query_sha256": qh, "reason": "paid_without_commitment"})
                continue
            try:
                lane.transcribe(self.clock())
                t0 = time.perf_counter()
                out = lane.call(query)
                ms = round((time.perf_counter() - t0) * 1000, 3)
            except Exception as exc:
                attempts.append({"lane": lane.name, "failed": type(exc).__name__})
                self._record("MORNA_FAIL", {"lane": lane.name, "query_sha256": qh, "error": type(exc).__name__})
                continue
            if not isinstance(out, str):
                attempts.append({"lane": lane.name, "failed": "non-text result"})
                self._record("MORNA_FAIL", {"lane": lane.name, "query_sha256": qh, "error": "non_text_result"})
                continue
            rh = _h(out)
            self.frozen[key] = (out, rh)
            self._record("MORNA_CALL", {"lane": lane.name, "cost": lane.cost, "query_sha256": qh, "result_sha256": rh, "latency_ms": ms, "gate": want})
            return {"ok": True, "lane": lane.name, "result": out, "recalled": False, "gate": want, "attempts": attempts}
        return {"ok": False, "lane": None, "result": None, "recalled": False, "gate": want, "attempts": attempts}

    def _paid(self, lane, qh):
        try:
            return self.paid_ok(lane.name, qh) is True
        except Exception:
            return False

    def collapse_idle(self, now, idle_seconds):
        done = []
        for l in self.lanes.values():
            if l.active and now - l.last_used >= idle_seconds:
                if l.unload:
                    l.unload()
                l.active = False
                done.append(l.name)
        return sorted(done)
