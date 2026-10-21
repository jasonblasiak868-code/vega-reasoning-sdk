# vega-reasoning-sdk

![vega-reasoning-sdk](assets/tile.svg)

<!-- vega-install-order -->
> **Build order: 2/2. This kit needs 1 other Vega kit installed first.** Install them in this order, then this one:
> 1/2 `vega-custody-sdk`  
> 2/2 `vega-reasoning-sdk` (this kit)
> Install each with `pip install --no-deps git+https://github.com/jasonblasiak868-code/<name>` in the order shown. Full steps: [INTEGRATION_GUIDE](https://github.com/jasonblasiak868-code/vega-umbrella-sdk/blob/main/INTEGRATION_GUIDE.md).

Lattice-5 reasoning: ALTAIR fidelity gate, AQUIRE forecasting over outcome distributions, MoRNA capsule routing, Lyra (model MRI and difficulty governor), model vitals, the Overseer, and lattice prediction of accuracy from recorded history. This SDK owns the **reason** concern (layer 11): it forecasts how a model will do, routes to the cheapest capable lane, and refuses when the record does not support the claim.

> **Licensing.** Source-available, not open source. Free for personal use; free for registered small businesses (under US$1M revenue and valuation); everyone else needs a commercial license (see LICENSE; for a commercial license write to jasonblasiak.ai.mail@gmail.com). Patent pending. Draft licence text, not yet reviewed by an attorney.

## Specifications

| Item | Detail |
|---|---|
| Version | 0.1.0 |
| Python | >=3.10 |
| Runtime dependency | vega-custody-sdk (layer 0) |
| Tests | 96 tests in 5 files, all passing |
| Status | All 9 modules BUILT and tested (STATUS.md) |
| License | Source-available, Patent pending (U.S. provisional 64/178,949 and others) |

## End-to-end functions

1. **Record a graded exchange** — `records.make()` hashes query/trace/answer, stores scores and labels; `ReasoningLog.add()` appends to the custody chain (hashes only, never text).
2. **Gate autonomy per task class** — `fidelity.status()` computes Wilson lower bound and CUSUM drift on apprentice records; `fidelity.route()` returns `apprentice` only when promoted (n≥30, Wilson≥0.80, no drift alarm), otherwise `reference_required`.
3. **Compare reasoning** — `judge.grade()` applies a judge (lexical stand-in or pluggable embedding/entailment) to trace AND answer; `combined_verified` requires BOTH pass.
4. **Read model vitals** — `vitals.vitals()` returns GREEN/AMBER/RED from fidelity, correctness, latency, drift, staleness; small samples cap at AMBER.
5. **MRI + difficulty governor** — `lyra.MRI.observe()` records prompt features and outcome flags (hashes only); `lyra.MRI.attribute()` ranks features by association with a flag; `lyra.Governor.step()` rises fast, falls slow, caps depth.
6. **Forecast outcomes** — `aquire.forecast()` runs beam search + Viterbi over a weighted outcome graph; reports entropy, mass kept/dropped, soft landing; `aquire.collapse()` picks only when requirements leave exactly one outcome.
7. **Route to cheapest capable lane** — `morna.Router.route()` checks frozen cache → fidelity gate → cheapest lane (free > local > paid); paid lanes run only when `paid_ok(lane, query_sha256)` returns exactly `True`; every attempt recorded.
8. **Digest candidates by test** — `overseer.digest()` runs build+test; returns NOURISHING/SICK/HUNGRY; `overseer.promote()` requires a human `cosign(verdict_hash)` returning exactly `True`.
9. **Predict accuracy from history** — `predict.Lattice.predict()` uses nested cells (task_class, model, difficulty) → (task_class, model) → (task_class) → global, shrunk toward parent; `predict.backtest()` walks forward scoring Brier skill; `predict.training_gate()` blocks restricted (frontier-derived) rows for non-personal-research purposes.

## Controls

| Knob / Entry point | Module | What it does |
|---|---|---|
| `MIN_N=30`, `WILSON_BAR=0.80`, `CUSUM_K=0.05`, `CUSUM_H=4.0` | fidelity | Promotion thresholds (module constants) |
| `SIM_BAR=0.45`, `CONTRA_BAR=0.5` | judge | Verification bars for similarity/contradiction |
| `MIN_N=20`, `STALE_SECONDS=14*24*3600` | vitals | Sample floor and staleness window |
| `WEIGHTS` (uncertainty 0.35, disagreement 0.25, retries 0.15, overrun 0.15, novelty 0.10) | lyra | Difficulty signal weights |
| `MAX_NODES=5000`, `MAX_BEAM=1000`, `MAX_DEPTH=64` | aquire | Graph/beam/depth bounds |
| `SHRINK=5.0`, `MIN_N=10` | predict | Shrinkage toward parent cell, minimum cell count |
| `paid_ok(lane_name, query_sha256) -> bool` | morna | Caller-supplied commitment check for paid lanes |
| `cosign(verdict_hash) -> bool` | overseer | Caller-supplied human signature verification |
| `build(candidate), test(artifact) -> {passed, missing[]}` | overseer | Caller-supplied build and test functions |
| `judge=lexical_judge` (replaceable) | judge | Pluggable judge function (embedding + entailment) |

## What it CANNOT do

- **Not production-hardened.** Reference implementation with tests; not stress-tested at scale.
- **Not independently security-reviewed.** No third-party audit of the code or its threat model.
- **Crypto not expert-reviewed.** Relies on `vega-custody-sdk` for chain integrity; do not protect real secrets with it before independent review.
- **No embedding/entailment judges included.** `lexical_judge` is a floor for tests and offline use; real deployments must supply their own judge.
- **No model lanes included.** MoRNA routes to caller-supplied functions (local model, remote endpoint, lookup); the SDK never opens a network connection.
- **No fine-tune loop.** Training gate only refuses restricted rows; it does not run training.
- **LoRNA is not a separate module.** The lattice router + runtime + reasoning system around MoRNA is the composition of these modules; no `lorna.py` exists.
- **Frontier-derived records carry a personal-research-only restriction.** The training gate enforces this; commercial/competing/sellable/public purposes are refused.
- **Promoted means "matches the reference on the tested distribution."** It does not mean frontier quality; the reference's own mistakes are inherited.
- **AQUIRE makes no quantum claim of any kind.** Classical beam search + Viterbi; "quantum-inspired" is a design philosophy only.

## Platform support

| Platform | Support |
|---|---|
| Windows, macOS, Linux (CPython 3.10+) | Runs anywhere CPython runs — pure Python, no POSIX-only code, no native extensions |
| Android (Termux) | Runs inside Termux where the Python runtime supports its dependencies |
| Apple platforms (BeeWare/Kivy) | Runs inside an embedded Python runtime where that runtime supports its dependencies |
| Native mobile (.apk/.ipa) | No native mobile build is published |
| GPU / TPM / hardware keys | Not required; no hardware-dependent code |

## Standalone & unified install

**Standalone:** `pip install -e .` installs with one declared dependency: `vega-custody-sdk`. It imports nothing else from the family. Runs alone with zero family dependencies beyond custody.

**Unified:** Registered in `vega-umbrella-sdk` registry as layer 11 (reason), `requires=["custody"]`. The umbrella resolves wiring; this SDK depends only on the custody layer (layer 0).

## Diagnostic control

- **CLI entry points:** None (no `console_scripts` in pyproject.toml).
- **Introspection functions:** `ReasoningLog.history()`, `fidelity.all_status()`, `vitals.vitals()`, `lyra.MRI.attribute()`, `lyra.MRI.shift()`, `predict.accuracy_report()`, `predict.backtest()`, `predict.training_gate()`.
- **Log surface:** All records written through `vega-custody-sdk` Dag; verify with `ReasoningLog.verify()`.
- **Exit codes / fail-closed indicators:** Every module raises a dedicated `*Refused`/`*RefusedError` exception on invalid input; promotion/routing/prediction return explicit status objects (`promoted: bool`, `route: "apprentice"|"reference_required"`, `basis: "cell"|"NO BASIS"`, `health: "GREEN"|"AMBER"|"RED"`, `collapse status: "COLLAPSED"|"AMBIGUOUS"|"NONE"`, `promote status: "PROMOTED"|"PROPOSED"|"REJECTED"|"INCOMPLETE"`).
- **Environment variables honored:** None.

## Fail-closed constraints & custom constraints

**Fail-closed points (module + function):**
- `records.make()` / `ReasoningLog.add()` — refuse invalid fields, non-hashable text, bad verdicts (`RecordRefusedError`).
- `fidelity.status()` — demotes on drift alarm (`cusum_alarm=True` → `promoted=False` → route=`reference_required`).
- `judge.grade()` — requires BOTH trace and answer verified; `combined_verified=False` if either fails.
- `vitals.vitals()` — caps at AMBER when n<MIN_N; RED on drift or Wilson<0.5.
- `lyra.MRI.observe()` / `lyra.Governor.step()` — refuse bad inputs (`LyraRefused`); difficulty caps at `max_depth`.
- `aquire.forecast()` / `aquire.collapse()` — refuse bad graphs/params (`AquireRefused`); collapse returns `AMBIGUOUS`/`NONE` unless exactly one survivor.
- `morna.Router.route()` — paid lanes skip unless `paid_ok` returns exactly `True`; failures fall through; non-text results treated as failures.
- `overseer.promote()` — only `cosign() is True` promotes; crashes → `PROPOSED`; SICK/HUNGRY never promote.
- `predict.Lattice.predict()` — returns `NO BASIS` (probability=None) when no cell has records; never guesses.
- `predict.training_gate()` — refuses restricted rows for non-personal-research purposes.

**Custom constraints:** This version publishes no user-defined constraint hooks; constraints are fixed by the module and the jurisdiction floor (vega-jurisdiction-sdk). User-defined constraints may be STRICTER than the legal minimum for the applicable jurisdiction, never looser. Jurisdictional legal minimums are defined by the jurisdiction registry; a custom constraint that would drop below a registered minimum is rejected at the gate.

---

> **Licensing.** Source-available, not open source. Free for personal use; free for registered small businesses (under US$1M revenue and valuation); everyone else needs a commercial license (see LICENSE; for a commercial license write to jasonblasiak.ai.mail@gmail.com). Patent pending. Draft licence text, not yet reviewed by an attorney.
