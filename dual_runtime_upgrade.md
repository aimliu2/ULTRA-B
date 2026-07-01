# Dual Runtime Upgrade Plan

## Summary

The current `DualSmcRuntime` treats `start_time` as the first visible replay bar, then
uses a mixed startup window before it:

- LTF gets roughly `window_bars` worth of startup context.
- HTF Layer 3 only gets `warmup_bars` before the Layer 4 bootstrap point.
- Layer 4 then classifies from whatever HTF terrain Layer 3 reconstructed.

This caused the `2025-10-09T00:00:00Z` cold replay mismatch: the runtime missed the
older 4H anchor from `2025-07-31T00:00:00Z`, reconstructed a bearish Oct 8 HTF epoch,
and therefore classified D/C instead of the Phase A path seen in longer continuous
runs.

The remake should make `start_time` mean **right-edge probe time**:

```text
requested/probe time T = current evaluation time

LTF history = last N LTF bars ending at T
HTF history = last N HTF bars ending at or before T

Layer 3 rebuilds by replaying both histories forward.
Layer 4 bootstraps over the rebuilt LTF timeline.
The first user-facing snapshot is at T.
```

Use a staged rollout:

1. **Right-edge rebuild mode** becomes the default runtime startup mode.
2. **Legacy startup mode** remains available for audit/comparison.
3. **Layer 3 persistence** — deferred. Not needed for chunk sampling or replayer
   agreement. Live restarts fall back to right-edge rebuild. If the window cannot
   reconstruct the epoch anchor (anchor age > `window_bars` HTF bars), terrain
   relocation applies and the system forms a new narrative. This is correct
   behavior: a downtime long enough to lose the epoch anchor means the old
   thesis should not be blindly restored.

## Design Decisions (from architecture review 2026-07-01)

### `window_bars` dual responsibility
`window_bars=500` carries two distinct responsibilities that are now explicitly aligned:

1. **Startup history depth** — how far back to feed bars during Layer 3 warmup
   (both LTF and HTF). Before this upgrade, LTF used `window_bars` but HTF used
   `warmup_bars` (200). After: both use `window_bars`.
2. **Attention/eviction window** — Layer 3's internal memory bound. Structures
   older than `window_bars` bars are evicted from active state.

Aligning startup depth = eviction window = `window_bars` is the core invariant.
The "mystic eye problem" (system remembering anchors from years ago) does not exist
because eviction runs during warmup. State at the probe point contains only the last
`window_bars` bars of structure.

### `warmup_bars` eliminated as startup depth
`warmup_bars=200` as a "how far back to start Layer 3" parameter is dead config after
the upgrade. Both `_warm_lower_engines()` and `_warm_higher_engines()` switch to
`window_bars`. The implicit convergence meaning (Layer 3 needs ~200 bars to stabilize
before EC output is trustworthy) remains but does not need explicit configuration.

### `hypothesis_bootstrap_bars` dissolved
`hypothesis_bootstrap_bars = window_bars - warmup_bars = 300` disappears. Layer 4
now bootstraps over the full `window_bars` warmup replay, not just the tail remainder.

### Layer 3 persistence deferred
Layer 3 terrain is always rebuilt from scratch. The correct separation:

- **Layer 3 terrain** = reconstructable from bars → always rebuild, never persist
- **Layer 4 commitment** = not reconstructable from terrain alone → persist as
  Shadow Thesis journal (already done)

Phase 2 (Layer 3 persistence) is deferred because:
- Chunk sampling does not have a "live terrain state" to restore from anyway
- Right-edge rebuild with `window_bars` depth fixes chunk-vs-replayer disagreement
- Adding saved Layer 3 state introduces stale-restore risk (valid schema, wrong
  terrain due to parquet backfill) that requires bar-level checksums to guard safely
- Live deployment: downtime < ~83 days (500 × 4H) → right-edge rebuild correct;
  downtime > ~83 days → self-relocation is the correct response, not thesis restore

### Chunk sampling guarantee
Null case measurements are only trustworthy when the chunk anchor is within the
window guarantee. See `.claude/plans/sampling_method.md` for the full design.

### Live deployment policy
- Downtime < `window_bars` HTF bars (~83 days for 15m/4H): right-edge rebuild
  reconstructs the epoch anchor; Shadow Thesis journal restores the thesis.
- Downtime > `window_bars` HTF bars: epoch anchor is outside the window; epoch
  mismatch fires; terrain relocation resets to E.seeking. The system forms a new
  narrative. This is correct — a thesis that old should not be blindly restored.

## Current Code Boundaries

Main runtime:

- `src/ultrab/runtime/dual_smc.py`
  - Loads full LTF/HTF parquet data.
  - Resolves `lower_start_index` from `start_time`.
  - Resolves `higher_start_index` at the same timestamp.
  - `_init_engines()` tries saved Shadow Thesis, then hidden Layer 4 bootstrap, then
    terrain relocation.
  - `_warm_layer3_to_lower_index()` warms lower and higher engines, but higher warmup
    uses `warmup_bars`, not `window_bars`.

Replayer wrapper:

- `src/ultrab/replayer/replay_session.py`
  - `DualReplaySession` composes `DualSmcRuntime`.
  - `snapshot()` replaces runtime bar payloads with visible chart windows.
  - `rewind_one()` and `rewind_to_time()` call `_rebuild_to_lower_index()`, which
    currently resets the whole runtime and steps forward from `lower_start_index`.

Backtest entry:

- `src/ultrab/entry/run_layer5_backtest.py`
  - Constructs `DualSmcRuntime` directly.
  - Assumes `start_time` is the first replay/backtest cursor, then steps forward.

Tests to preserve/adjust:

- `tests/test_headless_runtime_reuse.py`
  - Proves `DualReplaySession` and `DualSmcRuntime` share state.
  - Verifies rewind rebuilds stateful hypothesis memory.
- `tests/test_hypothesis_restart_hierarchy.py`
  - Verifies saved Shadow Thesis restore, hidden bootstrap, terrain relocation.

## Concerns / Risk Register

These concerns must be resolved before implementation is declared complete.

### Semantic Risks

- `start_time` currently means "first visible replay bar" in practice. The remake changes
  it to "right-edge probe/evaluation time" in default mode. Any caller that expects to
  start scanning forward from `start_time` must be reviewed.
- `window_bars` currently behaves like an LTF-centered startup budget. The remake makes
  it a per-timeframe historical context budget. This changes HTF terrain and may change
  historical sample results.
- `warmup_bars` is overloaded today. It is both a Layer 3 convergence guard and part of
  the Layer 4 bootstrap arithmetic. The remake must separate these meanings or the same
  bug can reappear under new names.
- Bar 0 of a fetched historical window is not truth. The system must document that early
  reconstructed bars are warmup-only and that only the right edge is the evaluation target.

### Runtime / State Risks

- Layer 3 engines are stateful and path-dependent. Replaying 500 bars may still be
  insufficient for some HTF structures; right-edge rebuild improves the situation but does
  not mathematically guarantee perfect terrain.
- Persisting Layer 3 state is broader than the current Shadow Thesis journal. Structure,
  SD zones, liquidity, orderflow, partial HTF bar, and indices all need compatible
  export/import contracts.
- Partial HTF bar handling is a high-risk boundary. A persisted or rebuilt runtime must
  agree on whether the current HTF bar is closed or partial at the LTF cursor.
- Saved state can become stale across data revisions, parquet backfills, config changes,
  schema changes, and timeframe/combo changes. Restore rejection must be strict and noisy.
- Atomic saves are mandatory. A partial Layer 3 journal is worse than no journal because it
  can make terrain look valid while its dependent stores are stale.

### Replayer / UI Risks

- Rewind currently resets and steps from `lower_start_index`. In right-edge mode that index
  is the probe/right edge, so rewind into historical context will break unless it rebuilds
  from `history_start_index`.
- Hidden bootstrap events must not leak into `visible_events`; otherwise rewind and replay
  logs will show events that happened before the user-visible cursor.
- Chart windows, runtime classifier payloads, and visible replay bars have different
  purposes. The implementation must avoid treating `snapshot["bars"]` as the Layer 3
  history source.
- Metadata will be misleading unless it distinguishes `history_start_time`,
  `visible_start_time`, `probe_time`, and `window_start_time`.
- Browser replay controls need clear behavior when rewinding before the available history
  window: reject or clamp with diagnostics, never silently rebuild from incomplete context.

### Backtest / Sample Risks

- Existing sample directories may no longer be comparable after right-edge rebuild becomes
  default. Sample notes must record `startup_mode`.
- `run_layer5_backtest.py` may need separate semantics for "probe this right edge" vs
  "scan forward from this anchor." Do not let a backtest chunk accidentally skip the bars it
  was supposed to scan.
- Phase A/B/D sample counts can change after HTF terrain becomes more stable. This should be
  treated as expected migration fallout, not automatically as a Layer 5 regression.
- Legacy mode is required during audit so old samples can be reproduced and compared against
  new right-edge results.

### Test / Rollout Risks

- A green `tests/test_headless_runtime_reuse.py` only proves replayer/runtime parity. It does
  not prove the reconstructed terrain is historically correct.
- The Oct 9 Phase A case must become a fixed regression because it exercises the exact HTF
  anchor-loss failure.
- Rewind tests must compare hypothesis projections before and after rebuild, not just cursor
  indices.
- Deployment should roll out in stages: right-edge rebuild first, then full Layer 3
  persistence. Combining both in one implementation would make failures hard to diagnose.

## Target Semantics

### Startup Modes

Add `replay.hypothesis.startup_mode`:

```yaml
replay:
  hypothesis:
    startup_mode: right_edge_rebuild  # default
```

Supported values:

- `right_edge_rebuild`
  - Default.
  - Treat `start_time` as the right-edge probe/evaluation time.
  - Rebuild historical context ending at `start_time`.
- `legacy_window_remainder`
  - Current behavior for audit.
  - Keep old `warmup_bars + hypothesis_bootstrap_bars` mechanics.

### Index Terms

Rename the mental model in code; actual symbol names can vary, but the behavior should
be explicit:

- `probe_lower_index`
  - First visible/current evaluation bar resolved from `start_time`.
- `lower_history_start_index`
  - `probe_lower_index - lower_config.window_bars + 1`, bounded at 0.
- `higher_probe_index`
  - Last closed HTF bar at or before `probe_time`.
- `higher_history_start_index`
  - `higher_probe_index - higher_config.window_bars + 1`, bounded at 0.
- `visible_start_index`
  - In replayer mode, initially equal to `probe_lower_index`.
  - In backtest/chunk mode, may be the first bar after bootstrap if the command is
    intentionally scanning forward.

### Layer 3 Rebuild

For `right_edge_rebuild`:

1. Build engines fresh.
2. Process HTF bars from `higher_history_start_index` through the HTF bar at or before
   `probe_time`.
3. Process LTF bars from `lower_history_start_index` through `probe_lower_index`.
4. Keep partial HTF state aligned to `probe_time`.
5. Do not classify user-visible snapshots until the bootstrap phase says the current
   state is ready.

Important: the first fetched bar is allowed to be inaccurate. The contract is that the
runtime converges by the right edge if the configured history depth is sufficient.

### Layer 4 Bootstrap

For `right_edge_rebuild`:

- Run EC + hypothesis classification during the historical LTF replay.
- Keep the first N bars as terrain-only if needed, but do not let this shorten HTF
  history.
- Do not use `window_bars - warmup_bars` as the only classifier bootstrap range unless
  explicitly configured.
- Record bootstrap diagnostics:
  - `startup_mode`
  - `probe_time`
  - `lower_history_start_time`
  - `higher_history_start_time`
  - `layer4_bootstrap_start_time`
  - `layer4_bootstrap_end_time`
  - `restored_layer3_state`
  - `restored_shadow_state`

### Layer 4 Bootstrap (continued)

- `X.warm_up` is fully absorbed into the hidden 500-bar replay. It never appears in
  user-visible output after the upgrade. No changes to `hypothesis.py` required.
- `hypothesis_bootstrap_bars`, `_hypothesis_bootstrap_start_index()`, and
  `_resolve_hypothesis_bootstrap_bars()` are dead code after Phase 1. Remove them.
- `_run_hidden_layer4_bootstrap()` is restructured to replay from `history_start_index`
  to `probe_lower_index` (500 bars) instead of from `bootstrap_start_index` (300 bars).
- Layer 4 is driven via `_process_lower_step()` (live mechanism, interleaves HTF advances)
  not via pre-warmed Layer 3 snapshot. HTF/LTF interleaving is preserved.
- Early cold-start noise in the first ~50–100 warmup bars is acceptable. Convergence
  contract applies at the probe edge, not at bar 0.

### Layer 5 Impact

- `layer5.py` (`EntryPermissionEngine`) is unchanged. It consumes hypothesis snapshots
  and is unaware of startup mode.
- `run_layer5_backtest.py` needs one addition: `--startup-mode` CLI arg threaded through
  to the runtime. Record `startup_mode` in output rows for audit.
- Chunk sampling use case (`start_time=T`, `max_steps=200`) and continuous scan use case
  (`start_time=earliest_bar`, unbounded) are the same loop — distinguished only by
  `max_steps`. No structural change required.
- Layer 5 budget/episode state is fresh per chunk (new `EntryPermissionEngine` per run).
  No change.

### Layer 6 and Sampling Module

- `layer6.py` (`TradeAnalyzer`, `TradeResult`) is unchanged by the runtime upgrade.
- `SampleRecord` schema (see `.claude/plans/sampling_method.md`) extends `TradeResult`
  with terrain-provenance fields: `anchor_time`, `reconstruction_ok`,
  `eligible_htf_age_bars`, `eligible_ltf_age_bars`, `startup_mode`. These live in Layer 6.
- A `ChunkAnalyzer` (extends `TradeAnalyzer`) handles bounded forward scan from a known
  probe anchor. Layer 6 owns it.
- The sampling method itself is an independent module. Dependency direction:

  ```
  sampling_module
    → DualSmcRuntime  (terrain warmup + snapshot)
    → ChunkAnalyzer   (Layer 6, forward scan + outcome)
    → SampleRecord    (Layer 6 schema)

  Layer 6 has no dependency on the sampling module.
  ```

- Survey pass, eligibility filter, sampling strategy, cross-verification, and chunk
  orchestration all live in the sampling module (not in Layer 6).
- Layer 6 stays unit-testable in isolation with a mock runtime.

### Layer 3 Persistence

Deployment must support persisted Layer 3 terrain state.

Persist atomically alongside or near the existing Shadow Thesis journal:

- symbol, combo, lower_tf, higher_tf
- schema version
- saved timestamp and current indices
- lower/higher structure engine state
- lower/higher SD zone state
- liquidity state
- lower orderflow state
- partial HTF bar state
- existing Shadow Thesis classifier state

Restore order:

1. Try persisted Layer 3 + Shadow Thesis state.
2. Validate schema, symbol/combo/timeframes, index monotonicity, and terrain identity.
3. If valid, resume and step forward from saved timestamp to `probe_time`.
4. If invalid or unavailable, fall back to `right_edge_rebuild`.
5. If right-edge rebuild cannot reconstruct a valid hypothesis, use existing terrain
   relocation diagnostics instead of guessing A/B anchors.

This keeps live deployment stronger than cold probes while preserving a safe fallback.

## Replayer / Rewind Impact Review

The replayer will break or become misleading if rewind keeps the current reset model
unchanged.

Current rewind behavior:

```text
DualReplaySession.rewind_to_time(target)
  -> _rebuild_to_lower_index(target_index)
  -> reset runtime
  -> step from lower_start_index to target_index
```

Why this is fragile after the remake:

- In right-edge mode, `lower_start_index` is the probe/current right edge.
- A target before that right edge is inside the historical rebuild window, not inside
  the visible stepping range.
- Resetting and stepping only from the right edge cannot rebuild a target that is
  earlier than the right edge.
- Visible event replay would also be wrong if hidden bootstrap events are mixed with
  user-visible events.

Required replayer changes:

1. Split runtime cursors:
   - `history_start_index`
   - `visible_start_index`
   - `current_lower_index`
   - `probe_lower_index`
2. Let `DualReplaySession` rewind to any target inside the visible window by asking
   runtime to rebuild from `history_start_index`, not from `visible_start_index`.
3. Keep hidden bootstrap events out of `visible_events`.
4. Make chart windows derive from visible cursor state, not from runtime startup
   diagnostics.
5. Update metadata:
   - `history_start_time`
   - `visible_start_time`
   - `probe_time`
   - `window_start_time`
   - `window_end_time`
   - `startup_mode`

Recommended behavior:

- Initial replayer snapshot at `start_time` should show historical bars ending at
  `start_time`, with the cursor at `start_time`.
- Step forward should behave as today.
- Rewind backward should rebuild from `history_start_index` to the requested target and
  then restore only visible events up to that target.
- Rewind to a time before `probe_lower_index` (`start_time`): clamp with diagnostics.
  Rule: **the user can never rewind past `start_time`**. The clamp already exists in
  `rebuild_to_lower_index()` via `bounded_index < self.lower_start_index`; after upgrade
  replace the silent no-op with an explicit diagnostic.
- Rewind to a time before `history_start_index` (before warmup window): reject with error.
  This is a different boundary from `start_time` — it means the history data itself is
  insufficient. Return a clear error, not a clamp.

### Warmup Event Suppression

The unified warmup loop inside `_init_engines()` uses `_process_lower_step()`, which
emits events. These events must be explicitly discarded — never appended to
`visible_events`. The warmup loop must do:

```python
_events = self._process_lower_step(row)  # drive engine state forward
# discard _events — warmup events are not user-visible
```

Only events from the forward-step phase (probe onwards) reach `visible_events`.

### WarmupTrace — Replayer Helper

**Not a Layer 7. Not part of the dataflow.** A lightweight observability module for the
replayer only.

**Problem it solves:** after the upgrade, pre-probe bars appear on the chart as background
context. The 500-bar warmup drove Layer 3 and Layer 4 through real hypothesis transitions
(E.seeking → D.watch → C.pullback, self-relocation, etc.) but those are invisible. The
user sees the probe-edge state (e.g. `C.pullback`) with no path explaining how the system
arrived there.

**What WarmupTrace collects:** during `_init_engines()` warmup, per bar:
```python
{
    "bar_time":         ...,
    "phase":            ...,
    "phase_sub_status": ...,
    "direction":        ...,
    "recovery_mode":    ...   # non-null only on relocation bars
}
```
Collected into `self.warmup_trace: list[dict]` — a side-channel alongside the existing
warmup loop. No re-run, no extra processing cost.

**Config-gated:** `replay.hypothesis.trace_warmup: true` (off by default for headless
runtime and chunk sampling; on for the replayer UI).

**What the replayer renders from WarmupTrace:**

- **Phase band overlay**: dimmed colored background on pre-probe bars showing the
  hypothesis phase at each warmup bar. Visually distinct from post-probe events
  (lower opacity, no arrows or markers).
- **Layer 3 / Layer 4 event pre-feed**: structural events and hypothesis transitions
  from the warmup are drawn in the L3/L4 sections of the UI so the user can see what
  the system was reading during warmup.
- **Probe-edge annotation**: on the probe bar, a callout showing the startup outcome
  e.g. "self-relocated → E.seeking" or "bootstrap succeeded → C.pullback short".

**Dependency direction:**
```
WarmupTrace module
  ← DualSmcRuntime (collects trace during _init_engines)
  → Replayer UI   (renders phase band, annotations, L3/L4 pre-feed)

Core pipeline (Layer 1–6) has no dependency on WarmupTrace.
```

**Scope boundary:** WarmupTrace is replayer-only. The headless runtime, backtest runner,
and sampling module do not consume it. It is never an input to Layer 4 or Layer 5.

## Implementation Steps

### Phase 1: Right-Edge Rebuild

1. Add startup mode config and runtime metadata.
2. Refactor `DualSmcRuntime` startup indices:
   - keep legacy path unchanged behind `legacy_window_remainder`;
   - add right-edge history windows per timeframe.
3. Add a unified historical replay method that can:
   - process Layer 3 only;
   - process Layer 3 + EC + Layer 4;
   - suppress user-visible events during hidden startup.
4. Make HTF history use `higher_config.window_bars`, not `warmup_bars`.
5. Preserve `classify_snapshot()` idempotence at the current cursor.
6. Update `DualReplaySession` metadata, visible bars, and rewind rebuild path.
7. Keep `run_layer5_backtest.py` compatible:
   - default uses right-edge rebuild;
   - legacy mode remains available for old sample comparison.

**Performance note (Phase 1):** Replace `iterrows()` with `itertuples()` in `_warm_lower_engines`,
`_warm_higher_engines`, and `_warm_liquidity_lower_interactions`. `iterrows()` allocates a
new `pd.Series` per bar; `itertuples()` avoids that overhead. The gain is modest (~3–5×
on row access) but costless to apply. Not a substitute for the unified replay loop; just
removes unnecessary pandas overhead inside it.

### Phase 2: Layer 3 Persistence

1. Add explicit export/import state methods to Layer 3 engines.
2. Add combined runtime state save/restore:
   - Layer 3 terrain state;
   - partial HTF state;
   - Shadow Thesis classifier state.
3. Extend restart diagnostics to distinguish:
   - `resume_full_runtime_state`
   - `resume_shadow_only`
   - `right_edge_rebuild`
   - `terrain_relocation`
4. Keep atomic write via temp + replace.
5. Reject incompatible persisted state before mutating runtime engines.

### Phase 3: Documentation and Migration

1. Update `docs/403-shadow-thesis.html` to replace the old `window_bars - warmup_bars`
   mental model.
2. Update replay config comments to state that `start_time` is the right-edge probe
   time in default mode.
3. Add `legacy_window_remainder` examples only for audit/reproduction.
4. Update sample-generation notes so chunk anchors describe their startup mode.

## Test Plan

Regression tests:

- `2025-10-09T00:00:00Z` right-edge rebuild with 500 HTF bars preserves the July 31
  HTF anchor and reproduces the Phase A path by `2025-10-09T12:30:00Z`.
- `legacy_window_remainder` reproduces current D/C behavior for the same cold start.

Runtime tests:

- Runtime metadata reports correct LTF and HTF history windows.
- HTF Layer 3 starts from `higher_probe_index - window_bars + 1`.
- `classify_snapshot()` remains idempotent.
- `DualReplaySession` and `DualSmcRuntime` projections remain identical.

Replayer tests:

- Initial snapshot at `start_time` includes historical bars ending at `start_time`.
- Step forward from `start_time` still reveals one LTF bar at a time.
- Rewind to an already visible target rebuilds the same hypothesis projection.
- Rewind before `history_start_index` is rejected or clamped with diagnostics.
- Hidden bootstrap events do not appear in visible event logs.

Persistence tests:

- Valid full runtime state resumes and matches continuous runtime projection.
- Schema mismatch, epoch mismatch, symbol mismatch, missing engine state, and corrupt
  JSON fall back to right-edge rebuild.
- Atomic write leaves no partial journal after save.

## Acceptance Criteria

- Cold probe at `2025-10-09T00:00:00Z` no longer creates a false HTF terrain solely
  because HTF used only `warmup_bars`.
- Replayer, headless runtime, and backtest all use the same runtime startup semantics.
- Rewind remains deterministic after the startup remake.
- Deployment can prefer persisted Layer 3 state, with right-edge rebuild as fallback.
- Legacy mode can still reproduce old samples during audit.
