from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from ultrab.core.smc.candleEvent import FvgEvent
from ultrab.core.smc.pivotEvent import PivotEvent


LiquiditySide = Literal["buy_side", "sell_side"]
LiquidityDirection = Literal["bearish", "bullish"]
PoolKind = Literal["htf_pd", "htf_eq", "htf_itr"]
PoolVariant = Literal["level", "eq"]


def _iso(ts: pd.Timestamp | None) -> str | None:
    return ts.isoformat() if ts is not None else None


def _round_price(value: float | None) -> float | None:
    return round(float(value), 6) if value is not None else None


def _liquidity_event_id(pool_id: str, confirmed_at: pd.Timestamp | None) -> str | None:
    return f"{pool_id}|{confirmed_at.isoformat()}" if confirmed_at is not None else None


@dataclass
class LiquidityEvent:
    event_type: str
    pool_id: str
    pool_kind: PoolKind
    variant: PoolVariant | None
    source: str
    side: LiquiditySide
    direction: LiquidityDirection
    level_price: float
    timestamp: pd.Timestamp
    confirmed_by: str | None = None
    take_type: str | None = None
    scope: str | None = None
    htf_pd_epoch_id: str | None = None
    liquidity_event_id: str | None = None
    is_triggerable: bool = False
    came_from: str | None = None
    left_to: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "pool_id": self.pool_id,
            "pool_kind": self.pool_kind,
            "variant": self.variant,
            "source": self.source,
            "side": self.side,
            "direction": self.direction,
            "level_price": _round_price(self.level_price),
            "timestamp": self.timestamp.isoformat(),
            "bar_time": self.timestamp.isoformat(),
            "confirmed_by": self.confirmed_by,
            "take_type": self.take_type,
            "scope": self.scope,
            "htf_pd_epoch_id": self.htf_pd_epoch_id,
            "liquidity_event_id": self.liquidity_event_id,
            "is_triggerable": self.is_triggerable,
            "came_from": self.came_from,
            "left_to": self.left_to,
        }


@dataclass
class LiquidityPool:
    pool_id: str
    pool_kind: PoolKind
    source: str
    side: LiquiditySide
    direction: LiquidityDirection
    price: float
    created_at: pd.Timestamp
    variant: PoolVariant | None = None
    tolerance: float = 0.0
    upper: float | None = None
    lower: float | None = None
    scope: str = "active_current_epoch"
    status: str = "active"
    last_interaction_at: pd.Timestamp | None = None
    taken_at: pd.Timestamp | None = None
    taken_lower_index: int | None = None
    reclaimed_at: pd.Timestamp | None = None
    reclaimed_price: float | None = None
    confirmed_at: pd.Timestamp | None = None
    confirmed_lower_index: int | None = None
    confirmed_higher_index: int | None = None
    take_type: str | None = None
    confirmed_by: str | None = None
    anchor_run_at: pd.Timestamp | None = None
    anchor_run_lower_index: int | None = None
    anchor_run_take_type: str | None = None
    evidence: dict[str, bool] = field(default_factory=dict)
    htf_bias: str | None = None
    htf_pd_epoch_id: str | None = None
    eq_tolerance: float | None = None
    created_higher_index: int | None = None
    approached_from: str | None = None
    left_to: str | None = None
    archived_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool_id": self.pool_id,
            "pool_kind": self.pool_kind,
            "variant": self.variant,
            "source": self.source,
            "side": self.side,
            "direction": self.direction,
            "price": _round_price(self.price),
            "level_price": _round_price(self.price),
            "tolerance": _round_price(self.tolerance),
            "upper": _round_price(self.upper),
            "lower": _round_price(self.lower),
            "scope": self.scope,
            "status": self.status,
            "created_at": _iso(self.created_at),
            "last_interaction_at": _iso(self.last_interaction_at),
            "taken_at": _iso(self.taken_at),
            "taken_lower_index": self.taken_lower_index,
            "reclaimed_at": _iso(self.reclaimed_at),
            "reclaimed_price": _round_price(self.reclaimed_price),
            "confirmed_at": _iso(self.confirmed_at),
            "liquidity_event_id": _liquidity_event_id(self.pool_id, self.confirmed_at),
            "confirmed_higher_index": self.confirmed_higher_index,
            "take_type": self.take_type,
            "confirmed_by": self.confirmed_by,
            "anchor_run_at": _iso(self.anchor_run_at),
            "anchor_run_lower_index": self.anchor_run_lower_index,
            "anchor_run_take_type": self.anchor_run_take_type,
            "evidence": dict(self.evidence),
            "htf_bias": self.htf_bias,
            "htf_pd_epoch_id": self.htf_pd_epoch_id,
            "eq_tolerance": _round_price(self.eq_tolerance),
            "created_higher_index": self.created_higher_index,
            "approached_from": self.approached_from,
            "left_to": self.left_to,
            "archived_reason": self.archived_reason,
        }


class LiquidityContextEngine:
    """
    Layer 3 liquidity memory for the dual-timeframe runtime.

    HTF creates the levels: P/D range boundaries and EQH/EQL pools. The LTF
    heartbeat observes the lifecycle at those remembered levels without waiting
    for the next HTF close.
    """

    def __init__(self, config: dict[str, Any] | None, lower_tf: str, higher_tf: str) -> None:
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.lower_tf = lower_tf
        self.higher_tf = higher_tf

        grab_cfg = cfg.get("grab", {})
        self.grab_evidence_window_bars = max(1, int(grab_cfg.get("evidence_window_bars", 8)))
        self.ready_ttl_bars = max(1, int(grab_cfg.get("ready_ttl_bars", 16)))
        self.event_log_limit = max(1, int(cfg.get("event_log_limit", 50)))

        eq_cfg = cfg.get("eq", {})
        self.eq_enabled = bool(eq_cfg.get("enabled", True))
        self.eq_atr_period = max(1, int(eq_cfg.get("atr_period", 14)))
        self.eq_threshold = float(eq_cfg.get("eq_threshold", 0.1))
        self.eq_pivot_tier = str(eq_cfg.get("pivot_tier", "itr")).lower()

        itr_cfg = cfg.get("itr", {})
        self.itr_enabled = bool(itr_cfg.get("enabled", True))
        self.itr_eq_enabled = bool(itr_cfg.get("eq_enabled", True))
        self.itr_pivot_tier = str(itr_cfg.get("pivot_tier", "itr")).lower()
        self.itr_eq_threshold = float(itr_cfg.get("eq_threshold", self.eq_threshold))

        memory_cfg = cfg.get("memory", {})
        self.carryover_recent_pools = max(0, int(memory_cfg.get("carryover_recent_pools", 3)))
        self.max_active_itr_pools_per_side = max(1, int(memory_cfg.get("max_active_itr_pools_per_side", 5)))
        self.max_pool_age_htf_bars = max(1, int(memory_cfg.get("max_pool_age_htf_bars", 50)))
        self.max_confirmed_anchor_watch_per_side = max(
            1,
            int(memory_cfg.get("max_confirmed_anchor_watch_per_side", 3)),
        )
        self.anchor_watch_ttl_htf_bars = max(1, int(memory_cfg.get("anchor_watch_ttl_htf_bars", 20)))

        self._pd_pools: dict[str, LiquidityPool] = {}
        self._eq_pools: dict[str, LiquidityPool] = {}
        self._itr_pools: dict[str, LiquidityPool] = {}
        self._events: list[LiquidityEvent] = []
        self._last_confirmed_pd: LiquidityPool | None = None
        self._last_confirmed_eq: LiquidityPool | None = None
        self._last_confirmed_itr: LiquidityPool | None = None
        self._last_itr_anchor_run: LiquidityPool | None = None
        self._last_htf_structure: dict[str, Any] | None = None

        self._prev_higher_close: float | None = None
        self._true_ranges: list[float] = []
        self._last_eq_high: PivotEvent | None = None
        self._last_eq_low: PivotEvent | None = None
        self._last_itr_eq_high: PivotEvent | None = None
        self._last_itr_eq_low: PivotEvent | None = None
        self._current_lower_index: int | None = None
        self._higher_index = 0
        self._current_epoch_id: str | None = None
        self._current_range_high: float | None = None
        self._current_range_low: float | None = None

    def on_higher_bar(
        self,
        row: pd.Series,
        pivot_events: list[PivotEvent],
        higher_structure: dict[str, Any] | None,
    ) -> None:
        if not self.enabled:
            return
        self._higher_index += 1
        self._update_atr(row)
        self.observe_higher_structure(higher_structure)
        if self.itr_enabled:
            self._observe_itr_pivots(pivot_events)
        if self.eq_enabled:
            self._observe_eq_pivots(pivot_events)
        self._archive_expired_pools()
        self._limit_confirmed_itr_anchor_watch()

    def observe_higher_structure(self, higher_structure: dict[str, Any] | None) -> None:
        if not self.enabled or not higher_structure:
            return
        self._last_htf_structure = higher_structure
        bias = higher_structure.get("bias")
        high = higher_structure.get("range_high")
        low = higher_structure.get("range_low")
        if bias not in {"bullish", "bearish"} or high is None or low is None:
            return

        epoch_id = self._htf_pd_epoch_id(higher_structure)
        epoch_changed = self._current_epoch_id != epoch_id
        self._current_epoch_id = epoch_id
        self._current_range_high = float(high)
        self._current_range_low = float(low)
        if epoch_changed:
            self._rescope_pd_pools(epoch_id)
            self._rescope_eq_pools()
            self._rescope_itr_pools()
        self._upsert_pd_pool(
            source="range_high",
            side="buy_side",
            direction="bearish",
            price=float(high),
            created_at=self._structure_timestamp(higher_structure, "range_high"),
            htf_bias=str(bias),
            epoch_id=epoch_id,
        )
        self._upsert_pd_pool(
            source="range_low",
            side="sell_side",
            direction="bullish",
            price=float(low),
            created_at=self._structure_timestamp(higher_structure, "range_low"),
            htf_bias=str(bias),
            epoch_id=epoch_id,
        )

    def on_lower_bar(
        self,
        row: pd.Series,
        ce02_events: list[FvgEvent] | None = None,
        lower_index: int | None = None,
    ) -> None:
        if not self.enabled:
            return
        self._current_lower_index = lower_index
        for pool in list(self._pd_pools.values()) + list(self._eq_pools.values()) + list(self._itr_pools.values()):
            self._observe_pool_interaction(pool, row, ce02_events or [], lower_index)
        self._limit_confirmed_itr_anchor_watch()

    def snapshot(self) -> dict[str, Any]:
        if not self.enabled:
            return {}
        pd_ready = self._pool_is_ready(self._last_confirmed_pd)
        eq_ready = self._pool_is_ready(self._last_confirmed_eq)
        itr_ready = self._pool_is_ready(self._last_confirmed_itr)
        itr_anchor_run_ready = self._itr_anchor_run_is_ready(self._last_itr_anchor_run)
        latest_pd = self._last_confirmed_pd if pd_ready else None
        latest_eq = self._last_confirmed_eq if eq_ready else None
        latest_itr = self._last_confirmed_itr if itr_ready else None
        latest_itr_anchor_run = self._last_itr_anchor_run if itr_anchor_run_ready else None

        payload: dict[str, Any] = {
            "htf_pd_epoch_id": self._current_epoch_id,
            "active_htf_pd_pools": [
                self._pool_snapshot(pool)
                for pool in self._pd_pools.values()
                if pool.status != "archived"
            ],
            "active_htf_eq_pools": [
                self._pool_snapshot(pool)
                for pool in self._eq_pools.values()
                if pool.status != "archived"
            ],
            "active_htf_itr_pools": [
                self._pool_snapshot(pool)
                for pool in self._itr_pools.values()
                if self._pool_belongs_to_current_triggerable_set(pool)
            ],
            "current_triggerable_liquidity_events": self._current_triggerable_liquidity_events(),
            "events": [event.to_dict() for event in self._events[-self.event_log_limit :]],
            "event_log": [event.to_dict() for event in self._events[-self.event_log_limit :]],
            "htf_pd_grab_reclaim_ready": bool(pd_ready),
            "htf_pd_grab_reclaim_side": latest_pd.side if latest_pd else None,
            "htf_pd_grab_reclaim_direction": latest_pd.direction if latest_pd else None,
            "htf_pd_grab_reclaim_level": _round_price(latest_pd.price) if latest_pd else None,
            "htf_pd_grab_reclaim_source": latest_pd.source if latest_pd else None,
            "htf_pd_grab_reclaim_pool_id": latest_pd.pool_id if latest_pd else None,
            "htf_pd_grab_reclaim_take_type": latest_pd.take_type if latest_pd else None,
            "htf_pd_grab_reclaim_taken_at": _iso(latest_pd.taken_at) if latest_pd else None,
            "htf_pd_grab_reclaim_reclaimed_at": _iso(latest_pd.reclaimed_at) if latest_pd else None,
            "htf_pd_grab_reclaim_confirmed_at": _iso(latest_pd.confirmed_at) if latest_pd else None,
            "htf_pd_grab_reclaim_confirmed_by": latest_pd.confirmed_by if latest_pd else None,
            "htf_eq_grab_reclaim_ready": bool(eq_ready),
            "htf_eq_grab_reclaim_side": latest_eq.side if latest_eq else None,
            "htf_eq_grab_reclaim_direction": latest_eq.direction if latest_eq else None,
            "htf_eq_grab_reclaim_level": _round_price(latest_eq.price) if latest_eq else None,
            "htf_eq_grab_reclaim_source": latest_eq.source if latest_eq else None,
            "htf_eq_grab_reclaim_pool_id": latest_eq.pool_id if latest_eq else None,
            "htf_eq_grab_reclaim_take_type": latest_eq.take_type if latest_eq else None,
            "htf_eq_grab_reclaim_taken_at": _iso(latest_eq.taken_at) if latest_eq else None,
            "htf_eq_grab_reclaim_reclaimed_at": _iso(latest_eq.reclaimed_at) if latest_eq else None,
            "htf_eq_grab_reclaim_confirmed_at": _iso(latest_eq.confirmed_at) if latest_eq else None,
            "htf_eq_grab_reclaim_confirmed_by": latest_eq.confirmed_by if latest_eq else None,
            "htf_itr_grab_reclaim_ready": bool(itr_ready),
            "htf_itr_grab_reclaim_variant": latest_itr.variant if latest_itr else None,
            "htf_itr_grab_reclaim_side": latest_itr.side if latest_itr else None,
            "htf_itr_grab_reclaim_direction": latest_itr.direction if latest_itr else None,
            "htf_itr_grab_reclaim_level": _round_price(latest_itr.price) if latest_itr else None,
            "htf_itr_grab_reclaim_source": latest_itr.source if latest_itr else None,
            "htf_itr_grab_reclaim_pool_id": latest_itr.pool_id if latest_itr else None,
            "htf_itr_grab_reclaim_take_type": latest_itr.take_type if latest_itr else None,
            "htf_itr_grab_reclaim_came_from": latest_itr.approached_from if latest_itr else None,
            "htf_itr_grab_reclaim_left_to": latest_itr.left_to if latest_itr else None,
            "htf_itr_grab_reclaim_taken_at": _iso(latest_itr.taken_at) if latest_itr else None,
            "htf_itr_grab_reclaim_reclaimed_at": _iso(latest_itr.reclaimed_at) if latest_itr else None,
            "htf_itr_grab_reclaim_confirmed_at": _iso(latest_itr.confirmed_at) if latest_itr else None,
            "htf_itr_grab_reclaim_confirmed_by": latest_itr.confirmed_by if latest_itr else None,
            "htf_itr_level_grab_reclaim_ready": bool(
                itr_ready and latest_itr is not None and latest_itr.variant == "level"
            ),
            "htf_itr_eq_grab_reclaim_ready": bool(
                itr_ready and latest_itr is not None and latest_itr.variant == "eq"
            ),
            "htf_itr_anchor_run_ready": bool(itr_anchor_run_ready),
            "htf_itr_anchor_run_variant": latest_itr_anchor_run.variant if latest_itr_anchor_run else None,
            "htf_itr_anchor_run_side": latest_itr_anchor_run.side if latest_itr_anchor_run else None,
            "htf_itr_anchor_run_direction": latest_itr_anchor_run.direction if latest_itr_anchor_run else None,
            "htf_itr_anchor_run_level": _round_price(latest_itr_anchor_run.price) if latest_itr_anchor_run else None,
            "htf_itr_anchor_run_source": latest_itr_anchor_run.source if latest_itr_anchor_run else None,
            "htf_itr_anchor_run_pool_id": latest_itr_anchor_run.pool_id if latest_itr_anchor_run else None,
            "htf_itr_anchor_run_take_type": latest_itr_anchor_run.anchor_run_take_type if latest_itr_anchor_run else None,
            "htf_itr_anchor_run_at": _iso(latest_itr_anchor_run.anchor_run_at) if latest_itr_anchor_run else None,
            "htf_itr_level_anchor_run_ready": bool(
                itr_anchor_run_ready
                and latest_itr_anchor_run is not None
                and latest_itr_anchor_run.variant == "level"
            ),
            "htf_itr_eq_anchor_run_ready": bool(
                itr_anchor_run_ready
                and latest_itr_anchor_run is not None
                and latest_itr_anchor_run.variant == "eq"
            ),
            "eq_atr_period": self.eq_atr_period,
            "eq_threshold": self.eq_threshold,
            "eq_tolerance": _round_price(self._eq_tolerance()),
        }
        payload.update(self._current_event_fields("htf_pd_grab_reclaim", latest_pd))
        payload.update(self._current_event_fields("htf_eq_grab_reclaim", latest_eq))
        payload.update(self._current_event_fields("htf_itr_grab_reclaim", latest_itr))
        payload.update(self._legacy_sweep_aliases(payload))
        return payload

    def _upsert_pd_pool(
        self,
        source: str,
        side: LiquiditySide,
        direction: LiquidityDirection,
        price: float,
        created_at: pd.Timestamp,
        htf_bias: str,
        epoch_id: str,
    ) -> None:
        pool_id = f"htf-pd-{self.higher_tf}-{epoch_id}-{source}-{price:.6f}"
        existing = self._pd_pools.get(pool_id)
        if existing is not None:
            return
        for pool in self._pd_pools.values():
            if pool.source == source:
                self._archive_pool(pool, "pd_boundary_replaced")
        self._pd_pools = {
            key: pool
            for key, pool in self._pd_pools.items()
            if pool.source != source
        }
        self._pd_pools[pool_id] = LiquidityPool(
            pool_id=pool_id,
            pool_kind="htf_pd",
            source=source,
            side=side,
            direction=direction,
            price=price,
            created_at=created_at,
            variant="level",
            htf_bias=htf_bias,
            htf_pd_epoch_id=epoch_id,
            created_higher_index=self._higher_index,
        )

    def _observe_eq_pivots(self, pivot_events: list[PivotEvent]) -> None:
        tolerance = self._eq_tolerance()
        if tolerance is None:
            for event in pivot_events:
                self._remember_eq_pivot(event)
            return
        for event in pivot_events:
            if str(event.tier).lower() != self.eq_pivot_tier:
                continue
            if event.pivot_side == 1:
                previous = self._last_eq_high
                if previous is not None and abs(event.pivot_price - previous.pivot_price) < tolerance:
                    self._create_eq_pool(previous, event, "buy_side", "bearish", tolerance)
            elif event.pivot_side == -1:
                previous = self._last_eq_low
                if previous is not None and abs(event.pivot_price - previous.pivot_price) < tolerance:
                    self._create_eq_pool(previous, event, "sell_side", "bullish", tolerance)
            self._remember_eq_pivot(event)

    def _remember_eq_pivot(self, event: PivotEvent) -> None:
        if str(event.tier).lower() != self.eq_pivot_tier:
            return
        if event.pivot_side == 1:
            self._last_eq_high = event
        elif event.pivot_side == -1:
            self._last_eq_low = event

    def _create_eq_pool(
        self,
        first: PivotEvent,
        second: PivotEvent,
        side: LiquiditySide,
        direction: LiquidityDirection,
        tolerance: float,
    ) -> None:
        source = "eqh" if side == "buy_side" else "eql"
        price = (float(first.pivot_price) + float(second.pivot_price)) / 2.0
        pool_id = (
            f"htf-eq-{self.higher_tf}-{source}-"
            f"{first.pivot_timestamp.isoformat()}-{second.pivot_timestamp.isoformat()}-{price:.6f}"
        )
        if pool_id in self._eq_pools:
            return
        self._eq_pools[pool_id] = LiquidityPool(
            pool_id=pool_id,
            pool_kind="htf_eq",
            source=source,
            side=side,
            direction=direction,
            price=price,
            created_at=second.event_timestamp,
            variant="eq",
            tolerance=tolerance,
            upper=price + tolerance,
            lower=price - tolerance,
            eq_tolerance=tolerance,
            htf_pd_epoch_id=self._current_epoch_id,
            created_higher_index=self._higher_index,
        )

    def _observe_itr_pivots(self, pivot_events: list[PivotEvent]) -> None:
        tolerance = self._itr_eq_tolerance()
        for event in pivot_events:
            if str(event.tier).lower() != self.itr_pivot_tier:
                continue
            self._create_itr_level_pool(event)
            if self.itr_eq_enabled and tolerance is not None:
                if event.pivot_side == 1:
                    previous = self._last_itr_eq_high
                    if previous is not None and abs(event.pivot_price - previous.pivot_price) < tolerance:
                        self._create_itr_eq_pool(previous, event, "buy_side", "bearish", tolerance)
                elif event.pivot_side == -1:
                    previous = self._last_itr_eq_low
                    if previous is not None and abs(event.pivot_price - previous.pivot_price) < tolerance:
                        self._create_itr_eq_pool(previous, event, "sell_side", "bullish", tolerance)
            self._remember_itr_eq_pivot(event)
        self._limit_itr_pools()

    def _create_itr_level_pool(self, event: PivotEvent) -> None:
        if self._current_epoch_id is None or not self._price_inside_current_range(float(event.pivot_price)):
            return
        if event.pivot_side == 1:
            side: LiquiditySide = "buy_side"
            direction: LiquidityDirection = "bearish"
            source = "htf_itr_high"
        else:
            side = "sell_side"
            direction = "bullish"
            source = "htf_itr_low"
        pool_id = (
            f"htf-itr-{self.higher_tf}-level-{event.event_code}-"
            f"{event.pivot_timestamp.isoformat()}-{event.event_timestamp.isoformat()}-{event.pivot_price:.6f}"
        )
        if pool_id in self._itr_pools:
            return
        self._itr_pools[pool_id] = LiquidityPool(
            pool_id=pool_id,
            pool_kind="htf_itr",
            source=source,
            side=side,
            direction=direction,
            price=float(event.pivot_price),
            created_at=event.event_timestamp,
            variant="level",
            htf_pd_epoch_id=self._current_epoch_id,
            created_higher_index=self._higher_index,
        )

    def _create_itr_eq_pool(
        self,
        first: PivotEvent,
        second: PivotEvent,
        side: LiquiditySide,
        direction: LiquidityDirection,
        tolerance: float,
    ) -> None:
        price = (float(first.pivot_price) + float(second.pivot_price)) / 2.0
        if self._current_epoch_id is None or not self._price_inside_current_range(price, tolerance):
            return
        source = "htf_itr_eqh" if side == "buy_side" else "htf_itr_eql"
        pool_id = (
            f"htf-itr-{self.higher_tf}-eq-{source}-"
            f"{first.pivot_timestamp.isoformat()}-{second.pivot_timestamp.isoformat()}-{price:.6f}"
        )
        if pool_id in self._itr_pools:
            return
        self._itr_pools[pool_id] = LiquidityPool(
            pool_id=pool_id,
            pool_kind="htf_itr",
            source=source,
            side=side,
            direction=direction,
            price=price,
            created_at=second.event_timestamp,
            variant="eq",
            tolerance=tolerance,
            upper=price + tolerance,
            lower=price - tolerance,
            htf_pd_epoch_id=self._current_epoch_id,
            eq_tolerance=tolerance,
            created_higher_index=self._higher_index,
        )

    def _remember_itr_eq_pivot(self, event: PivotEvent) -> None:
        if str(event.tier).lower() != self.itr_pivot_tier:
            return
        if event.pivot_side == 1:
            self._last_itr_eq_high = event
        elif event.pivot_side == -1:
            self._last_itr_eq_low = event

    def _observe_pool_interaction(
        self,
        pool: LiquidityPool,
        row: pd.Series,
        ce02_events: list[FvgEvent],
        lower_index: int | None,
    ) -> None:
        if pool.status == "liquidity_grab_confirmed":
            self._observe_confirmed_itr_anchor_run(pool, row, lower_index)
            return
        if not self._pool_can_trigger_hypothesis(pool):
            return
        if self._pool_expired_by_age(pool):
            self._archive_pool(pool, "max_pool_age_htf_bars")
            return
        ts = row.name
        if ts < pool.created_at:
            return
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        breached = high > self._breach_price(pool) if pool.side == "buy_side" else low < self._breach_price(pool)
        if not breached:
            self._update_approach_side(pool, float(row["open"]), close)
        if breached and pool.taken_at is None:
            if pool.pool_kind == "htf_itr" and not self._has_required_itr_trajectory(pool, row):
                return
            pool.taken_at = ts
            pool.taken_lower_index = lower_index
            pool.last_interaction_at = ts
            pool.take_type = self._take_type(pool, close)
            pool.status = "breached_outside_level"
            self._append_event("breached_outside_level", pool, ts)

        if pool.taken_at is None:
            return
        if self._grab_window_expired(pool, lower_index):
            self._reset_unconfirmed_grab(pool)
            return

        self._update_rejection_evidence(pool, row, ce02_events)
        if self._is_reclaimed(pool, close):
            pool.reclaimed_at = pool.reclaimed_at or ts
            pool.reclaimed_price = pool.reclaimed_price if pool.reclaimed_price is not None else close
            pool.last_interaction_at = ts
            pool.left_to = self._leave_side(pool)
            if pool.pool_kind == "htf_pd":
                pool.status = "reclaimed_inside_pd_range"
            elif pool.pool_kind == "htf_eq":
                pool.status = "reclaimed_inside_eq_range"
            else:
                pool.status = "reclaimed_to_origin_side"

        if self._can_confirm_grab(pool):
            pool.status = "liquidity_grab_confirmed"
            pool.confirmed_at = ts
            pool.confirmed_lower_index = lower_index
            pool.confirmed_higher_index = self._higher_index
            pool.confirmed_by = self._confirmed_by(pool)
            pool.last_interaction_at = ts
            if pool.pool_kind == "htf_pd":
                self._last_confirmed_pd = pool
            elif pool.pool_kind == "htf_eq":
                self._last_confirmed_eq = pool
            else:
                self._last_confirmed_itr = pool
            self._append_event("liquidity_grab_confirmed", pool, ts)
            self._limit_confirmed_itr_anchor_watch()

    def _observe_confirmed_itr_anchor_run(
        self,
        pool: LiquidityPool,
        row: pd.Series,
        lower_index: int | None,
    ) -> None:
        if pool.pool_kind != "htf_itr" or pool.anchor_run_at is not None:
            return
        if not self._pool_can_trigger_hypothesis(pool):
            return
        if lower_index is not None and pool.confirmed_lower_index is not None:
            if lower_index <= pool.confirmed_lower_index:
                return

        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        breached = high > self._breach_price(pool) if pool.side == "buy_side" else low < self._breach_price(pool)
        if not breached:
            return

        pool.anchor_run_at = row.name
        pool.anchor_run_lower_index = lower_index
        pool.anchor_run_take_type = self._take_type(pool, close)
        pool.last_interaction_at = row.name
        self._last_itr_anchor_run = pool
        self._append_event("confirmed_itr_anchor_run", pool, row.name)

    def _breach_price(self, pool: LiquidityPool) -> float:
        if pool.pool_kind in {"htf_eq", "htf_itr"} and pool.variant == "eq":
            if pool.side == "buy_side":
                return pool.price + pool.tolerance
            return pool.price - pool.tolerance
        return pool.price

    def _reclaim_price(self, pool: LiquidityPool) -> float:
        return pool.price

    def _update_approach_side(self, pool: LiquidityPool, open_: float, close: float) -> None:
        if pool.pool_kind != "htf_itr" or pool.taken_at is not None:
            return
        required = self._required_approach_side(pool)
        if self._price_side(pool, close) == required or self._price_side(pool, open_) == required:
            pool.approached_from = required

    def _has_required_itr_trajectory(self, pool: LiquidityPool, row: pd.Series) -> bool:
        required = self._required_approach_side(pool)
        if pool.approached_from == required:
            return True
        if self._price_side(pool, float(row["open"])) == required:
            pool.approached_from = required
            return True
        return False

    def _required_approach_side(self, pool: LiquidityPool) -> str:
        return "below" if pool.side == "buy_side" else "above"

    def _leave_side(self, pool: LiquidityPool) -> str:
        return "below" if pool.side == "buy_side" else "above"

    def _price_side(self, pool: LiquidityPool, price: float) -> str | None:
        if price > pool.price:
            return "above"
        if price < pool.price:
            return "below"
        return None

    def _take_type(self, pool: LiquidityPool, close: float) -> str:
        if pool.side == "buy_side" and close > self._breach_price(pool):
            return "close_run"
        if pool.side == "sell_side" and close < self._breach_price(pool):
            return "close_run"
        return "wick_sweep"

    def _is_reclaimed(self, pool: LiquidityPool, close: float) -> bool:
        if pool.side == "buy_side":
            return close < self._reclaim_price(pool)
        return close > self._reclaim_price(pool)

    def _update_rejection_evidence(
        self,
        pool: LiquidityPool,
        row: pd.Series,
        ce02_events: list[FvgEvent],
    ) -> None:
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        body = abs(close - open_)
        bar_range = max(high - low, 0.0)
        upper_wick = max(0.0, high - max(open_, close))
        lower_wick = max(0.0, min(open_, close) - low)

        evidence = pool.evidence
        if pool.side == "buy_side":
            if upper_wick >= max(body, bar_range * 0.25):
                evidence["rejection_wick"] = True
            if close < open_ and upper_wick >= max(body, bar_range * 0.2):
                evidence["hammer_like_rejection"] = True
            if any(event.fvg_type == "drop" for event in ce02_events):
                evidence["counter_fvg"] = True
            if close < self._reclaim_price(pool):
                evidence["close_back_inside"] = True
        else:
            if lower_wick >= max(body, bar_range * 0.25):
                evidence["rejection_wick"] = True
            if close > open_ and lower_wick >= max(body, bar_range * 0.2):
                evidence["hammer_like_rejection"] = True
            if any(event.fvg_type == "rally" for event in ce02_events):
                evidence["counter_fvg"] = True
            if close > self._reclaim_price(pool):
                evidence["close_back_inside"] = True

    def _can_confirm_grab(self, pool: LiquidityPool) -> bool:
        evidence = pool.evidence
        return bool(
            pool.taken_at is not None
            and pool.reclaimed_at is not None
            and evidence.get("close_back_inside")
            and (
                evidence.get("rejection_wick")
                or evidence.get("hammer_like_rejection")
                or evidence.get("counter_fvg")
            )
        )

    def _grab_window_expired(self, pool: LiquidityPool, lower_index: int | None) -> bool:
        if lower_index is None or pool.taken_lower_index is None:
            return False
        return lower_index - pool.taken_lower_index > self.grab_evidence_window_bars

    def _reset_unconfirmed_grab(self, pool: LiquidityPool) -> None:
        pool.status = "active"
        pool.last_interaction_at = None
        pool.taken_at = None
        pool.taken_lower_index = None
        pool.reclaimed_at = None
        pool.reclaimed_price = None
        pool.take_type = None
        pool.confirmed_by = None
        pool.evidence = {}

    def _confirmed_by(self, pool: LiquidityPool) -> str:
        keys = [
            key
            for key in ("rejection_wick", "hammer_like_rejection", "counter_fvg")
            if pool.evidence.get(key)
        ]
        if len(keys) > 1:
            return "mixed"
        return keys[0] if keys else "unknown"

    def _append_event(self, event_type: str, pool: LiquidityPool, ts: pd.Timestamp) -> None:
        take_type = pool.anchor_run_take_type if event_type == "confirmed_itr_anchor_run" else pool.take_type
        self._events.append(
            LiquidityEvent(
                event_type=event_type,
                pool_id=pool.pool_id,
                pool_kind=pool.pool_kind,
                variant=pool.variant,
                source=pool.source,
                side=pool.side,
                direction=pool.direction,
                level_price=pool.price,
                timestamp=ts,
                confirmed_by=pool.confirmed_by,
                take_type=take_type,
                scope=pool.scope,
                htf_pd_epoch_id=pool.htf_pd_epoch_id,
                liquidity_event_id=(
                    _liquidity_event_id(pool.pool_id, pool.confirmed_at)
                    if event_type == "liquidity_grab_confirmed"
                    else None
                ),
                is_triggerable=self._pool_belongs_to_current_triggerable_set(pool),
                came_from=pool.approached_from,
                left_to=pool.left_to,
            )
        )
        if len(self._events) > self.event_log_limit:
            self._events = self._events[-self.event_log_limit :]

    def _pool_is_ready(self, pool: LiquidityPool | None) -> bool:
        if pool is None or pool.confirmed_lower_index is None or self._current_lower_index is None:
            return False
        if not self._pool_belongs_to_current_triggerable_set(pool):
            return False
        return self._current_lower_index - pool.confirmed_lower_index <= self.ready_ttl_bars

    def _itr_anchor_run_is_ready(self, pool: LiquidityPool | None) -> bool:
        if pool is None or pool.anchor_run_lower_index is None or self._current_lower_index is None:
            return False
        if not self._pool_belongs_to_current_triggerable_set(pool):
            return False
        return self._current_lower_index - pool.anchor_run_lower_index <= self.ready_ttl_bars

    def _pool_can_trigger_hypothesis(self, pool: LiquidityPool) -> bool:
        """Compatibility alias for the neutral current-triggerable-set check."""
        return self._pool_belongs_to_current_triggerable_set(pool)

    def _pool_belongs_to_current_triggerable_set(self, pool: LiquidityPool) -> bool:
        stores = {
            "htf_pd": self._pd_pools,
            "htf_eq": self._eq_pools,
            "htf_itr": self._itr_pools,
        }
        store = stores.get(pool.pool_kind)
        if store is None or store.get(pool.pool_id) is not pool:
            return False
        if pool.scope not in {"active_current_epoch", "carryover_recent"} or pool.status == "archived":
            return False
        if self._pool_expired_by_age(pool):
            return False
        if self._current_epoch_id is None or pool.htf_pd_epoch_id != self._current_epoch_id:
            return False
        return True

    def _pool_expired_by_age(self, pool: LiquidityPool) -> bool:
        if pool.pool_kind not in {"htf_eq", "htf_itr"} or pool.created_higher_index is None:
            return False
        return self._higher_index - pool.created_higher_index > self.max_pool_age_htf_bars

    def _update_atr(self, row: pd.Series) -> None:
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        if self._prev_higher_close is None:
            true_range = high - low
        else:
            true_range = max(
                high - low,
                abs(high - self._prev_higher_close),
                abs(low - self._prev_higher_close),
            )
        self._true_ranges.append(true_range)
        if len(self._true_ranges) > self.eq_atr_period:
            self._true_ranges = self._true_ranges[-self.eq_atr_period :]
        self._prev_higher_close = close

    def _eq_tolerance(self) -> float | None:
        if len(self._true_ranges) < self.eq_atr_period:
            return None
        atr = sum(self._true_ranges[-self.eq_atr_period :]) / self.eq_atr_period
        return atr * self.eq_threshold

    def _itr_eq_tolerance(self) -> float | None:
        if len(self._true_ranges) < self.eq_atr_period:
            return None
        atr = sum(self._true_ranges[-self.eq_atr_period :]) / self.eq_atr_period
        return atr * self.itr_eq_threshold

    def _htf_pd_epoch_id(self, structure: dict[str, Any]) -> str:
        last_sc = structure.get("last_sc") or {}
        parts = [
            str(last_sc.get("eventTimestamp") or ""),
            str(last_sc.get("eventCode") or ""),
            str(last_sc.get("breakDirection") or ""),
            str(structure.get("phase_start_ts") or ""),
        ]
        return "|".join(parts)

    def _structure_timestamp(self, structure: dict[str, Any], source: str | None = None) -> pd.Timestamp:
        if source == "range_high":
            keys = ("range_high_ts", "phase_start_ts", "range_low_ts")
        elif source == "range_low":
            keys = ("range_low_ts", "phase_start_ts", "range_high_ts")
        else:
            keys = ("phase_start_ts", "range_high_ts", "range_low_ts")
        for key in keys:
            value = structure.get(key)
            if value:
                return pd.Timestamp(value)
        return pd.Timestamp.utcnow()

    def _price_inside_current_range(self, price: float, tolerance: float = 0.0) -> bool:
        if self._current_range_low is None or self._current_range_high is None:
            return False
        return price + tolerance >= self._current_range_low and price - tolerance <= self._current_range_high

    def _pool_snapshot(self, pool: LiquidityPool) -> dict[str, Any]:
        payload = pool.to_dict()
        payload["is_triggerable"] = self._pool_belongs_to_current_triggerable_set(pool)
        return payload

    def _current_event_fields(
        self,
        prefix: str,
        pool: LiquidityPool | None,
    ) -> dict[str, Any]:
        triggerable = bool(pool and self._pool_belongs_to_current_triggerable_set(pool))
        return {
            f"{prefix}_event_id": _liquidity_event_id(pool.pool_id, pool.confirmed_at) if triggerable and pool else None,
            f"{prefix}_htf_pd_epoch_id": pool.htf_pd_epoch_id if triggerable and pool else None,
            f"{prefix}_scope": pool.scope if triggerable and pool else None,
            f"{prefix}_is_triggerable": triggerable,
            f"{prefix}_reclaimed_price": _round_price(pool.reclaimed_price) if triggerable and pool else None,
        }

    def _current_triggerable_liquidity_events(self) -> list[dict[str, Any]]:
        pools = [
            pool
            for pool in (
                list(self._pd_pools.values())
                + list(self._eq_pools.values())
                + list(self._itr_pools.values())
            )
            if self._pool_is_ready(pool)
        ]
        pools.sort(key=lambda pool: pool.confirmed_at or pool.created_at)
        return [
            {
                "liquidity_event_id": _liquidity_event_id(pool.pool_id, pool.confirmed_at),
                "pool_id": pool.pool_id,
                "pool_kind": pool.pool_kind,
                "variant": pool.variant,
                "source": pool.source,
                "side": pool.side,
                "direction": pool.direction,
                "level": _round_price(pool.price),
                "tolerance": _round_price(pool.tolerance),
                "scope": pool.scope,
                "htf_pd_epoch_id": pool.htf_pd_epoch_id,
                "is_triggerable": True,
                "taken_at": _iso(pool.taken_at),
                "reclaimed_at": _iso(pool.reclaimed_at),
                "reclaimed_price": _round_price(pool.reclaimed_price),
                "confirmed_at": _iso(pool.confirmed_at),
                "confirmed_by": pool.confirmed_by,
                "take_type": pool.take_type,
            }
            for pool in pools
        ]

    def _rescope_pd_pools(self, epoch_id: str) -> None:
        for pool in self._pd_pools.values():
            if pool.htf_pd_epoch_id != epoch_id:
                self._archive_pool(pool, "pd_epoch_changed")

    def _rescope_eq_pools(self) -> None:
        if not self._eq_pools:
            return
        eligible = [
            pool
            for pool in self._eq_pools.values()
            if pool.status not in {"archived", "liquidity_grab_confirmed"}
            and self._price_inside_current_range(pool.price, pool.tolerance)
            and not self._pool_expired_by_age(pool)
        ]
        eligible.sort(key=lambda pool: pool.created_at, reverse=True)
        carryover_ids = {
            pool.pool_id
            for pool in eligible[: self.carryover_recent_pools]
        }
        for pool in self._eq_pools.values():
            if pool.status == "liquidity_grab_confirmed":
                self._archive_pool(pool, "pd_epoch_changed_after_confirmation")
            elif pool.pool_id in carryover_ids:
                pool.scope = "carryover_recent"
                pool.htf_pd_epoch_id = self._current_epoch_id
            else:
                self._archive_pool(pool, "outside_current_pd_or_not_recent_carryover")

    def _archive_expired_pools(self) -> None:
        for pool in list(self._eq_pools.values()) + list(self._itr_pools.values()):
            if pool.status != "archived" and self._pool_expired_by_age(pool):
                self._archive_pool(pool, "max_pool_age_htf_bars")

    def _rescope_itr_pools(self) -> None:
        if not self._itr_pools:
            return
        eligible_carryover = [
            pool
            for pool in self._itr_pools.values()
            if pool.status not in {"archived", "liquidity_grab_confirmed"}
            and self._price_inside_current_range(pool.price, pool.tolerance)
        ]
        eligible_by_side: dict[LiquiditySide, list[LiquidityPool]] = {"buy_side": [], "sell_side": []}
        for pool in eligible_carryover:
            eligible_by_side[pool.side].append(pool)

        carryover_ids: set[str] = set()
        for pools in eligible_by_side.values():
            pools.sort(key=lambda candidate: candidate.created_at, reverse=True)
            carryover_ids.update(pool.pool_id for pool in pools[: self.carryover_recent_pools])

        for pool in self._itr_pools.values():
            if pool.status == "liquidity_grab_confirmed":
                self._archive_pool(pool, "pd_epoch_changed_after_confirmation")
            elif pool.pool_id in carryover_ids:
                pool.scope = "carryover_recent"
                pool.htf_pd_epoch_id = self._current_epoch_id
            else:
                self._archive_pool(pool, "outside_current_pd_or_not_recent_carryover")

    def _limit_itr_pools(self) -> None:
        for side in ("buy_side", "sell_side"):
            candidates = [
                pool
                for pool in self._itr_pools.values()
                if pool.side == side
                and pool.status not in {"archived", "liquidity_grab_confirmed"}
                and self._pool_can_trigger_hypothesis(pool)
            ]
            candidates.sort(key=lambda pool: pool.created_at, reverse=True)
            for pool in candidates[self.max_active_itr_pools_per_side :]:
                self._archive_pool(pool, "max_active_itr_pools_per_side")

    def _limit_confirmed_itr_anchor_watch(self) -> None:
        eligible_by_side: dict[LiquiditySide, list[LiquidityPool]] = {"buy_side": [], "sell_side": []}
        for pool in self._itr_pools.values():
            if pool.status != "liquidity_grab_confirmed" or not self._pool_can_trigger_hypothesis(pool):
                continue
            if pool.anchor_run_at is not None:
                if (
                    self._current_lower_index is not None
                    and pool.anchor_run_lower_index is not None
                    and self._current_lower_index - pool.anchor_run_lower_index > self.ready_ttl_bars
                ):
                    self._archive_pool(pool, "anchor_run_ready_ttl_elapsed")
                continue
            if (
                pool.confirmed_higher_index is not None
                and self._higher_index - pool.confirmed_higher_index > self.anchor_watch_ttl_htf_bars
            ):
                self._archive_pool(pool, "anchor_watch_ttl_htf_bars")
                continue
            eligible_by_side[pool.side].append(pool)

        for pools in eligible_by_side.values():
            pools.sort(key=lambda pool: pool.confirmed_at or pool.created_at, reverse=True)
            for pool in pools[self.max_confirmed_anchor_watch_per_side :]:
                self._archive_pool(pool, "max_confirmed_anchor_watch_per_side")

    def _archive_pool(self, pool: LiquidityPool, reason: str) -> None:
        pool.status = "archived"
        pool.scope = "external_archive"
        pool.archived_reason = reason
        for event in self._events:
            if event.pool_id == pool.pool_id:
                event.scope = pool.scope
                event.is_triggerable = False

    def _legacy_sweep_aliases(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            key.replace("htf_pd_grab_reclaim", "htf_pd_sweep_reclaim"): value
            for key, value in payload.items()
            if key.startswith("htf_pd_grab_reclaim")
        }
