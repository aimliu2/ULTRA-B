# Project status

## Current state — 2026-06-13

**Phase D + C + B + A model complete. X.none unification done. A.watch → X.thesis_over wired. Direction-sensitive EC fact audit complete. Next real work: cold-start self-location, then remaining small runtime/debug open issues.**

- Phase D: `D.watch`-only model. `D.speculation` removed from DAG (commit `10dff12`).
- Phase C: 2-state model `C.pullback` / `C.pullback_weaken`. Replay validated. Docs archived.
- Phase B: `B.watch` wired. `PhaseBShadow` with `commitment_extreme_level` locked at C→B entry. commitment-extreme breach exit (→C) added.
- Phase A: `A.watch` / `A.watch_weaken` wired. pro extreme advance gate on recovery (blocks oscillation in ranging). `PhaseAShadow.pro_extreme_at_weaken`.
- Phase X: `"none"` phase eliminated — all 4 call sites → `_phase_x()`. `none_sub_status` field removed. `X.warm_up`, `X.no_direction`, `X.none`, `X.thesis_over` sub-statuses live. `X.none` emits blocked-transition debug. `A.watch → X.thesis_over` fires on `phase_a_thesis_matured`.
- Test suite: **138 passed, 31 skipped.** Targeted checks on 2026-06-14: `tests/test_headless_runtime_reuse.py` = 7 passed; `tests/test_hypothesis_classifier.py tests/test_hypothesis_phase_d_simplify.py` = 23 passed, 31 skipped.

**Current open issue focus — 2026-06-14**
- **Next Milestone**: cold-start self-location. Post-warmup bar 0 should locate into best current DAG node from EC evidence (E/D/C/B/A) instead of always establishing E first.
- **Open audit**: `htf_b_phase_setup` key names used by `_update_phase_b_watch_shadow()` may be legacy. Verify EC emits `htf_last_resolved_zone_id` and `ltf_pro_sd_zone_ids` in the B.watch context.
- **Next Milestone**: expose warmup health/readiness in replay payload for easier startup debugging.
- **Edge Case**: D liquidity consumed-event ledger expiry after `X.thesis_over`; currently persists until epoch reset.
- **Out of scope / Layer 5**: A.watch and B.watch entry permission engines are not built; DAG shadow surfaces are the interface.

---

## Phase D — complete

**D.watch gate (from E.pullback_developing):**
- Opens on first LTF pro-HTF macro ChoCh: `last_sc.breakDirection == pro-HTF direction` (SC01/SC02)
- `phase_e.pro_attempt_seen == True` AND `pro_attempt_started_at > pullback_developing_entered_at`
- `consumed_leg_id` = `phase_e.source_orderflow_leg_id` — prevents same MSS from re-triggering C

**D.watch exits (DAG):**
- `→ C.pullback`: `ltf_counter_orderflow_mss_watch` fires on fresh leg (leg_id != consumed_leg_id)
- `→ E.seeking`: HTF close above PD range

**D.watch shadow fields:**
```
phase_d.node             "D.watch"
phase_d.consumed_leg_id  from phase_e.source_orderflow_leg_id
phase_d.watch_entered_at eventTimestamp of choch_1 (freshness floor for Layer 5)
phase_d.choch_1          { trigger_type, at, level }  ← pro-HTF SC level → Layer 5 SL ref
phase_d.pro_attempt      { htf_reaction_status, ltf_story_status }  ← quality metadata
```

**D.speculation removed from DAG (commit 10dff12):**
- Path A (SC06 iChoCh → D.speculation) and Path B (counter SB + pullback_confirmed) are now Layer 5.
- `choch_2` and `speculation_entered_at` dropped from `PhaseDShadow`.
- Docs: `docs/402-hypothesis-phD.html`, `docs/501-entry.html`.

**SC05-SC08 status:**
- SC05/SC06 (ITR internal iSb/iChoCh): emitted by EC, consumed by Layer 5. Not DAG gates.
- SC07/SC08 (LTR internal): disabled — `_sb_internal()` returns None when `tier == "ltr"`.

---

## Phase C — complete

**2-state model:**
```
C.pullback        — counter pullback active (MSS confirmed)
C.pullback_weaken — pro-HTF last_sc broke a pullback LH
                    (bounce attempt within counter pullback)
```

**Entry paths:**
- V1 (fast): `E.pullback_developing` + `phase_d.node is None` + `ltf_pullback_depth_pct >= 51%`
  → `origin_node = "E.pullback_developing_no_pro"`
- V2 (structural): `D.watch` + counter MSS on fresh leg → `origin_node = "D.watch_mss"`

**State transitions:**
```
C.pullback → C.pullback_weaken:  pro-HTF last_sc breaks pullback LH
C.pullback_weaken → C.pullback:  counter MSS re-fires in pullback direction (recovery)
C → E.seeking:                   new HTF extreme fires
C → B.xxx:                       pullback depth / reclaim conditions (pending B impl.)
```

**PhaseCshadow fields:**
```
origin_node    "D.watch_mss" | "E.pullback_developing_no_pro"
entered_at     eventTimestamp of the MSS/event that opened C.pullback
weaken_at      eventTimestamp of pro-HTF SC that opened C.pullback_weaken
recover_at     cursor_time of weaken → pullback recovery
```

---

## Layer 5 entry confirmation (iChoCh mechanics)

DAG does NOT act on iChoCh. Layer 5 reads from `D.watch` snapshot:

- **Path A**: `ltf_counter_choch_seen` (SC06 iChoCh, `last_isc`) + freshness (`choch_event_at > watch_entered_at`)
- **Path B**: `ltf_counter_sb_seen` (macro SB, `last_sc`, `choch=False`) + `pullback_confirmed` + freshness

SL reference: `phase_d.choch_1.level`. Quality: `phase_d.pro_attempt`.
Full spec: `docs/501-entry.html`.

---

## Key boundaries (settled)

- **DAG structural gate**: `last_sc` only (SC01/SC02 macro ChoCh). `last_isc` is Layer 5.
- **Orderflow MSS** (`mss_regime = "mss_watch"`): gate for `E.stalling → E.pullback_developing`
  AND `D.watch → C.pullback` (fresh leg, leg_id != consumed_leg_id).
- **Terminology**: SB/ChoCh = structural (`structureEngine`). BoS/MSS = orderflow. Never mix.
- **`ltf_counter_choch` EC pattern**: emits `choch_seen` (`last_isc` SC06) and `sb_seen`
  (`last_sc` macro SB). Consumed by E tracking + Layer 5. Not a DAG transition gate.

---

## Phase E model (complete)

```
E.seeking → E.stalling → E.pullback_developing
```

- `E.stalling → E.pullback_developing`: `ltf_counter_orderflow_mss_watch == True`
- `pro_attempt_seen`: `last_sc.breakDirection == pro-HTF direction` (SC01/SC02 only)
  → sets `pro_attempt_started_at`, triggers D.watch entry.

**PhaseEShadow fields (key):**
```
source_orderflow_leg_id        MSS leg that opened E.pullback_developing
consumed_orderflow_leg_id      marked when D.watch consumes the leg
counter_structure_confirmed_at first counter structural close confirmation
pro_attempt_seen               True once first pro-HTF macro ChoCh fires
pro_attempt_started_at         timestamp
pro_attempt_event_id
pro_attempt_level
```

---

## Migration state

**Done**
- ✅ EC wired in `dual_smc._init_engines()`
- ✅ Phase E shadow + state machine
- ✅ Phase D: `D.watch`-only model, `D.speculation` removed, `last_sc` gate
- ✅ Phase C: 2-state `C.pullback` / `C.pullback_weaken`, V1/V2 entry, PhaseCshadow
- ✅ SC05/SC06 active; SC07/SC08 disabled
- ✅ Layer3 naming migration
- ✅ `docs/401-hypothesis-DAG.html` — D.spec removed, C.pullback updated
- ✅ `docs/402-hypothesis-phD.html` — D.watch-only, archive block
- ✅ `docs/402-hypothesis-phC.html` — 2-state model + section 06 Old Model (5 variants archived, Open Issues → 07)
- ✅ `docs/402-hypothesis-phB.html` — B.watch model (old model archived in §06)
- ✅ Phase B rework: `B.watch` + `PhaseBShadow`, depth gate C→B at 51%, D-symmetric exits, E.HTF_reaction folded
- ✅ `docs/401-hypothesis-DAG.html` — E.HTF_reaction removed, C_ind/C_no removed, B_watch node, depth gate edges
- ✅ `docs/402-hypothesis-phX.html` — X sub-status taxonomy + X.none blocked-transition debug
- ✅ `docs/501-entry.html` — Layer 5 iChoCh mechanics
- ✅ A.watch → X.thesis_over wiring — `phase_a_objective_progress_pct` + `phase_a_thesis_matured`, configurable via `replay.hypothesis.phase_a.objective_progress_threshold`
- ✅ Direction-sensitive EC fact audit — `_ec_candidate_for_direction()` added; E/C/D/B/A direction-sensitive candidate reads now require `candidate.direction == direction`; opposite-direction regression tests added.
- ✅ `.claude/layer34-contract.md` — D.speculation removed, PhaseCshadow added
- ✅ Replay validated: EURUSD 15m/4h — D.watch → C.pullback fires at 2026-01-29T12:45
- ✅ Orderflow MSS gate fix — `probe_breaks_protected_anchor` decoupled from direction scorer; EC gate = `ltf_bias_counter AND probe_breaks_protected_anchor`; `higher_orderflow` deleted

**In-flight / not started**
- **Next**: cold-start self-location:
  - Big follow-up item; intentionally deferred until E/D/C/B/A and X.none were stable.
  - Post-warmup bar should locate into the best current DAG node from EC evidence (E, D, C, B, or A).
  - Do not force every session-start bar through `X.warm_up → E.seeking`.
- Shadow consumed-event ledger for D liquidity expiry.

---

## Phase X sub-status taxonomy (planned)

```
X.warm_up       entry_policy="wait"  ← warmup_waiting_for_first_closed_htf, waiting_for_htf_structure
X.no_direction  entry_policy="wait"  ← htf_neutral
X.none          entry_policy="wait"  ← htf_resolve_unclassified (gap — emits blocked_transition_reason)
X.thesis_over   entry_policy="skip"  ← phase_a_thesis_matured; budget spent
```

Spec: `docs/402-hypothesis-phX.html`.

---

## Phase B — current code state (pre-rework audit, 2026-06-11)

**What exists (partially wired, partially commented out):**
- `_phase_b_setup()` — reads EC `htf_b_phase_setup`; variants: `strict_reclaim` / `shallow_reclaim`. Gate: `htf_pullback_context_ready`, pd_half location, `ltf_turns_back_toward_htf`, `htf_pro_sd_reaction`, `ltf_pro_sd_selected`.
- `_phase_b_initiation_setup()` — separate initiation watch path.
- **C → B** (`hypothesis.py:474`): active — fires when `previous_phase == "C"` and `phase_b_ready`.
- **B.initiation_watch** (`hypothesis.py:656`): active — handles B.initiation → C.no_followthrough / C.after_inducement fallbacks.
- **B.shallow_reclaim** (`hypothesis.py:769`): active — holds or transitions to D/E from shallow.
- **Direct E → B** (`hypothesis.py:844`): commented out — intentionally blocked (`direct_e_to_b_requires_c_origin`).
- **Phase A** (`hypothesis.py:826`): commented out — EC candidate not written.

**What's messy / needs rework decision:**
- B sub-statuses (`strict_reclaim`, `shallow_reclaim`, `initiation_watch`) are legacy naming — may not align with new 2-state C model.
- `C → B` transition condition is `ltf_pullback_depth_pct >= 50%` per DAG docs, but not enforced in the C block.
- `htf_b_phase_setup` EC candidate may be stale relative to `last_sc`-only structural model.
- Need user decision: target B model (how many states, entry gate from C, B → A trigger).
- `_phase_a_setup()` disabled — Phase A EC candidate not written
- Shadow consumed-event ledger for D liquidity expiry

---

## Orderflow MSS fix (2026-06-11)

**Root cause**: `_score_direction()` returns `"mixed"` at transition (bull==bear window) → probe-breaks-anchor block was gated on `score["direction"] == "bullish/bearish"` → never ran at the MSS moment.

**Fix (3 files)**:
- `orderflow.py` lines 129-148: direction scorer still nominates `protected_anchor_ref` for Layer 5 SL. Break check now direction-agnostic — finds latest HL/LH and fires regardless of window score.
- `evidence_compiler.py` lines 1683-1685: `ltf_counter_orderflow_mss_watch = ltf_bias_counter AND probe_breaks_protected_anchor`. structureEngine bias replaces 5-condition scorer gate.
- `dual_smc.py` + `replay_session.py`: `higher_orderflow` removed entirely (zero logic readers).

---

## Key file locations

```
hypothesis.py            PhaseDShadow, PhaseCshadow, ShadowThesis dataclasses
hypothesis.py            D.watch state machine: _phase_d block
hypothesis.py            C.pullback state machine: V1/V2 entry, weaken, recovery
evidence_compiler.py     _compile_ltf_counter_choch (last_isc primary, sb_seen fallback)
structureEngine.py       _sb_internal LTR guard (SC07/SC08 disabled)
tests/test_hypothesis_phase_d_simplify.py   D.watch tests (2 remaining)
tests/test_hypothesis_classifier.py         legacy D/B/C/A tests (skipped)
docs/401-hypothesis-DAG.html                DAG diagram (D.watch-only)
docs/402-hypothesis-phD.html                Phase D spec
docs/402-hypothesis-phC.html                Phase C spec
docs/402-hypothesis-phE.html                Phase E spec
docs/501-entry.html                         Layer 5 iChoCh entry mechanics
.claude/layer34-contract.md                 EC→DAG interface spec (gitignored)
.claude/layer34-guide.md                    architectural invariants (read-only)
```
