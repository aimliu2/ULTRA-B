from __future__ import annotations

import pandas as pd


def prepare_ohlcv(
    df: pd.DataFrame,
    bar_duration: str | pd.Timedelta,
    timestamp_col: str = "timestamp",
) -> pd.DataFrame:
    """
    Normalize raw OHLCV data to the engine's bar-close timestamp convention.

    Raw parquet files store `timestamp` as the bar open time. The replay and
    backtest engines make decisions only after a bar closes, so the DataFrame
    index must be the UTC bar close time: timestamp + bar_duration.
    """
    out = df.copy()

    if timestamp_col in out.columns:
        open_time = pd.to_datetime(out[timestamp_col], utc=True)
        out = out.drop(columns=[timestamp_col])
    elif isinstance(out.index, pd.DatetimeIndex):
        open_time = pd.to_datetime(out.index, utc=True)
    else:
        raise ValueError(
            f"Expected a `{timestamp_col}` column or DatetimeIndex with bar-open times."
        )

    out.index = open_time + pd.Timedelta(bar_duration)
    out.index.name = "bar_close_time"

    if "volume" not in out.columns and "tick_vol" in out.columns:
        out = out.rename(columns={"tick_vol": "volume"})

    return out.sort_index()

