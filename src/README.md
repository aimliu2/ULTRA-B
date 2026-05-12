# Replay App Data Contract

The replay app expects market data under the root configured in `src/.env`.
That file is a small YAML file used for local runtime paths that should not be
hardcoded into `src/ultrab/replayer/config.yaml`.

```yaml
root: /absolute/path/to/fx-parquet
```

`root` must point at the parquet folder that contains one directory per symbol.
On machines where the real data lives outside the repository, create a symlink
at the repository root and point `src/.env` at either the symlink or the real
absolute path.

```bash
ln -s /absolute/path/to/fx-parquet ln-data
```

Example `src/.env` using the symlink target:

```yaml
root: /Users/you/path/to/py-ULTRA-B/ln-data
```

If `src/.env` is missing, the app falls back to `data.root` in
`src/ultrab/replayer/config.yaml`, then to the repository-root `ln-data` symlink
when it exists.

## Expected Folder Layout

```text
<root>/
  EURUSD/
    EURUSD-sorted-1d.parquet
    EURUSD-sorted-4h.parquet
    EURUSD-sorted-1h.parquet
    EURUSD-sorted-15m.parquet
    EURUSD-sorted-5m.parquet
    EURUSD-sorted-1m.parquet
  USDJPY/
    USDJPY-sorted-1d.parquet
    USDJPY-sorted-4h.parquet
    USDJPY-sorted-1h.parquet
    USDJPY-sorted-15m.parquet
    USDJPY-sorted-5m.parquet
    USDJPY-sorted-1m.parquet
```

## Naming Rule

Each symbol must live in its own upper-case folder:

```text
<root>/<SYMBOL>/
```

Each timeframe file must follow:

```text
<SYMBOL>-sorted-<timeframe>.parquet
```

Examples:

```text
EURUSD-sorted-1d.parquet
EURUSD-sorted-4h.parquet
EURUSD-sorted-1h.parquet
EURUSD-sorted-15m.parquet
EURUSD-sorted-5m.parquet
EURUSD-sorted-1m.parquet
```

## Parquet Shape

Each parquet file is a pandas-readable table for one symbol and one timeframe.
The file name tells the app which symbol and timeframe it contains.

Required columns:

- `timestamp`: bar open time; parsed as UTC and shifted by the timeframe duration
  to become the app's `bar_close_time` index
- `open`: bar open price
- `high`: bar high price
- `low`: bar low price
- `close`: bar close price

Optional columns currently present in the local data:

- `tick_vol`: tick volume; renamed to `volume` by the loader
- `spread`: spread value from the source export
- `bar_close_bull`: boolean marker for bullish closes

Current local sample shape:

```text
EURUSD/EURUSD-sorted-1d.parquet
rows: 1890
columns: timestamp, open, high, low, close, tick_vol, spread, bar_close_bull
```

## Supported Timeframe Keys

- `1d`
- `4h`
- `1h`
- `15m`
- `5m`
- `1m`

The replay app uses these keys to:

- populate the timeframe dropdown
- locate parquet files
- map event log timeframe labels

If a symbol is missing a timeframe file, that timeframe is hidden from the
selector for that symbol.
