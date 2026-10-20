# vega-reasoning-sdk — Capabilities

This is the deep capability brief for the **reason** layer (layer 11). Each capability is inventoried as: what it does / why a policy-or-prompt-level approach structurally cannot provide it / where enforced in code / which test demonstrates it / honest limit.

---

## Capability inventory

### 1. Hash-only reasoning records on a tamper-evident chain

**What it does:** Every graded exchange (reference/apprentice/frontier) is recorded as SHA-256 hashes of query/trace/answer plus scores, labels, and metadata. Texts never reach the chain.

**Why policy/prompt cannot provide it:** A prompt saying "don't log the secret" is a request the model can ignore or be tricked into violating. The enforcement is structural: `records.make()` hashes immediately; `ReasoningLog.add()` validates only hashes reach the Dag; the Dag (custody layer) is append-only and hash-chained.

**Where enforced:** `records.py` — `make()` (lines 37-64), `ReasoningLog.add()` (lines 71-80), `sha()` (lines 25-27).

**Test:** `test_reasoning.py::LogAndGate::test_records_hold_hashes_not_text`; `redteam_1_gaming_the_record.py::C_Records::test_nothing_but_hashes_reaches_the_chain`.

**Honest limit:** Relies on `vega-custody-sdk` Dag integrity; not independently security-reviewed; do not protect real secrets before expert review.

---

### 2. Autonomy gate: promotion by record, demotion by drift

**What it does:** An apprentice lane is trusted for a task class only when: n≥30, Wilson lower bound ≥0.80, no CUSUM drift alarm. Drift after promotion demotes immediately. Route returns `apprentice` iff promoted, else `reference_required`.

**Why policy/prompt cannot provide it:** A prompt "only use the small model when it's good" has no access to the record, no statistical rigor, and no enforcement. The gate computes on the actual custody chain, uses Wilson (not raw rate) so lucky streaks on small n cannot promote, and CUSUM detects late drift against the model's own earlier rate.

**Where enforced:** `fidelity.py` — `status()` (lines 15-24), `route()` (lines 27-28), constants `MIN_N=30`, `WILSON_BAR=0.80`, `CUSUM_K=0.05`, `CUSUM_H=4.0`.

**Test:** `test_reasoning.py::LogAndGate::test_promotion_needs_enough_good_unbroken_records`, `test_a_lucky_streak_on_a_bad_record_does_not_promote`, `test_drift_after_promotion_demotes`; `redteam_1_gaming_the_record.py::D_Gate::test_duplicates_cannot_inflate_n`, `test_records_without_a_verdict_do_not_count_as_successes`, `test_a_good_start_then_collapse_is_demoted_even_with_a_high_overall_rate`.

**Honest limit:** Promoted means "matches the reference on the tested distribution" — not frontier quality; reference mistakes are inherited. Thresholds are module constants, not user-configurable hooks.

---

### 3. Dual-verdict reasoning comparison (trace AND answer)

**What it does:** `judge.grade()` runs a judge on trace AND answer separately; `combined_verified` requires BOTH pass. Lexical stand-in includes negation parity check (contradiction=0.9 when same topic, one negated).

**Why policy/prompt cannot provide it:** A prompt "check if the reasoning matches" is a single model call that can be gamed. Structural enforcement: two independent comparisons, both must verify; negation check catches "do NOT delete" vs "delete" which cosine similarity misses; judge is pluggable for real embeddings/entailment.

**Where enforced:** `judge.py` — `lexical_judge()` (lines 24-36), `grade()` (lines 49-52), `_side()` (lines 39-46), bars `SIM_BAR=0.45`, `CONTRA_BAR=0.5`.

**Test:** `test_reasoning.py::Judge::test_negation_is_a_contradiction`, `test_both_trace_and_answer_must_pass`; `redteam_1_gaming_the_record.py::B_Judge::test_a_judge_that_lies_in_shape_is_refused`, `test_a_negated_answer_with_the_same_words_does_not_pass`.

**Honest limit:** `lexical_judge` is a floor for tests/offline; real deployments must supply embedding+entailment judge. No judge quality guarantee.

---

### 4. Model vitals with honest small-sample handling

**What it does:** `vitals.vitals()` returns GREEN/AMBER/RED from fidelity, correctness, latency, drift, staleness. n<20 caps at AMBER; no data → AMBER; drift or Wilson<0.5 → RED.

**Why policy/prompt cannot provide it:** A prompt "tell me if the model is healthy" has no access to the record, no statistical grounding, and the model will say GREEN. The code computes Wilson bounds, CUSUM drift, and enforces sample floors structurally.

**Where enforced:** `vitals.py` — `vitals()` (lines 25-54), `_column()` (lines 18-22), constants `MIN_N=20`, `STALE_SECONDS=14*24*3600`.

**Test:** `test_reasoning.py::Vitals::test_colours` (40→GREEN, 5→AMBER, 30+14 failures→RED); `test_sharpened.py::Sharpened::test_sixteen_perfect_answers_are_still_too_few_to_be_green`; `redteam_1_gaming_the_record.py::E_Vitals::test_a_handful_of_perfect_answers_is_never_green`, `test_no_data_is_amber_not_green`, `test_a_green_model_goes_amber_when_stale`, `test_ground_truth_failures_turn_it_red_even_if_fidelity_is_perfect`.

**Honest limit:** Fidelity and correctness tracked separately; not combined. Staleness window is a constant (14 days).

---

### 5. Model MRI (prompt feature → behavior association)

**What it does:** `lyra.MRI.observe()` records prompt features (hashes only) and outcome flags (0/1). `attribute()` ranks features by rate difference with 95% half-width; `clear = |diff| > half_width`. `shift()` compares recent window vs prior.

**Why policy/prompt cannot provide it:** A prompt "what prompts make the model fail?" asks the model to introspect — which it cannot do reliably. MRI records actual observations on the chain, computes associations statistically, and reports confidence intervals. It sees associations in the record; it does not prove cause.

**Where enforced:** `lyra.py` — `MRI.observe()` (lines 33-44), `attribute()` (lines 49-64), `shift()` (lines 66-74), `MAX_FEATURES=64`, features/outcome dicts of 0/1.

**Test:** `test_reasoning.py::Lyra::test_mri_attribution_finds_the_feature_behind_the_flag`; `redteam_2_routing_and_overseer.py::E_Lyra::test_the_mri_stores_hashes_only`, `test_a_chance_pattern_is_not_called_clear`, `test_small_samples_are_not_attributed`, `test_mri_input_is_checked`.

**Honest limit:** Association, not causation. `clear` means statistically detectable (|diff| > 95% half-width), not proven cause. Max 64 features per observation.

---

### 6. Difficulty governor (fast rise, slow fall, capped depth)

**What it does:** `lyra.Governor.step(difficulty)` updates internal level: rises by `rise=0.6` of gap when difficulty>level, falls by `fall=0.15` when below. Returns integer depth in [min_depth, max_depth].

**Why policy/prompt cannot provide it:** A prompt "think harder when it's hard" has no state, no asymmetry, no ceiling. The governor is a stateful control loop: fast response to difficulty spikes, slow decay to avoid thrashing, hard ceiling on depth.

**Where enforced:** `lyra.py` — `Governor.__init__` (lines 83-87), `step()` (lines 100-106), `difficulty()` (lines 90-98), `WEIGHTS` for signal combination.

**Test:** `test_reasoning.py::Lyra::test_governor_rises_fast_and_falls_slow`, `test_depth_never_passes_the_ceiling`; `redteam_2_routing_and_overseer.py::E_Lyra::test_governor_inputs_are_checked`, `test_missing_signals_are_reported_not_guessed`.

**Honest limit:** Weights are constants; signals are caller-supplied; missing signals count as 0 and reported. No learning of weights.

---

### 7. Outcome distribution forecasting (AQUIRE)

**What it does:** `aquire.forecast()` runs beam search + Viterbi over a weighted outcome graph. Returns outcome distribution, entropy, best path, soft landing (top 3), mass kept/dropped. `collapse()` picks only when requirements leave exactly one survivor.

**Why policy/prompt cannot provide it:** A prompt "give me the answer" returns one answer. AQUIRE returns a distribution, reports entropy and dropped mass so a narrow beam cannot pass for certainty, and collapse refuses to pick unless requirements leave exactly one outcome. Classical probability only; "quantum-inspired" is a design philosophy.

**Where enforced:** `aquire.py` — `forecast()` (lines 36-69), `_viterbi()` (lines 72-95), `collapse()` (lines 98-108), bounds `MAX_NODES=5000`, `MAX_BEAM=1000`, `MAX_DEPTH=64`.

**Test:** `test_reasoning.py::Aquire::test_distribution_and_best_path`, `test_a_narrow_beam_reports_what_it_dropped`, `test_collapse_only_when_requirements_leave_one`; `redteam_2_routing_and_overseer.py::D_Aquire::test_bad_graphs_are_refused`, `test_cycles_terminate_and_probabilities_sum_to_one`, `test_a_requirement_must_return_exactly_true_to_count`, `test_a_wide_graph_is_bounded_by_the_beam`.

**Honest limit:** No quantum hardware, no quantum speedup, no quantum property claimed. Graph size/depth bounded. Requirements must return exactly `True` (truthy not accepted).

---

### 8. Dormant lane routing with frozen results and paid-gate

**What it does:** `morna.Router.route()` checks frozen cache → fidelity gate → cheapest lane (free>local>paid). Paid lanes run only when `paid_ok(lane, query_sha256) is True`. Every attempt recorded (MORNA_RECALL, MORNA_SKIP, MORNA_FAIL, MORNA_CALL). Failures fall through. `collapse_idle()` unloads unused lanes.

**Why policy/prompt cannot provide it:** A prompt "use the cheap model when you can" has no cache, no fidelity check, no paid-gate enforcement, no audit trail. The router: freezes results keyed by (lane, query_hash) so repeat calls cost zero; checks fidelity record before allowing apprentice; requires human commitment per query for paid lanes; records every attempt on the custody chain.

**Where enforced:** `morna.py` — `Router.route()` (lines 63-97), `_paid()` (lines 99-103), `collapse_idle()` (lines 105-113), `COSTS=("free","local","paid")`, `ROLES=("apprentice","reference")`.

**Test:** `test_reasoning.py::Morna::test_unpromoted_class_uses_a_reference_lane_cheapest_first`, `test_promoted_class_uses_the_apprentice`, `test_second_ask_is_recalled_not_recomputed`; `redteam_2_routing_and_overseer.py::A_PaidLanes::test_a_paid_lane_never_runs_without_a_commitment_check`, `test_only_exactly_true_opens_a_paid_lane`, `test_a_crashing_commitment_check_means_no`, `test_the_commitment_is_asked_per_query_hash`, `test_skips_are_recorded`, `test_a_free_lane_is_used_before_a_paid_one_and_paid_is_not_touched`; `B_LaneFailures::test_a_failing_lane_falls_through_to_the_next`, `test_non_text_results_are_failures_not_results`, `test_nothing_is_frozen_from_a_failed_call`, `test_the_chain_holds_hashes_not_results`.

**Honest limit:** SDK never opens network connections; lanes are caller-supplied callables. Paid gate requires caller to wire `paid_ok` to governance jacket. No lane quality guarantee.

---

### 9. Candidate digestion by test with human co-sign

**What it does:** `overseer.digest()` runs caller-supplied build+test; returns NOURISHING/SICK/HUNGRY. `promote()` requires `cosign(verdict_hash) is True` (exactly True). SICK/HUNGRY never promote regardless of cosign. Overseer never signs.

**Why policy/prompt cannot provide it:** A prompt "check if this is good" is the model checking itself. The overseer: runs actual build+test (caller-supplied), returns structured verdict, and promotion requires a human signature on the exact verdict hash. The overseer cannot feed itself flattering results — it proposes, human disposes.

**Where enforced:** `overseer.py` — `digest()` (lines 18-35), `promote()` (lines 42-55), `verdict_hash()` (lines 38-39), `STATES=("NOURISHING","SICK","HUNGRY")`.

**Test:** `test_reasoning.py::Overseer::test_states`, `test_nothing_promotes_itself`; `redteam_2_routing_and_overseer.py::C_Overseer::test_only_exactly_true_passes`, `test_cosign_must_return_exactly_true`, `test_a_crashing_cosign_does_not_promote`, `test_the_cosign_is_asked_about_this_verdict_only`, `test_sick_and_hungry_candidates_never_promote_whatever_the_cosign_says`, `test_a_forged_verdict_shape_is_refused`, `test_a_test_that_crashes_is_sick_and_a_build_that_crashes_is_sick`.

**Honest limit:** Build/test are caller-supplied; `cosign` is caller-wired to governance jacket. No quality guarantee on build/test functions.

---

### 10. Nested lattice prediction with shrinkage and training gate

**What it does:** `predict.Lattice.predict()` uses nested cells (task_class, model, difficulty_bucket) → (task_class, model) → (task_class) → global, shrunk toward parent (SHRINK=5.0). Returns NO BASIS (probability=None) when no cell has data. `backtest()` walks forward scoring Brier skill vs naive baseline. `accuracy_report()` keeps fidelity and correctness separate, pairs on shared queries. `training_gate()` blocks restricted (frontier-derived) rows for non-personal-research purposes.

**Why policy/prompt cannot provide it:** A prompt "how well will this model do?" is a guess. The lattice: forecasts from actual record, shrinks thin cells toward parent so 5 samples don't look like certainty, backtests walk-forward (never uses future), reports calibration (reliability diagram), and the training gate structurally refuses restricted rows for commercial purposes — the restriction is hashed on the chain.

**Where enforced:** `predict.py` — `Lattice.__init__` (lines 35-47), `predict()` (lines 53-67), `backtest()` (lines 70-91), `accuracy_report()` (lines 100-117), `training_gate()` (lines 120-126), `SHRINK=5.0`, `MIN_N=10`, `bucket()` (lines 22-27).

**Test:** `test_reasoning.py::Predict::test_no_basis_without_records`, `test_thin_cell_borrows_from_its_parent`, `test_backtest_scores_against_the_naive_baseline`, `test_accuracy_report_keeps_fidelity_and_correctness_apart_and_pairs_queries`, `test_training_gate`; `test_sharpened.py::Sharpened::test_a_thin_cell_is_pulled_toward_its_parent`; `redteam_1_gaming_the_record.py::F_Predict::test_a_forecast_never_uses_the_future`, `test_no_history_gives_no_basis_not_a_number`, `test_a_single_lucky_record_is_not_a_prediction_of_certainty`, `test_restricted_rows_never_pass_a_commercial_gate`, `test_an_edited_restriction_is_not_honoured_by_silence`.

**Honest limit:** Fidelity and correctness never combined. Shrinkage constant (5.0) not user-configurable. Training gate only refuses; does not run training. LoRNA (lattice router + runtime + reasoning) is the composition of these modules; no separate `lorna.py` exists.

---

## DKG + Lattice integration (family predictive loop)

This SDK sits at the **reason** layer (11) in the family predictive loop:

```
custody records (L0)
    → librarian distils lessons (L5)
    → dkg-lattice builds knowledge graph with origin+licence per fact (L7)
    → reasoning SDK (this) runs lattice forecast (predict.py) + galaxy convergence (vega-galaxy-sdk)
    → harness pre-registers predicted paths (L6)
    → metacog gates completion on evidence (L12)
    → feed/galaxy show it all to human (L13/L14)
    → human decides again (L1/L0)
```

**Real wiring in this repo:**
- `predict.py` imports `vega_reasoning.stats` (wilson_lower, brier) — local stats
- `predict.py` reads records from `ReasoningLog.history()` (custody chain via Dag)
- `lyra.MRI` writes `LYRA_OBSERVATION` records to the same Dag
- `morna.Router` calls `fidelity.status()` which reads records from Dag
- `records.py` imports `vega_custody.dag.dag.RecordRefused` — only cross-SDK import
- No import of `vega_dkg_lattice`, `vega_galaxy`, `vega_harness`, `vega_metacog` — those are separate SDKs that consume this SDK's outputs

**The lattice in this SDK (`predict.py`)** is the nested cell forecast (task_class, model, difficulty → task_class, model → task_class → global) with shrinkage. The **galaxy view** (levels, convergence, futures above present) lives in `vega-galaxy-sdk` (layer 14) which consumes this SDK's predictions.

---

## A category of its own

This SDK is differentiated by **governance-first architecture** — authority held outside the model:

| Differentiation | What this design does |
|---|---|
| Authority outside the model | Human signs commitments; `paid_ok`/`cosign` verify them; SDK never holds keys, never mints authority |
| Deterministic conductor | No model in the loop for gates — `fidelity.status` computes on record, `morna.Router` routes by record, `overseer.promote` requires human co-sign |
| Pre-registered predicted paths | `predict.Lattice` forecasts from record; `morna` freezes results; `aquire` forecasts distributions; all recorded before action |
| Single-use human commitments | `paid_ok(lane, query_hash)` and `cosign(verdict_hash)` checked per-query/per-verdict; caller wires to governance jacket |
| Chain-of-custody by default | Every record, every lane attempt, every MRI observation, every overseer digest → custody Dag (hashes only) |
| Lattice-informed foresight | Nested cells with shrinkage → honest forecasts; backtest scores skill vs naive; NO BASIS when no data |

**Honest framing:** These claims follow from the architecture (authority held outside the model cannot be replicated by prompt-level policy — see WHITEPAPER.md section 1). This is a reference implementation with tests; not production-hardened, not independently security-reviewed, crypto not expert-reviewed.