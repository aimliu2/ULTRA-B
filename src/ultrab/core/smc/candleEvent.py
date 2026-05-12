from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd


FvgType = Literal["rally", "drop"]


@dataclass
class FvgEvent:
    event_code: str
    event_name: str
    event_group: str
    event_timestamp: pd.Timestamp
    fvg_type: FvgType
    bar1_timestamp: pd.Timestamp
    bar1_high: float
    bar1_low: float
    bar2_timestamp: pd.Timestamp
    # CE01 only
    bar2_close: float | None = None
    bar2_open: float | None = None
    sub_type: str | None = None
    # CE02 only
    pivot_timestamp: pd.Timestamp | None = None
    gap_top: float | None = None
    gap_bottom: float | None = None
    gap_size: float | None = None
    bar3_timestamp: pd.Timestamp | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "eventCode": self.event_code,
            "eventName": self.event_name,
            "eventGroup": self.event_group,
            "eventTimestamp": self.event_timestamp,
            "type": self.fvg_type,
            "bar1Timestamp": self.bar1_timestamp,
            "bar1High": self.bar1_high,
            "bar1Low": self.bar1_low,
            "bar2Timestamp": self.bar2_timestamp,
        }
        if self.bar2_close is not None:
            payload["bar2Close"] = self.bar2_close
        if self.bar2_open is not None:
            payload["bar2Open"] = self.bar2_open
        if self.sub_type is not None:
            payload["subType"] = self.sub_type
        if self.pivot_timestamp is not None:
            payload["pivotTimestamp"] = self.pivot_timestamp
        if self.gap_top is not None:
            payload["gapTop"] = self.gap_top
        if self.gap_bottom is not None:
            payload["gapBottom"] = self.gap_bottom
        if self.gap_size is not None:
            payload["gapSize"] = self.gap_size
        if self.bar3_timestamp is not None:
            payload["bar3Timestamp"] = self.bar3_timestamp
        return payload


@dataclass
class _BarSnapshot:
    timestamp: pd.Timestamp
    high: float
    low: float


def _classify_sub_type(
    fvg_type: FvgType,
    bar1_high: float,
    bar1_low: float,
    bar2_open: float,
    bar2_high: float,
    bar2_low: float,
) -> str:
    if fvg_type == "rally":
        if bar2_open > bar1_high and bar2_low > bar1_high:
            return "gap_up"
        if bar2_open < bar1_low:
            return "engulfing_rally"
        return "expansion_up"
    else:
        if bar2_open < bar1_low and bar2_high < bar1_low:
            return "gap_down"
        if bar2_open > bar1_high:
            return "engulfing_drop"
        return "expansion_down"


class FvgEventEngine:
    """
    3-bar Fair Value Gap detector.

    CE01 (expansionSpotted) fires on bar 2 close when bar 2 closes beyond bar 1.
    CE02 (fvgConfirmed)     fires on bar 3 close when the gap between bar 1 and
                            bar 3 is preserved (wick-based).

    CE01 and CE02 are independent. CE02 does not require CE01 to have fired on bar 2.
    A gap confirmed by bar 3 is valid even when bar 2 was a doji or inside bar.

    A single bar can emit CE02 (as bar 3) and CE01 (as bar 2) in the same call.
    CE02 is emitted before CE01.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.min_gap_size: float = float(cfg.get("min_gap_size", 0.0))
        self._prev: _BarSnapshot | None = None       # bar n-1 (bar 2 for CE01, bar 2 ref for CE02)
        self._bar1_ref: _BarSnapshot | None = None   # bar n-2 (bar 1 ref for CE02)

    def on_bar(self, row: pd.Series) -> list[FvgEvent]:
        ts = row.name
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        emitted: list[FvgEvent] = []

        # CE02 first: current bar as bar 3, _bar1_ref as bar 1, _prev as bar 2
        if self._bar1_ref is not None and self._prev is not None:
            ce02 = self._try_confirm(self._bar1_ref, self._prev, ts, high, low)
            if ce02 is not None:
                emitted.append(ce02)

        # CE01 second: current bar as bar 2 against _prev as bar 1
        if self._prev is not None:
            ce01 = self._try_expansion(self._prev, ts, open_, high, low, close)
            if ce01 is not None:
                emitted.append(ce01)

        # Advance sliding window
        self._bar1_ref = self._prev
        self._prev = _BarSnapshot(timestamp=ts, high=high, low=low)

        return emitted

    def _try_expansion(
        self,
        bar1: _BarSnapshot,
        bar2_ts: pd.Timestamp,
        bar2_open: float,
        bar2_high: float,
        bar2_low: float,
        bar2_close: float,
    ) -> FvgEvent | None:
        if bar2_close > bar1.high:
            fvg_type: FvgType = "rally"
        elif bar2_close < bar1.low:
            fvg_type = "drop"
        else:
            return None

        sub_type = _classify_sub_type(fvg_type, bar1.high, bar1.low, bar2_open, bar2_high, bar2_low)

        return FvgEvent(
            event_code="CE01",
            event_name="expansionSpotted",
            event_group="CE",
            event_timestamp=bar2_ts,
            fvg_type=fvg_type,
            bar1_timestamp=bar1.timestamp,
            bar1_high=bar1.high,
            bar1_low=bar1.low,
            bar2_timestamp=bar2_ts,
            bar2_close=bar2_close,
            bar2_open=bar2_open,
            sub_type=sub_type,
        )

    def _try_confirm(
        self,
        bar1: _BarSnapshot,
        bar2: _BarSnapshot,
        bar3_ts: pd.Timestamp,
        bar3_high: float,
        bar3_low: float,
    ) -> FvgEvent | None:
        if bar3_low > bar1.high:
            fvg_type: FvgType = "rally"
            gap_top = bar3_low
            gap_bottom = bar1.high
        elif bar3_high < bar1.low:
            fvg_type = "drop"
            gap_top = bar1.low
            gap_bottom = bar3_high
        else:
            return None

        gap_size = gap_top - gap_bottom
        if gap_size < self.min_gap_size:
            return None

        return FvgEvent(
            event_code="CE02",
            event_name="fvgConfirmed",
            event_group="CE",
            event_timestamp=bar3_ts,
            fvg_type=fvg_type,
            bar1_timestamp=bar1.timestamp,
            bar1_high=bar1.high,
            bar1_low=bar1.low,
            bar2_timestamp=bar2.timestamp,
            pivot_timestamp=bar2.timestamp,
            gap_top=gap_top,
            gap_bottom=gap_bottom,
            gap_size=gap_size,
            bar3_timestamp=bar3_ts,
        )
