# Self-Relocation Restart Cases

Date documented: 2026-06-21

## Existing Notes

The main self-relocation / restart hierarchy note is `docs/403-shadow-thesis.html`, especially:

- `03 Bootstrap Window`
- `04 Terrain Relocation`
- Existing handled-case reference: `2026-02-02T00:00:00+00:00` hidden bootstrap reaches `C.pullback short` in the current docs/tests.

There is also a Layer 5-specific open issue in `docs/501-entry-details.html`: “Budget ownership and self-relocation reset.”

## Case: 2023-04-28 — Epoch-Flip Self-Relocation

### Symptom

Chunk sampling that continued one runtime across chunks missed restart-only behavior. A fresh runtime
started at:

```text
2023-04-28T00:00:00+00:00
```

could classify the fresh LONG epoch as `C.pullback` or accept stale bootstrap state, then miss the
continuous-run `D.watch` episode seen at:

```text
2023-04-29T00:00:00+00:00
2023-05-01T09:30:00+00:00
2023-05-02T11:15:00+00:00
```

### Root Cause

Two restart paths could hide the correct fallback:

1. Hidden bootstrap considered any active phase a success. It did not validate that the classifier
   state matched the current HTF terrain direction and epoch.
2. If bootstrap failed, terrain relocation preferred `C.pullback` whenever HTF terrain was
   `pullback_confirmed`. In a fresh E cycle after an epoch flip, `pullback_confirmed` can be early
   E pullback terrain, not established C provenance.

### Fixed Behavior

Restart recovery now treats this as a conservative E relocation when no valid journal exists:

```text
recovery_mode = terrain_relocation
bootstrap_success = False
relocation_selected_node = E.seeking
```

From there, the runtime advances organically:

```text
2023-04-28T00:00:00+00:00 -> E.stalling / E.seeking side of E
2023-04-29T00:00:00+00:00 -> D.watch
2023-05-01T09:30:00+00:00 -> D.watch
2023-05-02T11:15:00+00:00 -> D.watch
```

### Implementation Notes

- `_hidden_bootstrap_succeeded()` validates active phase, `active_phase_e_direction`, and
  `htf_pd_epoch_id` against current terrain before accepting bootstrap.
- After failed bootstrap, only the Layer 4 classifier is reset before terrain relocation. Layer 3
  structure, zones, orderflow, liquidity, and EC terrain stay warmed.
- `_relocate_hypothesis_from_terrain()` no longer relocates into `C.pullback`; `open` and
  `pullback_confirmed` terrain both relocate to safe `E.seeking`.
- Journal persistence is opt-in via environment-local config. Auto-save runs after visible
  classification only when `persist_shadow_state` is enabled, and journal writes are atomic.

## Case: 2021-01-27/28/29 — X.thesis_over Hard Gate

### Symptom

Initial symptom found during cold-start comparison:

```text
2021-01-28T00:00:00+00:00
2021-01-29T00:00:00+00:00
```

landed in:

```text
phase = X
phase_sub_status = X.none
direction = none
```

At first this looked wrong relative to the continuous run, because the continuous run showed `D.watch` at the same timestamps. Deeper inspection showed the continuous run was wrong: it re-entered `D.watch` after `X.thesis_over`.

### Root Cause

Continuous trace before the fix:

```text
2021-01-27T00:00:00+00:00 -> A.watch_weaken short
2021-01-27T15:45:00+00:00 -> A.watch short
2021-01-27T16:45:00+00:00 -> X.thesis_over
2021-01-27T17:00:00+00:00 -> D.watch   BUG
2021-01-28T00:00:00+00:00 -> D.watch   BUG
2021-01-29T08:45:00+00:00 -> D.watch_pathB candidate, skipped late_entry_risk_too_wide   BUG
```

`X.thesis_over` was emitted correctly at `2021-01-27T16:45:00+00:00`, but the hold guard lived too late in `HypothesisClassifier.classify()`. Stale same-epoch Phase E shadow state (`E.pullback_developing` / zone-reaction state) could reach the D gates before the `X.thesis_over` carry rule ran.

This violated the rule: after `X.thesis_over`, the only allowed same-epoch escape is a fresh `E.seeking` context. Regular `D.watch`, express `D.watch`, `C`, `B`, and `A` are all blocked.

### Fixed Behavior

After the fix, continuous run carries thesis-over:

```text
2021-01-27T16:45:00+00:00 -> X.thesis_over
2021-01-27T17:00:00+00:00 -> X.thesis_over
2021-01-28T00:00:00+00:00 -> X.thesis_over
2021-01-29T08:45:00+00:00 -> X.thesis_over
```

No `D.watch_pathB` decision should exist at `2021-01-29T08:45:00+00:00` after the fix.

### Cold-Start Diagnostics

Cold start diagnostics at `2021-01-28T00:00:00+00:00`:

```text
recovery_mode = cold_start_no_context
restore_reject_reason = None
bootstrap_start_time = 2021-01-22T21:00:00+00:00
bootstrap_end_time = 2021-01-27T23:45:00+00:00
bootstrap_bars_used = 300
bootstrap_success = False
relocation_attempted = True
relocation_selected_node = None
```

Cold start diagnostics at `2021-01-29T00:00:00+00:00`:

```text
recovery_mode = cold_start_no_context
restore_reject_reason = None
bootstrap_start_time = 2021-01-25T21:00:00+00:00
bootstrap_end_time = 2021-01-28T23:45:00+00:00
bootstrap_bars_used = 300
bootstrap_success = False
relocation_attempted = True
relocation_selected_node = None
```

Relocation rejected all candidates:

```text
A = a_relocation_requires_reconstructable_b_and_a_anchors
B = b_relocation_requires_reconstructable_commitment_extreme
D = d_relocation_requires_reconstructable_watch_provenance
C = phase_c_story_not_ready
E = htf_phase_not_open
```

The first visible bars after startup remain `X.none`. This is still not ideal state parity, but it is no longer evidence that continuous `D.watch` was correct. The correct continuous state after the hard-gate fix is `X.thesis_over`.

Cold start at `2021-01-27T00:00:00+00:00` does not fail to `X.none`; it relocates to `C.pullback`:

```text
recovery_mode = terrain_relocation
bootstrap_start_time = 2021-01-21T21:00:00+00:00
bootstrap_end_time = 2021-01-26T23:45:00+00:00
bootstrap_success = False
relocation_selected_node = C.pullback
```

However this is still not exact state parity. Continuous runtime at `2021-01-27T00:00:00+00:00` is `A.watch_weaken short`, while cold-start relocation downgrades to `C.pullback long armed`. In a probe starting at `2021-01-27T00:00:00+00:00`, runtime stayed in `C.pullback_weaken long` through `2021-01-29T08:45:00+00:00`. That path still differs from continuous runtime, but it no longer creates the invalid Path B after thesis-over.

### Consequence

Before fix:

```text
2021-01-29T08:45:00+00:00 -> D.watch_pathB candidate, skipped late_entry_risk_too_wide
```

After fix:

```text
2021-01-29T08:45:00+00:00 -> X.thesis_over, no Path B decision
```

Cold starts at `2021-01-28T00:00:00+00:00` or `2021-01-29T00:00:00+00:00` still fall to:

```text
X.none
```

Cold start at `2021-01-27T00:00:00+00:00` still relocates to:

```text
C.pullback / C.pullback_weaken
```

### Remaining Open Design Question

Should restart recovery support exact A/X thesis-over parity?

Possible directions:

1. Persist `PhaseAShadow` / `X.thesis_over` state in the Shadow Thesis journal and require it for live restart.
2. Add conservative relocation into `X.thesis_over` when terrain proves the A objective maturity threshold has already been reached.
3. Keep current cold-start behavior and accept that without a saved journal, post-cycle exact state may be downgraded to `X.none` or C terrain.

## Case: 2024-05-10T00:00:00Z — Cold-Start Relocation Failure

**Symptom**: Cold start at `2024-05-10T00:00:00+00:00` could not relocate itself. Relocation failed — runtime fell to `X.none` or could not reconstruct a valid node from terrain.

**Context**: The continuous run at this timestamp was in a Phase D episode that produced a `D.watch_pathC2` SHORT entry at `2024-05-10T03:45:00Z`. The underlying market context was a bullish trend continuation with a shallow pullback — terrain that may not provide enough structural evidence for relocation into `C.pullback` or higher.

**Status**: Not yet diagnosed to root cause. Likely relocation candidates (C/E/D) were all rejected for the same reasons as the 2021-01-28 case — no reconstructable watch provenance, no C story ready, HTF phase not open. Needs a headless probe with relocation diagnostics printed to confirm.

**Reference trade**: `2024-05-10T03:45:00Z` `D.watch_pathC2` SHORT timeout `-0.133R` — see `analysis/trades/note_on_trend_continue.md`.

---

## Case: 2026-02-02T00:00:00Z — Retest Checkpoint

Also retest:

```text
2026-02-02T00:00:00+00:00
```

This one is likely already handled. The current restart hierarchy docs/tests record it as a successful hidden Layer 4 bootstrap case that lands in `C.pullback short` before the first visible bar. Keep it on the retest list as a known-good comparison when debugging the `2021-01-29T00:00:00+00:00` D.watch relocation gap.
