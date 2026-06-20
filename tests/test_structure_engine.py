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

    def test_structure_event_uses_sb_name_and_keeps_legacy_alias(self):
        engine = warm_bullish_engine()

        last_sc = engine.get_snapshot(11)["last_sc"]

        self.assertEqual(last_sc["eventName"], "itrSbUp")
        self.assertEqual(last_sc["targetEventName"], "itrSbUp")
        self.assertEqual(last_sc["runtimeAlias"], "itrSbUp")
        self.assertEqual(last_sc["eventAction"], "structure_sb")
        self.assertTrue(last_sc["structure_sb"])
        self.assertFalse(last_sc["structure_choch"])
        self.assertFalse(last_sc["choch"])

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
        # No macro SC (SC01-SC04) fires — warmup registry no longer drives structure.
        # A new post-warmup PE03 at 12.5 arrived; close=12.8 broke it → SC05 iSb fires.
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_code, "SC05")
        self.assertEqual(events[0].event_name, "itrISb")
        self.assertFalse(events[0].choch)
        self.assertEqual(snapshot["phase"], "pullback_confirmed")
        self.assertEqual(snapshot["range_high"], 13)
        self.assertEqual(snapshot["confirmed_by"], "itr")

    def test_snapshot_exposes_recent_itr_levels(self):
        engine = warm_bullish_engine()

        snapshot = engine.get_snapshot(11)

        self.assertEqual(len(snapshot["recent_itr_levels"]), 2)
        self.assertEqual(snapshot["latest_itr_high"]["event_code"], "PE03")
        self.assertEqual(snapshot["latest_itr_low"]["event_code"], "PE04")
        self.assertTrue(snapshot["latest_itr_high"]["level_id"].startswith("PE03:"))
        self.assertTrue(snapshot["latest_itr_low"]["level_id"].startswith("PE04:"))

    def test_structure_sequence_records_confirmed_points_and_probe(self):
        engine = warm_bullish_engine()

        initial = engine.get_snapshot(11)
        self.assertEqual(
            [(p["side"], p["role"], p["price"]) for p in initial["structure_sequence"]],
            [("low", "range_origin", 4)],
        )
        self.assertEqual(initial["structure_probe"]["side"], "high")
        self.assertEqual(initial["structure_probe"]["role"], "extension_probe")
        self.assertEqual(initial["structure_probe"]["price"], 12)
        self.assertEqual(initial["structure_anchor_sequence"], initial["structure_sequence"])
        self.assertEqual(initial["recent_structure_anchor_points"], initial["structure_sequence"])
        self.assertEqual(initial["structure_anchor_probe"], initial["structure_probe"])
        self.assertEqual(len(initial["orderflow_anchor_sequence"]), 1)
        self.assertTrue(initial["orderflow_anchor_sequence"][0]["point_id"].startswith("OFANCH:"))
        self.assertEqual(
            initial["orderflow_anchor_sequence"][0]["source_structure_point_id"],
            initial["structure_sequence"][0]["point_id"],
        )
        self.assertTrue(initial["orderflow_probe"]["point_id"].startswith("OFPROBE:"))
        self.assertEqual(
            initial["orderflow_probe"]["source_structure_probe_id"],
            initial["structure_probe"]["point_id"],
        )

        step(engine, 2, 11, 15, 10, 14)
        step(engine, 3, 14, 14.2, 12, 13, pivots=[pe("PE03", 3, 13)])

        pullback = engine.get_snapshot(13)
        self.assertEqual(
            [(p["side"], p["role"], p["price"]) for p in pullback["structure_sequence"]],
            [("low", "range_origin", 4), ("high", "extension_extreme", 15)],
        )
        self.assertEqual(pullback["recent_structure_sequence_points"], pullback["structure_sequence"])
        self.assertEqual(pullback["recent_structure_anchor_points"], pullback["structure_sequence"])
        self.assertEqual(pullback["recent_orderflow_anchor_points"], pullback["orderflow_anchor_sequence"])
        self.assertEqual(pullback["structure_probe"]["side"], "low")
        self.assertEqual(pullback["structure_probe"]["role"], "pullback_probe")
        self.assertEqual(pullback["structure_probe"]["price"], 12)

        step(engine, 4, 13, 17, 11, 16)
        continued = engine.get_snapshot(16)
        self.assertEqual(
            [(p["side"], p["role"], p["price"]) for p in continued["structure_sequence"]],
            [
                ("low", "range_origin", 4),
                ("high", "extension_extreme", 15),
                ("low", "range_origin", 11),
            ],
        )
        self.assertEqual(continued["structure_probe"]["side"], "high")
        self.assertEqual(continued["structure_probe"]["role"], "extension_probe")
        self.assertEqual(continued["structure_probe"]["price"], 17)

    def test_structure_sequence_choch_promotes_existing_point(self):
        engine = warm_bullish_engine()

        step(engine, 2, 11, 15, 10, 14)
        step(engine, 3, 14, 14.2, 12, 13, pivots=[pe("PE03", 3, 13)])
        step(engine, 4, 13, 14, 3, 3.5)

        snapshot = engine.get_snapshot(3.5)
        self.assertEqual(snapshot["bias"], "bearish")
        self.assertTrue(snapshot["last_sc"]["choch"])
        self.assertTrue(snapshot["last_sc"]["structure_choch"])
        self.assertFalse(snapshot["last_sc"]["structure_sb"])
        self.assertEqual(snapshot["last_sc"]["eventAction"], "structure_choch")
        self.assertEqual(snapshot["last_sc"]["eventName"], "itrSbDown")
        self.assertEqual(snapshot["last_sc"]["targetEventName"], "itrSbDown")
        self.assertEqual(snapshot["last_sc"]["runtimeAlias"], "itrSbDown")
        self.assertNotIn("choach", snapshot["last_sc"])
        self.assertEqual(
            [(p["side"], p["role"], p["price"]) for p in snapshot["structure_sequence"]],
            [("low", "range_origin", 4), ("high", "reversal_ceiling", 15)],
        )
        self.assertEqual(snapshot["structure_probe"]["side"], "low")
        self.assertEqual(snapshot["structure_probe"]["role"], "extension_probe")
        self.assertEqual(snapshot["structure_probe"]["price"], 3)

    def test_structure_sequence_limit_keeps_recent_points(self):
        engine = StructureEngine({"tier": "itr", "structure_sequence_limit": 2}, "1h")
        step(engine, 0, 6, 9, 4, 8, pivots=[pe("PE03", 0, 10), pe("PE04", 0, 4.5)])
        step(engine, 1, 8, 12, 6, 11)
        step(engine, 2, 11, 15, 10, 14)
        step(engine, 3, 14, 14.2, 12, 13, pivots=[pe("PE03", 3, 13)])
        step(engine, 4, 13, 17, 11, 16)

        snapshot = engine.get_snapshot(16)
        self.assertEqual(
            [(p["side"], p["role"], p["price"]) for p in snapshot["structure_sequence"]],
            [("high", "extension_extreme", 15), ("low", "range_origin", 11)],
        )

    def test_bullish_structure_attempt_fails_through_itr_low_anchor(self):
        engine = warm_bullish_engine()

        step(engine, 2, 11, 9.5, 8.5, 9, pivots=[pe("PE04", 2, 8.5)])
        self.assertIsNone(engine.get_snapshot(14)["structure_attempt"])

        step(engine, 3, 9, 9.8, 8.8, 9.5, pivots=[pe("PE03", 3, 14.2)])
        self.assertIsNone(engine.get_snapshot(13.5)["structure_attempt"])

        step(engine, 4, 11.0, 14.5, 10.8, 11.5)
        active = engine.get_snapshot(13.5)["structure_attempt"]
        self.assertEqual(active["direction"], "bullish")
        self.assertEqual(active["alignment"], "pro")
        self.assertEqual(active["origin"], "unclean_orderflow_attempt")
        self.assertEqual(active["orderflow_quality"], "unclean")
        self.assertEqual(active["status"], "active")
        self.assertEqual(active["anchor_price"], 8.5)

        step(engine, 5, 13.5, 13.8, 8.2, 10.2)
        failed = engine.get_snapshot(9.8)["structure_attempt"]
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failure_reason"], "traded_below_itr_low")
        self.assertTrue(failed["anchor_level_id"].startswith("PE04:"))


class StructureEngineInternalSCTests(unittest.TestCase):
    """SC05–SC08: internal iSb / iChoCh against confirmed ITR/LTR pivot levels."""

    # ── bullish iSb (SC05) ────────────────────────────────────────────

    def test_isb_fires_on_new_hh_itr_high(self):
        engine = warm_bullish_engine()
        # New PE03@12 (HH vs warmup PE03@10), close=12.5 breaks it.
        events = step(engine, 2, 11, 13, 10, 12.5, pivots=[pe("PE03", 2, 12)])
        isc = next((e for e in events if e.event_code == "SC05"), None)
        self.assertIsNotNone(isc)
        self.assertEqual(isc.event_name, "itrISb")
        self.assertFalse(isc.choch)
        self.assertFalse(isc.bias_flip)
        self.assertTrue(isc.is_internal)
        self.assertEqual(isc.to_dict()["eventAction"], "structure_isb")

    def test_isb_blocked_when_new_itr_high_is_lh(self):
        engine = warm_bullish_engine()
        # PE03@8 is a LH (8 < warmup PE03@10) — iSb must not fire.
        events = step(engine, 2, 9, 9.5, 7, 8.5, pivots=[pe("PE03", 2, 8)])
        self.assertFalse(any(e.event_code == "SC05" for e in events))

    def test_isb_dedup_same_level_fires_once(self):
        engine = warm_bullish_engine()
        # Bar 2: new PE03@12 arrives, close breaks it → SC05.
        step(engine, 2, 11, 13, 10, 12.5, pivots=[pe("PE03", 2, 12)])
        # Bar 3: same PE03@12 still latest level, close still above it.
        events = step(engine, 3, 12.5, 13.2, 11.5, 12.8)
        self.assertFalse(any(e.event_code == "SC05" for e in events))

    def test_isb_resets_on_new_hh_pe(self):
        engine = warm_bullish_engine()
        step(engine, 2, 11, 13, 10, 12.5, pivots=[pe("PE03", 2, 12)])  # SC05 fires, consumed
        # Bar 3: new PE03@14 (HH vs 12) — fresh level, close breaks it → SC05 again.
        events = step(engine, 3, 12.5, 15, 12, 14.5, pivots=[pe("PE03", 3, 14)])
        self.assertTrue(any(e.event_code == "SC05" for e in events))

    def test_warmup_pivot_does_not_trigger_isb(self):
        # The PE03@10 that fired warmup SC01 is consumed; subsequent bars with
        # close > 10 must not re-emit SC05 while it remains the latest level.
        engine = warm_bullish_engine()
        events = step(engine, 2, 11, 15, 10, 14)  # close=14 > warmup PE03@10
        self.assertFalse(any(e.event_code == "SC05" for e in events))

    # ── bullish iChoCh (SC06) ─────────────────────────────────────────

    def test_ichoch_fires_below_itr_low_in_bullish(self):
        engine = warm_bullish_engine()
        # range_low=4 (wick). PE04@4.5. close=4.3: below PE04 but above range_low.
        events = step(engine, 2, 11, 12, 4.2, 4.3)
        isc = next((e for e in events if e.event_code == "SC06"), None)
        self.assertIsNotNone(isc)
        self.assertEqual(isc.event_name, "itrIChoCh")
        self.assertTrue(isc.choch)
        self.assertFalse(isc.bias_flip)
        self.assertTrue(isc.is_internal)
        self.assertEqual(isc.to_dict()["eventAction"], "structure_ichoch")

    def test_ichoch_dedup_same_itr_low_fires_once(self):
        engine = warm_bullish_engine()
        step(engine, 2, 11, 12, 4.2, 4.3)          # SC06 fires
        events = step(engine, 3, 4.3, 5, 4.1, 4.4)  # still below PE04@4.5, same level
        self.assertFalse(any(e.event_code == "SC06" for e in events))

    # ── pure observation ──────────────────────────────────────────────

    def test_isb_does_not_change_bias_or_range(self):
        engine = warm_bullish_engine()
        step(engine, 2, 11, 20, 10, 19)  # extend range_high to 20, no PE
        # Bar 3: PE03@16 (HH vs 10), close=17 > 16 but < range_high=20.
        # iSb fires (SC05). No macro SC (close < range_high). Bias and floor unchanged.
        events = step(engine, 3, 19, 20, 15, 17, pivots=[pe("PE03", 3, 16)])
        snap = engine.get_snapshot(17)
        self.assertTrue(any(e.event_code == "SC05" for e in events))
        self.assertFalse(any(e.event_code in {"SC01", "SC02"} for e in events))
        self.assertEqual(snap["bias"], "bullish")
        self.assertEqual(snap["range_low"], 4)    # wick floor untouched
        self.assertEqual(snap["range_high"], 20)  # ceiling untouched

    def test_ichoch_does_not_change_structural_state(self):
        engine = warm_bullish_engine()
        snap_before = engine.get_snapshot(11)
        step(engine, 2, 11, 12, 4.2, 4.3)
        snap_after = engine.get_snapshot(4.3)
        self.assertEqual(snap_after["bias"], "bullish")
        self.assertEqual(snap_after["range_low"], snap_before["range_low"])

    # ── co-emit: SC05 + SC01 on same bar ─────────────────────────────

    def test_isb_and_range_sc_coemit_on_same_bar(self):
        engine = warm_bullish_engine()
        step(engine, 2, 11, 15, 10, 14)                                   # extend
        step(engine, 3, 14, 15.2, 13, 13.5, pivots=[pe("PE03", 3, 13)])   # pullback_confirmed, SC05 fires
        # Bar 4: new PE03@14 (HH), pullback_confirmed; close=16 > range_high=15 → SC01 AND SC05.
        events = step(engine, 4, 13.5, 16.5, 13, 16, pivots=[pe("PE03", 4, 14)])
        codes = [e.event_code for e in events]
        self.assertIn("SC05", codes)
        self.assertIn("SC01", codes)
        self.assertEqual(codes.index("SC05"), 0)   # internal fires first

    # ── bearish iSb / iChoCh ─────────────────────────────────────────

    def test_bearish_isb_fires_on_new_ll_itr_low(self):
        engine = warm_bearish_engine()
        # Warmup PE04@5.5 consumed. New PE04@4 (LL vs 5.5), close=3.8 < 4.
        # range_low=3 (wick) so close=3.8 > 3 → no SC02.
        events = step(engine, 2, 5, 6, 3.5, 3.8, pivots=[pe("PE04", 2, 4)])
        isc = next((e for e in events if e.event_code == "SC05"), None)
        self.assertIsNotNone(isc)
        self.assertEqual(isc.event_name, "itrISb")
        self.assertFalse(isc.choch)
        self.assertEqual(isc.break_direction, "down")

    def test_bearish_ichoch_fires_above_itr_high(self):
        engine = warm_bearish_engine()
        # Bar 2: new PE03@8 arrives (a LH since 8 < 10.5), bearish extension.
        step(engine, 2, 5, 6, 2.5, 3, pivots=[pe("PE03", 2, 8)])
        # Bar 3: close=9 > PE03@8 but < range_high=10 → SC06 iChoCh; no range SC.
        events = step(engine, 3, 3, 9.5, 2.8, 9)
        isc = next((e for e in events if e.event_code == "SC06"), None)
        self.assertIsNotNone(isc)
        self.assertEqual(isc.event_name, "itrIChoCh")
        self.assertTrue(isc.choch)
        self.assertEqual(isc.break_direction, "up")
        self.assertEqual(engine.get_snapshot(9)["bias"], "bearish")  # pure observation

    # ── LTR tier → SC07 / SC08 ───────────────────────────────────────

    def test_ltr_tier_does_not_emit_sc07_sc08(self):
        # SC07/SC08 (LTR internal) are disabled — last_isc stays None for ltr tier
        engine = StructureEngine({"tier": "ltr"}, "1h")
        step(engine, 0, 6, 9, 4, 8, pivots=[pe("PE05", 0, 10), pe("PE06", 0, 4.5)])
        step(engine, 1, 8, 12, 6, 11)   # SC03 ltrSbUp

        events = step(engine, 2, 11, 13, 10, 12.5, pivots=[pe("PE05", 2, 12)])
        self.assertFalse(any(e.event_code in {"SC07", "SC08"} for e in events))

        snap = engine.get_snapshot(12.5)
        self.assertIsNone(snap["last_isc"])

        events = step(engine, 3, 11, 12, 4.2, 4.3)
        self.assertFalse(any(e.event_code in {"SC07", "SC08"} for e in events))

    # ── snapshot exposes last_isc ─────────────────────────────────────

    def test_snapshot_exposes_last_isc(self):
        engine = warm_bullish_engine()
        step(engine, 2, 11, 13, 10, 12.5, pivots=[pe("PE03", 2, 12)])
        snap = engine.get_snapshot(12.5)
        self.assertIsNotNone(snap["last_isc"])
        self.assertEqual(snap["last_isc"]["eventCode"], "SC05")
        self.assertEqual(snap["last_isc"]["eventAction"], "structure_isb")
        self.assertTrue(snap["last_isc"]["is_internal"])
        self.assertTrue(snap["last_isc"]["structure_isb"])
        self.assertFalse(snap["last_isc"]["structure_ichoch"])

    def test_snapshot_exposes_internal_structure_sequence(self):
        engine = warm_bullish_engine()
        step(engine, 2, 11, 13, 10, 12.5, pivots=[pe("PE03", 2, 12)])
        step(engine, 3, 12.5, 13, 4.2, 4.3)
        snap = engine.get_snapshot(4.3)

        sequence = snap["internal_structure_sequence"]
        self.assertEqual([event["eventCode"] for event in sequence], ["SC05", "SC06"])
        self.assertEqual(sequence, snap["recent_internal_structure_events"])
        self.assertEqual(sequence[0]["eventAction"], "structure_isb")
        self.assertEqual(sequence[1]["eventAction"], "structure_ichoch")


if __name__ == "__main__":
    unittest.main()
