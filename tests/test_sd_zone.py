import unittest

import pandas as pd

from ultrab.core.smc.candleEvent import FvgEvent
from ultrab.core.smc.sdZone import SDZoneEngine


BASE = pd.Timestamp("2024-01-01T00:00:00Z")


def ts(hours: int) -> pd.Timestamp:
    return BASE + pd.Timedelta(hours=hours)


def row(hours: int, open_: float, high: float, low: float, close: float) -> pd.Series:
    return pd.Series(
        {"open": open_, "high": high, "low": low, "close": close},
        name=ts(hours),
    )


def ce02(fvg_type: str, bar1_hours: int, bar2_hours: int, bar3_hours: int, gap_top: float, gap_bottom: float) -> FvgEvent:
    return FvgEvent(
        event_code="CE02",
        event_name="fvgConfirmed",
        event_group="CE",
        event_timestamp=ts(bar3_hours),
        fvg_type=fvg_type,
        bar1_timestamp=ts(bar1_hours),
        bar1_high=gap_bottom if fvg_type == "rally" else gap_top,
        bar1_low=gap_top if fvg_type == "drop" else gap_bottom,
        bar2_timestamp=ts(bar2_hours),
        pivot_timestamp=ts(bar2_hours),
        gap_top=gap_top,
        gap_bottom=gap_bottom,
        gap_size=gap_top - gap_bottom,
        bar3_timestamp=ts(bar3_hours),
    )


class SDZonePivotFallbackTests(unittest.TestCase):
    def test_demand_fallback_excludes_departure_high_that_invades_fvg(self):
        engine = SDZoneEngine({"max_zones_per_direction": 10}, "5M")
        engine.on_bar(row(0, 105, 110, 100, 101), [])
        engine.on_bar(row(1, 100, 102, 99, 101), [])
        engine.on_bar(row(2, 101, 105, 100, 104), [])
        result = engine.on_bar(
            row(3, 106, 108, 106, 107),
            [ce02("rally", 1, 2, 3, gap_top=106, gap_bottom=102)],
        )

        self.assertEqual(len(result.created), 1)
        zone = result.created[0]
        self.assertEqual(zone.direction, "demand")
        self.assertEqual(zone.high, 102)
        self.assertEqual(zone.low, 99)

    def test_demand_keeps_valid_departure_high(self):
        engine = SDZoneEngine({"max_zones_per_direction": 10}, "5M")
        engine.on_bar(row(0, 103, 105, 100, 101), [])
        engine.on_bar(row(1, 100, 102, 99, 101), [])
        engine.on_bar(row(2, 101, 105, 100, 104), [])
        result = engine.on_bar(
            row(3, 106, 108, 106, 107),
            [ce02("rally", 1, 2, 3, gap_top=106, gap_bottom=102)],
        )

        self.assertEqual(len(result.created), 1)
        self.assertEqual(result.created[0].high, 105)

    def test_demand_fallback_excludes_extreme_high_that_invades_fvg(self):
        engine = SDZoneEngine({"max_zones_per_direction": 10}, "5M")
        engine.on_bar(row(0, 104, 105, 101, 102), [])
        engine.on_bar(row(1, 101, 108, 99, 100), [])
        engine.on_bar(row(2, 100, 103, 100, 102), [])
        engine.on_bar(row(3, 102, 105, 101, 104), [])
        result = engine.on_bar(
            row(4, 106, 108, 106, 107),
            [ce02("rally", 2, 3, 4, gap_top=106, gap_bottom=103)],
        )

        self.assertEqual(len(result.created), 1)
        zone = result.created[0]
        self.assertEqual(zone.high, 105)
        self.assertEqual(zone.low, 99)

    def test_supply_fallback_excludes_departure_low_that_invades_fvg(self):
        engine = SDZoneEngine({"max_zones_per_direction": 10}, "5M")
        engine.on_bar(row(0, 95, 100, 90, 99), [])
        engine.on_bar(row(1, 100, 101, 98, 99), [])
        engine.on_bar(row(2, 99, 100, 95, 96), [])
        result = engine.on_bar(
            row(3, 95, 94, 92, 93),
            [ce02("drop", 1, 2, 3, gap_top=98, gap_bottom=94)],
        )

        self.assertEqual(len(result.created), 1)
        zone = result.created[0]
        self.assertEqual(zone.direction, "supply")
        self.assertEqual(zone.high, 101)
        self.assertEqual(zone.low, 98)

    def test_supply_keeps_valid_departure_low(self):
        engine = SDZoneEngine({"max_zones_per_direction": 10}, "5M")
        engine.on_bar(row(0, 97, 100, 96, 99), [])
        engine.on_bar(row(1, 100, 101, 98, 99), [])
        engine.on_bar(row(2, 99, 100, 95, 96), [])
        result = engine.on_bar(
            row(3, 95, 94, 92, 93),
            [ce02("drop", 1, 2, 3, gap_top=98, gap_bottom=94)],
        )

        self.assertEqual(len(result.created), 1)
        self.assertEqual(result.created[0].low, 96)

    def test_supply_fallback_excludes_extreme_low_that_invades_fvg(self):
        engine = SDZoneEngine({"max_zones_per_direction": 10}, "5M")
        engine.on_bar(row(0, 97, 100, 95, 99), [])
        engine.on_bar(row(1, 100, 101, 90, 99), [])
        engine.on_bar(row(2, 99, 100, 96, 98), [])
        engine.on_bar(row(3, 98, 99, 95, 96), [])
        result = engine.on_bar(
            row(4, 93, 94, 92, 93),
            [ce02("drop", 2, 3, 4, gap_top=96, gap_bottom=94)],
        )

        self.assertEqual(len(result.created), 1)
        zone = result.created[0]
        self.assertEqual(zone.high, 101)
        self.assertEqual(zone.low, 95)

    def test_last_resolved_zone_remembers_expired_bounce(self):
        engine = SDZoneEngine({"max_zones_per_direction": 10}, "5M")
        engine.on_bar(row(0, 95, 100, 90, 99), [])
        engine.on_bar(row(1, 100, 101, 98, 99), [])
        engine.on_bar(row(2, 99, 100, 95, 96), [])
        result = engine.on_bar(
            row(3, 95, 94, 92, 93),
            [ce02("drop", 1, 2, 3, gap_top=98, gap_bottom=94)],
        )
        zone = result.created[0]

        result = engine.on_bar(row(4, 97, 99, 96, 97), [])

        self.assertEqual(result.mitigated, [zone.zone_id])
        self.assertEqual(result.resolved[0].zone_id, zone.zone_id)
        self.assertEqual(result.resolved[0].direction, "supply")
        self.assertEqual(result.resolved[0].resolution, "bounced")
        self.assertEqual(engine.get_zone_snapshot(97), [])
        self.assertEqual(
            engine.get_last_resolved_zone_snapshot(),
            {
                "zone_id": zone.zone_id,
                "timeframe": "5M",
                "direction": "supply",
                "resolution": "bounced",
                "resolved_at": ts(4).isoformat(),
                "high": 101,
                "low": 98,
                "created_at": ts(3).isoformat(),
                "anchor_ts": ts(2).isoformat(),
            },
        )


if __name__ == "__main__":
    unittest.main()
