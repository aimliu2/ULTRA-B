# Project status

## Current implementation — Orderflow anchor store + D.watch gate (2026-06-09)

Replay diagnosis for EURUSD 15m/4h at `2026-01-28T16:00Z` found the real
`D.watch` immediate-fire bug:
- `2026-01-28T15:30Z`: `E.pullback_developing` opened when orderflow MSS-watch
  fired. The live probe broke the protected low-side HL at `1.19583`.
- `2026-01-28T16:00Z`: LTF structure closed below the same `1.19583` floor and
  emitted `itrSbDown` / `structure_choch`.
- The event was fresh, so timestamp freshness gates passed, but semantically it
  was the structural close-confirmation of the same MSS disruption that opened E,
  not a post-E Phase D setup.

Implemented fix:
- LTF Structure snapshot now exposes a separate derived
  `orderflow_anchor_sequence` + `orderflow_probe` store. It is still derived
  from filtered structure pivots during migration, but it has distinct
  `OFANCH:*` / `OFPROBE:*` IDs and provenance fields.
- Orderflow now defaults to `orderflow_anchor_sequence` and falls back to
  `structure_sequence` only for compatibility fixtures.
- EC emits provenance fields:
  - Orderflow MSS: `ltf_counter_orderflow_anchor_id`,
    `ltf_counter_orderflow_disruption_id`, `ltf_counter_orderflow_source_store`
  - Structural ChoCh/SB: `ltf_counter_choch_event_id`,
    `ltf_counter_choch_source_level_id`, `ltf_counter_choch_source_store`,
    plus SB equivalents
- Phase E shadow owns the initial counter break: orderflow MSS-watch and any
  same-origin structural close-confirmation.
- `D.watch` opens only after a distinct post-E pro-HTF attempt/bounce exists and
  a later fresh counter structural event resumes the reaction:
  `phase_e.pro_attempt_seen == true`,
  `phase_e.pro_attempt_started_at > phase_e.counter_structure_confirmed_at`,
  `ltf_counter_choch_event_at > phase_e.pro_attempt_started_at`, and
  structural provenance differs from consumed E MSS provenance.

Replay validation:
- Headless `DualSmcRuntime` EURUSD 15m/4h from `2026-01-27T22:00Z` confirmed:
  - `2026-01-28T15:30Z`: hypothesis is `E / pullback_developing`; source MSS
    anchor is `OFANCH:*1.195830`, disruption is `OFPROBE:*1.195710`.
  - `2026-01-28T16:00Z`: hypothesis remains `E / pullback_developing`; the
    structural ChoCh is recorded as
    `phase_e_shadow_counter_structure_confirmed_at = 2026-01-28T16:00:00+00:00`;
    `phase_e_shadow_pro_attempt_seen = False`; no `D.watch`.
- Tests: focused Structure/Orderflow/EC/Phase D set `64 passed`; full suite
  `116 passed, 31 skipped`.
- Supersedes older notes below that say the D.watch immediate-fire bug was
  attempted but not confirmed fixed.

Docs updated: `docs/302-structure-context.html`, `docs/305-orderflow-context.html`,
`docs/311-EC-context.html`, `docs/312-EC-context-group.html`,
`docs/401-hypothesis-DAG.html`, `docs/402-hypothesis-phD.html`,
`docs/40x-hypothesis-migration.html`.

Guide/contract update before user retest:
- `AGENTS.md` now contains the headless `DualSmcRuntime` timestamp-probe guide
  based on `tests/test_headless_runtime_reuse.py`.
- `.claude/layer34-guide.md` was changed back into architecture guardrails:
  EC/DAG/Shadow ownership, direction gate, freshness gate, shadow persistence,
  and fact-level readiness. It no longer globally bans consuming all
  `collecting` facts.
- `.claude/layer34-contract.md` now owns operational exceptions:
  `ltf_counter_choch_seen` needs `status == "ready"`, while
  `ltf_counter_sb_seen` may be consumed while `status == "collecting"` only for
  `D.watch -> D.speculation` Path B with direction, freshness, and
  `lower_structure.phase == "pullback_confirmed"` gates.
- Contract status enum corrected to `watching | armed | invalidated | fired |
  missed`; Phase E pullback memory fields expanded to current code.
- User will retest Phase D next.

## Phase E migration contract

Phase E has a small shadow node machine:

```
E.seeking -> E.stalling -> E.pullback_developing
```

The nodes are internal Phase E sub-statuses. They do not select the global
phase by themselves. The DAG still emits `phase == "E"` until an explicit
E→D or E→C transition fires.

### E.stalling — final boundary analysis

Current Phase E behavior in `_phase_e_shadow_facts()` is intentionally simple:

```
if previous phase/direction is not active E:
  E.seeking
elif new HTF extreme:
  E.seeking
elif previous E shadow node was E.seeking:
  E.stalling
elif previous E shadow node was E.stalling and LTF orderflow MSS watch fires:
  E.pullback_developing
elif previous E shadow node was E.pullback_developing:
  hold E.pullback_developing until new HTF extreme, D, or C
```

So `E.stalling` means: the active HTF Phase E expansion stopped extending on
this bar, but the pullback has not yet proven itself.

**EC owns the formal chronological facts:**
- `phase_e_context` emitted when HTF direction is known
- `new_htf_extreme`
- `htf_pd_stopped_expanding` (`not new_htf_extreme`)
- current HTF bias / direction
- current LTF bias, including whether it is counter to HTF
- LTF probe around or outside the current HTF P/D range, if detectable
- LTF counter SD / counter story facts
- clean/broken LTF counter-orderflow facts, source leg id, and started-at
- LTF pullback depth inside the current HTF P/D range (`ltf_pullback_depth_pct`)
- reaction facts: `reaction_warning`, `reaction_confirmed`, `reaction_failed`

**Layer 4 DAG owns the phase decision:**
- `none`/warmup -> `E.seeking` once usable HTF structure exists
- `E.seeking` -> `E.stalling` when EC says the HTF P/D did not extend and no
  higher-priority E→D transition fired
- hold `phase == "E"` while LTF probes outside the P/D range before HTF close
- `E.stalling` -> `E.pullback_developing` only after `ltf_counter_orderflow_mss_watch == true`
  (reads `phase_e_context` debug facts; MSS fires when live probe breaks latest confirmed HL)
- `E.pullback_developing` does not return to `E.stalling` on broken/pro LTF
  orderflow. That return path was a legacy decision and is retired. Once the
  first counter-orderflow MSS is recorded, the shadow holds
  `E.pullback_developing` until a new HTF extreme resets to `E.seeking`, or
  Layer 4 selects D/C.
- `E` -> `D` only on the agreed counter-reaction contract
- fast `E` -> `C.hard_pullback` when D did not fire, clean LTF counter
  orderflow is already present, and the LTF probe breached the HTF P/D midpoint
  (`ltf_pullback_depth_pct >= 50`)
- `E` -> `C` slow pullback only after shadow reports `E.pullback_developing`

**Phase E shadow owns only internal memory:**
- current node: `E.seeking`, `E.HTF_reaction`, `E.stalling`, or `E.pullback_developing`
- previous node
- bars in node
- first stalled timestamp, if added
- source LTF counter-orderflow leg id / started-at for `E.pullback_developing`
- consumed source id so one clean orderflow event does not double-fire
- `phase_sub_status` derived from the current node

**Deprecated Phase E fields:**
- Phase E no longer reads LTF `structure_attempt` / `ltf_structure_attempt`
- `phase_e_context_attempt_*`, `phase_e_shadow_source_attempt_id`, and
  `phase_e_shadow_source_itr_level_id` are deprecated debug aliases and should
  stay empty; use `phase_e_shadow_source_orderflow_leg_id` and
  `phase_e_shadow_consumed_orderflow_leg_id` instead

**Important rule:** do not require `E.stalling` to have full `HTF bullish +
LTF bearish` confirmation. That is useful EC/debug language, but it belongs
as evidence attached to the pause. If it becomes required for the transition,
the classifier skips the quiet pause and `E.stalling` starts meaning
"pullback already visible", which belongs to `E.pullback_developing`.

---

## Phase D — new simplified model (decided 2026-06-07)

Old sub-statuses (`HTF_reaction_point`, `LTF_reaction_point`,
`htf_pd_grab_reclaim_test`, `htf_eq_grab_reclaim_test`) are **superseded**.
All archived in `docs/402-hypothesis-phD.html` §06.

Two nodes: `D.watch` and `D.speculation`. Both originate from
`E.pullback_developing`.

**CORRECTED (2026-06-09):** D.watch trigger is the first LTF **pro-HTF** ChoCh
(bounce initiation), not a counter-HTF ChoCh. The old spec had the direction inverted.

```
E.pullback_developing
  + first LTF pro-HTF ChoCh (e.g. bullish ChoCh for long = bounce started)
    → phase_e.pro_attempt_seen == True
  → D.watch

D.watch
  + first LTF counter-HTF ChoCh (bounce failed, bias flips back counter) [Path A]
  OR LTF counter SB after pullback_confirmed (quiet bounce) [Path B]
  → D.speculation
  (same-bar shortcut retired: structureEngine emits at most one SC event per bar)

D.watch → E.seeking    on HTF close above PD range

D.speculation
  + ltf_counter_orderflow_mss_watch fires on fresh leg
    AND orderflow_leg_id != phase_d_shadow.consumed_leg_id
  → C.pullback

D.speculation → E.stalling    on SL hit (price absorbed, HTF not above PD)
D.speculation → E.seeking     on HTF close above PD range
```

**Shadow thesis — PhaseDShadow (not yet created):**
Three epoch-scoped snapshots, all persist into C and B:
- `phase_d_choch_1` — D.watch trigger context (ChoCh level, LTF/HTF SD zone,
  liquidity pool). SL reference.
- `phase_d_pro_attempt` — accumulated while in D.watch. Records HTF SD zone,
  LTF SD zone, liquidity pool encountered during the pro-HTF bounce.
  Layer 5 quality signal: any non-None = meaningful bounce; all None = shallow
  grind (acceptable, lower quality). Layer 5 grades quality, not the gate.
- `phase_d_choch_2` — D.speculation trigger context (same shape as choch_1).
  Layer 5 SL: reads choch_2 first, falls back to choch_1.
- `consumed_leg_id` — prevents same MSS leg that opened E.pullback_developing
  from also triggering C.pullback.

All three snapshots overwritten if a new D.watch opens later in the same epoch.

**Layer 5 SL placement (reads choch_2, falls back to choch_1):**
```
HTF SD zone present  →  htf_sd_zone_high + 10 pips
LTF SD zone present  →  ltf_sd_zone_high + 20 pips
liquidity grab       →  liquidity_level  + buffer
nothing              →  choch_level      + 20 pips (static)
```

## Phase C — new simplified model (decided 2026-06-07)

Old sub-statuses (`htf_reaction_pullback`, `hard_pullback`, `slow_pullback`,
`pullback.no_followthrough`, `pullback.after_inducement`) are **superseded**.

Two nodes: `C.pullback` and `C.pullback_weaken`.

```
C.pullback
  → B.xxx              when ltf_pullback_depth_pct >= 50% (discount zone)
  → C.pullback_weaken  when LTF ChoCh fires counter to expected pullback
                       (structural disruption before 50% depth)
  → E.seeking          when new HTF extreme fires (expansion resumed)

C.pullback_weaken
  → C.pullback   when LL confirmed (LTF orderflow) OR LTF P/D floor tested
  → B.xxx        only via C.pullback recovery path (must recover first)
  → E.seeking    when new HTF extreme fires
```

`_phase_c_sub_status_from_current_d()` is eliminated — no D→C name coupling.
B failure returns to C.pullback; if structure disrupted at that point,
C.pullback_weaken fires naturally from the ChoCh rule.

---

## Migration state — what is done and what is in-flight

**Done**
- EC implemented, 130 tests pass
- EC wired in `dual_smc._init_engines()` → `payload["evidence_candidates"]`
- `HypothesisClassifier` re-enabled in `dual_smc._init_engines()` (was `None`)
- `hypothesis.py`: `_phase_b_initiation_setup()` migrated — reads `ec["htf_b_initiation"].status == "ready"`
- `hypothesis.py`: `_phase_d_setup()`, `_phase_c_setup()`, `_phase_b_setup()`,
  `_phase_a_finale()`, and `_phase_e_reaction()` consume `evidence_candidates`
- EC candidate debug payloads aligned with DAG output keys for D liquidity tests,
  C watching-without-POI, B blocked reasons, A finale, and E two-bar reaction facts
- `HypothesisClassifierState.phase_b_shadow_*` extracted into `ShadowThesis` (`state.shadow_thesis`)
- `PhaseEShadow` extracted and nested as `state.shadow_thesis.phase_e` (root ShadowThesis
  owns all phase ledgers; `phase_e_shadow_node` property delegates to `shadow_thesis.phase_e.node`;
  `ShadowThesis.reset()` clears only B-phase fields — phase_e resets independently on epoch boundary)
- `phase_e_context` emits `htf_pd_stopped_expanding`, LTF counter-bias, LTF probe facts,
  clean/broken LTF counter-orderflow, orderflow leg id, started-at, pullback depth,
  and `htf_equal_extreme_*` facts
- `_phase_e_shadow_facts()` uses Phase E context facts for all node transitions
- Layer 4 blocks generic B/B-initiation selection from active/previous Phase E
- `E.pullback_developing` holds on broken/pro LTF orderflow. The legacy
  `E.pullback_developing -> E.stalling` disruption path is retired; D/C own
  later interpretation after the first counter-orderflow MSS has been recorded.
- Phase E `structure_attempt` debug deprecated; E pullback memory uses explicit
  orderflow fields (`source_orderflow_leg_id`, `consumed_orderflow_leg_id`)
- Fast E→C hard-pullback shortcut: D not ready + clean LTF counter orderflow +
  `ltf_pullback_depth_pct >= 50` → `C.hard_pullback`
- Warm-state HTF `pullback_confirmed` E-hold fallback added
- Classifier-local Phase E extreme tracker removed; EC `phase_e_context` owns price/time watermark
- `contextLedger.py` and `test_context_ledger.py` deleted
- Test helpers updated: `_build_fused()` + `with_evidence_compiler()` + `classify_with_ec()`
- `liquidity_grab()` test helper uses new `current_triggerable_liquidity_events` format
- EC `_compile_ltf_counter_choch()` added as standalone pattern; `_phase_d_setup()` reads
  it and exposes `ltf_counter_choch_*` as top-level debug facts
- `_phase_d_setup()` derives `phase_d_liquidity_selected_node` / `phase_d_liquidity_trigger` /
  `phase_d_liquidity_pool_id` from `liquidity_reclaim_candidates` + `liquidity_reclaim_ready_event_ids`
  (Layer 4 owns D-node selection; EC emits no `phase_d_*` keys — enforced by boundary test)
- **Phase E orderflow MSS trigger**: `E.stalling → E.pullback_developing` reads
  `phase_e_context_ltf_counter_orderflow_mss_watch`. MSS fires when live probe breaks the
  latest confirmed **HL** (bullish) or **LH** (bearish) in the orderflow swing sequence.
  `orderflow.py` now emits `regime = "mss_watch"` directly; `choch_watch` alias and
  `choch_monitor_status` / `choch_trigger_source` fields removed. EC choch fallback reads
  removed. 139 tests pass as of 2026-06-06.
- **Layer 3 naming migration completed (2026-06-06):**
  - Structure close-through event names are now `itrSbUp`, `itrSbDown`, `ltrSbUp`, `ltrSbDown`;
    legacy `itrBosUp` / `itrBosDown` / `ltrBosUp` / `ltrBosDown` remain only in `runtimeAlias`.
  - Structure memory is now named `structure_sequence`, `recent_structure_sequence_points`,
    and `structure_probe`; old `structure_anchor_*` snapshot keys remain as compatibility aliases.
  - Structure config uses `structure_sequence_limit`; old `anchor_sequence_limit` /
    `structure_anchor_limit` are accepted only as fallback compatibility keys.
  - Historical note: Orderflow originally defaulted to `source = "structure_sequence"`
    and owned anchor-swing concepts (`protected_anchor_ref`, HL/LH MSS gate, BoS /
    confirmed direction). This is now superseded by the 2026-06-09 target design:
    LTF Orderflow should use `orderflow_anchor_sequence` + `orderflow_probe` with
    distinct provenance from structural SB/ChoCh.
  - `docs/30x-layer3-migration.html` was deleted; remaining notes moved to
    `docs/302-structure-context.html`, `docs/305-orderflow-context.html`, and
    `docs/402-hypothesis-phC.html`.

**In-flight / not started**
- `hypothesis.py`: cold-start self-location only supports `none(warmup) -> E`.
  The first post-warmup bar should self-locate into the best current DAG node
  (`E`, `D`, `C`, `B`, or `A`) from EC/DAG evidence.
- `hypothesis.py`: `_phase_a_setup()` call is **disabled** (commented out, same as B/C gates).
  The method still reads legacy flat fields; EC Phase A candidate not yet written.
  `_phase_a_finale()` is migrated to `ec["htf_pd_objective"]`.
- `HypothesisClassifier.classify()` signature change to accept `evidence_candidates: list[dict]`
  → Final step — severs direct Layer 3 dependency, enables synthetic candidate-list testing
- Shadow Thesis consumed-event ledger for D liquidity: mark `liquidity_event_id` consumed
  when D confirms into C, fails into E, or expires; block same event from reopening D subtype

**Migration order**
1. ✅ Re-enable `hypothesis_classifier` in `dual_smc`
2. ✅ Migrate `_phase_b_initiation_setup()` → reads `ec["htf_b_initiation"]`
3. ✅ Migrate `_phase_d_setup()` → reads `ec["htf_counter_reaction"]` + `ec["ltf_counter_choch"]`
4. ✅ Migrate `_phase_c_setup()` → reads `ec["ltf_counter_story"]`
5. ✅ Migrate `_phase_b_setup()` → reads `ec["htf_b_phase_setup"]`
6. Partial: `_phase_a_finale()` reads `ec["htf_pd_objective"]`; `_phase_a_setup()` still needs EC candidate
7. ✅ Migrate `_phase_e_reaction()` → reads `ec["phase_e_context"]` + `ec["ltf_counter_choch"]`
8. Change `classify()` signature to accept `evidence_candidates: list[dict]`
9. ✅ Extract `ShadowThesis` + nest `PhaseEShadow` as `shadow_thesis.phase_e`

---

## Carry note — next session start here

**Key boundary (settled — do not re-open):**
- **Structural SB / ChoCh** (`structureEngine.py`, `last_sc.*`): LTF close-through event over ITR/LTR anchors. One SC per bar (hard cap — early return after first emit). All structural events in Phase D are LTF events. HTF provides directional reference only.
- **Orderflow MSS** (`orderflow.py`, `mss_regime = "mss_watch"`): live probe breaks the latest confirmed **HL** (bullish) or **LH** (bearish). This IS the `E.stalling → E.pullback_developing` gate AND the `D.speculation → C.pullback` gate (fresh leg required for the latter).
- **Orderflow BoS / confirmed_direction flip**: vote-based, 4+ anchor points. Later than MSS.
- `choch_watch` alias retired. `orderflow.py` emits `regime = "mss_watch"` directly.
- **Terminology ground (2026-06-08):** SB/ChoCh = structural (LTF structureEngine). BoS/MSS = orderflow (orderflow engine). Never mix the two layers in gate descriptions.
- **D.watch trigger direction (corrected 2026-06-09):** D.watch opens on the first LTF **pro-HTF** ChoCh (`phase_e.pro_attempt_seen`). The old spec said "counter-HTF ChoCh after pro attempt" — this had the trigger direction inverted. Code rewrite pending.

**Session work (2026-06-07) — design review: Phase D, C, E.HTF_reaction + docs update:**
- **E.HTF_reaction added** to Phase E shadow (4-node machine: seeking → HTF_reaction | stalling → pullback_developing).
  EC guard bug fixed: removed `new_extreme` guard from `ltf_probe_at_htf_opposing_zone` in
  `evidence_compiler.py` — the `new_extreme` guard made E.HTF_reaction unreachable.
- **C/B/A temporarily disabled** for diagnostic baseline — 3 gate blocks commented out in
  `hypothesis.py` (~line 436 C.hard_pullback, ~line 456 C.slow_pullback, ~lines 668/681 B gates).
- **Phase D simplified** to `D.watch` / `D.speculation` — old 4 sub-statuses archived in
  `docs/402-hypothesis-phD.html` §06. Full contract in AGENTS.md above.
- **Phase C simplified** to `C.pullback` / `C.pullback_weaken` — design decided, not yet in docs.
  `_phase_c_sub_status_from_current_d()` eliminated.

**Session work (2026-06-08) — Phase D design deep-dive + docs update:**
- **Terminology settled:** SB/ChoCh = LTF structureEngine (`itrSb*`). BoS/MSS = orderflow engine (anchor swings). Documented explicitly in `docs/402-hypothesis-phD.html` §01 terminology block.
- **`ltf_itr_level_run` gate dropped:** still dropped, but D.watch no longer opens
  on first LTF ChoCh alone. ITR level context remains optional quality in `choch_1`;
  the hard gate is now lineage + post-E pro-attempt separation.
- **Same-bar ChoCh shortcut archived:** structureEngine caps at 1 SC event per bar (early return in `_bos_range()`). Two ChoChs on the same bar is structurally impossible. 1-bar lag accepted.
- **D.watch opens on the first LTF pro-HTF ChoCh** (`phase_e.pro_attempt_seen = True`).
  This is the bounce initiation. No counter-ChoCh is needed to open D.watch.
- **D.watch → D.speculation: 2 paths (bounce failure):**
  - **Path A** (LTF counter-HTF ChoCh): LTF bias flips back counter-HTF after the D.watch bounce. `ltf_counter_choch_seen = True`. One LTF bias flip from D.watch.
  - **Path B** (LTF counter SB after `pullback_confirmed`): LTF bounce was quiet (ITR/SD pivot only, no SC event). `pullback_confirmed` set. Next counter-HTF SB fires → `ltf_counter_sb_seen = True`. No additional bias flip.
  - Discriminator: bounce size. Large bounce → LTF SC event (pro-HTF ChoCh = D.watch) → later counter ChoCh = Path A. Quiet bounce → ITR/SD pivot → Path B. Mutually exclusive.
  - **`_confirm_pullback_from_itr` detail:** in bearish bias fires on `pe_low_code` (ITR LOW pivot — swing low confirmed by subsequent bars with higher lows). NOT a high pivot. Fires ~2 bars after the actual swing low.
- **D.watch lock on pure impulse accepted:** if price impulses straight lower (no swing low forming, no ITR pivot), `pullback_confirmed` never fires, Path B unreachable. D.watch holds until HTF invalidation. Accepted — impulse case caught by Phase C condition, not D's responsibility.
- **`phase_d_choch_2` snapshot** gains `trigger_type: "choch" | "sb"` field so Layer 5 knows signal strength.
- **EC fact implemented: `ltf_counter_sb_seen`** — reads `last_sc` from LTF structure snapshot. Fires when `last_sc.eventAction == "structure_sb"` / `last_sc.structure_sb == True` AND `last_sc.breakDirection == counter-HTF direction`. Added to `_compile_ltf_counter_choch()` as additional debug fact alongside `ltf_counter_choch_seen`.
- **`docs/402-hypothesis-phD.html`** §01–§05 updated: both paths explicit, LTF prefix throughout, EC facts header block in §03, §05 issue cards updated (3 archived, 1 new EC fact card).

**Archived code state (2026-06-09 — superseded by current implementation above):**

Two bugs were found in replay and code changes were written:

**Bug 1 — Direction validation (code written, likely correct):**
- `_ec_candidate(snapshot, "ltf_counter_choch")` was read without checking candidate direction.
- Fix: capture `d_choch_candidate` and gate on `d_choch_candidate.get("direction") == direction` before consuming `choch_seen` / `sb_seen`.
- Applied at: D.watch entry gate and D.watch hold block.

**Bug 2 — Stale `last_sc` freshness (code written, user confirmed still broken in replay):**
- Three attempts were made, each using a different freshness floor:
  1. `source_orderflow_started_at` (orderflow `last_shift_at`) — TOO EARLY: ChoChs from E.stalling bars after the MSS started still passed.
  2. `pullback_developing_entered_at` = `cursor_time` when classifier first entered E.pullback_developing — added to `PhaseEShadow`, stored in `_phase_e_shadow_facts()`, used as gate floor. Tests pass but user confirmed D.watch STILL fires immediately in live replay.
- Superseded: root cause is now confirmed as shared orderflow/structure lineage plus
  missing post-E pro-attempt separation.

**Archived investigation note (superseded):**
- Add debug logging at the D.watch entry gate to print exact values of:
  - `_entry_choch_at` (`last_sc.eventTimestamp`)
  - `_e_entered` (`phase_e.pullback_developing_entered_at`)
  - `_entry_dir_ok` (direction check result)
  - `_entry_fresh` (freshness check result)
  - what `previous_phase` and `phase_e_shadow_node` are on the firing bar
- The issue may not be `last_sc` staleness at all — the actual event that fires D.watch may come from a different code path not yet identified.
- Consider: is the D.watch entry gate running correctly? Or is D.watch being set by something else (e.g., the D.watch hold block running with a stale `d_shadow.node`)?
- Check: does `d_shadow.node` ever get set to "D.watch" somewhere other than the entry gate?

**Current test suite: 59 passed, 31 skipped** (all D tests pass with synthetic data; real replay still broken).

- `_phase_a_setup()` call disabled (commented out) — reads legacy flat fields; Phase A EC candidate not yet written.

---

## Phase D Implementation — ready for replay validation (2026-06-08 session)

### What has been written so far

**`evidence_compiler.py` — DONE**
- `_compile_ltf_counter_choch()` updated with `ltf_counter_sb_seen` and `ltf_counter_sb_level` facts.
- Logic: `sb_seen = bool(not choch_seen AND _structure_event_action(last_sc) == "structure_sb" AND last_sc.get("breakDirection") == expected_counter_break)`
- `ltf_counter_sb_level = last_sc.get("levelPrice") if sb_seen else None`
- Added to `debug_facts` dict alongside existing `ltf_counter_choch_seen` key.
- EC tests: **42 passed, 0 failed** — no regressions.

**`hypothesis.py` — DONE for Phase D simplify**
Changes committed so far (all in one edit session, not committed to git):

1. **`PhaseDShadow` dataclass added** (inserted between `PhaseEShadow` and `ShadowThesis`):
   ```python
   @dataclass
   class PhaseDShadow:
       node: str | None = None        # "D.watch" | "D.speculation"
       consumed_leg_id: str | None = None
       choch_1: dict | None = None    # first counter ChoCh → D.watch open
       pro_attempt: dict | None = None # quality metadata accumulated in D.watch
       choch_2: dict | None = None    # second counter event → D.speculation
       def reset(self) -> None: ...   # clears all fields
   ```

2. **`ShadowThesis`** gained `phase_d: PhaseDShadow = field(default_factory=PhaseDShadow)`. Docstring updated.

3. **Epoch reset block** (near line 252): added `self._reset_phase_d_shadow()` call between `_reset_phase_e_shadow()` and `_reset_phase_b_shadow()`.

4. **`_reset_phase_d_shadow()` method** added after `_reset_phase_e_shadow()` near line 1634:
   ```python
   def _reset_phase_d_shadow(self) -> None:
       self.state.shadow_thesis.phase_d.reset()
   ```

5. **Replaced `previous_phase == "D"` hold block + old D entry gate** (old lines 401–447) with new Phase D state machine. New logic:
   - `previous_phase == "D"` block now reads `d_shadow = self.state.shadow_thesis.phase_d`
   - If `d_shadow.node == "D.watch"`:
     - Accumulates `pro_attempt` from `htf_counter_reaction` + `ltf_counter_story` EC status each bar
     - Path A (`choch_seen`): sets `d_shadow.node = "D.speculation"`, captures `choch_2` dict, emits `phase_sub_status="speculation"`
     - Path B (`sb_seen` + `pullback_confirmed`): sets `d_shadow.node = "D.speculation"`, emits `phase_sub_status="speculation"`
     - Otherwise: holds with `phase_sub_status="watch"`
   - If `d_shadow.node == "D.speculation"`:
     - Checks `ltf_counter_orderflow_mss_watch` + `leg_id != consumed_leg_id` → fires `_phase_c(..., phase_sub_status="pullback")`
     - Otherwise: holds with `phase_sub_status="speculation"`
   - If `d_shadow.node` is None: `_carry_current_hypothesis()` fallback
   - **New D.watch entry gate** (replaces old `_phase_d_setup()` + `phase_d_ready` gate):
     - Guards: `previous_phase != "B"` AND `!= "A"` AND `_previous_or_active_e(direction)` AND `phase_e_shadow_node == "E.pullback_developing"`
     - Gate: `ltf_counter_choch_seen == True`
     - Action: sets `d_shadow.node="D.watch"`, `consumed_leg_id = phase_e.source_orderflow_leg_id`, `choch_1 = {...}`, emits `phase_sub_status="watch"`

### Test situation after the code changes

**Current baseline after legacy quarantine (2026-06-08):**
- Full suite: **115 passed, 31 skipped**
- `tests/test_evidence_compiler.py`: **43 passed**
- `tests/test_hypothesis_classifier.py`: **12 passed, 31 skipped**
- `tests/test_hypothesis_phase_d_simplify.py`: **4 passed**

**Skipped intentionally:**
- B/C/A classifier tests while B/C/A gates are disabled in `hypothesis.py`
- Legacy four-node Phase D tests (`reaction_point`, `htf_pd_grab_reclaim_test`,
  `htf_eq_grab_reclaim_test`, stale `phase_d_ready` debug assertions)

**New active Phase D simplify coverage:**
- Current synthetic test still covers legacy simplified behavior:
  E pullback developing plus first LTF counter ChoCh opens D.watch
  (must be rewritten for the new post-E pro-attempt/provenance gate)
- `D.watch + second LTF counter ChoCh → D.speculation`
- `D.speculation` ignores the consumed E MSS leg and only enters `C.pullback` on a fresh MSS leg
- `D.watch + LTF counter SB after LTF pullback_confirmed → D.speculation`

**Implementation fixes found by new tests:**
- Phase E shadow now writes `source_orderflow_leg_id` / `source_orderflow_started_at`
  when entering `E.pullback_developing`
- D.watch marks that source leg consumed in both `phase_d.consumed_leg_id` and
  `phase_e.consumed_orderflow_leg_id`
- D.speculation reads EC raw key `ltf_counter_orderflow_leg_id` (not stale `orderflow_leg_id`)
- Path B reads `ltf["phase"] == "pullback_confirmed"` because EC `phase_e_context`
  does not emit a raw `pullback_confirmed` key
- Legacy `_phase_d_setup()` selector now returns a neutral disabled payload
  (`phase_d_ready == False`, `phase_d_legacy_disabled == True`) so archived
  reaction/liquidity Phase D nodes cannot be selected by paused B/C branches.
- `docs/402-hypothesis-phD.html` §03 now reflects implemented pseudocode;
  `docs/401-hypothesis-DAG.html` active graph now uses `D.watch` / `D.speculation`.
- `docs/401-hypothesis-DAG.html` leaves C/B/A visible as temporary closed phases:
  nodes are grey/dashed and have no click callbacks while their gates remain disabled.
- `docs/40x-hypothesis-migration.html` records that legacy Phase D code/tests will
  be deleted later after replay validation.

### Next step to resume

1. Implement separate LTF `orderflow_anchor_sequence` + `orderflow_probe` storage
   and keep `structure_sequence` / `structure_probe` structural-only.
2. Add EC provenance fields for Orderflow MSS and structural ChoCh so Layer 4 can
   detect same-origin MSS/ChoCh collisions.
3. Extend `PhaseEShadow` with counter-structure confirmation and pro-attempt fields.
4. Rewrite `D.watch` entry gate to require post-E pro-attempt separation and reject
   structural ChoCh provenance that matches the consumed E MSS.
5. Rewrite Phase D simplify tests away from the legacy first-counter-ChoCh
   D.watch shortcut.
6. Replay-validate EURUSD 15m/4h around `2026-01-28T15:30Z` / `16:00Z`.
7. Work on the new Phase C model after Phase D replay validation.
8. Re-enable/rewrite B/A gates/tests only when those gates are intentionally restored.

### Key references for next session

- `evidence_compiler.py` line ~1249: `_compile_ltf_counter_choch()` — EC change done
- `hypothesis.py` line ~88: `PhaseDShadow` dataclass — added
- `hypothesis.py` line ~104: `ShadowThesis.phase_d` field — added
- `hypothesis.py` line ~252: epoch reset — `_reset_phase_d_shadow()` added
- `hypothesis.py` line ~401 (new): D state machine — written, replacing old lines 401–447
- `hypothesis.py` line ~1635 (new): `_reset_phase_d_shadow()` method — added
- `tests/test_hypothesis_classifier.py`: legacy D and B/C/A tests are skipped by explicit reason constants
- `tests/test_hypothesis_phase_d_simplify.py`: new active D.watch/D.speculation tests

**Remaining open issues in `docs/402-hypothesis-phD.html` §05:**
- `ltf_counter_sb_seen` EC fact — DONE in code, direct EC boundary test added,
  and classifier Path B covered
- `D.speculation → E.stalling` SL hit: deferred Layer 4 work — tracked in `docs/40x-hypothesis-migration.html` §03

**Contracts updated (2026-06-08):**
- `.claude/layer34-contract.md` now reflects `ltf_counter_choch` as primary D gate; `htf_counter_reaction` archived note retained (still emitted for liquidity path). Contract split into `layer34-guide.md` (permanent rules) + `layer34-contract.md` (living spec) on 2026-06-09.
- `401-hypothesis-DAG.html` Mermaid still shows old 4-node D model — update after Phase D code ships.

**Next session checklist:**
1. ✅ D.watch reset bug fixed (shadow state now carries forward across E.pullback_developing re-entries)
2. **Rewrite D.watch entry gate in `hypothesis.py`**: replace `ltf_counter_choch_seen` gate with `phase_e.pro_attempt_seen` gate. Remove `_pro_attempt_after_counter`, `_entry_after_pro_attempt`, and all provenance distinctness checks from D.watch entry block (~lines 553–631). D.watch opens the moment `pro_attempt_seen` becomes True.
3. **Update `ltf_counter_choch` EC role**: only consumed by D.speculation Path A and E counter_structure tracking. Not a D.watch entry gate.
4. **Rewrite `PhaseDShadow.choch_1`**: now records the pro-HTF ChoCh (D.watch trigger), not a counter ChoCh.
5. Replay-validate: EURUSD 15m/4h, D.watch should open at 2026-01-28T22:30Z (bullish ChoCh, pro-HTF).
6. After code fix validated: start Phase C new model (`C.pullback` / `C.pullback_weaken`)
7. Re-enable B/A gates/tests only as a later separate migration step
