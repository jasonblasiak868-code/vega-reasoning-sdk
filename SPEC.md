# vega-reasoning-sdk — Specification

Spec v1.0 — 2026-10-19 — describes the published reference implementation as tested; where this document and the source disagree, the source wins.

## 1. Purpose and scope

This specification covers the **reason** layer (layer 11) of the Vega SDK family: forecasting model accuracy from recorded history, gating autonomy per task class, routing to the cheapest capable lane, comparing reasoning traces, reading model vitals, performing model MRI, forecasting over outcome distributions, digesting candidates by test, and predicting accuracy via a nested lattice. 

Out of scope: embedding/entailment judge implementations, model lane implementations (local/remote endpoints), fine-tune loops, training execution, any hardware-specific code, any network I/O, any key management or signing (delegated to vega-governance-jacket-sdk and vega-custody-sdk).

## 2. Vocabulary

| Term | Definition |
|---|---|
| **record** | A hash-only entry on the custody chain capturing one graded exchange: query/trace/answer hashes, role (reference/apprentice/frontier), model id, task class, scores, verdict, ground-truth correctness, latency, difficulty, source, training restriction. |
| **commitment** | A human-signed, single-use note authorizing exactly one action (e.g., running a paid lane). Verified by caller-supplied `paid_ok` or `cosign` functions; the SDK never holds signing keys. |
| **gate** | A function that refuses unless its conditions hold. Fail-closed: invalid input, missing commitment, failed check → refuse/deny. |
| **fidelity** | Whether an apprentice's trace AND answer both match the reference (judge.grade combined_verified). Distinct from correctness (ground truth). |
| **promotion** | An apprentice lane is trusted for a task class when: n≥30, Wilson lower bound ≥0.80, no CUSUM drift alarm. Demoted automatically when drift appears. |
| **lattice** | Nested cells from specific to general: (task_class, model, difficulty_bucket) → (task_class, model) → (task_class) → global. Forecasts shrink toward parent; thin cells borrow from above. |
| **collapse** | In AQUIRE: picking an outcome only when requirements leave exactly one survivor; otherwise AMBIGUOUS or NONE. |
| **MRI** | Model Reasoning Insight: records prompt features (hashes only) and outcome flags; attributes features to flags via rate difference with confidence interval. |
| **governor** | Difficulty → depth mapping: level rises fast (rise=0.6) when difficulty>level, falls slow (fall=0.15) when below, capped at max_depth. |
| **vitals** | GREEN/AMBER/RED health from fidelity, correctness, drift, sample count, staleness. |
| **overseer** | Digests a candidate (build+test) → NOURISHING/SICK/HUNGRY; promotes only with human co-sign on verdict hash. |
| **training restriction** | Frontier-derived records carry `PERSONAL_RESEARCH_ONLY__NOT_FOR_COMPETING_OR_SELLABLE_MODEL`; `training_gate` refuses them for other purposes. |

## 3. Components

### 3.1 records.py

**Role:** Hash-only record of every graded exchange on the custody chain; ground truth kept apart from fidelity.

**Public interface:**
- `ROLES = ("reference", "apprentice", "frontier")`
- `KIND = "REASONING_RECORD"`
- `RESTRICTION_DEFAULT = "PERSONAL_RESEARCH_ONLY__NOT_FOR_COMPETING_OR_SELLABLE_MODEL"`
- `sha(text) -> str`
- `make(role, model, task_class, query, trace, answer, verdict=None, correct=None, latency_ms=None, tokens=None, source="unspecified", reference_provenance=None, training_restriction=None, difficulty=None) -> dict`
- `RecordRefusedError`
- `ReasoningLog(dag)` with `.add(rec)`, `.history(task_class=None, model=None, role=None, latest_only=True)`, `.verify()`

**Behavior:** `make` validates all fields, hashes texts, attaches verdict scores if provided, applies default training restriction for reference role. `ReasoningLog.add` writes to custody Dag; `history` returns latest per (query_sha256, model, role) when `latest_only=True` (prevents regrade inflation). Fail-closed: any invalid field → `RecordRefusedError`; Dag refusal → `RecordRefusedError`.

**Invariants:** 
- Texts never reach the chain (only SHA-256 hashes).
- `latest_only` deduplication prevents count inflation.
- Training restriction hashed on chain; stripping it from a local copy does not affect the recorded version.
- `combined_verified` is None for reference rows (they are the yardstick, not measured against one).

### 3.2 fidelity.py

**Role:** Autonomy gate — promotes an apprentice per task class only when its record supports it; demotes on drift.

**Public interface:**
- `MIN_N = 30`, `WILSON_BAR = 0.80`, `CUSUM_K = 0.05`, `CUSUM_H = 4.0`
- `status(rows, task_class, min_n=MIN_N, bar=WILSON_BAR, k=CUSUM_K, h=CUSUM_H) -> dict`
- `route(st) -> "apprentice" | "reference_required"`
- `all_status(rows, **kw) -> dict`

**Behavior:** `status` filters apprentice rows with `combined_verified` in (True, False), computes n, successes, Wilson lower bound, CUSUM drift alarm (reference rate = first half of sequence). `promoted = n>=min_n and wl>=bar and not drift["alarm"]`. `route` returns "apprentice" iff promoted. Fail-closed: drift alarm → demotion; n<min_n → not promoted; Wilson<bar → not promoted.

**Invariants:**
- Rolling average not used; lucky streak cannot promote.
- Drift after promotion demotes immediately (CUSUM reference is first half, so late drift trips it).
- Per task class; one class cannot borrow another's record.

### 3.3 judge.py

**Role:** Compare two reasoning texts; trace AND answer must both pass.

**Public interface:**
- `SIM_BAR = 0.45`, `CONTRA_BAR = 0.5`
- `JudgeRefused`
- `lexical_judge(reference, candidate) -> {similarity, contradiction, judge:"lexical"}`
- `grade(reference_trace, reference_answer, candidate_trace, candidate_answer, judge=lexical_judge, sim_bar=SIM_BAR, contra_bar=CONTRA_BAR) -> {trace, answer, combined_verified}`

**Behavior:** `lexical_judge` uses word overlap (stopwords removed) plus negation parity check (contradiction=0.9 when same topic, one negated). `grade` runs judge on trace and answer separately; `combined_verified = trace.verified and answer.verified`. Fail-closed: invalid judge output → `JudgeRefused`; non-text input → `JudgeRefused`; similarity/contradiction outside 0..1 → `JudgeRefused`.

**Invariants:**
- Cosine alone is blind to negation; lexical_judge catches "do NOT delete" vs "delete".
- Real deployments plug in embedding + entailment judge; lexical is a floor for tests/offline.
- Both trace AND answer must verify; right answer via wrong reasoning does not count.

### 3.4 vitals.py

**Role:** Model vital signs from records: fidelity, correctness, latency, drift, staleness → GREEN/AMBER/RED.

**Public interface:**
- `MIN_N = 20`, `STALE_SECONDS = 14*24*3600`
- `vitals(rows, model, now_epoch=None, last_epoch=None) -> dict`

**Behavior:** Builds columns for fidelity (combined_verified) and correctness (correct bool), computes Wilson lower bound, CUSUM drift, latency percentiles. Color logic: RED if drift or Wilson<0.5; AMBER if n<MIN_N or Wilson<0.8 or stale (>14 days); GREEN only if n≥MIN_N, Wilson≥0.8, no drift, not stale. No data → AMBER.

**Invariants:**
- Small samples never GREEN (capped at AMBER).
- Fidelity and correctness tracked separately; not combined.
- Staleness degrades GREEN→AMBER, AMBER stays AMBER, RED stays RED.

### 3.5 lyra.py

**Role:** Model MRI (prompt feature → behavior association) + difficulty governor (fast rise, slow fall, capped depth).

**Public interface:**
- `KIND = "LYRA_OBSERVATION"`, `MAX_FEATURES = 64`
- `LyraRefused`
- `MRI(dag)` with `.observe(model, query, output, features, outcome)`, `.rows(model)`, `.attribute(model, flag, min_n=5)`, `.shift(model, flag, window=20)`
- `WEIGHTS = {uncertainty:0.35, disagreement:0.25, retries:0.15, overrun:0.15, novelty:0.10}`
- `Governor(rise=0.6, fall=0.15, min_depth=1, max_depth=8)` with `.difficulty(signals) -> {difficulty, known[], missing[]}`, `.step(difficulty) -> {level, depth}`

**Behavior:** `MRI.observe` hashes query/output, stores features (dict name→0/1) and outcome (dict flag→0/1). `attribute` computes rate difference with 95% half-width; requires min_n with and without feature; `clear = |diff| > half_width`. `shift` compares latest window vs prior. `Governor.difficulty` weights known signals, reports missing; `step` updates level with rise/fall asymmetry, returns integer depth in [min_depth, max_depth]. Fail-closed: bad inputs → `LyraRefused`; unknown signal names refused; missing signals count as 0 and reported.

**Invariants:**
- Hashes only on chain; features/outcome are 0/1 dicts ≤64 entries.
- Association in record, not causation; `clear` means statistically detectable, not proven cause.
- Governor never exceeds `max_depth`; rise>fall ensures fast response to difficulty.

### 3.6 aquire.py

**Role:** Forecast over outcome distributions via beam search + Viterbi; collapse only when requirements leave exactly one.

**Public interface:**
- `MAX_NODES = 5000`, `MAX_BEAM = 1000`, `MAX_DEPTH = 64`
- `AquireRefused`
- `forecast(graph, start, beam=8, depth=8) -> {outcomes, entropy_bits, best_path, soft_landing, mass_kept, mass_dropped}`
- `collapse(outcomes, requirements) -> {status, choice, candidates}`

**Behavior:** `graph = {node: {next_node: weight>0}}`; weights normalized to probabilities per node. Beam keeps top `beam` partial paths per step; `mass_kept` tracks probability retained. Nodes with no outgoing edges are outcomes. `collapse` filters outcomes by predicate functions; exactly one → COLLAPSED; none → NONE; multiple → AMBIGUOUS. Fail-closed: bad graph/params → `AquireRefused`; collapse never guesses.

**Invariants:**
- Classical probability only; "quantum-inspired" is a design philosophy, no quantum claim.
- `mass_dropped` reported so narrow beam cannot pass for certainty.
- Cycles terminate (depth limit); probabilities sum to 1.
- Requirements must return exactly `True` to count; truthy not accepted.

### 3.7 morna.py

**Role:** Dormant lane routing; cheapest capable lane; frozen results; paid lanes need verified commitment.

**Public interface:**
- `COSTS = ("free", "local", "paid")`, `ROLES = ("apprentice", "reference")`
- `MornaRefused`
- `Lane(name, call, cost, role, task_classes, load=None, unload=None)`
- `Router(lanes, rows_fn, dag, paid_ok=None, clock=time.time)` with `.route(task_class, query)`, `.collapse_idle(now, idle_seconds)`

**Behavior:** `route`: frozen cache hit → return instantly; else fidelity.status → want "apprentice" if promoted else "reference"; candidate lanes filtered by task_class and role, sorted by cost (free>local>paid). For each: paid lane skipped unless `paid_ok(lane, query_sha256) is True`; lane called; exceptions/non-text → skip and record; success → freeze result (hash + text), record MORNA_CALL, return. All attempts recorded (MORNA_RECALL, MORNA_SKIP, MORNA_FAIL, MORNA_CALL). `collapse_idle` unloads lanes unused for `idle_seconds`. Fail-closed: bad lane def → `MornaRefused`; duplicate names refused; paid_ok crash → treated as False; lane crash → fall through.

**Invariants:**
- SDK never opens network connections; lanes are caller-supplied callables.
- Frozen results keyed by (lane_name, query_sha256); same query → same lane = zero recompute.
- Paid lanes never run without `paid_ok` returning exactly `True` (truthy not accepted).
- Every attempt recorded on custody chain (hashes only).

### 3.8 overseer.py

**Role:** Digest candidate by build+test; promote only with human co-sign on verdict hash.

**Public interface:**
- `STATES = ("NOURISHING", "SICK", "HUNGRY")`
- `OverseerRefused`
- `digest(candidate, build, test) -> {candidate_sha256, state, why, missing[]}`
- `verdict_hash(verdict) -> str`
- `promote(verdict, cosign) -> {status, verdict_sha256, why?}`

**Behavior:** `digest`: build(candidate) → artifact or SICK; test(artifact) → {passed, missing[]} or SICK; passed=True → NOURISHING; passed=False with missing → HUNGRY; passed=False no missing → SICK. `promote`: only NOURISHING eligible; `cosign(verdict_hash) is True` → PROMOTED; None/crash/not True → PROPOSED; SICK/HUNGRY never promote regardless of cosign. Fail-closed: bad verdict shape → `OverseerRefused`; cosign crash → False; non-dict test result → SICK.

**Invariants:**
- Overseer never signs; `cosign` is caller-wired to governance jacket (human commitment).
- Cannot feed itself flattering results: only human co-sign anchors.
- Verdict hash binds the exact digest output; cosign checked against that hash.

### 3.9 predict.py

**Role:** Nested lattice forecast with shrinkage; walk-forward backtest; accuracy report; training gate for restricted rows.

**Public interface:**
- `SHRINK = 5.0`, `MIN_N = 10`
- `PredictRefused`
- `Lattice(rows, outcome="correct"|"fidelity", min_n=MIN_N)` with `.predict(task_class, model, difficulty=None) -> {probability, basis, level, n, wilson_lower, enough}`
- `backtest(rows, outcome, warmup=10) -> {n, brier, baseline_brier, skill, reliability[]}`
- `accuracy_report(rows) -> {task_class: {frontier_correctness, apprentice_fidelity, apprentice_correctness, paired_on_shared_queries, honesty}}`
- `training_gate(rows, purpose) -> {allowed, restricted_rows, why}`

**Behavior:** `Lattice` builds cells for each record (apprentice/frontier, not reference for fidelity): keys = (task_class, model, bucket(difficulty)), (task_class, model), (task_class,), (). Prediction walks general→specific, shrinking: `p = (s + SHRINK*p_parent) / (n + SHRINK)`. Uses most specific cell with n≥min_n, else most general with data. `NO BASIS` when no cell has data. `backtest` walks forward from warmup, predicts each row from past only, scores Brier vs overall-rate baseline. `accuracy_report` keeps fidelity and correctness separate, pairs on shared query hashes. `training_gate`: restricted rows (training_restriction present) allowed only for purpose="personal_research". Fail-closed: bad outcome/purpose → `PredictRefused`; difficulty>1 refused; no history → NO BASIS.

**Invariants:**
- Fidelity and correctness never combined; reported separately.
- Shrinkage pulls thin cells toward parent; a 0/12 cell with strong parent ~0.95 pulls to ~0.15, not 0 or 1.
- Backtest never uses future data (walk-forward).
- Training restriction hashed on chain; local edit to None does not affect recorded version.

### 3.10 stats.py

**Role:** Small statistics the autonomy gate stands on: Wilson lower bound, CUSUM, Brier, entropy.

**Public interface:**
- `wilson_lower(successes, n, z=1.95996) -> float`
- `cusum(seq, k=0.05, h=4.0, baseline=None) -> {alarm, max, at, current}`
- `brier(pairs) -> float`
- `entropy(probs) -> float`

**Behavior:** Standard formulas. Wilson: 0 successes on 0 trials → 0. CUSUM: reference rate = first half unless baseline given; alarms on late drift. Brier: MSE of probability forecasts. Entropy: Shannon in bits. All validate inputs strictly.

## 4. Guarantees and non-guarantees

| Guarantee | Module | Test |
|---|---|---|
| Texts never reach chain; only SHA-256 hashes stored | records | test_reasoning.py::LogAndGate::test_records_hold_hashes_not_text |
| Regrade supersedes, does not inflate count | records | test_reasoning.py::LogAndGate::test_regrade_supersedes_not_inflates |
| Promotion requires n≥30, Wilson≥0.80, no drift | fidelity | test_reasoning.py::LogAndGate::test_promotion_needs_enough_good_unbroken_records |
| Lucky streak on bad record does not promote | fidelity | test_reasoning.py::LogAndGate::test_a_lucky_streak_on_a_bad_record_does_not_promote |
| Drift after promotion demotes | fidelity | test_reasoning.py::LogAndGate::test_drift_after_promotion_demotes |
| Combined verified requires trace AND answer | judge | test_reasoning.py::Judge::test_both_trace_and_answer_must_pass |
| Negation detected as contradiction | judge | test_reasoning.py::Judge::test_negation_is_a_contradiction |
| Small samples never GREEN | vitals | test_reasoning.py::Vitals::test_colours (16 perfect → AMBER) |
| Paid lane never runs without paid_ok=True | morna | redteam_2_routing_and_overseer.py::A_PaidLanes::test_a_paid_lane_never_runs_without_a_commitment_check |
| Only exactly True opens paid lane | morna | redteam_2_routing_and_overseer.py::A_PaidLanes::test_only_exactly_true_opens_a_paid_lane |
| Overseer promotes only with cosign=True | overseer | test_reasoning.py::Overseer::test_nothing_promotes_itself |
| SICK/HUNGRY never promote regardless of cosign | overseer | redteam_2_routing_and_overseer.py::C_Overseer::test_sick_and_hungry_candidates_never_promote_whatever_the_cosign_says |
| Lattice returns NO BASIS (not a guess) with no history | predict | test_reasoning.py::Predict::test_no_basis_without_records |
| Thin cell borrows from parent via shrinkage | predict | test_reasoning.py::Predict::test_thin_cell_borrows_from_its_parent |
| Backtest walks forward, scores against naive baseline | predict | test_reasoning.py::Predict::test_backtest_scores_against_the_naive_baseline |
| Training gate blocks restricted rows for commercial purposes | predict | test_reasoning.py::Predict::test_training_gate / redteam_1_gaming_the_record.py::F_Predict::test_restricted_rows_never_pass_a_commercial_gate |
| Frozen results keyed by (lane, query_hash) prevent recompute | morna | test_reasoning.py::Morna::test_second_ask_is_recalled_not_recomputed |
| MRI stores hashes only | lyra | redteam_2_routing_and_overseer.py::E_Lyra::test_the_mri_stores_hashes_only |
| Governor caps depth at max_depth | lyra | test_reasoning.py::Lyra::test_depth_never_passes_the_ceiling |
| Collapse returns AMBIGUOUS/NONE unless exactly one survivor | aquire | test_reasoning.py::Aquire::test_collapse_only_when_requirements_leave_one |

| Non-guarantee | Module |
|---|---|
| Frontier quality — promoted means matches reference on tested distribution | fidelity |
| Embedding/entailment judge quality — lexical_judge is a floor only | judge |
| Model lane availability/quality — SDK never calls providers | morna |
| Training execution — gate only refuses restricted rows | predict |
| Causal attribution — MRI shows association, not cause | lyra |
| Quantum properties — AQUIRE is classical beam search + Viterbi | aquire |
| Production hardening — reference implementation only | all |

## 5. Failure modes

| Failure | Behavior | Test |
|---|---|---|
| Tampered record | `ReasoningLog.verify()` fails (delegates to custody Dag verify) | redteam_1_gaming_the_record.py::C_Records::test_a_credential_in_a_label_cannot_reach_the_chain |
| Missing commitment (paid lane) | Lane skipped, MORNA_SKIP recorded, next lane tried | redteam_2_routing_and_overseer.py::A_PaidLanes::test_a_paid_lane_never_runs_without_a_commitment_check |
| Expired/replayed commitment | `paid_ok`/`cosign` called per query_hash/verdict_hash; caller enforces single-use | redteam_2_routing_and_overseer.py::A_PaidLanes::test_the_commitment_is_asked_per_query_hash |
| Corrupt verdict in record | `records.make` refuses verdict not from `judge.grade` | redteam_1_gaming_the_record.py::C_Records::test_a_verdict_must_come_from_grade |
| Bad judge output | `judge.grade` raises `JudgeRefused` | redteam_1_gaming_the_record.py::B_Judge::test_a_judge_that_lies_in_shape_is_refused |
| Drift after promotion | `fidelity.status` returns `cusum_alarm=True`, `promoted=False`, `route="reference_required"` | test_reasoning.py::LogAndGate::test_drift_after_promotion_demotes |
| Paid lane crash | Fall through to next lane; MORNA_FAIL recorded | redteam_2_routing_and_overseer.py::B_LaneFailures::test_a_failing_lane_falls_through_to_the_next |
| Non-text lane result | Treated as failure; not frozen; fall through | redteam_2_routing_and_overseer.py::B_LaneFailures::test_non_text_results_are_failures_not_results |
| Overseer cosign crash | Treated as False → PROPOSED | redteam_2_routing_and_overseer.py::C_Overseer::test_a_crashing_cosign_does_not_promote |
| No history for prediction | `predict.Lattice.predict` returns `probability=None, basis="NO BASIS"` | test_reasoning.py::Predict::test_no_basis_without_records |
| Restricted rows to commercial gate | `training_gate` returns `allowed=False` | redteam_1_gaming_the_record.py::F_Predict::test_restricted_rows_never_pass_a_commercial_gate |

## 6. Dependencies and layer rules

Registry entry (verbatim from vega-umbrella-sdk):
```
"reasoning": {"layer": 11, "requires": ["custody"]}
```

Dependencies point down layers only (custody at layer 0), never up or sideways. This SDK imports only `vega_custody.dag.dag` (RecordRefused, Dag). No other family SDKs are imported.

## 7. Conformance

A third party can verify by running the test suite:
```bash
PYTHONPATH=src:../vega-custody-sdk/src python -m unittest discover -s tests
```
All 91 tests in 4 files must pass. Passing means the published reference implementation behaves as specified. Passing does NOT mean: production readiness, security audit completion, cryptographic expert review, frontier model quality, or any guarantee beyond what the tests demonstrate.