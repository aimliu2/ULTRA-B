# Phase D Path Samples

Fresh records only. Previous Phase D records from pre-self-relocation runs were cleared because
chunk starts could mis-relocate mid-episode and make older samples unreliable.

Generated from current-code, fresh-runtime chunk sampling after the self-relocation fix on 2026-06-27.

Source directories:

- `analysis/phase-d-recent-202601`
- `analysis/phase-d-recent-202511`
- `analysis/phase-d-recent-202510`
- `analysis/phase-d-recent-202509`
- `analysis/phase-d-recent-202507`
- `analysis/phase-d-recent-202505`
- `analysis/phase-d-recent-202504`
- `analysis/phase-d-recent-202503`
- `analysis/phase-d-recent-202501`
- `analysis/phase-d-recent-202411`
- `analysis/phase-d-recent-202409`
- `analysis/phase-d-recent-202407`
- `analysis/phase-d-recent-202405`
- `analysis/phase-d-recent-202403`
- `analysis/phase-d-recent-202401`
- `analysis/phase-d-recent-202311`

## Current Phase D Model

Only `D.watch_pathA` is active.

Pattern:

```text
EX.entry = counter SC06 iChoCh -> counter SC05 iSB
Both internal breaks are in the counter-HTF direction.
SL = phase_d_shadow_watch_range_extreme +/- configured buffer and min floor.
```

Removed legacy paths:

- `D.watch_pathSA`
- `D.watch_pathB`
- `D.watch_pathC2`

## Most Recent Accepted Phase D Trades

| Entry time | Outcome | Dir | Path | Entry | SL | TP | Risk pips | Target R | Exit time | R result | Source |
|---|---|---|---|---:|---:|---:|---:|---:|---|---:|---|
| `2025-05-22T05:45:00+00:00` | timeout | short | `D.watch_pathA` | 1.13435 | 1.13635 | 1.121355 | 20.0 | 6.497 | `2025-05-22T13:45:00+00:00` | +2.52 | `analysis/phase-d-recent-202503/layer5_trade_results.csv` |
| `2024-10-16T07:00:00+00:00` | loss | long | `D.watch_pathA` | 1.08905 | 1.08755 | 1.09174 | 15.0 | 1.793 | `2024-10-16T10:15:00+00:00` | -1.0 | `analysis/phase-d-recent-202409/layer5_trade_results.csv` |
| `2024-05-17T03:30:00+00:00` | timeout | short | `D.watch_pathA` | 1.08607 | 1.08773 | 1.0809 | 16.6 | 3.114 | `2024-05-17T11:30:00+00:00` | +0.7108 | `analysis/phase-d-recent-202403/layer5_trade_results.csv` |

## Findings

- Current Phase D samples are all `D.watch_pathA`; this matches the simplified design.
- The accepted rows include both short and long directions.
- Risk geometry is inside configured bounds after min-floor adjustment.
- The 2025-05-22 short timed out with positive R, showing the path can capture continuation toward TP even without a hard target hit inside the max hold window.
- The 2024-10-16 long is a valid path loss, not an integrity failure: trigger and SL geometry are consistent, but regime moved against the entry.
- Self-relocation was rerun chunk-by-chunk for these samples; these replace the stale pre-fix Phase D records.

## Trigger Retry Audit

The `2024-10-16T07:00:00+00:00` accepted long demonstrates the intentional
`runway_too_short` retry mechanic.

- EX.entry sequence became ready at `2024-10-16T06:15:00+00:00`.
- Trigger event: `SC05:2024-10-16T06:15:00+00:00:up:1.08924`.
- `06:15`, `06:30`, and `06:45` skipped as `runway_too_short`.
- `07:00` accepted the same `06:15` trigger after target R crossed `min_rr=1.75`.
- Current output records this as `trigger_age_bars=3`.

| Cursor | Close | SL | TP | Target R | Decision |
|---|---:|---:|---:|---:|---|
| `2024-10-16T06:15:00+00:00` | 1.08943 | 1.08793 | 1.09174 | 1.540 | skip: `runway_too_short` |
| `2024-10-16T06:30:00+00:00` | 1.08937 | 1.08787 | 1.09174 | 1.580 | skip: `runway_too_short` |
| `2024-10-16T06:45:00+00:00` | 1.08926 | 1.08776 | 1.09174 | 1.653 | skip: `runway_too_short` |
| `2024-10-16T07:00:00+00:00` | 1.08905 | 1.08755 | 1.09174 | 1.793 | accepted |
