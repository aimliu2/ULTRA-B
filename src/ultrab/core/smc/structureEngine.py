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
StructureSequenceSide = Literal["high", "low"]

_INF = float("inf")


@dataclass
class ScEvent:
    event_code: str                         # SC01–SC08
    event_name: str                         # itrSbUp / itrISb / itrIChoCh / etc.
    event_group: str                        # "SC"
    event_timestamp: pd.Timestamp
    level_tier: str                         # "itr" or "ltr"
    level_timestamp: pd.Timestamp
    level_price: float
    level_side: str                         # "high" or "low"
    break_direction: str                    # "up" or "down"
    bias_flip: bool = False
    choch: bool = False
    is_internal: bool = False              # True for SC05–SC08 (ITR/LTR pivot-level iSb/iChoCh)
    prior_anchor_high: float | None = None  # backward-compatible ChoCh field
    prior_anchor_low: float | None = None   # backward-compatible ChoCh field

    def to_dict(self) -> dict[str, Any]:
        if self.is_internal:
            event_action = "structure_ichoch" if self.choch else "structure_isb"
        else:
            event_action = "structure_choch" if self.choch else "structure_sb"
        runtime_alias = self.event_name
        d: dict[str, Any] = {
            "eventCode": self.event_code,
            "eventName": self.event_name,
            "targetEventName": self.event_name,
            "runtimeAlias": runtime_alias,
            "eventAction": event_action,
            "eventGroup": self.event_group,
            "eventTimestamp": self.event_timestamp.isoformat(),
            "levelTier": self.level_tier,
            "levelTimestamp": self.level_timestamp.isoformat(),
            "levelPrice": self.level_price,
            "levelSide": self.level_side,
            "breakDirection": self.break_direction,
            "biasFlip": self.bias_flip,
            "structure_sb": event_action == "structure_sb",
            "structure_choch": event_action == "structure_choch",
            "structure_isb": event_action == "structure_isb",
            "structure_ichoch": event_action == "structure_ichoch",
            "choch": self.choch,
            "is_internal": self.is_internal,
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


@dataclass
class StructureLevel:
    level_id: str
    event_code: str
    tier: str
    side: str
    price: float
    pivot_time: pd.Timestamp
    confirmed_at: pd.Timestamp
    relation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "level_id": self.level_id,
            "event_code": self.event_code,
            "tier": self.tier,
            "side": self.side,
            "price": round(self.price, 6),
            "pivot_time": self.pivot_time.isoformat(),
            "confirmed_at": self.confirmed_at.isoformat(),
            "relation": self.relation,
        }


@dataclass
class StructureSequencePoint:
    point_id: str
    timeframe: str
    side: StructureSequenceSide
    role: str
    price: float
    timestamp: pd.Timestamp
    confirmed_at: pd.Timestamp
    source_transition: str
    source_event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "point_id": self.point_id,
            "timeframe": self.timeframe,
            "side": self.side,
            "role": self.role,
            "price": round(self.price, 6),
            "timestamp": self.timestamp.isoformat(),
            "confirmed_at": self.confirmed_at.isoformat(),
            "source_transition": self.source_transition,
            "source_event_id": self.source_event_id,
        }


@dataclass
class StructureAttempt:
    attempt_id: str
    direction: str
    alignment: str
    origin: str
    orderflow_quality: str
    anchor_level_id: str
    anchor_price: float
    started_at: pd.Timestamp
    extreme_price: float
    status: str
    failed_at: pd.Timestamp | None = None
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "direction": self.direction,
            "alignment": self.alignment,
            "origin": self.origin,
            "orderflow_quality": self.orderflow_quality,
            "anchor_level_id": self.anchor_level_id,
            "anchor_price": round(self.anchor_price, 6),
            "started_at": self.started_at.isoformat(),
            "extreme_price": round(self.extreme_price, 6),
            "status": self.status,
            "failed_at": self.failed_at.isoformat() if self.failed_at is not None else None,
            "failure_reason": self.failure_reason,
        }


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
        self._recent_level_limit = max(1, int(config.get("recent_level_limit", 20)))
        self._structure_sequence_limit = max(
            1,
            int(
                config.get(
                    "structure_sequence_limit",
                    config.get("structure_anchor_limit", config.get("anchor_sequence_limit", 8)),
                )
            ),
        )

        # tier-specific PE codes and SC range codes (SC01–SC04)
        if self._tier == "itr":
            self._pe_high_code = "PE03"   # itrHighConfirmed
            self._pe_low_code  = "PE04"   # itrLowConfirmed
            self._sc_up_code   = "SC01"
            self._sc_up_name   = "itrSbUp"
            self._sc_dn_code   = "SC02"
            self._sc_dn_name   = "itrSbDown"
            # Internal SC codes — fire against confirmed ITR pivot levels (SC05–SC06)
            self._sc_isb_code    = "SC05"
            self._sc_isb_name    = "itrISb"
            self._sc_ichoch_code = "SC06"
            self._sc_ichoch_name = "itrIChoCh"
        else:
            self._pe_high_code = "PE05"   # ltrHighConfirmed
            self._pe_low_code  = "PE06"   # ltrLowConfirmed
            self._sc_up_code   = "SC03"
            self._sc_up_name   = "ltrSbUp"
            self._sc_dn_code   = "SC04"
            self._sc_dn_name   = "ltrSbDown"
            # Internal SC codes — fire against confirmed LTR pivot levels (SC07–SC08)
            self._sc_isb_code    = "SC07"
            self._sc_isb_name    = "ltrISb"
            self._sc_ichoch_code = "SC08"
            self._sc_ichoch_name = "ltrIChoCh"

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
        self._last_isc: ScEvent | None = None   # last internal iSb/iChoCh (SC05–SC08)

        # Internal iSb/iChoCh dedup — prevent same confirmed pivot from re-firing
        self._last_isb_level_id: str | None = None
        self._last_ichoch_level_id: str | None = None

        # Bounded structural memory for downstream hypothesis/audit consumers.
        self._recent_levels: list[StructureLevel] = []
        self._latest_level_high: StructureLevel | None = None
        self._latest_level_low: StructureLevel | None = None
        self._structure_attempt: StructureAttempt | None = None
        self._structure_sequence: list[StructureSequencePoint] = []

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
                self._remember_structure_level(pe, "high")
                self._registry_high = _RegistryLevel(
                    tier=self._tier,
                    side="high",
                    price=pe.pivot_price,
                    timestamp=pe.pivot_timestamp,
                    registered_at=pe.event_timestamp,
                )

            elif pe.event_code == self._pe_low_code:
                self._remember_structure_level(pe, "low")
                self._registry_low = _RegistryLevel(
                    tier=self._tier,
                    side="low",
                    price=pe.pivot_price,
                    timestamp=pe.pivot_timestamp,
                    registered_at=pe.event_timestamp,
                )

        if self._warmup_complete:
            self._maybe_open_pro_attempt_from_break(bar_high, bar_low, bar_ts)

        # 2. Warmup uses PE registry only; wick extremes seed the first price range.
        if not self._warmup_complete:
            self._extend_range_high(bar_high, bar_ts)
            self._extend_range_low(bar_low, bar_ts)
            sc = self._sb_warmup(bar_close, bar_ts, bar_high, bar_low)
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

        self._update_structure_attempt(bar_high, bar_low, bar_close, bar_ts)

        # 4a. Internal iSb/iChoCh — checked against confirmed ITR/LTR pivot levels
        # BEFORE the range check so they see the pre-transition structural state.
        isc = self._sb_internal(bar_close, bar_ts)
        if isc:
            emitted.append(isc)

        # 4b. Range SC01–SC04 detection — close against wick-defined boundaries.
        # Continuation requires confirmed pullback; ChoCh fires from any phase.
        sc = self._sb_range(bar_close, bar_ts, bar_high, bar_low)
        if sc:
            emitted.append(sc)
            return emitted  # skip pullback confirmation when a range SC transitions state

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

        structure_probe = self._structure_probe(current_price)
        structure_sequence = [
            point.to_dict()
            for point in self._structure_sequence
        ]
        orderflow_anchor_sequence = [
            self._orderflow_anchor_point(point)
            for point in self._structure_sequence
        ]
        orderflow_probe = self._orderflow_probe(structure_probe)

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
            "recent_itr_levels": [
                level.to_dict()
                for level in self._recent_levels
                if level.tier == "itr"
            ],
            "latest_itr_high": (
                self._latest_level_high.to_dict()
                if self._latest_level_high and self._latest_level_high.tier == "itr"
                else None
            ),
            "latest_itr_low": (
                self._latest_level_low.to_dict()
                if self._latest_level_low and self._latest_level_low.tier == "itr"
                else None
            ),
            "last_isc":      self._last_isc.to_dict() if self._last_isc else None,
            "structure_attempt": self._structure_attempt.to_dict() if self._structure_attempt else None,
            "ltf_structure_attempt": self._structure_attempt.to_dict() if self._structure_attempt else None,
            "structure_sequence": structure_sequence,
            "structure_probe": structure_probe,
            "recent_structure_sequence_points": structure_sequence,
            "orderflow_anchor_sequence": orderflow_anchor_sequence,
            "orderflow_probe": orderflow_probe,
            "recent_orderflow_anchor_points": orderflow_anchor_sequence,
            # Compatibility aliases for the current Orderflow/docs migration.
            "structure_anchor_sequence": structure_sequence,
            "recent_structure_anchor_points": structure_sequence,
            "structure_anchor_probe": structure_probe,
            # timestamps for P/D line drawing on the chart
            "phase_start_ts": self._phase_start_ts.isoformat() if self._phase_start_ts is not None else None,
            "range_high_ts": self._range_high_ts.isoformat() if self._range_high_ts is not None else None,
            "range_low_ts":  self._range_low_ts.isoformat()  if self._range_low_ts  is not None else None,
        }

    # ── internal ──────────────────────────────────────────────────────

    def _sb_warmup(
        self, close: float, ts: pd.Timestamp, bar_high: float, bar_low: float
    ) -> ScEvent | None:
        """Warmup (NEUTRAL): SC fires against registry — most recently confirmed PE pivot."""
        if self._registry_high is not None and close > self._registry_high.price:
            level = self._registry_high
            anchor_price = self._range_low if self._range_low is not None else bar_low
            anchor_ts = self._range_low_ts or ts
            self._registry_high = None
            self._warmup_complete = True
            self._start_bullish(
                ts,
                anchor_price,
                bar_high,
                range_low_ts=anchor_ts,
            )
            # Consume the warmup pivot so it cannot also fire an iSb on this bar or later.
            if self._latest_level_high is not None:
                self._last_isb_level_id = self._latest_level_high.level_id
            self._record_structure_point(
                "low",
                "range_origin",
                anchor_price,
                anchor_ts,
                ts,
                self._sc_up_code,
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
                choch=False,
            )
            self._last_sc = sc
            return sc

        if self._registry_low is not None and close < self._registry_low.price:
            level = self._registry_low
            anchor_price = self._range_high if self._range_high is not None else bar_high
            anchor_ts = self._range_high_ts or ts
            self._registry_low = None
            self._warmup_complete = True
            self._start_bearish(
                ts,
                anchor_price,
                bar_low,
                range_high_ts=anchor_ts,
            )
            # Consume the warmup pivot so it cannot also fire an iSb on this bar or later.
            if self._latest_level_low is not None:
                self._last_isb_level_id = self._latest_level_low.level_id
            self._record_structure_point(
                "high",
                "range_origin",
                anchor_price,
                anchor_ts,
                ts,
                self._sc_dn_code,
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
                choch=False,
            )
            self._last_sc = sc
            return sc

        return None

    def _sb_range(
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
                prior_high_ts = self._range_high_ts or ts
                prior_low = self._range_low
                self._record_structure_point(
                    "high",
                    "reversal_ceiling",
                    prior_high,
                    prior_high_ts,
                    ts,
                    self._sc_dn_code,
                )
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
                self._confirm_structure_attempt(ts)
                self._record_structure_point(
                    "low",
                    "range_origin",
                    new_floor,
                    new_floor_ts,
                    ts,
                    self._sc_up_code,
                )
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
                prior_low_ts = self._range_low_ts or ts
                self._record_structure_point(
                    "low",
                    "reversal_floor",
                    prior_low,
                    prior_low_ts,
                    ts,
                    self._sc_up_code,
                )
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
                self._confirm_structure_attempt(ts)
                self._record_structure_point(
                    "high",
                    "range_origin",
                    new_ceiling,
                    new_ceiling_ts,
                    ts,
                    self._sc_dn_code,
                )
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
            choch=bias_flip,
            prior_anchor_high=prior_high if bias_flip else None,
            prior_anchor_low=prior_low if bias_flip else None,
        )

    def _level_id(self, pe: PivotEvent) -> str:
        return ":".join(
            [
                pe.event_code,
                pe.pivot_timestamp.isoformat(),
                pe.event_timestamp.isoformat(),
                f"{float(pe.pivot_price):.6f}",
            ]
        )

    def _remember_structure_level(self, pe: PivotEvent, side: str) -> StructureLevel:
        level = StructureLevel(
            level_id=self._level_id(pe),
            event_code=pe.event_code,
            tier=pe.tier,
            side=side,
            price=float(pe.pivot_price),
            pivot_time=pe.pivot_timestamp,
            confirmed_at=pe.event_timestamp,
            relation=pe.relation,
        )
        self._recent_levels.append(level)
        if len(self._recent_levels) > self._recent_level_limit:
            self._recent_levels = self._recent_levels[-self._recent_level_limit :]
        if side == "high":
            self._latest_level_high = level
        else:
            self._latest_level_low = level
        return level

    def _sequence_point_id(
        self,
        side: StructureSequenceSide,
        price: float,
        timestamp: pd.Timestamp,
        confirmed_at: pd.Timestamp,
        source_transition: str,
    ) -> str:
        return ":".join(
            [
                self._tf,
                side,
                source_transition,
                timestamp.isoformat(),
                confirmed_at.isoformat(),
                f"{float(price):.6f}",
            ]
        )

    def _record_structure_point(
        self,
        side: StructureSequenceSide,
        role: str,
        price: float,
        timestamp: pd.Timestamp,
        confirmed_at: pd.Timestamp,
        source_transition: str,
        *,
        source_event_id: str | None = None,
    ) -> StructureSequencePoint:
        point = StructureSequencePoint(
            point_id=self._sequence_point_id(side, price, timestamp, confirmed_at, source_transition),
            timeframe=self._tf,
            side=side,
            role=role,
            price=float(price),
            timestamp=timestamp,
            confirmed_at=confirmed_at,
            source_transition=source_transition,
            source_event_id=source_event_id,
        )

        if self._structure_sequence and self._structure_sequence[-1].side == side:
            self._structure_sequence[-1] = point
        else:
            self._structure_sequence.append(point)

        if len(self._structure_sequence) > self._structure_sequence_limit:
            self._structure_sequence = self._structure_sequence[-self._structure_sequence_limit :]
        return point

    def _structure_probe(self, current_price: float) -> dict[str, Any] | None:
        if self._bias == "neutral":
            return None

        side: StructureSequenceSide
        role: str
        price: float | None = None
        timestamp: pd.Timestamp | None = None

        if self._phase == "open":
            if self._bias == "bullish":
                side = "high"
                role = "extension_probe"
                price = self._range_high
                timestamp = self._range_high_ts
            else:
                side = "low"
                role = "extension_probe"
                price = self._range_low
                timestamp = self._range_low_ts
        elif self._phase == "pullback_confirmed":
            if self._bias == "bullish":
                side = "low"
                role = "pullback_probe"
                price = self._pullback_low if self._pullback_low is not None else current_price
                timestamp = self._pullback_low_ts or self._pullback_confirmed_ts
            else:
                side = "high"
                role = "pullback_probe"
                price = self._pullback_high if self._pullback_high is not None else current_price
                timestamp = self._pullback_high_ts or self._pullback_confirmed_ts
        else:
            return None

        if price is None:
            return None
        evaluated_at = timestamp or self._phase_start_ts
        return {
            "point_id": ":".join(
                [
                    "probe",
                    self._tf,
                    side,
                    role,
                    evaluated_at.isoformat() if evaluated_at is not None else "NA",
                    f"{float(price):.6f}",
                ]
            ),
            "timeframe": self._tf,
            "side": side,
            "role": role,
            "price": round(float(price), 6),
            "timestamp": evaluated_at.isoformat() if evaluated_at is not None else None,
            "evaluated_at": evaluated_at.isoformat() if evaluated_at is not None else None,
            "confirmed": False,
            "source": "structure_live_probe",
        }

    def _orderflow_anchor_point(self, point: StructureSequencePoint) -> dict[str, Any]:
        source = point.to_dict()
        return {
            **source,
            "point_id": f"OFANCH:{source['point_id']}",
            "anchor_id": f"OFANCH:{source['point_id']}",
            "source_store": "structure_sequence",
            "source_structure_point_id": source["point_id"],
            "source": "orderflow_anchor_sequence",
        }

    def _orderflow_probe(self, structure_probe: dict[str, Any] | None) -> dict[str, Any] | None:
        if not structure_probe:
            return None
        point_id = str(structure_probe.get("point_id") or "unknown")
        return {
            **structure_probe,
            "point_id": f"OFPROBE:{point_id}",
            "probe_id": f"OFPROBE:{point_id}",
            "source_store": "structure_probe",
            "source_structure_probe_id": point_id,
            "source": "orderflow_probe",
        }

    def _maybe_open_pro_attempt_from_break(
        self,
        bar_high: float,
        bar_low: float,
        ts: pd.Timestamp,
    ) -> None:
        if not self._warmup_complete or self._bias == "neutral":
            return

        if self._bias == "bullish":
            trigger = self._latest_level_high
            anchor = self._latest_level_low
            if trigger is None or anchor is None:
                return
            if bar_high <= trigger.price:
                return
            if not self._can_open_or_replace_attempt("bullish", anchor):
                return
            self._open_pro_attempt(anchor, "bullish", "unclean_orderflow_attempt", "unclean", bar_high, ts)
            return

        if self._bias == "bearish":
            trigger = self._latest_level_low
            anchor = self._latest_level_high
            if trigger is None or anchor is None:
                return
            if bar_low >= trigger.price:
                return
            if not self._can_open_or_replace_attempt("bearish", anchor):
                return
            self._open_pro_attempt(anchor, "bearish", "unclean_orderflow_attempt", "unclean", bar_low, ts)
            return

    def _can_open_or_replace_attempt(self, direction: str, anchor: StructureLevel) -> bool:
        attempt = self._structure_attempt
        if attempt is None or attempt.status != "active":
            return True
        if attempt.direction != direction:
            return True
        if attempt.anchor_level_id == anchor.level_id:
            return False
        return anchor.confirmed_at >= attempt.started_at

    def _open_pro_attempt(
        self,
        anchor: StructureLevel,
        direction: str,
        origin: str,
        orderflow_quality: str,
        extreme_price: float,
        ts: pd.Timestamp,
    ) -> None:
        self._structure_attempt = StructureAttempt(
            attempt_id=f"pro:{origin}:{anchor.level_id}",
            direction=direction,
            alignment="pro",
            origin=origin,
            orderflow_quality=orderflow_quality,
            anchor_level_id=anchor.level_id,
            anchor_price=anchor.price,
            started_at=ts,
            extreme_price=float(extreme_price),
            status="active",
        )

    def _update_structure_attempt(
        self,
        bar_high: float,
        bar_low: float,
        close: float,
        ts: pd.Timestamp,
    ) -> None:
        attempt = self._structure_attempt
        if attempt is None or attempt.status != "active":
            return

        if attempt.started_at == ts:
            if attempt.direction == "bullish":
                attempt.extreme_price = max(attempt.extreme_price, bar_high)
            elif attempt.direction == "bearish":
                attempt.extreme_price = min(attempt.extreme_price, bar_low)
            return

        if attempt.direction == "bullish":
            attempt.extreme_price = max(attempt.extreme_price, bar_high)
            if bar_low < attempt.anchor_price:
                attempt.status = "failed"
                attempt.failed_at = ts
                attempt.failure_reason = "traded_below_itr_low"
        elif attempt.direction == "bearish":
            attempt.extreme_price = min(attempt.extreme_price, bar_low)
            if bar_high > attempt.anchor_price:
                attempt.status = "failed"
                attempt.failed_at = ts
                attempt.failure_reason = "traded_above_itr_high"

    def _confirm_structure_attempt(self, ts: pd.Timestamp) -> None:
        attempt = self._structure_attempt
        if attempt is None or attempt.status != "active":
            return
        attempt.status = "confirmed"

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
        self._last_isb_level_id = None
        self._last_ichoch_level_id = None

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
        self._last_isb_level_id = None
        self._last_ichoch_level_id = None

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
        if self._bias == "bullish" and self._range_high is not None:
            self._record_structure_point(
                "high",
                "extension_extreme",
                self._range_high,
                self._range_high_ts or ts,
                ts,
                "pullback_confirmed",
            )
        elif self._bias == "bearish" and self._range_low is not None:
            self._record_structure_point(
                "low",
                "extension_extreme",
                self._range_low,
                self._range_low_ts or ts,
                ts,
                "pullback_confirmed",
            )
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

    # ── Internal iSb / iChoCh (SC05–SC08) ────────────────────────────

    def _sb_internal(self, close: float, ts: pd.Timestamp) -> ScEvent | None:
        """Post-warmup: fire iSb or iChoCh against confirmed ITR/LTR pivot levels.

        iSb   — pro-bias close through a confirmed pivot (HH for bullish, LL for bearish).
        iChoCh — counter-bias close through the opposite confirmed pivot (breaks HL/LH).

        Pure observation: does not change bias, phase, or P/D range.
        At most one internal SC per bar; iSb is checked before iChoCh.
        """
        if not self._warmup_complete or self._bias == "neutral":
            return None
        if self._tier == "ltr":  # SC07/SC08 disabled; ITR-only
            return None

        lh = self._latest_level_high
        ll = self._latest_level_low

        if self._bias == "bullish":
            # iSb: close above latest confirmed ITR high AND it is a HH
            if lh and close > lh.price and self._last_isb_level_id != lh.level_id:
                if self._is_hh_or_seed(lh):
                    self._last_isb_level_id = lh.level_id
                    sc = self._make_isc(ts, lh, "high", "up", choch=False)
                    self._last_isc = sc
                    return sc
            # iChoCh: close below latest confirmed ITR low (breaks HL)
            if ll and close < ll.price and self._last_ichoch_level_id != ll.level_id:
                self._last_ichoch_level_id = ll.level_id
                sc = self._make_isc(ts, ll, "low", "down", choch=True)
                self._last_isc = sc
                return sc

        elif self._bias == "bearish":
            # iSb: close below latest confirmed ITR low AND it is a LL
            if ll and close < ll.price and self._last_isb_level_id != ll.level_id:
                if self._is_ll_or_seed(ll):
                    self._last_isb_level_id = ll.level_id
                    sc = self._make_isc(ts, ll, "low", "down", choch=False)
                    self._last_isc = sc
                    return sc
            # iChoCh: close above latest confirmed ITR high (breaks LH)
            if lh and close > lh.price and self._last_ichoch_level_id != lh.level_id:
                self._last_ichoch_level_id = lh.level_id
                sc = self._make_isc(ts, lh, "high", "up", choch=True)
                self._last_isc = sc
                return sc

        return None

    def _is_hh_or_seed(self, level: StructureLevel) -> bool:
        """True if the given ITR high is higher than the previous same-side ITR level,
        or if there is no previous (seed case — first iSb is always valid)."""
        prev = next(
            (lvl for lvl in reversed(self._recent_levels)
             if lvl.side == "high" and lvl.level_id != level.level_id),
            None,
        )
        return prev is None or level.price > prev.price

    def _is_ll_or_seed(self, level: StructureLevel) -> bool:
        """True if the given ITR low is lower than the previous same-side ITR level,
        or if there is no previous (seed case)."""
        prev = next(
            (lvl for lvl in reversed(self._recent_levels)
             if lvl.side == "low" and lvl.level_id != level.level_id),
            None,
        )
        return prev is None or level.price < prev.price

    def _make_isc(
        self,
        ts: pd.Timestamp,
        level: StructureLevel,
        level_side: str,
        break_direction: str,
        *,
        choch: bool,
    ) -> ScEvent:
        """Build a SC05–SC08 internal ScEvent against a confirmed ITR/LTR pivot level."""
        code = self._sc_ichoch_code if choch else self._sc_isb_code
        name = self._sc_ichoch_name if choch else self._sc_isb_name
        return ScEvent(
            event_code=code,
            event_name=name,
            event_group="SC",
            event_timestamp=ts,
            level_tier=self._tier,
            level_timestamp=level.pivot_time,
            level_price=level.price,
            level_side=level_side,
            break_direction=break_direction,
            bias_flip=False,
            choch=choch,
            is_internal=True,
        )
