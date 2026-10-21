"""overseer.py - the Overseer (the stomach): a candidate merger is promoted by TEST, and only a human anchors it.

  digest(candidate, build, test)   build(candidate) -> artifact (or raises); test(artifact) -> {"passed": bool, "missing": [names]}
      NOURISHING  built and passed          SICK  failed to build or failed the test          HUNGRY  built, did not pass, and names what is missing
  promote(verdict, cosign)         turns a NOURISHING verdict into PROMOTED only when cosign(verdict) is exactly True (a human's signature check supplied by the caller).
                                   Without it the candidate stays PROPOSED. The overseer digests and proposes; it never anchors its own findings, so it cannot feed itself flattering results.
Nothing here signs anything. `cosign` is a verification function the caller wires to the governance jacket (a human-signed commitment for exactly this verdict hash)."""
import hashlib
import json

STATES = ("NOURISHING", "SICK", "HUNGRY")


class OverseerRefused(ValueError):
    pass


def digest(candidate, build, test):
    if not callable(build) or not callable(test):
        raise OverseerRefused("build and test are functions")
    try:
        cid = hashlib.sha256(json.dumps(candidate, sort_keys=True, allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError, RecursionError) as exc:                   # an object inside would be hashed by its memory address (different every run): refuse it instead
        raise OverseerRefused("a candidate is plain data (text, numbers, lists, dicts)") from exc
    try:
        art = build(candidate)
    except Exception as exc:                                                    # a candidate that cannot be built is SICK, whatever the reason
        return {"candidate_sha256": cid, "state": "SICK", "why": "build failed: %s" % type(exc).__name__, "missing": []}
    try:
        res = test(art)
    except Exception as exc:
        return {"candidate_sha256": cid, "state": "SICK", "why": "test crashed: %s" % type(exc).__name__, "missing": []}
    if not isinstance(res, dict) or res.get("passed") not in (True, False):
        return {"candidate_sha256": cid, "state": "SICK", "why": "test returned no clear pass or fail", "missing": []}
    if res["passed"] is True:
        return {"candidate_sha256": cid, "state": "NOURISHING", "why": "built and passed", "missing": []}
    missing = [m for m in (res.get("missing") or []) if isinstance(m, str)][:50]
    return {"candidate_sha256": cid, "state": "HUNGRY" if missing else "SICK", "why": "did not pass", "missing": missing}


def verdict_hash(verdict):
    return hashlib.sha256(json.dumps(verdict, sort_keys=True).encode()).hexdigest()


def promote(verdict, cosign):
    if not isinstance(verdict, dict) or verdict.get("state") not in STATES:
        raise OverseerRefused("promote takes a verdict from digest()")
    if verdict["state"] != "NOURISHING":
        return {"status": "REJECTED" if verdict["state"] == "SICK" else "INCOMPLETE", "verdict_sha256": verdict_hash(verdict)}
    if not callable(cosign):
        return {"status": "PROPOSED", "verdict_sha256": verdict_hash(verdict), "why": "no human co-sign supplied"}
    try:
        ok = cosign(verdict_hash(verdict))
    except Exception:
        ok = False
    if ok is True:
        return {"status": "PROMOTED", "verdict_sha256": verdict_hash(verdict)}
    return {"status": "PROPOSED", "verdict_sha256": verdict_hash(verdict), "why": "human co-sign refused or failed"}
