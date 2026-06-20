# Project status

## Current state — 2026-06-21

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
