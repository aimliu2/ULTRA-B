from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from ultrab.core.market_data import prepare_ohlcv


SOURCE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = SOURCE_ROOT / ".env"
DEFAULT_DATA_ROOT = PROJECT_ROOT / "ln-data"
LEGACY_DATA_ROOT = "big-data/mlData/raw"
TIMEFRAME_ORDER = ("1d", "4h", "1h", "15m", "5m", "1m")
TIMEFRAME_LABELS = {
    "1d": "1D",
    "4h": "4H",
    "1h": "1H",
    "15m": "15M",
    "5m": "5M",
    "1m": "1M",
}


@dataclass(frozen=True)
class ReplayDataConfig:
    root: Path
    symbol: str
    timeframe: str
    window_bars: int
    start_time: str | None = None

    @property
    def parquet_path(self) -> Path:
        filename = f"{self.symbol.upper()}-sorted-{self.timeframe}.parquet"
        return self.root / self.symbol.upper() / filename

    @property
    def bar_duration(self) -> str:
        mapping = {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "1h": "1h",
            "4h": "4h",
            "1d": "1d",
        }
        if self.timeframe not in mapping:
            raise KeyError(f"Unsupported timeframe for replay app: {self.timeframe}")
        return mapping[self.timeframe]


def load_app_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_runtime_env(path: str | Path = ENV_PATH) -> dict[str, Any]:
    env_path = Path(path)
    if not env_path.exists():
        return {}
    with env_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _resolve_data_root(root_value: str | Path, config_path: Path) -> Path:
    root = Path(root_value).expanduser()
    if root.is_absolute():
        resolved = root.resolve()
        return resolved if resolved.exists() or not DEFAULT_DATA_ROOT.exists() else DEFAULT_DATA_ROOT.resolve()

    candidates = [
        (PROJECT_ROOT / root).resolve(),
        (config_path.parent / root).resolve(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    if DEFAULT_DATA_ROOT.exists():
        return DEFAULT_DATA_ROOT.resolve()
    return candidates[0]


def replay_data_config(path: str | Path) -> ReplayDataConfig:
    config_path = Path(path)
    config = load_app_config(config_path)
    data = config.get("data", {})
    runtime_env = load_runtime_env()
    root_value = data.get("root") or runtime_env.get("root") or LEGACY_DATA_ROOT
    root = _resolve_data_root(root_value, config_path)
    timeframe = str(data.get("timeframe", "1h")).lower()
    if timeframe == "daily":
        timeframe = "1d"
    start_time = data.get("start_time")
    if start_time is not None:
        start_time = str(start_time).strip() or None
    return ReplayDataConfig(
        root=root,
        symbol=str(data.get("symbol", "EURUSD")).upper(),
        timeframe=timeframe,
        window_bars=int(data.get("window_bars", 1000)),
        start_time=start_time,
    )


def effective_start_time(requested_start_time: Any, configured_start_time: str | None) -> str | None:
    value = requested_start_time if requested_start_time not in (None, "") else configured_start_time
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized or normalized.lower() == "latest_window":
        return None
    return normalized


def resolve_start_timestamp(bars: pd.DataFrame, start_time: str | None, default_index: int) -> str | None:
    if bars.empty:
        return None
    if not start_time:
        return bars.index[default_index].isoformat()
    start_ts = pd.Timestamp(start_time)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    else:
        start_ts = start_ts.tz_convert("UTC")
    idx = int(bars.index.searchsorted(start_ts, side="left"))
    idx = max(0, idx)
    idx = min(idx, len(bars) - 1)
    return bars.index[idx].isoformat()


def load_ohlc_window(config: ReplayDataConfig) -> pd.DataFrame:
    bars = load_full_ohlc(config)

    if bars.empty:
        return bars.iloc[0:0].copy()

    window = bars.iloc[-config.window_bars :].copy()
    window.index.name = "bar_close_time"
    return window


def load_full_ohlc(config: ReplayDataConfig) -> pd.DataFrame:
    raw = pd.read_parquet(config.parquet_path)
    bars = prepare_ohlcv(raw, bar_duration=config.bar_duration)
    return bars.loc[:, ["open", "high", "low", "close"]].copy()


def available_symbols(config: ReplayDataConfig) -> list[str]:
    symbols: list[str] = []
    if not config.root.exists():
        return symbols

    for child in sorted(config.root.iterdir()):
        if not child.is_dir():
            continue
        symbol = child.name.upper()
        parquet = child / f"{symbol}-sorted-{config.timeframe}.parquet"
        if parquet.exists():
            symbols.append(symbol)

    return symbols


def available_timeframes(config: ReplayDataConfig, symbol: str | None = None) -> list[str]:
    if not config.root.exists():
        return []

    resolved_symbol = (symbol or config.symbol).upper()
    symbol_dir = config.root / resolved_symbol
    if not symbol_dir.exists() or not symbol_dir.is_dir():
        return []

    available: list[str] = []
    for timeframe in TIMEFRAME_ORDER:
        parquet = symbol_dir / f"{resolved_symbol}-sorted-{timeframe}.parquet"
        if parquet.exists():
            available.append(timeframe)
    return available


def timeframe_label(timeframe: str) -> str:
    key = str(timeframe).lower()
    if key == "daily":
        key = "1d"
    return TIMEFRAME_LABELS.get(key, key.upper())


def bars_payload(config: ReplayDataConfig) -> dict[str, Any]:
    full = load_full_ohlc(config)
    window = load_ohlc_window(config)
    bars = []
    for ts, row in window.iterrows():
        bars.append(
            {
                "bar_index": int(full.index.get_loc(ts)),
                "time": ts.isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
        )

    default_start_time = resolve_start_timestamp(
        full,
        effective_start_time(None, config.start_time),
        max(0, len(full) - config.window_bars) if len(full) else 0,
    )

    return {
        "symbol": config.symbol,
        "timeframe": config.timeframe.upper(),
        "window_bars": config.window_bars,
        "data_start_time": full.index[0].isoformat() if len(full) else None,
        "data_end_time": full.index[-1].isoformat() if len(full) else None,
        "default_start_time": default_start_time,
        "bar_count": len(bars),
        "window_start_time": bars[0]["time"] if bars else None,
        "window_end_time": bars[-1]["time"] if bars else None,
        "bars": bars,
    }
