# Phase A Trade Samples

Generated from current-code fresh-runtime chunk reruns after the Phase A entry engine was
implemented.

Fresh source directories searched:

- `analysis/resample-a-202301`
- `analysis/resample-a-202303`
- `analysis/resample-a-202305`
- `analysis/resample-a-202307`
- `analysis/resample-a-202401`
- `analysis/resample-a-202403`
- `analysis/resample-a-202405`
- `analysis/resample-a-202407`
- `analysis/resample-a-202501`
- `analysis/resample-a-202503`
- `analysis/resample-a-202505`
- `analysis/resample-a-202507`
- `analysis/resample-a-202509`

Each chunk used:

```text
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m ultrab.entry.run_layer5_backtest \
  --start-time <anchor> --max-steps 5000 --output-dir analysis/resample-a-<anchor>
```

## Current Phase A Model

Active paths:

```text
A.watch_pathA = OTE.entry, counter SC06 iChoCh -> pro SC06 iChoCh while A.watch holds
A.watch_weaken_ex = EX.entry, pro SC06 iChoCh -> pro SC05 iSB while A.watch_weaken holds
```

SL/TP:

```text
A.watch_pathA SL = phase_a_shadow_commitment_extreme_level +/- configured buffer and min floor
A.watch_weaken_ex SL = phase_a_shadow_watch_range_extreme +/- configured buffer and min floor
TP = Phase A objective-progress level, capped at 2.5R
```

## Most Recent Accepted Phase A OTE.entry Trades

| Entry time | Outcome | Dir | Path | Entry | SL | TP | Risk pips | Target R | Exit time | R result | Trigger | Source |
|---|---|---|---|---:|---:|---:|---:|---:|---|---:|---|---|
| `2025-10-09T12:30:00+00:00` | loss | long | `A.watch_pathA` | 1.16210 | 1.15960 | 1.16835 | 25.0 | 2.5 | `2025-10-09T16:45:00+00:00` | -1.0 | `SC06:2025-10-09T12:30:00+00:00:up:1.16151` | `analysis/resample-a-202509/layer5_trade_results.csv` |
| `2025-09-02T05:30:00+00:00` | win | short | `A.watch_pathA` | 1.16946 | 1.17178 | 1.16366 | 23.2 | 2.5 | `2025-09-02T11:15:00+00:00` | +2.5 | `SC06:2025-09-02T05:30:00+00:00:down:1.17063` | `analysis/resample-a-202509/layer5_trade_results.csv` |
| `2025-09-02T03:15:00+00:00` | win | short | `A.watch_pathA` | 1.17061 | 1.17211 | 1.16686 | 15.0 | 2.5 | `2025-09-02T10:45:00+00:00` | +2.5 | `SC06:2025-09-02T03:15:00+00:00:down:1.17063` | `analysis/resample-a-202509/layer5_trade_results.csv` |

## Accepted Phase A EX.entry Trades Found

| Entry time | Outcome | Dir | Path | Entry | SL | TP | Risk pips | Target R | Exit time | R result | Trigger | Trigger age bars | Source |
|---|---|---|---|---:|---:|---:|---:|---:|---|---:|---|---:|---|
| `2025-10-20T09:15:00+00:00` | loss | long | `A.watch_weaken_ex` | 1.16627 | 1.16471 | 1.17017 | 15.6 | 2.5 | `2025-10-20T14:45:00+00:00` | -1.0 | `SC05:2025-10-20T07:45:00+00:00:up:1.16693` | 6 | `analysis/resample-a-202509/layer5_trade_results.csv` |
| `2025-05-08T18:00:00+00:00` | loss | long | `A.watch_weaken_ex` | 1.12777 | 1.12627 | 1.13152 | 15.0 | 2.5 | `2025-05-08T18:45:00+00:00` | -1.0 | `SC05:2025-05-08T15:15:00+00:00:up:1.12992` | 11 | `analysis/resample-a-202503/layer5_trade_results.csv` |
| `2023-08-11T13:30:00+00:00` | win | short | `A.watch_weaken_ex` | 1.09914 | 1.10064 | 1.09539 | 15.0 | 2.5 | `2023-08-11T18:45:00+00:00` | +2.5 | `SC05:2023-08-11T12:45:00+00:00:down:1.09834` | 3 | `analysis/resample-a-202307/layer5_trade_results.csv` |

## Supporting Fields

| Entry time | Path | Evidence kind | Evidence presented at | Phase episode id | Stale marked |
|---|---|---|---|---|---|
| `2025-10-09T12:30:00+00:00` | `A.watch_pathA` | `a_watch_commitment` | `2025-10-08T16:15:00+00:00` | `6b0aa402fa784c8c9afb9335056e2ca0` | false |
| `2025-09-02T05:30:00+00:00` | `A.watch_pathA` | `a_watch_commitment` | `2025-09-01T18:45:00+00:00` | `30dd8280c08b40a7b2fb773f317db165` | false |
| `2025-09-02T03:15:00+00:00` | `A.watch_pathA` | `a_watch_commitment` | `2025-09-01T18:45:00+00:00` | `30dd8280c08b40a7b2fb773f317db165` | false |
| `2025-10-20T09:15:00+00:00` | `A.watch_weaken_ex` | `a_watch_weaken_ex` | `2025-10-17T13:30:00+00:00` | `904c708d2c024c50ad023e8f4adca2b4` | false |
| `2025-05-08T18:00:00+00:00` | `A.watch_weaken_ex` | `a_watch_weaken_ex` | `2025-05-07T01:15:00+00:00` | `60df783cb88f4cfeb186817f23bdfcb6` | false |
| `2023-08-11T13:30:00+00:00` | `A.watch_weaken_ex` | `a_watch_weaken_ex` | `2023-08-11T05:00:00+00:00` | `c1e1d22e1a314765b9e3b3b389fea99c` | false |

## Chunk Search Counts

Accepted rows found after deduping by `entry_time`:

```text
A.watch_pathA:       9 accepted unique rows
A.watch_weaken_ex:   3 accepted unique rows
```

The newest three `A.watch_pathA` rows are listed above. The `A.watch_weaken_ex` table lists all
three unique accepted EX rows found in the searched chunks.

## Findings

- Current Phase A samples include both OTE.entry (`A.watch_pathA`) and EX.entry
  (`A.watch_weaken_ex`) accepted trades.
- The OTE sample set includes both wins and losses, all with risk inside the configured 15-25 pip
  band after min-floor adjustment.
- EX.entry samples are rarer in the searched chunks. The search found exactly three unique accepted
  EX rows across the chunk set.
- The 2025-05-08 EX row appears in overlapping chunks (`resample-a-202503` and
  `resample-a-202505`); the table keeps the first source path only to avoid double counting.
- `trigger_age_bars` is 0 for the three OTE samples. EX samples show delayed retry/accept behavior
  with trigger ages 6, 11, and 3 bars.
