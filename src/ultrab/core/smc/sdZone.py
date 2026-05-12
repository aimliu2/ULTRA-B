from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from ultrab.core.smc.candleEvent import FvgEvent


FvgDirection = Literal["demand", "supply"]


@dataclass
class _BarRecord:
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float


@dataclass
class SDZone:
    zone_id: str
    direction: FvgDirection
    high: float
    low: float
    drawing_mode: Literal["pivot"]
    timeframe: str
    created_at: pd.Timestamp
    anchor_ts: pd.Timestamp       # bar2 timestamp — x-start of rectangle on chart
    in_zone: bool = False         # True = TAPPED state


@dataclass
class ResolvedSDZone:
    zone_id: str
    timeframe: str
    direction: FvgDirection
    resolution: Literal["bounced", "liquidity_run", "liquidity_swept"]
    resolved_at: pd.Timestamp
    high: float
    low: float
    created_at: pd.Timestamp
    anchor_ts: pd.Timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "resolution": self.resolution,
            "resolved_at": self.resolved_at.isoformat(),
            "high": round(self.high, 6),
            "low": round(self.low, 6),
            "created_at": self.created_at.isoformat(),
            "anchor_ts": self.anchor_ts.isoformat(),
        }


class SDZoneStore:
    def __init__(self, max_zones: int) -> None:
        self._max = max_zones
        self._zones: dict[str, SDZone] = {}

    def register(self, zone: SDZone) -> None:
        self._zones[zone.zone_id] = zone
        self._enforce_cap(zone.direction)

    def _enforce_cap(self, direction: FvgDirection) -> None:
        while True:
            active = self.get_active(direction)
            if len(active) <= self._max:
                break
            watching = [z for z in active if not z.in_zone]
            if not watching:
                break  # all TAPPED — hold, do not evict
            oldest = min(watching, key=lambda z: z.created_at)
            del self._zones[oldest.zone_id]

    def transition_to_tapped(self, zone_id: str) -> None:
        if zone_id in self._zones:
            self._zones[zone_id].in_zone = True

    def mitigate(self, zone_id: str, reason: str) -> None:  # noqa: ARG002
        if zone_id in self._zones:
            self._zones.pop(zone_id)

    def contains(self, zone_id: str) -> bool:
        return zone_id in self._zones

    def get(self, zone_id: str) -> SDZone | None:
        return self._zones.get(zone_id)

    def get_active(self, direction: FvgDirection) -> list[SDZone]:
        return sorted(
            [z for z in self._zones.values() if z.direction == direction],
            key=lambda z: z.created_at,
            reverse=True,
        )

    def all_active(self) -> list[SDZone]:
        return sorted(self._zones.values(), key=lambda z: z.created_at, reverse=True)


@dataclass
class SDZoneBarResult:
    created: list[SDZone]
    mitigated: list[str]    # zone_ids removed this bar
    resolved: list[ResolvedSDZone] = field(default_factory=list)


class SDZoneEngine:
    """
    Pivot-mode SD zone engine.

    Triggered by CE02 events. For each CE02 fires:
      1. Backward trace from confirmation bar (bar3) to find ex_bar (swing extreme).
      2. Zone guard: skip if ex_bar matches the most recently drawn zone (same direction).
      3. Compute zone H/L from [ex_bar-1 … bar1, anchor_bar(asymmetric)].
      4. Register zone in state store.

    Detector runs every bar (deep model):
      WATCHING → gap-past detection → TAPPED
      TAPPED   → liquidity_run / liquidity_swept / bounced → EXPIRED
    """

    def __init__(self, config: dict[str, Any], timeframe: str) -> None:
        self._tf = timeframe
        self._store = SDZoneStore(int(config.get("max_zones_per_direction", 10)))
        self._bars: list[_BarRecord] = []
        self._ts_to_idx: dict[str, int] = {}
        self._last_ex_bar_ts: dict[FvgDirection, pd.Timestamp | None] = {
            "demand": None,
            "supply": None,
        }
        self._mitigated_this_bar: list[str] = []
        self._resolved_this_bar: list[ResolvedSDZone] = []
        self._last_resolved_zone: ResolvedSDZone | None = None
        self._created_this_bar: list[SDZone] = []

    def on_bar(self, row: pd.Series, ce02_events: list[FvgEvent]) -> SDZoneBarResult:
        ts = row.name
        bar = _BarRecord(
            timestamp=ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        self._mitigated_this_bar = []
        self._resolved_this_bar = []
        self._created_this_bar = []

        self._bars.append(bar)
        self._ts_to_idx[ts.isoformat()] = len(self._bars) - 1

        for event in ce02_events:
            self._try_draw_zone(event)

        self._run_detector(bar)

        return SDZoneBarResult(
            created=list(self._created_this_bar),
            mitigated=list(self._mitigated_this_bar),
            resolved=list(self._resolved_this_bar),
        )

    # ── zone drawing ──────────────────────────────────────────────────

    def _try_draw_zone(self, event: FvgEvent) -> None:
        if event.bar3_timestamp is None:
            return

        direction: FvgDirection = "demand" if event.fvg_type == "rally" else "supply"
        bar3_iso = event.bar3_timestamp.isoformat()
        if bar3_iso not in self._ts_to_idx:
            return

        ex_bar_idx = self._find_ex_bar_idx(bar3_iso, direction)
        ex_bar = self._bars[ex_bar_idx]

        # zone guard — deduplication per direction
        if (
            self._last_ex_bar_ts[direction] is not None
            and ex_bar.timestamp == self._last_ex_bar_ts[direction]
        ):
            return

        # ex_bar-1 required; idx 0 = warm-up edge, cannot draw
        if ex_bar_idx == 0:
            return
        ex_bar_minus1 = self._bars[ex_bar_idx - 1]

        bar1_iso = event.bar1_timestamp.isoformat()
        bar2_iso = event.bar2_timestamp.isoformat()
        if bar1_iso not in self._ts_to_idx or bar2_iso not in self._ts_to_idx:
            return

        bar1_idx = self._ts_to_idx[bar1_iso]
        anchor_bar = self._bars[self._ts_to_idx[bar2_iso]]

        window = self._bars[ex_bar_idx : bar1_idx + 1]

        if not window:
            # Engulfing exception: ex_bar landed on the anchor bar (bar2) itself.
            # Window collapses — zone is bounded by ex_bar_minus1's far edge and ex_bar's extreme.
            if direction == "demand":
                zone_high = ex_bar_minus1.high  # floor of FVG = prior bar's high
                zone_low = ex_bar.low            # engulfing bar's extreme low
            else:
                zone_high = ex_bar.high          # engulfing bar's extreme high
                zone_low = ex_bar_minus1.low     # floor of FVG = prior bar's low
            if zone_high <= zone_low:
                return
        elif direction == "demand":
            # HIGH = max(ex_bar-1.high, ex_bar.high … bar1.high)
            # LOW  = min(ex_bar.low … bar1.low, anchor_bar.low)
            high_candidates = [ex_bar_minus1.high, *(b.high for b in window)]
            if event.gap_top is not None:
                gap_top = float(event.gap_top)
                high_candidates = [price for price in high_candidates if price <= gap_top]
            if not high_candidates:
                return
            zone_high = max(high_candidates)
            zone_low = min(min(b.low for b in window), anchor_bar.low)
        else:
            # HIGH = max(ex_bar.high … bar1.high, anchor_bar.high)
            # LOW  = min(ex_bar-1.low, ex_bar.low … bar1.low)
            zone_high = max(max(b.high for b in window), anchor_bar.high)
            low_candidates = [ex_bar_minus1.low, *(b.low for b in window)]
            if event.gap_bottom is not None:
                gap_bottom = float(event.gap_bottom)
                low_candidates = [price for price in low_candidates if price >= gap_bottom]
            if not low_candidates:
                return
            zone_low = min(low_candidates)

        zone = SDZone(
            zone_id=f"SD-{self._tf}-{event.bar2_timestamp.isoformat()}",
            direction=direction,
            high=zone_high,
            low=zone_low,
            drawing_mode="pivot",
            timeframe=self._tf,
            created_at=event.event_timestamp,
            anchor_ts=event.bar2_timestamp,
        )
        self._store.register(zone)
        self._created_this_bar.append(zone)
        self._last_ex_bar_ts[direction] = ex_bar.timestamp

    def _find_ex_bar_idx(self, start_ts_iso: str, direction: FvgDirection) -> int:
        cursor = self._ts_to_idx[start_ts_iso]
        while cursor > 0:
            prev = cursor - 1
            if direction == "demand":
                if self._bars[prev].low < self._bars[cursor].low:
                    cursor = prev
                else:
                    break
            else:
                if self._bars[prev].high > self._bars[cursor].high:
                    cursor = prev
                else:
                    break
        return cursor

    # ── detector ─────────────────────────────────────────────────────

    def _run_detector(self, bar: _BarRecord) -> None:
        for direction in ("demand", "supply"):
            for zone in list(self._store.get_active(direction)):  # type: ignore[arg-type]
                self._check_zone(zone, bar)

    def _mitigate(
        self,
        zone_id: str,
        reason: Literal["bounced", "liquidity_run", "liquidity_swept"],
        resolved_at: pd.Timestamp,
    ) -> None:
        zone = self._store.get(zone_id)
        if zone is not None:
            resolved = ResolvedSDZone(
                zone_id=zone.zone_id,
                timeframe=zone.timeframe,
                direction=zone.direction,
                resolution=reason,
                resolved_at=resolved_at,
                high=zone.high,
                low=zone.low,
                created_at=zone.created_at,
                anchor_ts=zone.anchor_ts,
            )
            self._resolved_this_bar.append(resolved)
            self._last_resolved_zone = resolved
        self._store.mitigate(zone_id, reason)
        self._mitigated_this_bar.append(zone_id)

    def _check_zone(self, zone: SDZone, bar: _BarRecord) -> None:
        if not zone.in_zone:
            # WATCHING
            if zone.direction == "demand":
                if bar.open < zone.low:
                    # gap past floor
                    reason = "liquidity_run" if bar.close < zone.low else "liquidity_swept"
                    self._mitigate(zone.zone_id, reason, bar.timestamp)
                    return
                if bar.low <= zone.high:
                    self._store.transition_to_tapped(zone.zone_id)
                    # fall through to TAPPED resolution on same bar
                else:
                    return
            else:  # supply
                if bar.open > zone.high:
                    # gap past ceiling
                    reason = "liquidity_run" if bar.close > zone.high else "liquidity_swept"
                    self._mitigate(zone.zone_id, reason, bar.timestamp)
                    return
                if bar.high >= zone.low:
                    self._store.transition_to_tapped(zone.zone_id)
                else:
                    return

        # TAPPED (or just transitioned this bar)
        if not self._store.contains(zone.zone_id):
            return

        if zone.direction == "demand":
            if bar.close < zone.low:
                self._mitigate(zone.zone_id, "liquidity_run", bar.timestamp)
            elif bar.low < zone.low and bar.close >= zone.low:
                self._mitigate(zone.zone_id, "liquidity_swept", bar.timestamp)
            elif bar.close > zone.high:
                self._mitigate(zone.zone_id, "bounced", bar.timestamp)
        else:
            if bar.close > zone.high:
                self._mitigate(zone.zone_id, "liquidity_run", bar.timestamp)
            elif bar.high > zone.high and bar.close <= zone.high:
                self._mitigate(zone.zone_id, "liquidity_swept", bar.timestamp)
            elif bar.close < zone.low:
                self._mitigate(zone.zone_id, "bounced", bar.timestamp)

    # ── snapshot ──────────────────────────────────────────────────────

    def get_zone_snapshot(self, current_price: float) -> list[dict[str, Any]]:
        result = []
        for zone in self._store.all_active():
            distance = (
                current_price - zone.high
                if zone.direction == "demand"
                else zone.low - current_price
            )
            result.append({
                "zone_id": zone.zone_id,
                "direction": zone.direction,
                "high": round(zone.high, 6),
                "low": round(zone.low, 6),
                "in_zone": zone.in_zone,
                "drawing_mode": zone.drawing_mode,
                "timeframe": zone.timeframe,
                "created_at": zone.created_at.isoformat(),
                "anchor_ts": zone.anchor_ts.isoformat(),
                "anchor_unix": int(zone.anchor_ts.timestamp()),
                "distance": round(distance, 6),
            })
        return result

    def get_last_resolved_zone_snapshot(self) -> dict[str, Any] | None:
        return self._last_resolved_zone.to_dict() if self._last_resolved_zone else None
