# ULTRA-B
ultra forward time-lapse event-driven backtest framework. Written in Python

## Package Layout

[config path](src/ultrab/replayer/config.yaml)


## Replay App Quickstart

Run from the repository root:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m ultrab.replayer.app
```

Then open:

```text
http://127.0.0.1:5055
```

The replay app reads its UI/runtime settings from `src/ultrab/replayer/config.yaml`
and the parquet data root from `src/.env`. See `src/README.md` for the expected
parquet folder layout.

After installing the package in editable mode, the shorter command is:

```bash
python3 -m pip install -e .
ultrab-replay
```
