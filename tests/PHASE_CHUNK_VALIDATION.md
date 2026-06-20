# Phase Chunk Validation Guide

Use this when a phase-specific trade path has just been changed and full-history
backtesting would be too slow or too noisy. The goal is precision: prove the
path wiring behaves correctly on real replay state. Do not use this as a
strategy win-rate sample.

## What This Proves

- The real `DualSmcRuntime` can reach the target phase/path.
- Path routing is mutually exclusive where expected.
- Entry geometry and skip reasons match the current contract.
- Accepted entries produce normal analysis outcomes: win, loss, or timeout.

## What This Does Not Prove

- Long-run expectancy.
- Stable win rate.
- Parameter quality.
- Symbol-wide or regime-wide robustness.

## Default Chunk Size

Use 6000 lower-timeframe steps for EURUSD 15m/4h chunks:

```bash
--max-steps 6000
```

At 15m this is about 62.5 calendar days. That usually spans enough 4H PD
epochs to exercise phase transitions without scanning the entire 2019-2026
local history.

For a known regression episode, use a smaller targeted chunk first:

```bash
--max-steps 1500
```

At 15m this is about 15.6 calendar days.

## Phase D Layer 5 Example

Known regression window:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m ultrab.entry.run_layer5_backtest \
  --start-time 2019-03-04T00:00:00+00:00 \
  --max-steps 1500 \
  --output-dir analysis/layer5-smoke-201903
```

Spread 2-month chunks across history:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m ultrab.entry.run_layer5_backtest \
  --start-time 2019-03-04T00:00:00+00:00 \
  --max-steps 6000 \
  --output-dir analysis/layer5-chunk-201903
```

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m ultrab.entry.run_layer5_backtest \
  --start-time 2020-06-01T00:00:00+00:00 \
  --max-steps 6000 \
  --output-dir analysis/layer5-chunk-202006
```

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m ultrab.entry.run_layer5_backtest \
  --start-time 2021-09-01T00:00:00+00:00 \
  --max-steps 6000 \
  --output-dir analysis/layer5-chunk-202109
```

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m ultrab.entry.run_layer5_backtest \
  --start-time 2023-01-01T00:00:00+00:00 \
  --max-steps 6000 \
  --output-dir analysis/layer5-chunk-202301
```

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m ultrab.entry.run_layer5_backtest \
  --start-time 2024-06-01T00:00:00+00:00 \
  --max-steps 6000 \
  --output-dir analysis/layer5-chunk-202406
```

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m ultrab.entry.run_layer5_backtest \
  --start-time 2026-01-01T00:00:00+00:00 \
  --max-steps 6000 \
  --output-dir analysis/layer5-chunk-202601
```

## Inspect The Reports

Use `rg`; do not scan the CSVs by hand first.

```bash
rg --no-heading "Path A|Path B|Path C1|Path C2|risk_too_tight|late_entry|runway" \
  analysis/layer5-*/layer5_report.md
```

For deeper inspection:

```bash
rg --no-heading "D.watch_pathA|D.watch_pathB|D.watch_pathC1|D.watch_pathC2|risk_too_tight" \
  analysis/layer5-*/layer5_trade_results.csv
```

## Phase D Pass Criteria

- `D.watch_pathA` appears at least once.
- `D.watch_pathB` appears at least once.
- `D.watch_pathC1` or `D.watch_pathC2` appears if the sampled chunks reach
  `C.pullback` from `D.watch_mss`.
- `risk_too_tight` does not appear.
- Skips are limited to expected contract reasons, currently:
  - `late_entry_risk_too_wide`
  - `runway_too_short`
- Accepted entries have sane geometry:
  - `risk_pips >= 15`
  - `risk_pips <= 25`
  - `target_r >= 1.75`

If A/B appear but C1/C2 do not, do not expand directly to full history. First
run chunks around known D.watch -> C.pullback periods, or use
`tests/test_headless_runtime_reuse.py` plus an exact timestamp probe to locate
real `D.watch_mss` transitions.

## Reusing For Phase C, B, And A

When adding C/B/A trade paths, keep the same method:

1. Pick one known regression or hand-inspected timestamp window.
2. Run one targeted 1500-step chunk around it.
3. Run 4-6 spread 6000-step chunks.
4. Stop when every new path has appeared at least once and skip reasons match
   the phase contract.
5. Only after integration is clean, run larger samples for performance.

For future phases, replace the report patterns with the phase path tags, for
example `C.*`, `B.*`, or `A.*` trigger paths once those contracts exist.
