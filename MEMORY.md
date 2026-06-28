# Project status

## Current state — 2026-06-28 (Phase D + B integrity fixes COMPLETE)

4 issues from `20260628_bugs.md` implemented and audited. All changes confined to
`layer5.py`, `layer6.py`, `run_layer5_backtest.py`, `tests/test_layer5_phase_b.py`.
Plan file: `.claude/plans/let-s-formulate-a-plan-compiled-manatee.md`.

### What was fixed

**Issue 4 — Phase B TP formula** (`_phase_b_tp()` helper):
- Pushed `tp_price` out of `_make_intent()` as explicit param — `_make_intent()` no longer hardcodes TP.
- Phase D `_try_path_a()` still computes `pd_midpoint` TP (unchanged behavior).
- Phase B paths now use `min(progress_pips, 2.5 × sl_pips)` toward the 90% HTF objective level.
  - HTF range keys: `higher_structure["range_low"]` / `["range_high"]` (not `pd_range_*`).
  - Directional: `max(0.0, (progress_level - entry) / pip_size)` for long, mirrored for short.
  - 2.5R cap applied; `min_rr` gate still rejects if neither level yields ≥ 1.75 RR.
- `phase_a_objective_threshold` threaded from `config.yaml → replay.hypothesis.phase_a.objective_progress_threshold` (default 0.90).

**Issue 3 — Phase B episode budget** (`_b_watch_episode_spent`, `_b_watch_pending_trigger`):
- Dispatch (Phase B block + Phase A transition block): guard-only `if episode in _b_watch_episode_spent: return None`.
- Path helpers own all state: `_b_watch_trigger_locked()` (pre-`_make_intent()` check) + `_record_b_watch_result()` (post-`_make_intent()` state machine):
  - Expired (age > max, returns None) → pending lock stays; episode dead, no new trigger accepted.
  - `runway_too_short` → lock episode to this trigger ID (`_b_watch_pending_trigger`).
  - `EntryIntent` or stale `SkipIntent` → add to `_b_watch_episode_spent`, pop pending lock.

**Issues 1 + 2 — `trigger_age_bars` output + `max_trigger_age_bars` gate**:
- `_parse_bar_minutes(tf)` and `_trigger_age_bars(cursor_time, trigger_at, bar_minutes)` added as module-level helpers.
- Timeframe read from `snapshot["lower_tf"] or snapshot["timeframe"]` (always uppercase, e.g. `"15M"`, `"4H"`).
- `cursor_time` from `snapshot.get("cursor_time")` (top-level, not `hypothesis.debug_facts`).
- Gate: `age_bars > max_trigger_age_bars` → return None (silent drop, not stale-marked).
- `trigger_age_bars: int = 0` field added to `EntryIntent`, `SkipIntent`, `TradeResult`.
- Propagation: `EntryIntent.trigger_age_bars` → `TradeResult` via `_close()` and `result_from_skip()` → `to_row()["trigger_age_bars"]` → CSV.
- `"trigger_age_bars"` inserted into `RESULT_COLUMNS` after `"trigger_event_at"`.

### Verification

- `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest tests/test_layer5_phase_b.py -q` → **30 passed** (12 new tests)
- `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest -q` → **210 passed / 32 skipped**
- Baseline was 198 passed / 32 skipped.

### Next session

Phase A and Phase C integrity — to be discussed. Phase D and Phase B are correct.

---

## Current state — 2026-06-27 (Phase D note reset; Phase B samples rerun)

Updated ignored analysis notes under `analysis/trades/`:

- `analysis/trades/sample_phase_d.md` was cleared and rewritten with fresh post-self-relocation Phase D findings only.
- `analysis/trades/sample_phase_b.md` was created with the three most recent accepted Phase B trades found under current code.

Fresh Phase B chunk reruns:

- `analysis/phase-b-recent-202307`
- `analysis/phase-b-recent-202009`
- `analysis/phase-b-recent-202001`
- `analysis/phase-b-recent-201906`

Three most recent accepted Phase B trades found:

| Entry time | Outcome | Direction | Path | Risk | R result | Source |
|---|---|---|---|---:|---:|---|
| 2023-08-30T15:00:00+00:00 | loss | short | B.watch_pathA | 15.2 | -1.0 | `analysis/phase-b-recent-202307/layer5_trade_results.csv` |
| 2020-10-14T06:30:00+00:00 | loss | long | B.watch_pathA | 15.8 | -1.0 | `analysis/phase-b-recent-202009/layer5_trade_results.csv` |
| 2020-01-23T09:15:00+00:00 | loss | long | B.watch_pathA | 19.5 | -1.0 | `analysis/phase-b-recent-202001/layer5_trade_results.csv` |

No accepted B.watch_pathB trade was found in the fresh rerun set; recent 2024-2026 chunks mostly produced Phase B geometry skips.

## Current state — 2026-06-27 (Phase D recent chunk sampling rerun)

Archived all top-level `analysis/layer5*` directories into `analysis/archives/`.

Reran fresh-runtime Phase D Layer 5 chunks with overlapping recent starts so each chunk start exercises self-relocation independently. New output dirs use `analysis/phase-d-recent-*` (not `layer5*`).

Most recent 3 unique accepted Phase D trades found:

| Entry time | Outcome | Dir | Path | Entry | SL | TP | Risk pips | Target R | Exit time | R result | Source |
|---|---|---|---|---:|---:|---:|---:|---:|---|---:|---|
| 2025-05-22T05:45:00+00:00 | timeout | short | D.watch_pathA | 1.13435 | 1.13635 | 1.121355 | 20.0 | 6.497 | 2025-05-22T13:45:00+00:00 | 2.52 | `analysis/phase-d-recent-202503/layer5_trade_results.csv` |
| 2024-10-16T07:00:00+00:00 | loss | long | D.watch_pathA | 1.08905 | 1.08755 | 1.09174 | 15.0 | 1.793 | 2024-10-16T10:15:00+00:00 | -1.0 | `analysis/phase-d-recent-202409/layer5_trade_results.csv` |
| 2024-05-17T03:30:00+00:00 | timeout | short | D.watch_pathA | 1.08607 | 1.08773 | 1.0809 | 16.6 | 3.114 | 2024-05-17T11:30:00+00:00 | 0.7108 | `analysis/phase-d-recent-202403/layer5_trade_results.csv` |

Chunks run: `2026-01`, `2025-11`, `2025-10`, `2025-09`, `2025-07`, `2025-05`, `2025-04`, `2025-03`, `2025-01`, `2024-11`, `2024-09`, `2024-07`, `2024-05`, `2024-03`, `2024-01`, `2023-11`.

## Current state — 2026-06-27 (self-relocation COMPLETE; next: Phase D + B integrity retest)

Self-relocation restart fix is implemented, audited (two codex review passes), and green.

### What was fixed

- `DualSmcRuntime` journal auto-save wired in `_hypothesis_for_payload()` (not `step()`), guarded on `persist_shadow_state`. Saves on phase transition (V1).
- `save_shadow_state()` writes atomically via temp + replace — corrupt partial journals eliminated.
- Hidden bootstrap success now validates `active_phase_e_direction` (correct for all phases; `current.direction` is counter for C and `"none"` for D) and `htf_pd_epoch_id` against current terrain. Rejects stale wrong-direction and stale same-direction wrong-epoch bootstrap.
- After failed bootstrap, only `HypothesisClassifier` is reset before terrain relocation; Layer 3 stays warmed.
- Terrain relocation: `pullback_confirmed` and `open` both route to `E.seeking` (unified). Old `C.pullback` relocation branch removed. `rejections["D"]` removed.
- `.gitignore`: `state/` added. `config.yaml` unchanged — `persist_shadow_state` is opt-in for production only.
- 4 new tests in `tests/test_hypothesis_restart_hierarchy.py`: epoch-flip probe (2023-04-28), same-timestamp D.watch journal restore, auto-save guard, epoch-mismatch fallback.
- `analysis/restart_self_relocation.md` updated with 2023-04-28 epoch-flip diagnosis.

### Verification

- `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest tests/test_hypothesis_restart_hierarchy.py -q` → **6 passed / 1 skipped**
- `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest -q` → **198 passed / 32 skipped**

### Next session

Retest Phase D and Phase B trade integrity now that self-relocation is fixed.

Earlier backtest samples (`analysis/layer5-*`) were collected under broken self-relocation — chunk starts mid-episode misclassified as `C.pullback` or `X.none` instead of the correct `E.seeking → D.watch` path. Sample counts and skip/accept decisions cannot be trusted for null-test baseline until re-run with the fixed restart.

Priority:
1. **Phase D null-test baseline** — re-run D.watch_pathA chunk sampling with fixed restart. Compare counts vs old `analysis/layer5-tagged-*` runs.
2. **Phase B integrity recheck** — B.watch_pathA and B.watch_pathB fire rates under fixed restart. The 2023-05-01 and 2023-05-02 D.watch timestamps were confirmed in continuous run; verify they now appear correctly in chunk-start restarts.
3. **B.watch deduplication bug** (deferred): `runway_too_short` returning `stale=False` re-fires same `pro_ichoch_event_id` on every subsequent B.watch bar — fix before measuring B trade counts.

## Current state — 2026-06-27 (EC/B.watch fixes audited; docs updated; layer5-temp.md deleted)

All three items from `.claude/plans/were-all-of-that-shimmering-hellman.md` are implemented and audited:

- **EC** `_compile_internal_ichoch_isb_sequence()` line 1329: `expected_counter_break` ✓ — EX.entry is counter iChoCh → counter iSB (both counter-HTF).
- **B.watch_pathA**: ITR gate removed; step 3 temporal check is `pro_ichoch_at > counter_ichoch_at` ✓
- **B.watch_pathB**: ITR gate removed; added guard `transition_at > counter_ichoch_at` ✓
- **Docs updated**: `docs/402-hypothesis-phD.html` (4 occurrences of "pro iSB" → "counter iSB / EX.entry"), `docs/501-entry-details.html` D.medium trigger line.
- **`layer5-temp.md` deleted** — all items resolved.
- Suite: **194 passed / 32 skipped** (83 focused: test_evidence_compiler + test_layer5_phase_b + test_layer5_layer6).

### Entry pattern summary (settled)

| Pattern | Phase | Step 1 | Step 2 | Step 3 | SL |
|---|---|---|---|---|---|
| EX.entry (`D.watch_pathA`) | D.watch | counter SC06 iChoCh | counter SC05 iSB | — | `watch_range_extreme` ± buffer |
| OTE.entry (`B.watch_pathA`) | B.watch | counter SC06 iChoCh | retracement (any form, not gated) | pro SC06 iChoCh | `commitment_extreme` ± buffer |
| OTE.entry (`B.watch_pathB`) | A.watch (B→A transition) | counter SC06 iChoCh (during B.watch) | retracement (not gated) | B→A major structure transition | `commitment_extreme` ± buffer |

### Next session

- Run a bounded backtest chunk to observe B.watch_pathA and B.watch_pathB fire rates (expected low; measurement mode).
- Phase A entry engine (OTE.entry, SL anchor = `phase_a_shadow_pro_extreme_at_weaken`).
- Phase C trade (regime-conditional, deferred).

## Current state — 2026-06-26 (entry pattern naming resolved; EC bug and OTE gate found)

**Session clarified EX.entry and OTE.entry definitions, found EC direction bug, simplified OTE step 2.**

### Entry pattern definitions (settled this session)

**EX.entry (D.watch_pathA) — counter-HTF trade:**
- Sequence: counter SC06 iChoCh → **counter SC05 iSB** (BOTH breaks in the counter-HTF direction)
- “Counter” = counter to HTF bias. D.watch trade direction is counter-HTF.
- No retracement between steps — two consecutive structural confirmations in the same direction.
- EC BUG FOUND: `_compile_internal_ichoch_isb_sequence()` checks iSB against `pro_break` (line ~1330 `evidence_compiler.py`). Must be `expected_counter_break`. One-line fix needed.

**OTE.entry (B.watch_pathA) — pro-HTF trade:**
- Sequence: counter SC06 iChoCh → retracement (any form, not gated) → pro SC06 iChoCh
- “Pro” = pro to HTF bias. B.watch trade direction is pro-HTF.
- Step 2 is NOT an explicit ITR pivot gate — accepts any of: ITR low pivot, sideways chop, iSB chain in counter direction, or immediate reversal (sharp turn → step 3 fires quickly). Temporal ordering enforced by `pro_ichoch_at > counter_ichoch_at`.
- Previous code had `latest_itr_low/high` as an explicit step 2 gate — this is wrong and must be removed from `_try_b_watch_path_a()` and `_try_b_watch_path_b()`.

**Key distinction:**

| Pattern | Step 1 | Step 2 | Final signal | Direction flip? |
|---|---|---|---|---|
| EX.entry (D.watch) | counter iChoCh | — | counter iSB | No — both counter-HTF |
| OTE.entry (B.watch) | counter iChoCh | retracement (not gated) | pro iChoCh | Yes — flip to pro-HTF |

### Next session TODO (ordered)

1. **Fix EC bug**: `_compile_internal_ichoch_isb_sequence()` in `evidence_compiler.py` — change line `and break_direction == pro_break` → `and break_direction == expected_counter_break` for the iSB check. Level validation (lines 1354–1358) is already correct for counter→counter.
2. **Fix layer5.py `_try_b_watch_path_a()`**: remove `latest_itr_low/high` gate; step 3 `_time_gt(pro_ichoch_at, counter_ichoch_at)` is the only temporal guard.
3. **Fix layer5.py `_try_b_watch_path_b()`**: remove `itr_confirmed_at` gate from the step 1+2 check.
4. **Update tests** (`test_layer5_phase_b.py`, `test_evidence_compiler.py`): update fixtures and assertions to match corrected EC iSB direction and removed ITR gate.
5. **Audit all session-implemented code** against corrected specs: `layer5.py`, `evidence_compiler.py`, `hypothesis.py`, `regime_tags.py`, `run_layer5_backtest.py`. The Codex implementation from the previous session used the wrong iSB direction in EC and the wrong ITR gate in layer5 — all consumers of `ltf_counter_ichoch_isb_sequence_seen` need a post-fix re-check.
6. Run full suite after fixes. Expect test count changes (ITR gate removal may affect B.watch test fixtures).
7. After passing: run Layer 5 replayer verification for Phase D and Phase B integrity.

### What was implemented by Codex (previous session) — partially incorrect

- Phase D now has only `D.watch_pathA`: gates on `ltf_counter_ichoch_isb_sequence_seen` from EC. SL = `phase_d_shadow_watch_range_extreme` plus buffer. HTF zone is not an SL anchor — analysis tag only.
- Removed: `D.watch_pathB`, `D.watch_pathC2`, `D.watch_pathSA`. `htf_zone_context` moved to `regime_tags.py`.
- EC `_compile_ltf_counter_choch()`: removed `ltf_counter_isb_*`; added `ltf_pro_ichoch_seen/event_at/event_id`.
- `B.watch_pathA`: counter iChoCh → ITR gate → pro iChoCh (using EC `ltf_pro_ichoch_seen`). **ITR gate is wrong — must be removed next session.**
- `B.watch_pathB`: one-shot `phase_a_entry_transition_origin_node == "B.watch"` dispatch. ITR gate also present — **must be removed next session.**
- DAG: `PhaseBShadow.phase_episode_id` added; `phase_a_entry_transition_*` one-shot fields emitted on B→A bar, cleared on A.watch hold bars.
- EC iSB direction in `_compile_internal_ichoch_isb_sequence()`: uses `pro_break` for iSB. **This is the EC bug — must be fixed to `expected_counter_break` next session.**

### Docs updated this session

- `docs/501-entry-details.html`: TL;DR, OTE.entry step 3, EX.entry iSB direction, B.watch_pathA gate sequence — all corrected to reflect settled definitions.
- `layer5-temp.md`: EC fix note, corrected EX.entry sequence, OTE.entry step 2 simplified.

### Terminology (settled)

- **counter/pro**: always relative to HTF bias direction. Counter = against HTF; pro = with HTF.
- **expansion/retracement**: expansion = pro-HTF direction; retracement = counter-HTF direction.
- **Internal structure**: `internal_structure_sequence` / `last_isc`; events `structure_ichoch` (SC06) and `structure_isb` (SC05).
- **Major structure**: `last_sc`; events `structure_choch` and `structure_sb`.

Verification:

- `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest tests/test_evidence_compiler.py tests/test_layer5_phase_b.py tests/test_layer5_layer6.py tests/test_hypothesis_classifier.py::HypothesisPhaseBToATransitionTests -q` → **81 passed**
- `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest tests/test_hypothesis_classifier.py -q` → **22 passed / 31 skipped**
- `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest tests/test_headless_runtime_reuse.py -q` → **7 passed**
- `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest -q` → **190 passed / 32 skipped**

Docs follow-up:

- Updated `docs/30*.html`, `docs/40*.html`, and `docs/50*.html` downstream references affected by the EC/Layer 5 changes.
- Main updated pages: `302-structure-context.html`, `312-EC-context-group.html`, `401-hypothesis-DAG.html`, `402-hypothesis-phA.html`, `402-hypothesis-phB.html`, `402-hypothesis-phC.html`, `402-hypothesis-phD.html`, `501-entry-details.html`, `501-entry-diagram.html`.
- Removed stale current-behavior references to `D.watch_pathSA`, `D.watch_pathB`, `D.watch_pathC2`, `B.watch_ote`, `_try_b_watch_ote`, and standalone `ltf_counter_isb_*`.
- Reworded B→A/A recovery/C transitions so `last_sc` is “major structure” and MSS/BoS-style flow stays “orderflow.”
- Validation: targeted `rg` scans over `docs/30*.html docs/40*.html docs/50*.html` and Python `HTMLParser` parse pass over touched pages completed cleanly.

## Current state — 2026-06-25 (Phase D + B entry path redesign planned)

**Plans documented in `layer5-temp.md`; `docs/501-entry-details.html` updated with boundary/FOMO edge-case notes. No entry code changed for this design shift yet.**

**Safe terminology note:** `OTE.entry` is now documented in `docs/501-entry-details.html` as a reusable Layer 5 regular entry pattern, not a Phase B-only special case.

**Next:** formulate the implementation plan from `layer5-temp.md` before changing code. The plan should sequence Phase D Path A tightening, EC cleanup/additions, B.watch OTE rewiring, B→A one-shot transition metadata, and validation chunks.

### Phase D — path redesign plan

| Path | Trigger | SL | Status |
|---|---|---|---|
| **A** (tighten from SA) | counter iChoCh → pro iSB (`ltf_counter_ichoch_isb_sequence_seen`) | `watch_range_extreme`; zone-distal = validity gate + wider cap (deferred) | PLAN |
| **C2** | MSS transition bar D.watch→C.pullback | Phase C policy decides | MOVE OUT OF PHASE D — Phase C owns this episode |
| **C1** | removed | — | Phase C owns its own episode |

- SA (iChoCh alone) → tighten to Path A (iChoCh + iSB) now that SC05/SC06 upstream fix is stable.
- Path B (HTF zone branch) → collapse into Path A: zone context = SL cap selector + analysis tag, not a separate path. Zone validity gate: if `watch_range_extreme` already past zone-distal → reject (price too fast, let other phases handle).
- C2 is now considered a boundary/FOMO trade. Keep `phase_c_entry_transition_*` provenance, but any transition-bar entry after `D.watch → C.pullback` spends Phase C budget, not Phase D budget.
- Edge-case rule documented: if the LTF P/D range is too compressed or fast-moving for the current phase to produce a clean MP entry, the early skip is correct because it prevents a FOMO handoff trade and preserves the next phase quota.
- EC field `ltf_counter_ichoch_isb_sequence_seen` is already produced (observation-only). Needs wiring in `layer5.py`.

### Phase B — entry path design (DEFERRED, plan in layer5-temp.md)

Symmetric to Phase D. Two paths:

| Path | Fires in phase | Trigger | SL |
|---|---|---|---|
| **B.watch_pathA** (OTE) | B.watch (holds) | SC06 counter iChoCh → ITR → SC06 pro iChoCh | `commitment_extreme_level` |
| **B.watch_pathB** | A.watch (at B→A transition) | steps 1+2 confirmed + pro ChoCh/MSS as step 3 | `commitment_extreme_level` |

- Path A: SC06 only at step 3 — pro ChoCh/MSS exit B.watch → A.watch, never reach Path A gate.
- Path B / transition candidate: fires only on one-shot `phase_a_entry_transition_origin_node == "B.watch"` metadata, not persistent `phase_a_origin_node`. Steps 1+2 (counter iChoCh + ITR) must have confirmed during B.watch hold. Transition itself is step 3. If steps 1+2 were observable, this is still a valid OTE.entry and spends **Phase B budget** even though the snapshot has shifted to A.watch.
- B→A edge distinction: if the LTF P/D range was tight/fast and there was no observable counter iChoCh + retracement before pro ChoCh/MSS, do not force a B trade; shift to A.watch and let Phase A spend Phase A quota.
- Step 1 co-firing: counter ChoCh + counter iChoCh → B.watch stays (counter ChoCh has no B.watch exit). Counter MSS + counter iChoCh → B.watch exits to C.pullback, OTE lost.
- EC additions needed: `ltf_pro_ichoch_seen` + `_event_at` + `_event_id` in `_compile_ltf_counter_choch()`. Remove `ltf_counter_isb_seen`.

### Prerequisites (ordered, from layer5-temp.md)
1. Phase D Path A tightening (SA→A, B collapsed) — implement + chunk-validate.
2. Remove `ltf_counter_isb_seen` from EC.
3. Add `ltf_pro_ichoch_seen` to EC.
4. Rewire `_try_b_watch_ote()` → `_try_b_watch_path_a()` using EC sequence gate.
5. Add B-owned transition dispatch: fire only when `phase_a_entry_transition_origin_node == "B.watch"` AND B OTE steps 1+2 were observed during B.watch.

---

## Current state — 2026-06-25 (EC bugs fixed after upstream iSB/iChoCh fix)

**Two EC bugs in `_compile_ltf_counter_choch()` sub-routines are fixed.**

- `_compile_internal_ichoch_isb_sequence()` now ignores intervening pro-direction SC06 iChoCh while waiting for the pro SC05 iSB confirmation; the active counter iChoCh sequence remains alive.
- `_compile_internal_pullback_pressure()` now treats only pro-direction SC05 iSB as a contradiction. Pro-direction SC06 iChoCh is ignored for contradiction purposes.
- Tests updated in `tests/test_evidence_compiler.py`, including a short-direction mirror for the iChoCh→iSB sequence and a positive SC05 pro-iSB contradiction test.
- Verification:
  - `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest tests/test_evidence_compiler.py -q` → **54 passed**
  - `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest tests/test_hypothesis_classifier.py tests/test_layer5_layer6.py -q` → **38 passed / 31 skipped**
  - `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest -q` → **196 passed / 32 skipped**

### ltf_counter_choch candidate — undocumented sub-facts

`_compile_ltf_counter_choch()` merges three sub-routine outputs into one candidate's `debug_facts`.
The 312 doc only showed the top-level `ltf_counter_choch_*` keys. Full set (all inside `ltf_counter_choch` candidate):

```
ltf_counter_choch_*       — iChoCh(counter) SC06 flags       → 8 keys
ltf_counter_isb_*         — iSB(pro) SC05 flags               → 4 keys
ltf_counter_sb_*          — macro SB(counter) fallback        → 5 keys
ltf_counter_ichoch_isb_sequence_seen  — sequence detection     → from _compile_internal_ichoch_isb_sequence
ltf_counter_internal_pressure_*       — pullback pressure      → 12 keys from _compile_internal_pullback_pressure
```

### Consumer map (ltf_counter_choch candidate facts)

| Fact | Phase E | Phase D | Phase C | B / A / X | Layer 5 |
|---|---|---|---|---|---|
| `ltf_counter_choch_seen` | ✓ counter-structure latch (`_phase_e_shadow_facts` gate) | — | — | — | pathSA gate (→ pathA after tightening); B.watch_pathA step1, pathB step1 |
| `ltf_counter_sb_seen` | ✓ `phase_e_context_ltf_counter_sb_seen` | orphaned `_phase_d_setup` (not called) | — | — | — |
| `ltf_counter_isb_seen` | — | — | — | — | none |
| `ltf_counter_internal_pressure_*` | — | journaled at D.watch→C.pullback as `phase_c_entry_transition_internal_pressure_*`; invalidation gates C2 in Layer 5 | metadata journaled | none | `_try_path_c()` rejects `phase_c_entry_transition_internal_pressure_invalidated` |
| `ltf_counter_ichoch_isb_sequence_seen` | — | — | — | — | `run_layer5_backtest.py` `path_a_ready` flag only |

### Docs updated 2026-06-24/25

- `docs/302-structure-context.html` — upstream SC05/SC06 fix issue closed
- `docs/312-EC-context-group.html` — 2 EC bug issue cards + doc-gap issue archived 2026-06-25; 2 open: "Phase A setup candidate missing" + "_phase_a_setup() EC migration" (reworded from classify() narrowing)

---

## Current state — 2026-06-24 (iSB / iChoCh upstream structure classification fixed)

**Upstream SC05/SC06 internal structure classification is fixed in `structureEngine.py`.**

- `StructureLevel` now stores `level_relation` (`HH`, `LH`, `HL`, `LL`, `seed`) computed causally from prior same-side remembered levels.
- `_sb_internal()` no longer classifies iSB/iChoCh from macro bullish/bearish bias.
- Correct internal SC rule:
  - high break of `HH` or `seed` → SC05 iSB up
  - high break of `LH` → SC06 iChoCh up
  - low break of `HL` or `seed` → SC06 iChoCh down
  - low break of `LL` → SC05 iSB down
- Existing `relation` from `PivotEvent` is preserved; `level_relation` is the new Structure-owned same-side relation used for SC05/SC06.
- Tests added/updated in `tests/test_structure_engine.py` for bullish LL, bullish LH, bearish HL, bearish HH mirrors.
- Docs updated in `docs/302-structure-context.html`; the prior “SC05–SC08 invalid signal” open issue is now marked completed.
- Verification:
  - `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest tests/test_structure_engine.py -q` → **30 passed**
  - `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest -q` → **194 passed / 32 skipped**
- Downstream EC / hypothesis / Layer 5 tests did **not** cascade-fail after the upstream fix.

## Current state — 2026-06-24 (Phase B OTE.entry wired but gate is WRONG — fix needed)

**Phase B OTE.entry (`B.watch_ote`) is implemented in `layer5.py` but fires 0 trades across 7 years.**

Infrastructure (correct — do not change):
- Dispatch: `phase == "B" and phase_sub_status == "watch"` → `_try_b_watch_ote()`
- `trade_direction = direction` (pro-HTF — opposite convention from Phase D counter trades)
- SL = `commitment_extreme_level ± buffer` (fixed floor from C→B entry)
- No budget gate — infinite budget for measurement
- `budget.spend("D", ...)` bug fixed → now `budget.spend(effective_phase, ...)`
- Analysis tags: `b_watch_origin_node`, `b_watch_at_extreme_entry`, `b_watch_htf_sd_zone_tapped` in `regime_tags.py`
- Contract updated in `.claude/layer5-entry-contract.md`; 15 tests in `tests/test_layer5_phase_b.py` all pass
- Suite: **191 passed / 32 skipped**

**The bug — wrong freshness gate ordering:**

The CORRECT B.watch OTE sequence (user-confirmed, LONG case):
```
1. B.watch holds (bullish HTF)
2. LTF bearish counter sequence develops:
   - bearish iChoCh fires (last_isc = down)   ← counter SC06
   - LTF ITR low forms (latest_itr_low fresh)  ← lower lows in counter sequence
3. Bearish sequence gets INTERRUPTED before reaching commitment_extreme:
   - bullish initiation iChoCh fires (last_isc = up)  ← entry signal
4. Entry LONG. SL = commitment_extreme_level - buffer
```

Current gate: `last_isc.ts > itr_low.confirmed_at` (iChoCh must post-date ITR confirm)
Problem: in 7-year full scan (181,328 bars), this gate fires 0 times. Funnel for LONG:
- 1234 bars: bearish counter isc active + fresh ITR → waiting for UP initiation iChoCh
- UP initiation iChoCh never appears in `last_isc` while still in B.watch
- Root cause not fully resolved: the initiation iChoCh may exit B.watch simultaneously,
  appear in a different field, or the correct signal is not `lower_structure.last_isc`

User will fix the gate/signal source in the next session.

**Do NOT change the unit tests or infrastructure — only the gate inside `_try_b_watch_ote()` needs fixing.**

**Phase A OTE.entry: deferred until Phase B gate is correct.**
- Phase A rule: same OTE pattern, SL anchor = `phase_a_shadow_pro_extreme_at_weaken` (from `PhaseAShadow`)
- Phase C entry: regime-conditional, deferred

## Current state — 2026-06-23 (E.pullback_developing → C.pullback 3-path + ghost C→D disabled)

**E.pullback_developing → C.pullback now has 3 explicit paths (hypothesis.py):**
- Path 1 (unchanged): D.watch involved — `pro_attempt_seen → D.watch → counter MSS → C.pullback`, `origin_node = "D.watch_mss"`
- Path 2 (NEW): LTF BoS in counter direction, no D entered — `ltf_counter_bos_confirmed` from `ltf_counter_story` candidate; freshness gate: `ltf_counter_orderflow_started_at` from `phase_e_context` candidate must be after `pullback_developing_entered_at`; `origin_node = "E.pullback_developing_bos"`
- Path 3 (renamed from "no_pro"): depth ≥ 51% express fallback — `origin_node = "E.pullback_developing_depth"` (was `"E.pullback_developing_no_pro"`)
- Path priority: 1 → 2 → 3. Path 2 checked via `_ec_candidate_for_direction(snapshot, "ltf_counter_story"/"phase_e_context", direction)`.
- `PhaseCshadow.origin_node` comment updated: `"D.watch_mss" | "E.pullback_developing_bos" | "E.pullback_developing_depth"`
- Tests in `tests/test_hypothesis_phase_d_simplify.py`: Path 2 fresh BoS fires, stale BoS blocked, Path 3 renamed, both-active: Path 2 wins.

**Ghost C.pullback → D.watch DAG path disabled:**
- `_phase_d_setup` was hardcoding `phase_d_liquidity_ready: False` — path was dead code.
- Call site removed, `if phase_d_from_c["phase_d_liquidity_ready"]:` block removed.
- Five orphaned helpers (`_phase_d_setup`, `_phase_d_liquidity_grab_setup`, `_phase_d_sub_status`, `_phase_d_origin_node`, `_phase_d_selection_reason`) marked with comment — kept for reference, not called.
- Reason: C.pullback → D.watch re-entry is a Layer 5 trade decision, not a Layer 4 DAG gate.
- Dead code cleanup deferred to when Phase C Layer 5 trade is wired.
- Suite: **176 passed / 32 skipped** (no regressions; `phase_d_liquidity_ready` was always False).

**Next: Phase B regular trade (B.watch at Layer 5).** Regime classifier deferred — wire regular path first, apply regime gate later.
- DAG: B.watch entered from `C.pullback` via depth gate at 51% + pro-HTF last_sc. `PhaseBShadow`: `commitment_extreme_level`, `entered_at`, `htf_sd_zone_id` etc.
- Phase C trade: deferred (regime affects C.pullback recovery most — do last).

---

## Current state — 2026-06-23 (Phase D integrity confirmed + express dead code removed)

**Phase D integrity confirmed — SA/B/C2 paths all correct:**
- Manually inspected latest accepted samples for each path (see `analysis/trades/sample_phase_d.md`).
- All losses in Phase D were regime losses (counter-trend trades in strong trend-continuation markets), not path-mechanic failures.
- Trend-continuation loss pattern documented in `analysis/trades/note_on_trend_continue.md`.
- C2 loss at `2024-06-07T11:45:00Z`: correct direction, SL too tight (15.2 pips) → swept before TP.
- Self-relocation failure at `2024-05-10T00:00:00Z` noted in `analysis/restart_self_relocation.md`.
- **Phase D declared stable. Next: Phase B entry engine.**

**Express D.watch gate dead code removed (across 9 files):**
- `hypothesis.py`: Removed `PhaseEShadow.htf_reaction_active/htf_reaction_left_at`, `PhaseDShadow.entry_express/express_zone_proximal/express_zone_proximal_zone_id`; removed `_express_zone_proximal()`, `_express_zone_current_bar_taps()`, `_phase_e_reaction_episode_allows_express()` methods; removed express gate block (~37 commented lines + live debug call).
- `layer5.py`: Removed `is_express` branch in `_try_d_watch()`, removed `_try_path_b_express()` (~86 lines), removed `is_express` logic in `_try_path_c()`.
- `regime_tags.py`: Removed `old_express_condition_seen` column and `_old_express_condition_seen()` function.
- `run_layer5_backtest.py`: Removed express path counters and report rows.
- `tests/test_layer5_layer6.py`: Removed 4 express tests and 2 express helpers.
- `tests/test_hypothesis_phase_d_simplify.py`: Removed 3 express tests and 2 express helpers.
- `.claude/layer34-contract.md`: Removed express gate policy block.
- `.claude/layer5-entry-contract.md`: Updated to SA/B/C2 only; removed express sections.
- `docs/402-hypothesis-phD.html`: Removed express gate section and pseudocode.
- **Suite: 172 passed / 32 skipped** (down from 177; 5 express tests removed).
- KEPT: `_htf_proximal_zone_id()` and `_htf_opposing_zone()` in hypothesis.py — live callers set `d_shadow.htf_zone_seen_id` for Path B zone-latch guard.

## Current state — 2026-06-22 (tagged E-seeking HTF S/D chunk sweep)

**Tagged chunk sweep COMPLETE for “HTF S/D tapped from E.seeking before Phase D trade” check:**
- Ran 20 bounded EURUSD `15m_4h` chunks with current regime tag columns:
  - Base windows: `analysis/layer5-tagged-e-seeking-201901/`, `202001/`, `202012/`, `202109/`, `202207/`, `202401/`.
  - Offset windows: `analysis/layer5-tagged-e-seeking-offset-201904/`, `201910/`, `202003/`, `202009/`, `202106/`, `202112/`, `202204/`, `202210/`, `202304/`, `202310/`, `202404/`, `202410/`, `202504/`, `202510/`.
- Aggregate across the 20 chunks:
  - `183` result rows, `4406` Phase D observation rows.
  - Result paths: `D.watch_pathSA=157`, `D.watch_pathC2=24`, `D.watch_pathB=2`, `D.watch_pathB_express=0`, `D.watch_pathC2_express=0`.
  - Result `htf_sd_zone_touch_timing`: blank `178`, `at_entry=3`, `during_d=2`, `before_d=0`.
  - Observation `htf_sd_zone_touch_timing`: blank `2886`, `before_d=999`, `at_entry=342`, `during_d=179`.
- Interpretation:
  - The new tags do find many D.watch bars where the HTF S/D touch was inherited from Phase E (`before_d`).
  - No Phase D entry/skip decision fired from those `before_d` bars in this 20-chunk sweep (`entry_decision=none` for all 999).
  - `before_d` is a supported proxy for “HTF S/D tapped while Phase E shadow was leaving `E.seeking`”: `phase_e_shadow_htf_reaction_seen` latches only in `_phase_e_shadow_facts()` under `previous_node == "E.seeking"` and `ltf_probe_at_htf_opposing_zone`.
  - This is not a risk-geometry skip finding; no `before_d` rows reached a Layer 5 decision. Current Path B still requires ITR arming + fresh iChoCh, and those bars did not produce an entry decision.
- Useful candidate observation clusters for replay/debug:
  - `2019-04-30T04:30:00Z`→`2019-05-03T17:00:00Z` in offset `201904`, mostly wide range, short prior direction.
  - `2022-02-01T18:00:00Z`→`2022-02-02T16:00:00Z` in offset `202112`, wide range, short prior direction.
  - `2023-04-28T17:00:00Z`→`2023-05-04T03:45:00Z` in offset `202304`, wide range, long prior direction.
  - `2024-03-26T18:30:00Z`→`2024-03-27T12:00:00Z` in base `202401`, normal range, short prior direction.
- Arrow `sysctlbyname` CPU-info warnings appeared under sandbox during the runs, but every chunk completed and wrote CSV/report outputs.

**Latest Phase D path samples / stability checkpoint:**
- Additional bounded current-code sample directories written under `analysis/layer5-tagged-phase-d-path-sample-*` to find latest SA/B/C2 rows.
- Current de-duplicated current-code result sample set: 156 unique decisions across `analysis/layer5-tagged-e-seeking-*` and `analysis/layer5-tagged-phase-d-path-sample-*`.
- Latest accepted SA samples:
  - `2026-01-29T09:45:00Z` SHORT timeout, `+2.429R`, risk 24.0 pips, `watch_extreme`, `counter_ichoch_immediate`.
  - `2025-06-04T21:45:00Z` SHORT timeout, `+0.353R`, risk 15.0 pips, `watch_extreme`, `counter_ichoch_immediate`.
  - `2024-10-16T00:15:00Z` LONG timeout, `-0.273R`, risk 15.0 pips, `watch_extreme`, `counter_ichoch_immediate`.
- Regular Path B remains extremely sparse under current conservative rules:
  - Accepted B: `2021-01-14T07:00:00Z` LONG loss, `-1R`, risk 15.0 pips, zone `SD-4H-2021-01-12T20:00:00Z`, `at_entry`, ITR inside zone.
  - Skipped B: `2021-01-13T17:30:00Z` LONG skipped `late_entry_risk_too_wide`, risk 41.9 pips, same zone, `during_d`, ITR inside zone.
  - No third regular B decision found after the additional bounded sweep. This supports treating B as rare/conservative rather than launch-blocking.
- Latest accepted C2 samples:
  - `2024-06-07T11:45:00Z` SHORT loss, `-1R`, risk 15.2 pips, `watch_extreme`, `d_watch_mss_plain`.
  - `2024-05-10T03:45:00Z` SHORT timeout, `-0.133R`, risk 15.0 pips, `watch_extreme`, `d_watch_mss_plain`, `at_entry`, ITR inside zone.
  - `2024-03-27T12:15:00Z` LONG loss, `-1R`, risk 17.9 pips, `watch_extreme`, `d_watch_mss_plain`.
- Focused integrity tests passed after sampling:
  - `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest tests/test_layer5_layer6.py tests/test_hypothesis_phase_d_simplify.py -q` -> 30 passed.
- Stability conclusion candidate: Phase D paths SA/C2 have enough current-code accepted samples and passing focused tests; regular B is sparse but has candidate rows saved. **Phase D is not signed off yet**; user still needs to manually inspect sample integrity before calling it stable.
- End-of-day decision: stop additional sampling for now. Saved candidate sample note at `analysis/trades/sample_phased.md`; resume with manual integrity inspection, not more HTF S/D refinement.
- Next session:
  - Manually inspect integrity of the saved SA/B/C2 samples in `analysis/trades/sample_phased.md`.
  - If samples pass inspection, then call Phase D stable.
  - After sign-off, clean up disabled/dead express Path B/C code and matching docs/tests/contracts.
  - Then move on to Phase B entry engine work.

## Current state — 2026-06-21 (express Path B/C fresh chunk sample)

**Fresh express chunk sampling rerun COMPLETE:**
- Previous sampling outputs were deleted/outdated, so six new bounded EURUSD `15m_4h` runs were written:
  - `analysis/layer5-express-sample-201901/`
  - `analysis/layer5-express-sample-202001/`
  - `analysis/layer5-express-sample-202012/`
  - `analysis/layer5-express-sample-202109/`
  - `analysis/layer5-express-sample-202207/`
  - `analysis/layer5-express-sample-202401/`
- Exact trigger-path extraction found:
  - `D.watch_pathB_express`: 4 rows.
  - `D.watch_pathC2_express`: 3 rows.
- Suggested Path B express inspection samples:
  - `2021-01-14T18:00:00+00:00` LONG, skipped `late_entry_risk_too_wide`, risk 32.3 pips.
  - `2021-09-16T22:30:00+00:00` LONG, skipped `late_entry_risk_too_wide`, risk 32.0 pips.
  - `2022-07-19T15:15:00+00:00` SHORT, skipped `late_entry_risk_too_wide`, risk 33.8 pips.
- Suggested Path C2 express inspection samples:
  - `2021-09-17T10:15:00+00:00` LONG, skipped `late_entry_risk_too_wide`, risk 50.3 pips.
  - `2021-10-14T04:45:00+00:00` SHORT, skipped `runway_too_short`, risk 21.2 pips.
  - `2024-03-25T15:45:00+00:00` LONG, skipped `late_entry_risk_too_wide`, risk 37.4 pips.
- User decision: do not rely on current Path D entry statistics yet; Phase D entry behavior is still being stabilized. `min_rr` / max acceptable SL can be reconsidered later after express Path B/C integrity is inspected.
- `runway_too_short` clarification: current Layer 5 uses `min_rr = 1.75`, not 1.5. With an estimated 33% win rate, theoretical breakeven RR is about `2.03R`, so `1.75R` would require roughly `36.4%` win rate before costs.
- Inspection note: `2021-01-14T18:00:00+00:00` Path B express is a chase-high case. Price was `E.seeking`, then hit the HTF lower in bearish HTF bias; immediate flickering turned it into `D.watch`. Treat this as a suspect express transition case to inspect before trusting the sample.
- Temporary code state: the Layer 4 express `D.watch` transition is commented out in `src/ultrab/core/smc/hypothesis.py` while Phase E HTF-reaction branch semantics are redesigned. The helper still observes current-bar zone overlap and emits `phase_d_express_blocked_reason = "express_gate_temporarily_disabled"` when the old gate would have been relevant.
- Regime tag analysis added under `src/ultrab/entry/regime_tags.py` and wired into `run_layer5_backtest.py`. Both `layer5_trade_results.csv` and `layer5_phase_d_observations.csv` now include compact analysis-only tags: HTF S/D zone context, old express condition, HTF P/D liquidity-grab context, D/watch and zone-touch bar ages, ITR-in-zone context, HTF P/D range bucket, and session. These tags do not change phase or entry permission yet; they are for filtering/tightening later.
- Next session:
  - Retest the correctness of the new regime tags against real replay samples before using them for filtering.
  - Inspect whether Phase C DAG walking needs additional evidence. If C can advance with no meaningful evidence in wide HTF P/D ranges, that may be a correctness problem; distinguish intended tight-range fast C from over-lax wide-range C.

## Current state — 2026-06-21 (X.thesis_over hard gate fix)

**X.thesis_over same-epoch re-entry bug fixed:**
- Root issue discovered while investigating `2021-01-29T08:45:00+00:00`: the continuous run was wrong, not just the cold-start relocation. It emitted `X.thesis_over` at `2021-01-27T16:45:00+00:00`, then stale same-epoch Phase E shadow state reopened `D.watch` at `2021-01-27T17:00:00+00:00`.
- This violated the rule that `X.thesis_over` is the hard post-cycle / budget-spent gate. Same-epoch regular `D.watch`, express `D.watch`, `C`, `B`, and `A` must be blocked; only a fresh `E.seeking` context from a new HTF extreme or structural epoch may escape.
- Fix in `hypothesis.py`: an early `X.thesis_over` guard now runs before stale E/D gates. It carries `X.thesis_over` with `phase_x_blocked_stale_shadow_transitions = True`, unless `phase_e_context_new_htf_extreme` is true, in which case it resets shadows and moves to `E.seeking`.
- Regression tests added in `tests/test_hypothesis_phase_d_simplify.py`: regular stale `E.pullback_developing` cannot reopen D; stale express zone reaction cannot reopen D; new HTF extreme can restart `E.seeking`.
- Historical probe after fix:
  - `2021-01-27T16:45:00+00:00` -> `X.thesis_over`
  - `2021-01-27T17:00:00+00:00` -> `X.thesis_over`
  - `2021-01-28T00:00:00+00:00` -> `X.thesis_over`
  - `2021-01-29T08:45:00+00:00` -> `X.thesis_over`, no `D.watch_pathB`
- Targeted chunk rerun: `analysis/layer5-chunk-202012-pathB-integrity/` now writes 6 result rows; the old `2021-01-29T08:45:00+00:00` Path B row is gone.
- Docs updated: `docs/401-hypothesis-DAG.html`, `docs/402-hypothesis-phX.html`, `docs/402-hypothesis-phD.html`.
- Focused tests: `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest tests/test_hypothesis_phase_d_simplify.py -q` -> 9 passed.
- Broader focused tests: `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest tests/test_hypothesis_phase_d_simplify.py tests/test_hypothesis_classifier.py -q` -> 30 passed / 31 skipped.
- Full suite: `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest -q` -> 177 passed / 32 skipped.

**Self-relocation case note updated:**
- Existing restart/self-relocation docs live in `docs/403-shadow-thesis.html`, especially Bootstrap Window / Terrain Relocation. A separate Layer 5 budget-reset note is in `docs/501-entry-details.html` under “Budget ownership and self-relocation reset.”
- New shared restart case note: `analysis/restart_self_relocation.md`.
- Cold starts at `2021-01-28T00:00:00+00:00` or `2021-01-29T00:00:00+00:00` still fall to `X.none`. This is no longer compared against D.watch; after the hard-gate fix, continuous state is `X.thesis_over`.
- Cold-start diagnostics:
  - `recovery_mode = cold_start_no_context`
  - `2021-01-28T00:00:00+00:00` bootstrap window `2021-01-22T21:00:00+00:00` → `2021-01-27T23:45:00+00:00`
  - `2021-01-29T00:00:00+00:00` bootstrap window `2021-01-25T21:00:00+00:00` → `2021-01-28T23:45:00+00:00`
  - `bootstrap_bars_used = 300`, `bootstrap_success = False`
  - `relocation_attempted = True`, `relocation_selected_node = None`
  - rejections: A/B expected anchor rejects, `D = d_relocation_requires_reconstructable_watch_provenance`, `C = phase_c_story_not_ready`, `E = htf_phase_not_open`
- Boundary probe: cold start at `2021-01-27T00:00:00+00:00` relocates to `C.pullback` (`terrain_relocation`) instead of exact continuous `A.watch_weaken short`, then stays around `C.pullback_weaken long`. Remaining open design question: whether restart should support exact A/X thesis-over parity without a saved journal.
- Retest checkpoint added: `2026-02-02T00:00:00+00:00`. This one is likely handled already; docs/tests record hidden bootstrap landing in `C.pullback short`. Keep it as a known-good comparison case when retesting relocation.

## Current state — 2026-06-21 (Path B integrity chunk test)

**Regular Path B integrity chunk test COMPLETE:**
- Fresh bounded runs written to `analysis/layer5-chunk-*-pathB-integrity/`.
- Windows: standard six 6000-step chunks (`2019-03-04`, `2020-06-01`, `2021-09-01`, `2023-01-01`, `2024-06-01`, `2026-01-01`) plus targeted `2020-12-01` chunk.
- Across 7 chunks after the `X.thesis_over` hard-gate fix: 5 Path B-family decisions:
  - Regular `D.watch_pathB`: 2 current rows, both in `analysis/layer5-chunk-202012-pathB-integrity/`.
  - `D.watch_pathB_express`: 3 rows, all skipped as `late_entry_risk_too_wide`.
- Additional post-hardgate offset chunk outputs written under `analysis/layer5-sample-*-pathB-hardgate/`. No new regular `D.watch_pathB` rows found there.
- Additional shifted in-memory sweep over 14 more 6000-step starts (`2019-04`, `2019-10`, `2020-03`, `2020-09`, `2021-06`, `2021-12`, `2022-04`, `2022-10`, `2023-04`, `2023-10`, `2024-04`, `2024-10`, `2025-04`, `2025-10`) also found no new regular `D.watch_pathB`.
- Regular Path B timestamps:
  - `2021-01-13T17:30:00+00:00` LONG, skipped `late_entry_risk_too_wide`, 41.9 pips, zone `SD-4H-2021-01-12T20:00:00+00:00`.
  - `2021-01-14T07:00:00+00:00` LONG, accepted, entry `1.21493`, SL `1.21343`, risk 15.0 pips, loss -1R at `2021-01-14T15:00:00+00:00`, zone `SD-4H-2021-01-12T20:00:00+00:00`.
- Invalidated row: `2021-01-29T08:45:00+00:00` is no longer Path B; after the hard-gate fix it remains `X.thesis_over`.
- Runtime integrity probe for the 2 current regular Path B rows passed all current contract checks: regular not express, Phase D watch, demand-zone direction for long trade, ITR low inside zone, ITR confirmed after D.watch open, iChoCh after ITR, SL raw anchored to zone distal low.
- Analysis note: `analysis/trades/path_b_integrity_20260621.md`.

## Current state — 2026-06-21 (updated)

**Layer 4 D.watch express re-dip guard COMPLETE:**
- Bug timestamp: `2021-01-11T08:00:00Z` Path B_express LONG came from an earlier Layer 4 express `D.watch`, not from Layer 5 ITR arming.
- Root cause: `phase_e_shadow_htf_reaction_seen` was sticky and sourced from HTF-zone `in_zone`; express could open after the live LTF bar had already left the original HTF reaction episode and later re-dipped the same zone.
- Fix in `hypothesis.py`: express D.watch now requires the current LTF bar to overlap the direction-correct HTF opposing zone (`long` → supply, `short` → demand) and requires the first continuous reaction episode to still be active.
- User integrity checklist to verify later before trusting Path B again:
  - Bullish context: `HTF PD level high > HTF supply zone > probe`; `D.watch` must come from the initiation, not from a later stale/re-dip flip.
  - Bearish mirror in code is `HTF PD level low < HTF demand zone < probe`; user wrote “supply” for the bearish bullet, so confirm wording if this was intentional.
  - Replay inspection should show no flickering and no later mis-flip after the first reaction episode leaves the HTF S/D zone.
- New Phase E shadow episode fields: `htf_reaction_active`, `htf_reaction_left_at`. Once `htf_reaction_seen` is true and a current LTF bar is outside the zone, `htf_reaction_left_at` is set; any later re-entry is blocked with `phase_d_express_blocked_reason = "htf_zone_reentry_after_reaction_left"`.
- Regression probe from `2021-01-08T00:00Z`: `2021-01-11T01:45Z` and `2021-01-11T08:00Z` now remain `E.stalling`; no `D.watch` express opens.
- Partial affected-window rerun: `analysis/layer5-sample-202012-pathB-express-episode-guard/` removes the old `2021-01-11T08:00Z` accepted B_express row. Because the bad express no longer spends budget, a later non-express accepted Path B appears at `2021-01-14T07:00Z` (LONG, 15.0 pips, loss -1R). Full 17-window totals are not rerun yet.
- Docs updated: `.claude/layer34-contract.md` and `docs/402-hypothesis-phD.html`.
- Verification: focused runtime/Layer 5 suite → 34 passed; full suite `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest -q` → 174 passed / 32 skipped.

**Path B ITR arming redesign COMPLETE:**
- Scope: Path B only (`D.watch_pathB`, `D.watch_pathB_express`). SA/C2/C2_express behavior intentionally unchanged.
- New Path B sequence: HTF zone context → direction-correct LTF ITR pivot arms the zone probe → fresh iChoCh after the armed ITR → entry.
- Direction rules:
  - SHORT / supply: require `lower_structure.latest_itr_high` inside the supply zone.
  - LONG / demand: require `lower_structure.latest_itr_low` inside the demand zone.
- Arming geometry:
  - SHORT: `zone.high + buffer - latest_itr_high.price <= max_sl_pips`.
  - LONG: `latest_itr_low.price - (zone.low - buffer) <= max_sl_pips`.
  - ITR `confirmed_at` must be after `phase_d_shadow.watch_entered_at`.
- Entry freshness: iChoCh must fire after the armed ITR confirmation, not merely after D.watch open.
- SL remains the HTF zone distal/invalidation edge + buffer, with min floor widen and max-risk late-entry skip handled by existing geometry.
- B_express now resolves `phase_d_shadow_express_zone_proximal_zone_id` against `snapshot["zones"]`; if the saved express zone is gone, B_express returns no entry. It no longer falls back to watch_range_extreme.
- Tests added for no ITR, unarmed ITR, unarmed-zone-not-poisoning later armed episode, iChoCh-before-ITR, short/supply armed entry, long/demand mirror armed entry, B_express saved-zone resolution, and B_express ITR arming.
- Docs updated: `.claude/layer5-entry-contract.md` and `docs/501-entry-details.html`.
- Verification: `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest tests/test_layer5_layer6.py -q` → 19 passed. Full suite → 172 passed / 32 skipped.

**Path B ITR-armed resample COMPLETE:**
- Re-ran six 6000-step EURUSD chunks into `analysis/layer5-chunk-*-pathB-itr-armed/`.
- Result: 2 Path B-family rows total, both `D.watch_pathB_express`, both skipped as `late_entry_risk_too_wide`; 0 accepted Path B/B_express trades.
- `2021-09-16T22:30:00Z`: B_express LONG skipped, 32.0 pips.
- `2024-07-11T19:30:00Z`: B_express SHORT skipped, 36.3 pips.
- Old rows at `2020-06-10T18:00Z` and `2024-06-14T20:15Z` no longer appear as Path B/B_express rows under ITR arming.
- Updated `analysis/trades/path_b_timestamps.md` with current counts and stale-row mapping.

**Path B expanded sampling note:**
- User asked for bounded sampling, not full-history. Full-history run was interrupted intentionally.
- Added 11 offset 6000-step sample windows across 2019-2025.
- Expanded sample total: 17 windows, 7 Path B-family rows, 1 accepted, 6 skipped.
- Only accepted Path B-family timestamp found so far: `2021-01-11T08:00:00Z`, `D.watch_pathB_express`, LONG, entry 1.21812, SL 1.21618, risk 19.4 pips, target_r 3.941, outcome loss -1R.
- Updated `analysis/trades/path_b_timestamps.md` with accepted/skipped rows and source directories.

**Path B / B_express SL edge fix COMPLETE:**
- `_express_zone_proximal` (hypothesis.py): was returning `zone.low` for SHORT / `zone.high` for LONG — the near/proximal edge. Fixed to return `zone.high` for SHORT / `zone.low` for LONG (the distal/far edge). This is the correct SL anchor: if price clears the far edge, the zone is invalidated.
- `_try_path_b` (layer5.py): same swap on the `proximal =` line.
- Path B_express and C2_express both read `phase_d_shadow_express_zone_proximal` — fixing `_express_zone_proximal` fixes all three paths automatically.
- 2020-06-10T18:00 case: wrong SL was 1.13274 (zone.low + buffer, below entry 1.13495 for SHORT → immediate stop-out in 1 bar). Correct SL = zone.high + buffer = 1.13851 (above entry). After fix: entry skipped as `late_entry_risk_too_wide` (35.6 pips > max_sl_pips). Tests: 166 passed / 32 skipped.

**Zone re-trigger guard COMPLETE (`_zone_first_episode`):**
- `PhaseDShadow` (hypothesis.py): added `htf_zone_seen_id: str | None` (set when `htf_zone_seen` latches) and `express_zone_proximal_zone_id: str | None` (set at express gate open). Both reset on D.watch open and in `reset()`. Both in debug output.
- New helper `_htf_proximal_zone_id(snapshot, direction)` in hypothesis.py: returns zone_id of the first direction-matched counter zone.
- `EntryPermissionEngine` (layer5.py): added `_zone_first_episode: dict[str, str]` — `{zone_id → phase_episode_id of first D.watch episode that armed it}`.
- `_try_path_b`: records zone_id after ITR arming but before the choch gate. Blocks if the same armed zone_id was seen in a prior (different) episode.
- `_try_path_b_express`: same block/record using `phase_d_shadow_express_zone_proximal_zone_id` after the saved express zone arms.
- Protects against: cross-epoch re-trigger after a valid armed probe (budget resets but zone_id is remembered), re-dip in new D.watch episode after an armed episode ended without entry. A shallow unarmed zone touch does not poison a later armed episode.

**Layer 6 bot no-timeout fix COMPLETE:**
- `TradeAnalyzer.__init__` (layer6.py): `max_hold_bars: int | None = 32`. Bot passes `None` (no timeout). Backtest default stays 32 bars (8h on 15m).

**Path B ITR trigger redesign — RESOLVED / IMPLEMENTED (2026-06-21):**

Context: All Path B/B_express entries rejected after SL fix (zone distal → 30-56 pip risk). iChoCh fires as price bounces OUT of zone → entry at zone proximal → full zone width risk. User asked: wait for ITR pivot inside zone (price ~50% deep) instead.

Infrastructure confirmed:
- `snapshot["lower_structure"]["latest_itr_high"]` / `["latest_itr_low"]` already exposed by `structureEngine.get_snapshot()` with `price`, `confirmed_at` fields. No EC changes needed.
- For express path: look up zone by `express_zone_proximal_zone_id` in snapshot["zones"]. If zone gone from snapshot, no express entry.
- `_time_gt(confirmed_at, watch_entered_at)` freshness check needed.

Geometry probe result (2024-07-11 SHORT, zone=[1.08827, 1.09013], 18.6 pip wide):
- First ITR high inside zone: `1.08969` at `17:30`, close=`1.08710` → zone distal SL risk=32.3 pips ❌, ITR pivot+buffer SL risk=27.9 pips ❌
- Bar +1 (`18:00`): same pivot, close=`1.08780` → zone distal SL=25.3 pips ❌, ITR pivot+buffer SL=20.9 pips ✓
- Bar +2 (`18:15`): new lower pivot `1.08868`, close=`1.08782` → zone distal SL=25.1 pips ❌, ITR pivot+buffer SL=10.6 pips → below min_sl=15

Resolved design:
- ITR is an arming evidence gate, not the entry trigger and not the SL anchor.
- iChoCh remains the entry trigger, but must occur after the armed ITR.
- SL remains zone distal/invalidation edge + buffer. ITR-to-zone-edge geometry must be within max risk before Path B can arm, and entry-to-zone-edge geometry is still checked at execution.

**Open / deferred:**
- Express gate pre-existing zone: 2020-06-10 case showed the phase transition from C.pullback_weaken → E.seeking happened while price was already inside the HTF supply zone. `htf_reaction_seen` latched immediately at E.stalling (not from a fresh probe). Express gate fired on a stale zone tap. Discussed fix (`htf_zone_pre_existed_at_e_open` flag) but **not implemented** — user concluded the SL fix (zone.high anchor → late_entry_risk_too_wide) already filters this case correctly. Deferred.
- Path B timestamps at `analysis/trades/path_b_timestamps.md` are **STALE** — all 3 previously "accepted" entries were bugs (wrong proximal SL). With correct distal SL: 0 Path B/B_express accepted across all 6 chunks.

## Current state — 2026-06-21 (original)

**Phase D Express Taxonomy COMPLETE** — plan `.claude/plans/ok-we-could-proceed-polymorphic-perlis.md` fully implemented.

- **`D.watch_ichoch` renamed → `D.watch_pathSA`** in `layer5.py` and all tests.
- **`D.watch_pathC1` removed** (unreachable — SA fires on any fresh iChoCh during D.watch hold; B fires with zone context). C1 tests deleted.
- **Express gate extended**: now fires from `{"E.stalling", "E.pullback_developing"}` (was `"E.stalling"` only). Guard: `not pro_attempt_seen` prevents pre-empting regular D.watch on the same bar. Label: `"E.stalling_zone_tap"` or `"E.pullback_developing_zone_tap"`.
- **New `PhaseDShadow` fields**: `entry_express: bool = False`, `express_zone_proximal: float | None = None`. Stored at express open, survive D.watch → C.pullback. Explicitly reset to `False/None` at regular D.watch open. Both in `reset()` and `_phase_d_shadow_debug()`.
- **`_express_zone_proximal()` helper in `hypothesis.py`**: reads `htf_counter_reaction` candidate + `snapshot["zones"]`, mirrors `_htf_proximal_zone`'s supply/demand direction filter.
- **`_try_path_b_express()`** new method in `layer5.py`: iChoCh + express_zone_proximal SL (fallback: watch_range_extreme). `evidence_kind="htf_sd_zone_express"`, `source_store="phase_d_shadow"`.
- **`_try_path_c()`** updated: C1 removed, always C2. Express detected via `phase_d_shadow_entry_express`; uses express_zone_proximal (fallback: watch_range_extreme); trigger_path = `"D.watch_pathC2_express"` when express.
- **`run_layer5_backtest.py`**: summary columns and report updated for 5-path taxonomy.
- **`.claude/layer5-entry-contract.md`**: updated trigger paths, evidence kinds, express shadow fields.
- Tests: **166 passed / 32 skipped** (3 new express tests, 2 C1 tests removed).

**Next session:**
- Path B design tension (zone-gone scenario) documented but stable: if `htf_zone_context=True` in non-express D.watch but zone gone from snapshot, `_try_path_b` returns None and entry is silently blocked. Decision deferred (zone-gone = skip remains correct behavior — no zone SL anchor).
- Extend trade permission to Phase B (layer5 Phase B entry engine).
- Run full backtest after taxonomy change to validate counts align.

## Current state — 2026-06-20

**Phase D super-lax entry COMPLETE** — plan `.claude/plans/validated-whistling-waffle.md` fully implemented.

- **Path A erased.** Superseded by `D.watch_ichoch`: fires from D.watch on iChoCh bar close alone (no iSB wait). Gate: `ltf_counter_choch_seen=True`, `choch_at > watch_entered_at`, `phase_d_shadow_watch_range_extreme` present, `max_sl_pips` check rejects fast flush (>25 pips).
- **`_watch_extreme` migrated** from Layer 5 dict cache to `PhaseDShadow.watch_range_extreme` (updated per hold bar in DAG, reset on D.watch open). `source_store` changed from `layer5_cache` → `phase_d_shadow`.
- **`_watch_htf_zone_seen` migrated** from Layer 5 dict cache to `PhaseDShadow.htf_zone_seen` (latches True in DAG when `htf_opposing_sd_tapped` during D.watch hold). Path B reads `phase_d_shadow_htf_zone_seen` OR `phase_e_shadow_htf_reaction_seen`.
- **`_d_watch_budget_spent`** stays in Layer 5 (deferred open issue: `docs/501-entry-details.html §11`).
- **Path C `_try_path_c()`** now reads `_float(debug.get("phase_d_shadow_watch_range_extreme"))` instead of `self._watch_extreme.get(cache_key)`.
- Files changed: `hypothesis.py`, `layer5.py`, `tests/test_layer5_layer6.py`, `run_layer5_backtest.py`, `.claude/layer5-entry-contract.md`, `.claude/layer34-contract.md`.
- Tests: **165 passed / 32 skipped** (full suite).
- Chunk validation data in `analysis/layer5-chunk-*-patha-integrity/` is now stale — new backtest run needed.

**`watch_range_extreme` direction bug — fixed 2026-06-20:**
- Bug: `hypothesis.py` was tracking `range_low` (min) when `direction == "long"` and `range_high` (max) when `direction == "short"` — backwards.
- Correct: `direction == "long"` (hypothesis bullish, trade = short) → SL must be ABOVE entry → needs `range_high` max. `direction == "short"` (trade = long) → SL below entry → needs `range_low` min.
- Fix: swapped the condition in `hypothesis.py` line ~933. All 165 tests still pass.
- Before fix: 2026-01-29 episode saw `watch_range_extreme = 1.18953` (wrong: range LOW), risk = 73.9 pips, skipped.
- After fix: `watch_range_extreme = 1.19932` (correct: range HIGH), risk = 24.0 pips, D.watch_ichoch **accepted** SHORT at 1.19712, SL 1.19952, TP 1.18757, R=3.98. Outcome: timeout +2.43R at bar 32.

**2026-01-29 episode probe (post fix):**
- D.watch opened `2026-01-28T22:30Z`. `prior_direction = long`, `trade_direction = short`.
- `D.watch_ichoch` fired SHORT at `2026-01-29T09:45Z`: entry `1.19712`, SL `1.19952` (+24 pips), TP `1.18757`.
- Budget spent. C.pullback + Path C1 suppressed at `12:45Z` (correct).
- Timeout at `2026-01-29T17:45Z`, exit `1.19129`, r_result `+2.43R`.

**2019-03-06/07 episode probe (post D.watch_ichoch):**
- D.watch opened `2019-03-06T21:15Z`. `prior_direction = short`, `trade_direction = long`.
- `D.watch_ichoch` fired LONG at `2019-03-07T02:00Z`: `sl=1.12974` (below entry ≈ 1.13124), `risk_pips=15.0` (min_sl_pips floor).
- Budget spent at `02:00`. DAG moved to `C.pullback` at `10:15Z`. C1 blocked by budget.
- Note: in 2019 case the 15-pip floor masked the wrong extreme — bug didn't affect acceptance, just SL placement.

**Next session:**
- **Path B design tension — resolve before spec:** Scenario 3 (zone tapped in E phase, zone consumed before D.watch opens): `phase_e_shadow_htf_reaction_seen` sticky flag routes exclusively to Path B; Path B inner check passes `htf_opposing_sd_reaction` (via `htf_opposing_sd_resolved`), but `_htf_proximal_zone` returns None because zone is gone from snapshot → **no entry, D.watch_ichoch also silently blocked**. Decision needed: should zone-gone → fall back to `D.watch_ichoch`, or is zero entry the correct behavior (no zone SL anchor → skip)?
- Path C sampling done. C1 confirmed (2020-06-04, 2021-10-14). C2 near-unreachable with current code (DAG accumulates pressure from E.pullback_developing, not D.watch open). Accepted as-is.
- Path C + D.watch_ichoch stable enough to backtest. Path B spec pending above decision.

**Deferred to System V4 / bot layer:**
- `NewsCalendarFilter`: suppress Phase D/C entries ±1h of high-impact EUR/USD news; optionally exit open positions before release. Finding documented in `analysis/trades/phase_d_news_compression_finding.md`. Historical announcement data (2019–present) is available via ForexFactory scrape or pre-scraped GitHub CSVs. Stress-test plan: flag `within_news_window` on all backtest trade rows, measure fraction of D.watch/Path C losses that are news-driven before building the module.

Prior state (Path A integrity work, 2026-06-19 early):
- Created and aligned `.claude/layer5-entry-guide.md`: Layer 5 must not store market memory; Layer 3 owns market sequence/range/lifecycle memory; Layer 4 owns thesis commitment memory.
- Implemented Path C semantic cleanup: C1/C2 are `D.watch → C.pullback` transition-bar entries; EC emits `ltf_counter_internal_pressure_*`; Layer 4 annotates the one-shot transition.
- 2019 replay probe: Path A (strict iChoCh+iSB) had 0 valid trigger bars across six 6000-step chunks.
- Path C probe (`2026-01-29`): C1 fires at `12:45Z` from `D.watch_mss`; skipped by geometry (`late_entry_risk_too_wide`, ~44.9 pips).

## Current state — 2026-06-18

**Phase D entry redesign COMPLETE** (four Layer 5 paths: A/B/C1/C2, DAG bug fixes, `_watch_extreme` SL, symbol geometry from yaml). Suite: 150 passed / 32 skipped.

**Layer 5 pending bug trio fixed — 2026-06-18:**

1. `_try_path_a` now resolves `entry_price_est` before computing `abs(entry_price_est - sl_raw)`, so compressed `_watch_extreme` setups widen to the 15 pip floor.

2. `_try_path_b` now applies the same 15 pip floor widen to zone-proximal SLs. If zone proximal + buffer is too tight, SL widens outward from entry.

3. `_make_intent` no longer emits `risk_too_tight`; path-level geometry owns the minimum SL floor. Remaining skip reasons are `late_entry_risk_too_wide` and `runway_too_short`.

Focused regressions were added in `tests/test_layer5_layer6.py` for Path A floor widen, Path B floor widen, and direct `_make_intent` removal of `risk_too_tight`.

Reusable chunk-validation guide added at `tests/PHASE_CHUNK_VALIDATION.md` for Phase D precision checks and future Phase C/B/A trade-path validation.

**Phase D chunk validation COMPLETE — 2026-06-18:**

Ran `tests/PHASE_CHUNK_VALIDATION.md` sampling, not full history:
- smoke: `2019-03-04`, `--max-steps 1500`
- chunks: `2019-03-04`, `2020-06-01`, `2021-09-01`, `2023-01-01`, `2024-06-01`, `2026-01-01`, each `--max-steps 6000`

Across the six 6000-step chunks: 25 Layer 5 decisions.
- `D.watch_pathA`: 6 total = 3 loss, 2 timeout, 1 win.
- `D.watch_pathB`: 13 total = 3 timeout, 6 `runway_too_short`, 4 `late_entry_risk_too_wide`.
- `D.watch_pathC1`: 0 total — not observed in sampled chunks.
- `D.watch_pathC2`: 6 total = 3 loss, 3 `late_entry_risk_too_wide`.

Validation checks:
- `risk_too_tight`: 0 occurrences.
- Accepted risk range: 15.0 to 17.7 pips.
- Skip reasons seen: only `runway_too_short` and `late_entry_risk_too_wide`.

Known 2019-03-06/07 case:
- `2019-03-06T21:15Z`: entered `D.watch`.
- `2019-03-07T02:00Z`: iChoCh cached.
- `2019-03-07T09:00Z`: Path A accepted on iSB, long, entry `1.13019`, SL `1.12869`, target `1.13461`, risk `15.0` pips.
- `2019-03-07T15:00Z`: loss at SL, `-1R`.
- Headless probe: `2019-03-07T10:15Z` still moved DAG to `C.pullback` with `phase_c_origin_node = D.watch_mss`, but Layer 5 budget had already been spent by Path A at `09:00`.

Output files:
- `analysis/layer5-smoke-201903/`
- `analysis/layer5-chunk-201903/`
- `analysis/layer5-chunk-202006/`
- `analysis/layer5-chunk-202109/`
- `analysis/layer5-chunk-202301/`
- `analysis/layer5-chunk-202406/`
- `analysis/layer5-chunk-202601/`

**Next:** User will inspect sampled timestamps in the replayer. If C1 coverage is required, search targeted `D.watch_mss` episodes where iChoCh was cached during D.watch and iSB fires after `C.pullback` entry. Otherwise extend trade permission to Phase B (Layer 5 Phase B entry engine).

---

## Prior state — 2026-06-15

**Phase D + C + B + A model complete. X.none unification done. Shadow Thesis restart hierarchy implemented and documented. Phase D trade layer + lightweight analysis CSV path implemented.**

- Phase D: `D.watch`-only model. `D.speculation` removed from DAG (commit `10dff12`).
- Phase C: 2-state model `C.pullback` / `C.pullback_weaken`. Replay validated. Docs archived.
- Phase B: `B.watch` wired. `PhaseBShadow` with `commitment_extreme_level` locked at C→B entry. commitment-extreme breach exit (→C) added.
- Phase A: `A.watch` / `A.watch_weaken` wired. pro extreme advance gate on recovery (blocks oscillation in ranging). `PhaseAShadow.pro_extreme_at_weaken`.
- Phase X: `"none"` phase eliminated — all 4 call sites → `_phase_x()`. `none_sub_status` field removed. `X.warm_up`, `X.no_direction`, `X.none`, `X.thesis_over` sub-statuses live. `X.none` emits blocked-transition debug. `A.watch → X.thesis_over` fires on `phase_a_thesis_matured`.
- Runtime: Shadow Thesis restart hierarchy wired in `DualSmcRuntime`: saved-journal restore with epoch/direction/anchor validation, 300-bar hidden Layer 4 bootstrap, conservative C/E terrain relocation, and restart diagnostics in payload/runtime metadata.
- Tests: persistence roundtrip + real-history restart coverage added. `2026-02-02T00:00:00+00:00` random wake-up bootstraps 300 hidden bars and lands in `C.pullback short`. Deeper live Shadow Thesis validation can be revisited after the bot layer exists.
- Test suite: **142 passed, 32 skipped.**

**Current open issue focus — 2026-06-16**
- **Terminology update**: from now on, call Layer 5 `trade` and Layer 6 `analysis`.
  - `trade` = former Layer 5 entry permission, budget, stale-opportunity, MP geometry, and broker/backtest intent layer.
  - `analysis` = former Layer 6 outcome/result ledger, win/loss/timeout classifier, and CSV metrics layer.
- **Next Milestone**: extend `trade` beyond Phase D once C/B/A phase-specific iChoCh rules are decided.
- **After trade + analysis validation**: run broader backtest windows to validate the trading system end-to-end, then build/retest bot operation.
- **Open audit**: `htf_b_phase_setup` key names used by `_update_phase_b_watch_shadow()` may be legacy. Verify EC emits `htf_last_resolved_zone_id` and `ltf_pro_sd_zone_ids` in the B.watch context.
- **Done**: expose restart/warmup recovery diagnostics in replay/runtime payload via `hypothesis_restart`.
- **Trade scope**: A.watch and B.watch entry permission engines are not built yet; DAG shadow surfaces are the interface.
- **Docs update**: `docs/501-entry.html` expanded for trade V1: MP-only entry, `htf_pd_epoch_id` epoch budget, per-phase first/re-entry budgets, D.watch detailed Path A/B entry, E/X hard-gate zero budget/no trade, initial 2R/2.5R geometry, and C/B/A iChoCh rule placeholders pending user spec.
- **Trade policy decision — 2026-06-16 (revised)**: Phase D uses `D.lax` policy. No separate evidence prerequisite — evidence is already baked into Phase D context. Path A: D.watch → iChoCh (SC06) → iSB (SC05) same direction → entry at close. SL = `commitment_extreme_level` + 2 pips. Path B: D.watch at HTF SD zone → price bounces → iChoCh confirms initiation fade → entry. SL = zone distal line + 2 pips. TP = pd_midpoint (50% HTF PD). RR gate: ≥ 1.75 to take; no upper cap. SL band: 15–25 pips. `commitment_extreme_level` is a `PhaseDShadow` field set at D.watch open (ltf.range_high for long, ltf.range_low for short). `ltf_counter_isb_*` facts now emitted in EC `_compile_ltf_counter_choch()`.
- **Docs update — 2026-06-16**: `docs/401-hypothesis.html` is simplified back to Layer 4 dataflow with one downstream trade consumer node; analysis is intentionally omitted there. `docs/501-entry-diagram.html` now exposes the Layer 3 Entry Facts Contract explicitly and marks Path A/B as a Phase D-only `D.watch` trigger contract. `docs/601-trade-analysis-details.html` documents the V1 no-spread/no-slippage win/loss/timeout ledger contract.
- **Trade scope note**: Phase D `D.lax` is implemented first. Remaining phase-specific iChoCh rules for C/B/A are still pending, so C/B/A trade permission stays out of scope.
- **Trade/analysis implementation — 2026-06-16**: Added `ultrab.entry` package with Phase D `D.lax` trade permission (`EntryPermissionEngine`), budget/stale ledger, MP geometry, and lightweight no-spread/no-slippage analysis outcome classifier. Added CLI `python3 -m ultrab.entry.run_layer5_backtest` writing:
  - `analysis/layer5/layer5_trade_results.csv`
  - `analysis/layer5/layer5_phase_d_observations.csv`
  - `analysis/layer5/layer5_epoch_summary.csv`
  Default run produced 56 `D.watch` observation bars across 2 HTF P/D epochs and 0 entry chances because no D.medium evidence or trigger facts appeared in that window. This was a smoke-test-sized default replay window, not a count across all local EURUSD history. The saved CSV window is `2026-04-10T16:15:00+00:00` through `2026-04-16T00:15:00+00:00`; local EURUSD 15m parquet spans `2019-01-02T00:15:00+00:00` through `2026-04-16T00:15:00+00:00`. Full-history Phase D / Path A / Path B counts still need a deliberate broader run later. Full test suite: `146 passed, 32 skipped`.

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
phase_d.watch_entered_at eventTimestamp of choch_1 (freshness floor for trade)
phase_d.choch_1          { trigger_type, at, level }  ← pro-HTF SC level → trade SL ref
phase_d.pro_attempt      { htf_reaction_status, ltf_story_status }  ← quality metadata
```

**D.speculation removed from DAG (commit 10dff12):**
- Path A (SC06 iChoCh → D.speculation) and Path B (counter SB + pullback_confirmed) are now trade.
- `choch_2` and `speculation_entered_at` dropped from `PhaseDShadow`.
- Docs: `docs/402-hypothesis-phD.html`, `docs/501-entry.html`.

**SC05-SC08 status:**
- SC05/SC06 (ITR internal iSb/iChoCh): emitted by EC, consumed by trade. Not DAG gates.
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

## Trade entry confirmation — D.lax policy (redesign planned 2026-06-18)

**Plan file**: `.claude/plans/ancient-growing-hoare.md` — full design, ready to implement.

Three DAG bugs being fixed + SL anchors redesigned. Four Layer 5 paths replace the old two:

| Path | Fire state | Trigger | SL |
|---|---|---|---|
| A | D.watch, no zone | iChoCh + iSB (both during D.watch) | `_watch_extreme` + 15 pip floor |
| B | D.watch, zone ctx | iChoCh alone | zone proximal |
| C1 | C.pullback (`D.watch_mss`), iChoCh was cached | iSB fires after `c_pullback_entered_at` | `_watch_extreme` + 15 pip floor |
| C2 | C.pullback (`D.watch_mss`), no iChoCh cached | immediate at transition bar | `_watch_extreme` + 15 pip floor |

All four spend D.watch budget (`_d_watch_budget_spent[cache_key]`). Tagged `evidence_kind="D.watch_pathA/B/C1/C2"`.

**DAG fixes (hypothesis.py):**
- D.watch→C.pullback: replace `ltf_counter_isb_seen` gate with `ltf_counter_orderflow_mss_watch` + fresh leg. `origin_node="D.watch_mss"`.
- Add express gate: `E.stalling + htf_reaction_seen → D.watch` (emits `phase_d_entry_express=True`).
- D.watch hold: emit `phase_e_shadow_htf_reaction_seen` into debug for Layer 5.

**New Layer 5 caches (cache_key = epoch_id+direction):**
- `_watch_extreme`: running min/max of `lower_structure.range_low/high` during D.watch hold
- `_watch_htf_zone_seen`: latches True when `htf_opposing_sd_tapped` during D.watch
- `_d_watch_budget_spent`: True once any path fires and is accepted

**Old Path A/B (pre-redesign):** `commitment_extreme_level` SL (stale), zone distal SL (100% rejected). Superseded.

Full spec: `docs/501-entry-details.html`.

---

## Key boundaries (settled)

- **DAG structural gate**: `last_sc` only (SC01/SC02 macro ChoCh). `last_isc` is trade.
- **Orderflow MSS** (`mss_regime = "mss_watch"`): gate for `E.stalling → E.pullback_developing`
  AND `D.watch → C.pullback` (fresh leg, leg_id != consumed_leg_id).
- **Terminology**: SB/ChoCh = structural (`structureEngine`). BoS/MSS = orderflow. Never mix.
- **`ltf_counter_choch` EC pattern**: emits `choch_seen` (`last_isc` SC06) and `sb_seen`
  (`last_sc` macro SB). Consumed by E tracking + trade. Not a DAG transition gate.

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
- ✅ `docs/403-shadow-thesis.html` — Shadow Thesis persistence/restart design: saved journal resume, hidden Layer 4 bootstrap, terrain relocation, and narrowed `X.none` role.
- ✅ `docs/501-entry.html` — trade iChoCh mechanics
- ✅ A.watch → X.thesis_over wiring — `phase_a_objective_progress_pct` + `phase_a_thesis_matured`, configurable via `replay.hypothesis.phase_a.objective_progress_threshold`
- ✅ Direction-sensitive EC fact audit — `_ec_candidate_for_direction()` added; E/C/D/B/A direction-sensitive candidate reads now require `candidate.direction == direction`; opposite-direction regression tests added.
- ✅ `.claude/layer34-contract.md` — D.speculation removed, PhaseCshadow added
- ✅ Replay validated: EURUSD 15m/4h — D.watch → C.pullback fires at 2026-01-29T12:45
- ✅ Orderflow MSS gate fix — `probe_breaks_protected_anchor` decoupled from direction scorer; EC gate = `ltf_bias_counter AND probe_breaks_protected_anchor`; `higher_orderflow` deleted
- ✅ Shadow Thesis restart hierarchy — state serialization/restore, epoch/direction/anchor validation, hidden Layer 4 bootstrap, conservative C/E terrain relocation, and restart diagnostics.

**Next session queue (ordered)**
1. **Implement plan** at `.claude/plans/ancient-growing-hoare.md` — DAG bug fixes (hypothesis.py) + four-path Layer 5 redesign (layer5.py) + contract/docs updates. Run full suite (146/32 baseline) + headless probe (2019-03-04 start) + backtest.
2. ~~Review/spec shadow consumed-event ledger for D liquidity expiry~~ — **closed, no shadow ledger needed.** Resolved by: `D.watch → E.seeking` (new HTF extreme), `D.watch → C.pullback` (MSS fresh), Layer 5 `_d_watch_budget_spent`, and budget guard. Epoch boundary resets the shadow. No gap.
3. Extend trade permission to Phase B (layer5 Phase B entry engine).

**Restart hierarchy — implemented**
- Epoch (`htf_pd_epoch_id`) is the validity discriminator, not calendar time. Epoch unchanged → persist valid regardless of downtime duration. Epoch changed → reject persist, fall to bootstrap.
- `commitment_extreme_level` is a historical `last_sc` snapshot taken at C→B entry. Layer 3 only holds current `last_sc` — this field cannot be reconstructed from terrain or EC. Persist is the only mechanism that preserves it across a shutdown boundary.
- Must-persist fields: `b_shadow.commitment_extreme_level`, `b_shadow.commitment_extreme_event_id`, `a_shadow.entered_at`, `a_shadow.pro_extreme_at_weaken`, `c_shadow.origin_node`, `c_shadow.entered_at`, `e_shadow.source_orderflow_leg_id`.
- Bootstrap window: `window_bars(500) - warmup_bars(200) = 300 bars ≈ 75h on 15m`. Already fetched in both replay and bot — no extra data dependency.
- Terrain relocation is conservative: A/B/D are rejected with explicit reasons until anchors/provenance are reconstructable; C is selected when HTF pullback terrain and direction-checked C story are ready; E is selected when HTF open terrain is supported.

**Sequence after restart hierarchy**
1. Extend trade permission beyond Phase D
2. Backtest trading system end-to-end
3. Build/retest bot operation

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

## Orderflow MSS fix (2026-06-11)

**Root cause**: `_score_direction()` returns `"mixed"` at transition (bull==bear window) → probe-breaks-anchor block was gated on `score["direction"] == "bullish/bearish"` → never ran at the MSS moment.

**Fix (3 files)**:
- `orderflow.py` lines 129-148: direction scorer still nominates `protected_anchor_ref` for trade SL. Break check now direction-agnostic — finds latest HL/LH and fires regardless of window score.
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
docs/501-entry.html                         trade iChoCh entry mechanics
.claude/layer34-contract.md                 EC→DAG interface spec (gitignored)
.claude/layer34-guide.md                    architectural invariants (read-only)
```
