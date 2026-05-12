import unittest

import pandas as pd

from ultrab.core.smc.pivotEvent import PivotEvent
from ultrab.core.smc.sdZone import SDZone, SDZoneBarResult
from ultrab.core.smc.structureEngine import StructureEngine


BASE = pd.Timestamp("2024-01-01T00:00:00Z")


def ts(hours: int) -> pd.Timestamp:
    return BASE + pd.Timedelta(hours=hours)


def row(hours: int, open_: float, high: float, low: float, close: float) -> pd.Series:
    return pd.Series(
        {"open": open_, "high": high, "low": low, "close": close},
        name=ts(hours),
    )


def pe(event_code: str, hours: int, price: float) -> PivotEvent:
    side = 1 if event_code in {"PE03", "PE05"} else -1
    tier = "itr" if event_code in {"PE03", "PE04"} else "ltr"
    side_name = "High" if side == 1 else "Low"
    return PivotEvent(
        event_code=event_code,
        event_name=f"{tier}{side_name}Confirmed",
        event_group="PE",
        tier=tier,
        event_timestamp=ts(hours),
        pivot_timestamp=ts(hours - 1),
        pivot_price=price,
        pivot_side=side,
        mode="conservative",
        survival_bars=2,
    )


def zone(zone_id: str, direction: str, high: float, low: float, hours: int) -> SDZone:
    return SDZone(
        zone_id=zone_id,
        direction=direction,
        high=high,
        low=low,
        drawing_mode="pivot",
        timeframe="1h",
        created_at=ts(hours),
        anchor_ts=ts(hours - 1),
    )


def empty_bar_result() -> SDZoneBarResult:
    return SDZoneBarResult(created=[], mitigated=[])


def step(
    engine: StructureEngine,
    hours: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    *,
    pivots: list[PivotEvent] | None = None,
    zones: list[SDZone] | None = None,
    mitigated: list[str] | None = None,
):
    return engine.on_bar(
        row(hours, open_, high, low, close),
        pivots or [],
        [],
        SDZoneBarResult(created=zones or [], mitigated=mitigated or []),
    )


def warm_bullish_engine() -> StructureEngine:
    engine = StructureEngine({"tier": "itr"}, "1h")
    step(engine, 0, 6, 9, 4, 8, pivots=[pe("PE03", 0, 10), pe("PE04", 0, 4.5)])
    events = step(engine, 1, 8, 12, 6, 11)
    assert len(events) == 1
    return engine


def warm_bearish_engine() -> StructureEngine:
    engine = StructureEngine({"tier": "itr"}, "1h")
    step(engine, 0, 8, 10, 5, 6, pivots=[pe("PE03", 0, 10.5), pe("PE04", 0, 5.5)])
    events = step(engine, 1, 6, 7, 3, 4)
    assert len(events) == 1
    return engine


class StructureEngineRangeTests(unittest.TestCase):
    def test_itr_confirms_pullback_but_pd_uses_wick_extreme(self):
        engine = warm_bullish_engine()

        step(engine, 2, 11, 15, 10, 14)
        step(engine, 3, 14, 14.2, 12, 13, pivots=[pe("PE03", 3, 13)])

        snapshot = engine.get_snapshot(13)
        self.assertEqual(snapshot["phase"], "pullback_confirmed")
        self.assertEqual(snapshot["confirmed_by"], "itr")
        self.assertEqual(snapshot["range_low"], 4)
        self.assertEqual(snapshot["range_high"], 15)
        self.assertEqual(snapshot["pd_midpoint"], 9.5)
        self.assertEqual(snapshot["range_position_pct"], 81.8)
        self.assertEqual(snapshot["pd_value_pct"], 81.8)
        self.assertEqual(snapshot["pd_pct"], 81.8)

    def test_bearish_pd_value_is_bias_relative(self):
        engine = warm_bearish_engine()

        step(engine, 2, 4, 8, 2, 3)

        snapshot = engine.get_snapshot(8)
        self.assertEqual(snapshot["bias"], "bearish")
        self.assertEqual(snapshot["range_low"], 2)
        self.assertEqual(snapshot["range_high"], 10)
        self.assertEqual(snapshot["range_position_pct"], 75.0)
        self.assertEqual(snapshot["pd_value_pct"], 25.0)
        self.assertEqual(snapshot["pd_pct"], 75.0)

    def test_sd_confirms_pullback_and_later_sd_does_not_restart(self):
        engine = warm_bullish_engine()

        step(engine, 2, 11, 16, 10, 15)
        first_zone = zone("z1", "supply", high=15.5, low=14.8, hours=3)
        step(engine, 3, 15, 15.2, 13, 14, zones=[first_zone])
        first_snapshot = engine.get_snapshot(14)

        second_zone = zone("z2", "supply", high=14.5, low=13.5, hours=4)
        step(engine, 4, 14, 14.8, 12, 13, zones=[second_zone])
        second_snapshot = engine.get_snapshot(13)

        self.assertEqual(first_snapshot["phase"], "pullback_confirmed")
        self.assertEqual(first_snapshot["confirmed_by"], "sd_zone")
        self.assertEqual(first_snapshot["confirmed_zone_id"], "z1")
        self.assertEqual(second_snapshot["confirmed_by"], "sd_zone")
        self.assertEqual(second_snapshot["confirmed_zone_id"], "z1")

    def test_sd_mitigation_does_not_reset_structure_phase(self):
        engine = warm_bullish_engine()

        step(engine, 2, 11, 16, 10, 15)
        first_zone = zone("z1", "supply", high=15.5, low=14.8, hours=3)
        step(engine, 3, 15, 15.2, 13, 14, zones=[first_zone])
        step(engine, 4, 14, 14.2, 12, 13, mitigated=["z1"])

        snapshot = engine.get_snapshot(13)
        self.assertEqual(snapshot["phase"], "pullback_confirmed")
        self.assertEqual(snapshot["confirmed_by"], "sd_zone")

    def test_open_extension_does_not_fire_continuation_bos(self):
        engine = warm_bullish_engine()

        events = step(engine, 2, 11, 20, 10, 19)

        snapshot = engine.get_snapshot(19)
        self.assertEqual(events, [])
        self.assertEqual(snapshot["phase"], "open")
        self.assertEqual(snapshot["range_high"], 20)

    def test_warmup_registry_stops_driving_structure_after_first_sc(self):
        engine = warm_bullish_engine()

        events = step(engine, 2, 11, 13, 10, 12.8, pivots=[pe("PE03", 2, 12.5)])

        snapshot = engine.get_snapshot(12.8)
        self.assertEqual(events, [])
        self.assertEqual(snapshot["phase"], "pullback_confirmed")
        self.assertEqual(snapshot["range_high"], 13)
        self.assertEqual(snapshot["confirmed_by"], "itr")


if __name__ == "__main__":
    unittest.main()
