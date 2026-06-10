# Project status

## Current state — 2026-06-10

**Phase D + C complete. Ready for replay testing.**

- Phase D: `D.watch`-only model. `D.speculation` removed from DAG (commit `10dff12`).
- Phase C: 2-state model `C.pullback` / `C.pullback_weaken` (commit `113d4ca` + C PR).
- DAG uses `last_sc` (macro ChoCh, SC01/SC02) only for all structural transitions.
  `last_isc` (iChoCh, SC06) is Layer 5 entry confirmation — NOT a DAG gate.
- Test suite: **129 passed, 31 skipped.**
- Next: replay EURUSD 15m/4h to validate D.watch → C.pullback transitions.

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
- ✅ `docs/402-hypothesis-phC.html` — 2-state model, archive old 5-variant
- ✅ `docs/40x-hypothesis-migration.html` — Phase D + C closed
- ✅ `docs/501-entry.html` — Layer 5 iChoCh mechanics
- ✅ `.claude/layer34-contract.md` — D.speculation removed, PhaseCshadow added

**In-flight / not started**
- Replay validation: Phase D + C EURUSD 15m/4h — **START HERE (tomorrow)**
- Phase B/A gates: re-enable after replay validates D/C
- Cold-start self-location: post-warmup bar self-locates into best DAG node
- `_phase_a_setup()` disabled — Phase A EC candidate not written
- Shadow consumed-event ledger for D liquidity expiry

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
docs/40x-hypothesis-migration.html          migration tracker
docs/501-entry.html                         Layer 5 iChoCh entry mechanics
.claude/layer34-contract.md                 EC→DAG interface spec (gitignored)
.claude/layer34-guide.md                    architectural invariants (read-only)
```
