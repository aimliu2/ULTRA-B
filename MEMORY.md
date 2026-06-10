# Project status

## Phase D — COMPLETE (2026-06-10, commit 113d4ca)

Phase D fully implemented, replay-validated, and documented.

**D.watch gate (entry from E.pullback_developing):**
- Opens on first LTF pro-HTF iChoCh (SC06) via `phase_e.pro_attempt_seen == True`
- `hypothesis.py` checks `last_isc` first, then `last_sc` (macro ChoCh fallback)
- Squeeze edge case: when PD range contracts inside ITR pivots, SC01/SC02 fires
  before SC06 — fallback to `last_sc` correctly catches it. Discovered EURUSD
  15m/4h 2026-01-28T22:30 UTC.

**D.speculation triggers:**
- Path A: first LTF counter-HTF iChoCh (SC06, `last_isc`, `source_store="structure_isc"`)
- Path B: LTF counter macro SB (`last_sc`, `source_store="structure_sequence"`) after
  `pullback_confirmed` — unchanged, no internal equivalent for SB

**SC05-SC08 status:**
- SC05/SC06 (ITR internal iSb/iChoCh): active, fires against PE03/PE04 pivot prices
- SC07/SC08 (LTR internal): disabled — `_sb_internal()` returns None when `tier == "ltr"`
- `last_isc` always None for ltr-tier structure

**Test suite: 132 passed, 31 skipped.**

---

## Next — Phase C implementation

Design decided (MEMORY.md Phase C section, `docs/402-hypothesis-phC.html`).
Two nodes: `C.pullback` and `C.pullback_weaken`.

```
D.speculation
  + ltf_counter_orderflow_mss_watch fires on fresh leg
    AND orderflow_leg_id != phase_d_shadow.consumed_leg_id
  → C.pullback

C.pullback
  → B.xxx              when ltf_pullback_depth_pct >= 50% (discount zone)
  → C.pullback_weaken  when LTF ChoCh fires counter to expected pullback
                       (structural disruption before 50% depth)
  → E.seeking          when new HTF extreme fires

C.pullback_weaken
  → C.pullback   when LL confirmed (LTF orderflow) OR LTF P/D floor tested
  → B.xxx        only via C.pullback recovery path
  → E.seeking    when new HTF extreme fires
```

`_phase_c_sub_status_from_current_d()` eliminated. B/C/A gate blocks are
currently commented out in `hypothesis.py` (~line 436, ~456, ~668/681) —
re-enable as part of Phase C work.

---

## Key boundaries (settled — do not re-open)

- **Structural SB / ChoCh** (`structureEngine.py`, `last_sc` / `last_isc`):
  LTF close-through event over ITR/LTR anchors. One SC per bar (hard cap).
  `last_sc` = macro SC01-SC04. `last_isc` = internal SC05/SC06 (ITR only).
- **Orderflow MSS** (`orderflow.py`, `mss_regime = "mss_watch"`): live probe
  breaks latest confirmed HL (bullish) or LH (bearish). Gate for
  `E.stalling → E.pullback_developing` AND `D.speculation → C.pullback` (fresh leg).
- **Terminology:** SB/ChoCh = structural (`structureEngine`). BoS/MSS = orderflow
  (`orderflow.py`). Never mix in gate descriptions.
- **SC07/SC08 disabled.** `last_isc` reads ITR-only internal events.
- **`ltf_counter_choch` EC pattern** reads `last_isc` (SC06) as primary;
  `sb_seen` fallback reads `last_sc` (Path B macro SB). `blocked_reasons`:
  `"no_ltf_counter_ichoch"`.

---

## Phase E model (complete)

```
E.seeking → E.stalling → E.pullback_developing
```

- `E.stalling → E.pullback_developing`: `ltf_counter_orderflow_mss_watch == True`
- `E.pullback_developing` holds on broken/pro LTF orderflow — legacy disruption
  path retired; D/C own interpretation after first counter-orderflow MSS.
- `pro_attempt_seen`: first LTF pro-HTF iChoCh/ChoCh (checks `last_isc` first)
  → sets `pro_attempt_started_at`, triggers D.watch entry.

**PhaseEShadow fields (key):**
```
source_orderflow_leg_id        — MSS leg that opened E.pullback_developing
consumed_orderflow_leg_id      — marked when D.watch consumes the leg
counter_structure_confirmed_at — first counter structural close confirmation
pro_attempt_seen               — True once first pro-HTF iChoCh fires
pro_attempt_started_at         — timestamp of that event
pro_attempt_event_id
pro_attempt_level
```

---

## Migration state

**Done**
- ✅ EC implemented and wired in `dual_smc._init_engines()`
- ✅ `HypothesisClassifier` re-enabled in `dual_smc`
- ✅ `_phase_b_initiation_setup()` → reads `ec["htf_b_initiation"]`
- ✅ `_phase_d_setup()` / `_phase_c_setup()` / `_phase_b_setup()` consume EC candidates
- ✅ `_phase_a_finale()` reads `ec["htf_pd_objective"]`
- ✅ `_phase_e_reaction()` reads `ec["phase_e_context"]` + `ec["ltf_counter_choch"]`
- ✅ `ShadowThesis` extracted; `PhaseEShadow` nested as `shadow_thesis.phase_e`
- ✅ `PhaseDShadow` added as `shadow_thesis.phase_d`
- ✅ Phase D state machine (`D.watch` / `D.speculation`) — full iChoCh sensitivity
- ✅ SC05/SC06 ITR internal events; SC07/SC08 LTR disabled
- ✅ Layer3 naming migration (structure_sequence, orderflow_anchor_sequence)
- ✅ Orderflow MSS regime (`mss_watch`); `choch_watch` alias retired
- ✅ `docs/402-hypothesis-phD.html` updated incl. squeeze edge case

**In-flight / not started**
- Phase C: `C.pullback` / `C.pullback_weaken` implementation — **START HERE**
- D.speculation → Layer 5 migration — **NEXT after Phase C** (separate PR; keep D.watch in DAG, move iChoCh entry timing to Layer 5; drop `choch_2` / `speculation_entered_at` from PhaseDShadow)
- Phase B/A gates: re-enable after Phase C ships
- Cold-start self-location: post-warmup bar self-locates into best DAG node
- `_phase_a_setup()` disabled — Phase A EC candidate not written
- `classify()` signature change to accept `evidence_candidates: list[dict]`
- Shadow consumed-event ledger for D liquidity expiry

---

## Key file locations

```
hypothesis.py     ~88:  PhaseDShadow dataclass
hypothesis.py    ~104:  ShadowThesis.phase_d field
hypothesis.py    ~252:  epoch reset block (_reset_phase_d_shadow)
hypothesis.py    ~401:  Phase D state machine (D.watch / D.speculation)
hypothesis.py   ~1635:  _reset_phase_d_shadow method
hypothesis.py   ~1956:  _update_phase_e_pullback_progress (last_isc check)
evidence_compiler.py ~1280: _compile_ltf_counter_choch (last_isc primary)
structureEngine.py: _sb_internal LTR guard (SC07/SC08 disabled)
tests/test_hypothesis_phase_d_simplify.py — active D.watch/D.speculation tests
tests/test_hypothesis_classifier.py — legacy D/B/C/A tests skipped
docs/402-hypothesis-phC.html — Phase C design (reference before implementation)
docs/402-hypothesis-phD.html — Phase D complete spec + squeeze edge case
.claude/layer34-contract.md — living EC→DAG interface spec
```
