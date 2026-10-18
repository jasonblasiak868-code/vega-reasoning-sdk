"""aquire.py - AQUIRE: reason over a distribution of outcomes, not one answer.

QUANTUM-INSPIRED, CLASSICAL. The name is a design philosophy: a sampler returns a distribution, not 'the answer'. This file is ordinary probability: weighted multi-path beam search forward,
a max-product (Viterbi) best path, and a collapse that picks an outcome only when the requirements leave exactly one. No quantum hardware, no quantum speed-up, no quantum property is claimed.

  forecast(graph, start, beam, depth)   {outcomes: {node: probability}, entropy_bits, best_path, soft_landing, mass_kept}
      graph: {node: {next_node: weight > 0}}; weights out of a node are normalised into probabilities. A node with no way out is an outcome. The beam keeps the `beam` likeliest partial paths
      at each step; the probability mass the beam threw away is reported as 1 - mass_kept, so a narrow beam cannot pass for certainty.
  collapse(outcomes, requirements)      requirements: list of predicates on a node. Exactly one survivor -> COLLAPSED; none -> NONE; several -> AMBIGUOUS (nothing is chosen)."""
import math

from vega_reasoning.stats import entropy

MAX_NODES = 5000
MAX_BEAM = 1000
MAX_DEPTH = 64


class AquireRefused(ValueError):
    pass


def _check(graph):
    if not isinstance(graph, dict) or not graph or len(graph) > MAX_NODES:
        raise AquireRefused("graph is a non-empty dict of at most %d nodes" % MAX_NODES)
    for n, outs in graph.items():
        if not isinstance(n, str) or not isinstance(outs, dict):
            raise AquireRefused("graph maps a node name to a dict of next nodes")
        for m, w in outs.items():
            if not isinstance(m, str) or isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w <= 0:
                raise AquireRefused("an edge weight is a finite number above zero")
            if m not in graph:
                raise AquireRefused("edge %s -> %s leads to an unknown node" % (n, m))


def forecast(graph, start, beam=8, depth=8):
    _check(graph)
    if start not in graph:
        raise AquireRefused("start is not in the graph")
    if isinstance(beam, bool) or not isinstance(beam, int) or not 1 <= beam <= MAX_BEAM or isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= MAX_DEPTH:
        raise AquireRefused("beam is 1..%d and depth is 1..%d" % (MAX_BEAM, MAX_DEPTH))
    paths = [(1.0, (start,))]
    outcomes = {}
    kept = 1.0
    for _ in range(depth):
        nxt = []
        for p, path in paths:
            outs = graph[path[-1]]
            if not outs:
                outcomes[path[-1]] = outcomes.get(path[-1], 0.0) + p
                continue
            tot = sum(outs.values())
            for m, w in outs.items():
                nxt.append((p * w / tot, path + (m,)))
        if not nxt:
            paths = []
            break
        nxt.sort(key=lambda x: (-x[0], x[1]))
        before = sum(p for p, _ in nxt)
        paths = nxt[:beam]
        kept *= (sum(p for p, _ in paths) / before) if before > 0 else 1.0
    for p, path in paths:                                            # paths still open at the depth limit count as outcomes at their last node
        outcomes[path[-1]] = outcomes.get(path[-1], 0.0) + p
    mass = sum(outcomes.values())
    dist = {k: v / mass for k, v in outcomes.items()} if mass > 0 else {}
    best = _viterbi(graph, start, depth)
    ranked = sorted(dist.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"outcomes": {k: round(v, 6) for k, v in ranked}, "entropy_bits": round(entropy(list(dist.values())), 6) if dist else 0.0, "best_path": best,
            "soft_landing": [k for k, _ in ranked[:3]], "mass_kept": round(kept, 6), "mass_dropped": round(1 - kept, 6)}


def _viterbi(graph, start, depth):
    """Highest-probability path of at most `depth` steps from start to a node with no way out (or to the last node reached at the limit)."""
    best = {start: (1.0, (start,))}
    finished = []
    for _ in range(depth):
        nxt = {}
        for n, (p, path) in best.items():
            outs = graph[n]
            if not outs:
                finished.append((p, path))
                continue
            tot = sum(outs.values())
            for m, w in outs.items():
                q = p * w / tot
                if m not in nxt or q > nxt[m][0]:
                    nxt[m] = (q, path + (m,))
        best = nxt
        if not best:
            break
    finished.extend(best.values())
    if not finished:
        return {"path": [start], "probability": 1.0}
    p, path = max(finished, key=lambda x: (x[0], x[1]))
    return {"path": list(path), "probability": round(p, 6)}


def collapse(outcomes, requirements):
    if not isinstance(outcomes, dict) or not outcomes:
        raise AquireRefused("outcomes is a non-empty dict from node to probability")
    if not isinstance(requirements, (list, tuple)) or not all(callable(r) for r in requirements):
        raise AquireRefused("requirements is a list of functions")
    keep = [n for n in outcomes if all(r(n) is True for r in requirements)]
    if len(keep) == 1:
        return {"status": "COLLAPSED", "choice": keep[0], "candidates": keep}
    if not keep:
        return {"status": "NONE", "choice": None, "candidates": []}
    return {"status": "AMBIGUOUS", "choice": None, "candidates": sorted(keep, key=lambda n: -outcomes[n])}
