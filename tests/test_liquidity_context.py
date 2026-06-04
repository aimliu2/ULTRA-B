from __future__ import annotations

import pandas as pd

from ultrab.core.smc.liquidity import LiquidityContextEngine
from ultrab.core.smc.pivotEvent import PivotEvent


def _bar(ts: str, open_: float, high: float, low: float, close: float) -> pd.Series:
    return pd.Series(
        {"open": open_, "high": high, "low": low, "close": close},
        name=pd.Timestamp(ts, tz="UTC"),
    )


def _htf_structure() -> dict:
    return {
        "bias": "bullish",
        "phase": "open",
        "range_high": 100.0,
        "range_low": 90.0,
        "phase_start_ts": "2026-01-01T00:00:00+00:00",
        "range_high_ts": "2026-01-02T00:00:00+00:00",
        "range_low_ts": "2026-01-01T00:00:00+00:00",
    }


def _htf_structure_range(high: float, low: float, start: str = "2026-01-01T00:00:00+00:00") -> dict:
    return {
        "bias": "bullish",
        "phase": "open",
        "range_high": high,
        "range_low": low,
        "phase_start_ts": start,
        "range_high_ts": "2026-01-02T00:00:00+00:00",
        "range_low_ts": "2026-01-01T00:00:00+00:00",
    }


def _pivot(
    side: int,
    price: float,
    pivot_ts: str,
    event_ts: str,
) -> PivotEvent:
    return PivotEvent(
        event_code="PE03" if side == 1 else "PE04",
        event_name="itrHighConfirmed" if side == 1 else "itrLowConfirmed",
        event_group="PE",
        tier="itr",
        event_timestamp=pd.Timestamp(event_ts, tz="UTC"),
        pivot_timestamp=pd.Timestamp(pivot_ts, tz="UTC"),
        pivot_price=price,
        pivot_side=side,  # type: ignore[arg-type]
        mode="conservative",
        survival_bars=2,
    )


def test_pd_boundary_grab_reclaim_confirms_from_ltf_heartbeat():
    engine = LiquidityContextEngine({"enabled": True}, "15m", "4H")
    engine.on_higher_bar(
        _bar("2026-01-02T04:00:00Z", 96.0, 100.0, 92.0, 98.0),
        [],
        _htf_structure(),
    )

    engine.on_lower_bar(
        _bar("2026-01-02T04:15:00Z", 99.8, 101.0, 99.6, 99.7),
        lower_index=1,
    )
    snapshot = engine.snapshot()

    assert snapshot["htf_pd_grab_reclaim_ready"] is True
    assert snapshot["htf_pd_grab_reclaim_side"] == "buy_side"
    assert snapshot["htf_pd_grab_reclaim_direction"] == "bearish"
    assert snapshot["htf_pd_grab_reclaim_level"] == 100.0
    assert snapshot["htf_pd_grab_reclaim_event_id"].startswith(
        f"{snapshot['htf_pd_grab_reclaim_pool_id']}|"
    )
    assert snapshot["htf_pd_grab_reclaim_htf_pd_epoch_id"] == snapshot["htf_pd_epoch_id"]
    assert snapshot["htf_pd_grab_reclaim_scope"] == "active_current_epoch"
    assert snapshot["htf_pd_grab_reclaim_is_triggerable"] is True
    assert snapshot["current_triggerable_liquidity_events"][0]["liquidity_event_id"] == (
        snapshot["htf_pd_grab_reclaim_event_id"]
    )
    assert snapshot["events"][-1]["event_type"] == "liquidity_grab_confirmed"


def test_confirmed_pd_grab_is_not_ready_after_epoch_change():
    engine = LiquidityContextEngine({"enabled": True}, "15m", "4H")
    engine.on_higher_bar(
        _bar("2026-01-02T04:00:00Z", 96.0, 100.0, 92.0, 98.0),
        [],
        _htf_structure(),
    )
    engine.on_lower_bar(
        _bar("2026-01-02T04:15:00Z", 99.8, 101.0, 99.6, 99.7),
        lower_index=1,
    )
    assert engine.snapshot()["htf_pd_grab_reclaim_ready"] is True

    engine.on_higher_bar(
        _bar("2026-01-02T08:00:00Z", 101.0, 105.0, 95.0, 102.0),
        [],
        _htf_structure_range(105.0, 95.0, "2026-01-02T08:00:00+00:00"),
    )
    snapshot = engine.snapshot()

    assert snapshot["htf_pd_grab_reclaim_ready"] is False
    assert snapshot["htf_pd_grab_reclaim_is_triggerable"] is False
    assert snapshot["current_triggerable_liquidity_events"] == []
    assert snapshot["events"][-1]["scope"] == "external_archive"
    assert snapshot["events"][-1]["is_triggerable"] is False


def test_confirmed_pd_grab_is_not_ready_after_boundary_replacement_in_same_epoch():
    engine = LiquidityContextEngine({"enabled": True}, "15m", "4H")
    engine.on_higher_bar(
        _bar("2026-01-02T04:00:00Z", 96.0, 100.0, 92.0, 98.0),
        [],
        _htf_structure(),
    )
    engine.on_lower_bar(
        _bar("2026-01-02T04:15:00Z", 99.8, 101.0, 99.6, 99.7),
        lower_index=1,
    )
    old_epoch = engine.snapshot()["htf_pd_epoch_id"]

    engine.on_higher_bar(
        _bar("2026-01-02T08:00:00Z", 101.0, 105.0, 90.0, 102.0),
        [],
        _htf_structure_range(105.0, 90.0),
    )
    snapshot = engine.snapshot()

    assert snapshot["htf_pd_epoch_id"] == old_epoch
    assert snapshot["htf_pd_grab_reclaim_ready"] is False
    assert snapshot["current_triggerable_liquidity_events"] == []


def test_lower_bars_before_pool_creation_do_not_backfill_grabs():
    engine = LiquidityContextEngine({"enabled": True}, "15m", "4H")
    engine.on_higher_bar(
        _bar("2026-01-02T04:00:00Z", 96.0, 100.0, 92.0, 98.0),
        [],
        _htf_structure(),
    )

    engine.on_lower_bar(
        _bar("2026-01-01T12:00:00Z", 99.8, 101.0, 99.6, 99.7),
        lower_index=1,
    )
    assert engine.snapshot()["htf_pd_grab_reclaim_ready"] is False

    engine.on_lower_bar(
        _bar("2026-01-02T04:15:00Z", 99.8, 101.0, 99.6, 99.7),
        lower_index=2,
    )
    assert engine.snapshot()["htf_pd_grab_reclaim_ready"] is True


def test_eq_pool_uses_htf_atr_and_confirms_grab_reclaim():
    engine = LiquidityContextEngine(
        {
            "enabled": True,
            "eq": {
                "enabled": True,
                "atr_period": 14,
                "eq_threshold": 0.1,
                "pivot_tier": "itr",
            },
        },
        "15m",
        "4H",
    )

    for idx in range(14):
        ts = pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(hours=4 * idx)
        engine.on_higher_bar(
            pd.Series({"open": 105.0, "high": 110.0, "low": 100.0, "close": 105.0}, name=ts),
            [],
            _htf_structure(),
        )

    engine.on_higher_bar(
        _bar("2026-01-03T08:00:00Z", 105.0, 110.0, 100.0, 105.0),
        [_pivot(1, 100.0, "2026-01-02T00:00:00Z", "2026-01-03T08:00:00Z")],
        _htf_structure(),
    )
    engine.on_higher_bar(
        _bar("2026-01-03T12:00:00Z", 105.0, 110.0, 100.0, 105.0),
        [_pivot(1, 100.5, "2026-01-03T00:00:00Z", "2026-01-03T12:00:00Z")],
        _htf_structure(),
    )

    pre_grab = engine.snapshot()
    assert pre_grab["eq_tolerance"] == 1.0
    assert len(pre_grab["active_htf_eq_pools"]) == 1

    engine.on_lower_bar(
        _bar("2026-01-03T12:15:00Z", 100.2, 101.5, 99.8, 100.0),
        lower_index=1,
    )
    snapshot = engine.snapshot()

    assert snapshot["htf_eq_grab_reclaim_ready"] is True
    assert snapshot["htf_eq_grab_reclaim_side"] == "buy_side"
    assert snapshot["htf_eq_grab_reclaim_direction"] == "bearish"
    assert snapshot["htf_eq_grab_reclaim_source"] == "eqh"
    assert snapshot["htf_eq_grab_reclaim_event_id"].startswith(
        f"{snapshot['htf_eq_grab_reclaim_pool_id']}|"
    )
    assert snapshot["htf_eq_grab_reclaim_htf_pd_epoch_id"] == snapshot["htf_pd_epoch_id"]
    assert snapshot["htf_eq_grab_reclaim_is_triggerable"] is True

    engine.on_higher_bar(
        _bar("2026-01-03T16:00:00Z", 101.0, 105.0, 95.0, 102.0),
        [],
        _htf_structure_range(105.0, 95.0, "2026-01-03T16:00:00+00:00"),
    )
    rescoped = engine.snapshot()
    assert rescoped["htf_eq_grab_reclaim_ready"] is False
    assert all(
        event["pool_kind"] != "htf_eq"
        for event in rescoped["current_triggerable_liquidity_events"]
    )


def test_htf_itr_low_grab_requires_from_above_then_leave_above():
    engine = LiquidityContextEngine({"enabled": True, "itr": {"enabled": True}}, "15m", "4H")
    engine.on_higher_bar(
        _bar("2026-01-02T04:00:00Z", 96.0, 100.0, 90.0, 98.0),
        [_pivot(-1, 94.0, "2026-01-02T00:00:00Z", "2026-01-02T04:00:00Z")],
        _htf_structure(),
    )

    snapshot = engine.snapshot()
    assert len(snapshot["active_htf_itr_pools"]) == 1
    assert snapshot["active_htf_itr_pools"][0]["source"] == "htf_itr_low"

    engine.on_lower_bar(
        _bar("2026-01-02T04:15:00Z", 94.5, 95.0, 93.4, 94.4),
        lower_index=1,
    )
    snapshot = engine.snapshot()

    assert snapshot["htf_itr_grab_reclaim_ready"] is True
    assert snapshot["htf_itr_level_grab_reclaim_ready"] is True
    assert snapshot["htf_itr_grab_reclaim_variant"] == "level"
    assert snapshot["htf_itr_grab_reclaim_source"] == "htf_itr_low"
    assert snapshot["htf_itr_grab_reclaim_direction"] == "bullish"
    assert snapshot["htf_itr_grab_reclaim_came_from"] == "above"
    assert snapshot["htf_itr_grab_reclaim_left_to"] == "above"


def test_confirmed_htf_itr_level_can_emit_later_anchor_run():
    engine = LiquidityContextEngine({"enabled": True, "itr": {"enabled": True}}, "15m", "4H")
    engine.on_higher_bar(
        _bar("2026-01-02T04:00:00Z", 96.0, 100.0, 90.0, 98.0),
        [_pivot(-1, 94.0, "2026-01-02T00:00:00Z", "2026-01-02T04:00:00Z")],
        _htf_structure(),
    )
    engine.on_lower_bar(
        _bar("2026-01-02T04:15:00Z", 94.5, 95.0, 93.4, 94.4),
        lower_index=1,
    )
    assert engine.snapshot()["htf_itr_grab_reclaim_ready"] is True

    engine.on_lower_bar(
        _bar("2026-01-02T04:30:00Z", 94.3, 94.5, 93.2, 93.6),
        lower_index=2,
    )
    snapshot = engine.snapshot()

    assert snapshot["htf_itr_anchor_run_ready"] is True
    assert snapshot["htf_itr_level_anchor_run_ready"] is True
    assert snapshot["htf_itr_eq_anchor_run_ready"] is False
    assert snapshot["htf_itr_anchor_run_variant"] == "level"
    assert snapshot["htf_itr_anchor_run_source"] == "htf_itr_low"
    assert snapshot["htf_itr_anchor_run_direction"] == "bullish"
    assert snapshot["events"][-1]["event_type"] == "confirmed_itr_anchor_run"


def test_confirmed_htf_itr_anchor_watch_is_capped_per_side():
    engine = LiquidityContextEngine(
        {
            "enabled": True,
            "itr": {"enabled": True},
            "memory": {"max_confirmed_anchor_watch_per_side": 1},
        },
        "15m",
        "4H",
    )
    engine.on_higher_bar(
        _bar("2026-01-02T04:00:00Z", 96.0, 100.0, 90.0, 98.0),
        [_pivot(-1, 94.0, "2026-01-02T00:00:00Z", "2026-01-02T04:00:00Z")],
        _htf_structure(),
    )
    engine.on_lower_bar(
        _bar("2026-01-02T04:15:00Z", 94.5, 95.0, 93.4, 94.4),
        lower_index=1,
    )
    engine.on_higher_bar(
        _bar("2026-01-02T08:00:00Z", 96.0, 100.0, 90.0, 98.0),
        [_pivot(-1, 95.0, "2026-01-02T05:00:00Z", "2026-01-02T08:00:00Z")],
        _htf_structure(),
    )
    engine.on_lower_bar(
        _bar("2026-01-02T08:15:00Z", 95.5, 96.0, 94.3, 95.4),
        lower_index=2,
    )

    pools = engine.snapshot()["active_htf_itr_pools"]
    confirmed = [pool for pool in pools if pool["status"] == "liquidity_grab_confirmed"]
    assert len(confirmed) == 1
    assert confirmed[0]["price"] == 95.0


def test_confirmed_htf_itr_anchor_watch_expires_by_htf_age():
    engine = LiquidityContextEngine(
        {
            "enabled": True,
            "itr": {"enabled": True},
            "memory": {"anchor_watch_ttl_htf_bars": 1},
        },
        "15m",
        "4H",
    )
    engine.on_higher_bar(
        _bar("2026-01-02T04:00:00Z", 96.0, 100.0, 90.0, 98.0),
        [_pivot(-1, 94.0, "2026-01-02T00:00:00Z", "2026-01-02T04:00:00Z")],
        _htf_structure(),
    )
    engine.on_lower_bar(
        _bar("2026-01-02T04:15:00Z", 94.5, 95.0, 93.4, 94.4),
        lower_index=1,
    )

    engine.on_higher_bar(_bar("2026-01-02T08:00:00Z", 96.0, 100.0, 90.0, 98.0), [], _htf_structure())
    engine.on_higher_bar(_bar("2026-01-02T12:00:00Z", 96.0, 100.0, 90.0, 98.0), [], _htf_structure())

    pools = engine.snapshot()["active_htf_itr_pools"]
    assert all(pool["status"] != "liquidity_grab_confirmed" for pool in pools)


def test_htf_itr_low_grab_ignores_wrong_trajectory_from_below():
    engine = LiquidityContextEngine({"enabled": True, "itr": {"enabled": True}}, "15m", "4H")
    engine.on_higher_bar(
        _bar("2026-01-02T04:00:00Z", 96.0, 100.0, 90.0, 98.0),
        [_pivot(-1, 94.0, "2026-01-02T00:00:00Z", "2026-01-02T04:00:00Z")],
        _htf_structure(),
    )

    engine.on_lower_bar(
        _bar("2026-01-02T04:15:00Z", 93.5, 94.6, 93.2, 94.4),
        lower_index=1,
    )

    snapshot = engine.snapshot()
    assert snapshot["htf_itr_grab_reclaim_ready"] is False
    assert snapshot["events"] == []
    assert snapshot["active_htf_itr_pools"][0]["status"] == "active"


def test_htf_itr_eq_grab_uses_atr_tolerance_and_bundled_itr_ready():
    engine = LiquidityContextEngine(
        {
            "enabled": True,
            "itr": {
                "enabled": True,
                "eq_enabled": True,
                "eq_threshold": 0.1,
                "pivot_tier": "itr",
            },
            "eq": {"enabled": False, "atr_period": 14, "eq_threshold": 0.1},
        },
        "15m",
        "4H",
    )

    for idx in range(14):
        ts = pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(hours=4 * idx)
        engine.on_higher_bar(
            pd.Series({"open": 95.0, "high": 100.0, "low": 90.0, "close": 95.0}, name=ts),
            [],
            _htf_structure(),
        )

    engine.on_higher_bar(
        _bar("2026-01-03T08:00:00Z", 95.0, 100.0, 90.0, 95.0),
        [_pivot(1, 96.0, "2026-01-02T00:00:00Z", "2026-01-03T08:00:00Z")],
        _htf_structure(),
    )
    engine.on_higher_bar(
        _bar("2026-01-03T12:00:00Z", 95.0, 100.0, 90.0, 95.0),
        [_pivot(1, 96.5, "2026-01-03T00:00:00Z", "2026-01-03T12:00:00Z")],
        _htf_structure(),
    )

    pre_grab = engine.snapshot()
    itr_eq_pools = [pool for pool in pre_grab["active_htf_itr_pools"] if pool["variant"] == "eq"]
    assert len(itr_eq_pools) == 1
    assert itr_eq_pools[0]["source"] == "htf_itr_eqh"

    engine.on_lower_bar(
        _bar("2026-01-03T12:15:00Z", 95.8, 97.5, 95.6, 96.0),
        lower_index=1,
    )
    snapshot = engine.snapshot()

    assert snapshot["htf_itr_grab_reclaim_ready"] is True
    assert snapshot["htf_itr_eq_grab_reclaim_ready"] is True
    assert snapshot["htf_itr_grab_reclaim_variant"] == "eq"
    assert snapshot["htf_itr_grab_reclaim_source"] == "htf_itr_eqh"
    assert snapshot["htf_itr_grab_reclaim_direction"] == "bearish"


def test_confirmed_htf_itr_eq_can_emit_later_anchor_run():
    engine = LiquidityContextEngine(
        {
            "enabled": True,
            "itr": {
                "enabled": True,
                "eq_enabled": True,
                "eq_threshold": 0.1,
                "pivot_tier": "itr",
            },
            "eq": {"enabled": False, "atr_period": 14, "eq_threshold": 0.1},
        },
        "15m",
        "4H",
    )

    for idx in range(14):
        ts = pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(hours=4 * idx)
        engine.on_higher_bar(
            pd.Series({"open": 95.0, "high": 100.0, "low": 90.0, "close": 95.0}, name=ts),
            [],
            _htf_structure(),
        )

    engine.on_higher_bar(
        _bar("2026-01-03T08:00:00Z", 95.0, 100.0, 90.0, 95.0),
        [_pivot(-1, 94.0, "2026-01-02T00:00:00Z", "2026-01-03T08:00:00Z")],
        _htf_structure(),
    )
    engine.on_higher_bar(
        _bar("2026-01-03T12:00:00Z", 95.0, 100.0, 90.0, 95.0),
        [_pivot(-1, 94.5, "2026-01-03T00:00:00Z", "2026-01-03T12:00:00Z")],
        _htf_structure(),
    )

    engine.on_lower_bar(
        _bar("2026-01-03T12:15:00Z", 94.6, 95.0, 93.0, 94.4),
        lower_index=1,
    )
    assert engine.snapshot()["htf_itr_eq_grab_reclaim_ready"] is True

    engine.on_lower_bar(
        _bar("2026-01-03T12:30:00Z", 94.4, 94.7, 93.0, 93.5),
        lower_index=2,
    )
    snapshot = engine.snapshot()

    assert snapshot["htf_itr_anchor_run_ready"] is True
    assert snapshot["htf_itr_level_anchor_run_ready"] is False
    assert snapshot["htf_itr_eq_anchor_run_ready"] is True
    assert snapshot["htf_itr_anchor_run_variant"] == "eq"
    assert snapshot["htf_itr_anchor_run_source"] == "htf_itr_eql"
    assert snapshot["htf_itr_anchor_run_direction"] == "bullish"


def test_htf_itr_pool_outside_new_pd_range_archives_and_cannot_trigger():
    engine = LiquidityContextEngine(
        {"enabled": True, "itr": {"enabled": True}, "memory": {"carryover_recent_pools": 3}},
        "15m",
        "4H",
    )
    engine.on_higher_bar(
        _bar("2026-01-02T04:00:00Z", 96.0, 100.0, 90.0, 98.0),
        [_pivot(1, 98.0, "2026-01-02T00:00:00Z", "2026-01-02T04:00:00Z")],
        _htf_structure_range(100.0, 90.0),
    )
    assert len(engine.snapshot()["active_htf_itr_pools"]) == 1

    engine.on_higher_bar(
        _bar("2026-01-02T08:00:00Z", 86.0, 88.0, 80.0, 82.0),
        [],
        _htf_structure_range(88.0, 80.0, start="2026-01-02T08:00:00+00:00"),
    )
    assert engine.snapshot()["active_htf_itr_pools"] == []

    engine.on_lower_bar(
        _bar("2026-01-02T08:15:00Z", 97.5, 98.6, 97.3, 97.7),
        lower_index=1,
    )
    assert engine.snapshot()["htf_itr_grab_reclaim_ready"] is False
