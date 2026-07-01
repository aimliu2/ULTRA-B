# Phase B Trade Samples

Generated from current-code fresh-runtime chunk reruns after the Phase B duplicate-firing
and generalized-TP fixes.

Fresh source directories:

- `analysis/resample-b-202307`
- `analysis/resample-b-202009`
- `analysis/resample-b-202001`

These are targeted reruns of the three chunks used by the previous sample table. The goal is
comparison against the older baseline, not a full-history expectancy sample.

## Current Phase B Model

Active paths:

```text
B.watch_pathA = counter SC06 iChoCh -> pro SC06 iChoCh while B.watch holds
B.watch_pathB = counter SC06 iChoCh during B.watch, then one-shot B.watch -> A.watch transition
SL = phase_b_shadow_commitment_extreme_level +/- configured buffer and min floor
TP = Phase A objective-progress level, capped at 2.5R
```

Step 2 retracement is not explicitly ITR-gated.

Episode mechanics:

```text
Accepted entry or stale geometry skip spends the B.watch episode.
runway_too_short does not spend the episode, but locks the pending trigger so a different trigger
cannot replace it before retry/expiry.
```

## Current Accepted Phase B Trades In The Three Rerun Chunks

| Entry time | Outcome | Dir | Path | Entry | SL | TP | Risk pips | Target R | Exit time | R result | Trigger | Source |
|---|---|---|---|---:|---:|---:|---:|---:|---|---:|---|---|
| `2023-08-30T15:00:00+00:00` | loss | short | `B.watch_pathA` | 1.08783 | 1.08935 | 1.08403 | 15.2 | 2.5 | `2023-08-30T15:30:00+00:00` | -1.0 | `SC06:2023-08-30T15:00:00+00:00:down:1.08794` | `analysis/resample-b-202307/layer5_trade_results.csv` |
| `2020-10-14T06:30:00+00:00` | loss | long | `B.watch_pathA` | 1.17442 | 1.17284 | 1.17837 | 15.8 | 2.5 | `2020-10-14T10:30:00+00:00` | -1.0 | `SC06:2020-10-14T06:30:00+00:00:up:1.17437` | `analysis/resample-b-202009/layer5_trade_results.csv` |
| `2020-01-23T04:45:00+00:00` | timeout | long | `B.watch_pathA` | 1.10898 | 1.10676 | 1.11453 | 22.2 | 2.5 | `2020-01-23T12:45:00+00:00` | -0.0991 | `SC06:2020-01-23T04:45:00+00:00:up:1.10892` | `analysis/resample-b-202001/layer5_trade_results.csv` |

## Supporting Fields

| Entry time | Evidence kind | Evidence presented at | HTF zone tapped during B.watch | At HTF S/D entry | Stale marked | Trigger age bars |
|---|---|---|---|---|---|---:|
| `2023-08-30T15:00:00+00:00` | `b_watch_commitment` | `2023-08-30T08:15:00+00:00` | false | false | false | 0 |
| `2020-10-14T06:30:00+00:00` | `b_watch_commitment` | `2020-10-13T21:45:00+00:00` | false | false | false | 0 |
| `2020-01-23T04:45:00+00:00` | `b_watch_commitment` | `2020-01-23T01:15:00+00:00` | false | false | false | 0 |

## Skips Seen In The Same Three Chunks

| Chunk | Path | Count | Reason |
|---|---|---:|---|
| `analysis/resample-b-202009` | `B.watch_pathA` | 2 | `late_entry_risk_too_wide` |
| `analysis/resample-b-202009` | `B.watch_pathB` | 2 | `late_entry_risk_too_wide` |
| `analysis/resample-b-202001` | `B.watch_pathA` | 1 | `late_entry_risk_too_wide` |
| `analysis/resample-b-202001` | `B.watch_pathB` | 1 | `late_entry_risk_too_wide` |

## Findings

- Current accepted examples in these three chunks are all `B.watch_pathA`.
- No accepted `B.watch_pathB` trade was found in the rerun set; Path B appears only as stale
  geometry skips.
- The `2023-08-30T15:00:00+00:00` and `2020-10-14T06:30:00+00:00` entries still fire at
  the same timestamp and outcome as the previous sample, but their TP is now generalized to the
  Phase A objective-progress target capped at 2.5R.
- The previous `2020-01-23T09:15:00+00:00` loss no longer fires. The current code accepts the
  earlier `2020-01-23T04:45:00+00:00` trigger in the same B.watch episode, then the episode is
  consumed; this confirms the duplicate-firing fix changed the sample.
- `trigger_age_bars` is 0 on all accepted Phase B rows in these chunks.
- Integrity conclusion: these three rows are valid OTE executions under the current Phase B
  contract, not duplicate-firing or stale-trigger bugs.
- Quality concern: all three validated `B.watch_pathA` samples failed to follow through after
  the pro iChoCh. Each case later behaved like a failed reclaim / reversal-continuation episode
  where `B.watch` was run over and the thesis returned toward `C.pullback`.
- Working hypothesis: Phase B should theoretically be one of the highest-profit phases when the
  reclaim is real, so the current accepted trigger may be structurally correct but too permissive.
  Do not tune from three trades, but future analysis should look for a Phase B quality gate.
- Candidate analysis splits before adding any rule:
  - accepted B trades with vs without HTF S/D zone context;
  - MFE before `B.watch -> C.pullback`;
  - bars from pro iChoCh entry to C return or stop;
  - counter iChoCh depth and whether the pro iChoCh only barely reclaimed;
  - transition reason after failure: commitment extreme breached vs B.watch MSS failed.
