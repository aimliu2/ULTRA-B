from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from ultrab.core.smc.candleEvent import FvgEvent
from ultrab.core.smc.pivotEvent import PivotEvent
from ultrab.core.smc.sdZone import SDZone, SDZoneBarResult


StructureBias = Literal["neutral", "bullish", "bearish"]
StructurePhase = Literal["neutral", "open", "pullback_confirmed"]
StructureTier = Literal["itr", "ltr"]
PullbackConfirmedBy = Literal["itr", "sd_zone"]

_INF = float("inf")


@dataclass
class ScEvent:
    event_code: str                         # SC01 / SC02 / SC03 / SC04
    event_name: str                         # itrBosUp / itrBosDown / ltrBosUp / ltrBosDown
    event_group: str                        # "SC"
    event_timestamp: pd.Timestamp
    level_tier: str                         # "itr" or "ltr"
    level_timestamp: pd.Timestamp
    level_price: float
    level_side: str                         # "high" or "low"
    break_direction: str                    # "up" or "down"
    bias_flip: bool = False
    choach: bool = False
    prior_anchor_high: float | None = None  # backward-compatible ChoCh field
    prior_anchor_low: float | None = None   # backward-compatible ChoCh field

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "eventCode": self.event_code,
            "eventName": self.event_name,
            "eventGroup": self.event_group,
            "eventTimestamp": self.event_timestamp.isoformat(),
            "levelTier": self.level_tier,
            "levelTimestamp": self.level_timestamp.isoformat(),
            "levelPrice": self.level_price,
            "levelSide": self.level_side,
            "breakDirection": self.break_direction,
            "biasFlip": self.bias_flip,
            "choach": self.choach,
        }
        if self.prior_anchor_high is not None:
            d["priorAnchorHigh"] = self.prior_anchor_high
        if self.prior_anchor_low is not None:
            d["priorAnchorLow"] = self.prior_anchor_low
        return d


@dataclass
class _RegistryLevel:
    tier: str
    side: str                   # "high" or "low"
    price: float
    timestamp: pd.Timestamp     # pivot bar timestamp
    registered_at: pd.Timestamp # event_timestamp when PE fired


class StructureEngine:
    """
    Structure Context engine.

    Detects Break of Structure (SC01-SC04).
    Warmup uses selected ITR/LTR registry levels. After first SC, P/D uses
    wick-defined range boundaries; ITR and SD zones only confirm pullback phase.

    Inputs per bar:
      - row             completed OHLC bar
      - pivot_events    PE events from PivotEventEngine for this bar
      - ce02_events     CE02 FVG events from FvgEventEngine for this bar
      - bar_result      SDZoneBarResult (created/mitigated zones) from SDZoneEngine

    Configuration keys (under "structure" in replay config):
      tier:           "itr" (default) | "ltr"
      ltf_enabled:    false (default) — enable LTF structural context in dual mode
    """

    def __init__(self, config: dict[str, Any], timeframe: str) -> None:
        self._tf = timeframe
        raw_tier = str(config.get("tier", "itr")).lower()
        self._tier: StructureTier = "ltr" if raw_tier == "ltr" else "itr"

        # tier-specific PE codes
        if self._tier == "itr":
            self._pe_high_code = "PE03"   # itrHighConfirmed
            self._pe_low_code  = "PE04"   # itrLowConfirmed
            self._sc_up_code   = "SC01"
            self._sc_up_name   = "itrBosUp"
            self._sc_dn_code   = "SC02"
            self._sc_dn_name   = "itrBosDown"
        else:
            self._pe_high_code = "PE05"   # ltrHighConfirmed
            self._pe_low_code  = "PE06"   # ltrLowConfirmed
            self._sc_up_code   = "SC03"
            self._sc_up_name   = "ltrBosUp"
            self._sc_dn_code   = "SC04"
            self._sc_dn_name   = "ltrBosDown"

        # state
        self._bias: StructureBias = "neutral"
        self._phase: StructurePhase = "neutral"

        # level registry — single most-recent level per side (item 3)
        self._registry_high: _RegistryLevel | None = None
        self._registry_low:  _RegistryLevel | None = None

        # wick-defined P/D range. During warmup these accumulate bootstrap wick
        # extremes; after first SC they become the active price range.
        self._range_high: float | None = None
        self._range_low: float | None = None
        self._range_high_ts: pd.Timestamp | None = None
        self._range_low_ts: pd.Timestamp | None = None
        self._phase_start_ts: pd.Timestamp | None = None

        # Pullback confirmation is phase/timing context, never the P/D price source.
        self._confirmed_by: PullbackConfirmedBy | None = None
        self._confirmed_zone_id: str | None = None
        self._pullback_confirmed_ts: pd.Timestamp | None = None
        self._pullback_low: float | None = None
        self._pullback_low_ts: pd.Timestamp | None = None
        self._pullback_high: float | None = None
        self._pullback_high_ts: pd.Timestamp | None = None

        # SC event log for snapshot
        self._last_sc: ScEvent | None = None

        # warmup gate — flips True on first SC; post-warmup uses wick range
        self._warmup_complete: bool = False

    # ── public API ────────────────────────────────────────────────────

    def on_bar(
        self,
        row: pd.Series,
        pivot_events: list[PivotEvent],
        ce02_events: list[FvgEvent],
        bar_result: SDZoneBarResult,
    ) -> list[ScEvent]:
        bar_high  = float(row["high"])
        bar_low   = float(row["low"])
        bar_close = float(row["close"])
        bar_ts    = row.name

        emitted: list[ScEvent] = []

        # 1. Ingest PE events → update warmup registry. Post-warmup PE events
        # only become pullback confirmation candidates.
        for pe in pivot_events:
            if pe.event_code == self._pe_high_code:
                self._registry_high = _RegistryLevel(
                    tier=self._tier,
                    side="high",
                    price=pe.pivot_price,
                    timestamp=pe.pivot_timestamp,
                    registered_at=pe.event_timestamp,
                )

            elif pe.event_code == self._pe_low_code:
                self._registry_low = _RegistryLevel(
                    tier=self._tier,
                    side="low",
                    price=pe.pivot_price,
                    timestamp=pe.pivot_timestamp,
                    registered_at=pe.event_timestamp,
                )

        # 2. Warmup uses PE registry only; wick extremes seed the first price range.
        if not self._warmup_complete:
            self._extend_range_high(bar_high, bar_ts)
            self._extend_range_low(bar_low, bar_ts)
            sc = self._bos_warmup(bar_close, bar_ts, bar_high, bar_low)
            if sc:
                emitted.append(sc)
            return emitted

        # 3. Post-warmup range state. OPEN extends in the bias direction.
        # PULLBACK_CONFIRMED tracks retracement extremes for the next leg.
        if self._phase == "open":
            if self._bias == "bullish":
                self._extend_range_high(bar_high, bar_ts)
            elif self._bias == "bearish":
                self._extend_range_low(bar_low, bar_ts)
        elif self._phase == "pullback_confirmed":
            self._track_pullback_extreme(bar_high, bar_low, bar_ts)

        # 4. SC detection — close only. Continuation requires confirmed pullback;
        # ChoCh can fire from either OPEN or PULLBACK_CONFIRMED.
        sc = self._bos_range(bar_close, bar_ts, bar_high, bar_low)
        if sc:
            emitted.append(sc)
            return emitted

        # 5. Pullback confirmation sources. ITR and SD confirm timing only; the
        # P/D range remains wick-defined.
        if self._phase == "open":
            phase_before_confirmation = self._phase
            self._confirm_pullback_from_itr(pivot_events)
            if self._phase == "open":
                self._confirm_pullback_from_sd(bar_result.created)
            if phase_before_confirmation == "open" and self._phase == "pullback_confirmed":
                self._track_pullback_extreme(bar_high, bar_low, bar_ts)

        return emitted

    def get_snapshot(self, current_price: float) -> dict[str, Any]:
        mid = self._pd_midpoint()
        range_position_pct: float | None = None
        pd_value_pct: float | None = None
        if mid is not None and self._range_low is not None and self._range_high is not None:
            range_size = self._range_high - self._range_low
            if range_size > 0:
                range_position_pct = round((current_price - self._range_low) / range_size * 100, 1)
                if self._bias == "bullish":
                    pd_value_pct = range_position_pct
                elif self._bias == "bearish":
                    pd_value_pct = round(100.0 - range_position_pct, 1)

        return {
            "tier": self._tier,
            "bias": self._bias,
            "phase": self._phase,
            "range_high": round(self._range_high, 6) if self._range_high is not None else None,
            "range_low": round(self._range_low, 6) if self._range_low is not None else None,
            "pd_midpoint":  round(mid, 6) if mid is not None else None,
            "range_position_pct": range_position_pct,
            "pd_value_pct": pd_value_pct,
            "pd_pct": range_position_pct,
            "confirmed_by": self._confirmed_by,
            "confirmed_zone_id": self._confirmed_zone_id,
            "pullback_confirmed_ts": self._pullback_confirmed_ts.isoformat() if self._pullback_confirmed_ts is not None else None,
            "last_sc":      self._last_sc.to_dict() if self._last_sc else None,
            # timestamps for P/D line drawing on the chart
            "phase_start_ts": self._phase_start_ts.isoformat() if self._phase_start_ts is not None else None,
            "range_high_ts": self._range_high_ts.isoformat() if self._range_high_ts is not None else None,
            "range_low_ts":  self._range_low_ts.isoformat()  if self._range_low_ts  is not None else None,
        }

    # ── internal ──────────────────────────────────────────────────────

    def _bos_warmup(
        self, close: float, ts: pd.Timestamp, bar_high: float, bar_low: float
    ) -> ScEvent | None:
        """Warmup (NEUTRAL): SC fires against registry — most recently confirmed PE pivot."""
        if self._registry_high is not None and close > self._registry_high.price:
            level = self._registry_high
            self._registry_high = None
            self._warmup_complete = True
            self._start_bullish(
                ts,
                self._range_low if self._range_low is not None else bar_low,
                bar_high,
                range_low_ts=self._range_low_ts,
            )
            sc = ScEvent(
                event_code=self._sc_up_code,
                event_name=self._sc_up_name,
                event_group="SC",
                event_timestamp=ts,
                level_tier=self._tier,
                level_timestamp=level.timestamp,
                level_price=level.price,
                level_side="high",
                break_direction="up",
                bias_flip=False,
                choach=False,
            )
            self._last_sc = sc
            return sc

        if self._registry_low is not None and close < self._registry_low.price:
            level = self._registry_low
            self._registry_low = None
            self._warmup_complete = True
            self._start_bearish(
                ts,
                self._range_high if self._range_high is not None else bar_high,
                bar_low,
                range_high_ts=self._range_high_ts,
            )
            sc = ScEvent(
                event_code=self._sc_dn_code,
                event_name=self._sc_dn_name,
                event_group="SC",
                event_timestamp=ts,
                level_tier=self._tier,
                level_timestamp=level.timestamp,
                level_price=level.price,
                level_side="low",
                break_direction="down",
                bias_flip=False,
                choach=False,
            )
            self._last_sc = sc
            return sc

        return None

    def _bos_range(
        self, close: float, ts: pd.Timestamp, bar_high: float, bar_low: float
    ) -> ScEvent | None:
        """Post-warmup: SC fires against wick-defined range boundaries."""
        if self._range_high is None or self._range_low is None:
            return None

        if self._bias == "bullish":
            # ChoCh: close below wick-defined floor.
            if close < self._range_low:
                level_price = self._range_low
                level_ts = self._range_low_ts or ts
                prior_high = self._range_high
                prior_low = self._range_low
                self._start_bearish(ts, prior_high, bar_low, range_high_ts=self._range_high_ts)
                sc = self._make_sc(
                    ts,
                    level_ts,
                    level_price,
                    "low",
                    "down",
                    bias_flip=True,
                    prior_high=prior_high,
                    prior_low=prior_low,
                )
                self._last_sc = sc
                return sc

            # Continuation: only after pullback is confirmed.
            if self._phase == "pullback_confirmed" and close > self._range_high:
                level_price = self._range_high
                level_ts = self._range_high_ts or ts
                new_floor = self._pullback_low if self._pullback_low is not None else bar_low
                new_floor_ts = self._pullback_low_ts if self._pullback_low is not None else ts
                self._start_bullish(ts, new_floor, bar_high, range_low_ts=new_floor_ts)
                sc = self._make_sc(ts, level_ts, level_price, "high", "up")
                self._last_sc = sc
                return sc

        elif self._bias == "bearish":
            # ChoCh: close above wick-defined ceiling.
            if close > self._range_high:
                level_price = self._range_high
                level_ts = self._range_high_ts or ts
                prior_high = self._range_high
                prior_low = self._range_low
                self._start_bullish(ts, prior_low, bar_high, range_low_ts=self._range_low_ts)
                sc = self._make_sc(
                    ts,
                    level_ts,
                    level_price,
                    "high",
                    "up",
                    bias_flip=True,
                    prior_high=prior_high,
                    prior_low=prior_low,
                )
                self._last_sc = sc
                return sc

            # Continuation: only after pullback is confirmed.
            if self._phase == "pullback_confirmed" and close < self._range_low:
                level_price = self._range_low
                level_ts = self._range_low_ts or ts
                new_ceiling = self._pullback_high if self._pullback_high is not None else bar_high
                new_ceiling_ts = self._pullback_high_ts if self._pullback_high is not None else ts
                self._start_bearish(ts, new_ceiling, bar_low, range_high_ts=new_ceiling_ts)
                sc = self._make_sc(ts, level_ts, level_price, "low", "down")
                self._last_sc = sc
                return sc

        return None

    def _make_sc(
        self,
        ts: pd.Timestamp,
        level_ts: pd.Timestamp,
        level_price: float,
        level_side: str,
        break_direction: str,
        *,
        bias_flip: bool = False,
        prior_high: float | None = None,
        prior_low: float | None = None,
    ) -> ScEvent:
        return ScEvent(
            event_code=self._sc_up_code if break_direction == "up" else self._sc_dn_code,
            event_name=self._sc_up_name if break_direction == "up" else self._sc_dn_name,
            event_group="SC",
            event_timestamp=ts,
            level_tier=self._tier,
            level_timestamp=level_ts,
            level_price=level_price,
            level_side=level_side,
            break_direction=break_direction,
            bias_flip=bias_flip,
            choach=bias_flip,
            prior_anchor_high=prior_high if bias_flip else None,
            prior_anchor_low=prior_low if bias_flip else None,
        )

    def _start_bullish(
        self,
        ts: pd.Timestamp,
        range_low: float,
        bar_high: float,
        *,
        range_low_ts: pd.Timestamp | None = None,
    ) -> None:
        """Start a bullish leg from a wick floor; extension high begins at this bar."""
        self._range_low = range_low
        self._range_low_ts = range_low_ts or ts
        self._range_high = bar_high
        self._range_high_ts = ts
        self._phase_start_ts = ts
        self._bias = "bullish"
        self._phase = "open"
        self._clear_pullback_confirmation()

    def _start_bearish(
        self,
        ts: pd.Timestamp,
        range_high: float,
        bar_low: float,
        *,
        range_high_ts: pd.Timestamp | None = None,
    ) -> None:
        """Start a bearish leg from a wick ceiling; extension low begins at this bar."""
        self._range_high = range_high
        self._range_high_ts = range_high_ts or ts
        self._range_low = bar_low
        self._range_low_ts = ts
        self._phase_start_ts = ts
        self._bias = "bearish"
        self._phase = "open"
        self._clear_pullback_confirmation()

    def _extend_range_high(self, price: float, ts: pd.Timestamp) -> None:
        if self._range_high is None or price > self._range_high:
            self._range_high = price
            self._range_high_ts = ts

    def _extend_range_low(self, price: float, ts: pd.Timestamp) -> None:
        if self._range_low is None or price < self._range_low:
            self._range_low = price
            self._range_low_ts = ts

    def _track_pullback_extreme(self, bar_high: float, bar_low: float, ts: pd.Timestamp) -> None:
        if self._bias == "bullish":
            if self._pullback_low is None or bar_low < self._pullback_low:
                self._pullback_low = bar_low
                self._pullback_low_ts = ts
        elif self._bias == "bearish":
            if self._pullback_high is None or bar_high > self._pullback_high:
                self._pullback_high = bar_high
                self._pullback_high_ts = ts

    def _clear_pullback_confirmation(self) -> None:
        self._confirmed_by = None
        self._confirmed_zone_id = None
        self._pullback_confirmed_ts = None
        self._pullback_low = None
        self._pullback_low_ts = None
        self._pullback_high = None
        self._pullback_high_ts = None

    def _set_pullback_confirmed(
        self,
        confirmed_by: PullbackConfirmedBy,
        ts: pd.Timestamp,
        *,
        zone_id: str | None = None,
    ) -> None:
        self._phase = "pullback_confirmed"
        self._confirmed_by = confirmed_by
        self._confirmed_zone_id = zone_id
        self._pullback_confirmed_ts = ts
        self._pullback_low = None
        self._pullback_low_ts = None
        self._pullback_high = None
        self._pullback_high_ts = None

    def _confirm_pullback_from_itr(self, pivot_events: list[PivotEvent]) -> None:
        if self._bias == "bullish":
            for pe in pivot_events:
                if pe.event_code == self._pe_high_code:
                    self._set_pullback_confirmed("itr", pe.event_timestamp)
                    return
        elif self._bias == "bearish":
            for pe in pivot_events:
                if pe.event_code == self._pe_low_code:
                    self._set_pullback_confirmed("itr", pe.event_timestamp)
                    return

    def _confirm_pullback_from_sd(self, zones: list[SDZone]) -> None:
        mid = self._pd_midpoint()
        if mid is None:
            return

        if self._bias == "bullish":
            for zone in zones:
                if zone.direction == "supply" and zone.high > mid:
                    self._set_pullback_confirmed("sd_zone", zone.created_at, zone_id=zone.zone_id)
                    return
        elif self._bias == "bearish":
            for zone in zones:
                if zone.direction == "demand" and zone.low < mid:
                    self._set_pullback_confirmed("sd_zone", zone.created_at, zone_id=zone.zone_id)
                    return

    def _pd_midpoint(self) -> float | None:
        if self._bias == "neutral":
            return None
        if self._range_low is None or self._range_high is None or self._range_high <= self._range_low:
            return None
        return (self._range_low + self._range_high) / 2
