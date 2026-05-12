import unittest

from ultrab.core.smc.hypothesis import HypothesisClassifier


def structure(bias="bullish", phase="open", high=1.12, low=1.10):
    return {
        "tier": "itr",
        "bias": bias,
        "phase": phase,
        "range_high": high,
        "range_low": low,
        "pd_midpoint": (high + low) / 2,
        "pd_pct": 70.0,
        "confirmed_by": None,
        "confirmed_zone_id": None,
        "pullback_confirmed_ts": None,
        "last_sc": {
            "eventTimestamp": "2024-01-01T00:00:00+00:00",
            "eventCode": "SC01" if bias == "bullish" else "SC02",
            "breakDirection": "up" if bias == "bullish" else "down",
        },
        "phase_start_ts": "2024-01-01T00:00:00+00:00",
        "range_high_ts": "2024-01-01T04:00:00+00:00",
        "range_low_ts": "2024-01-01T00:00:00+00:00",
    }


def dual_snapshot(htf, bars, ltf=None, zones=None, higher_last_resolved_zone=None):
    return {
        "mode": "dual",
        "combo": "15m_4h",
        "lower_tf": "15m",
        "higher_tf": "4h",
        "cursor_time": bars[-1]["time"],
        "higher_structure": htf,
        "lower_structure": ltf,
        "higher_bars": bars,
        "lower_bars": [],
        "zones": zones or [],
        "higher_last_resolved_zone": higher_last_resolved_zone,
    }


def sd_zone(zone_id, direction, timeframe, in_zone=False):
    return {
        "zone_id": zone_id,
        "direction": direction,
        "high": 1.13,
        "low": 1.12,
        "in_zone": in_zone,
        "timeframe": timeframe,
        "created_at": "2024-01-01T08:00:00+00:00",
    }


def resolved_zone(zone_id, direction, timeframe, resolution):
    return {
        "zone_id": zone_id,
        "direction": direction,
        "timeframe": timeframe,
        "resolution": resolution,
        "resolved_at": "2024-01-01T12:00:00+00:00",
        "high": 1.13,
        "low": 1.12,
        "created_at": "2024-01-01T08:00:00+00:00",
        "anchor_ts": "2024-01-01T04:00:00+00:00",
    }


def classify_bullish_phase_c(classifier):
    classifier.classify(
        dual_snapshot(
            structure("bullish", "open", high=1.123, low=1.10),
            [
                {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
            ],
        )
    )
    ltf = structure("bearish", "open", high=1.119, low=1.108)
    classifier.classify(
        dual_snapshot(
            structure("bullish", "open", high=1.123, low=1.10),
            [
                {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.109},
            ],
            ltf=ltf,
            zones=[sd_zone("SD-15m-supply", "supply", "15m", in_zone=False)],
            higher_last_resolved_zone=resolved_zone("SD-4h-supply", "supply", "4h", "bounced"),
        )
    )
    return classifier.classify(
        dual_snapshot(
            structure("bullish", "open", high=1.123, low=1.10),
            [
                {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.109},
                {"time": "2024-01-01T16:00:00+00:00", "open": 1.109, "high": 1.120, "low": 1.107, "close": 1.118},
            ],
            ltf=ltf,
            zones=[sd_zone("SD-15m-supply", "supply", "15m", in_zone=True)],
            higher_last_resolved_zone=resolved_zone("SD-4h-supply", "supply", "4h", "bounced"),
        )
    )


class HypothesisClassifierTests(unittest.TestCase):
    def test_bullish_open_htf_classifies_phase_e(self):
        classifier = HypothesisClassifier()
        hyp = classifier.classify(
            dual_snapshot(
                structure("bullish", "open", high=1.12, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )

        self.assertEqual(hyp.phase, "E")
        self.assertEqual(hyp.direction, "long")
        self.assertEqual(hyp.entry_policy, "skip")

    def test_bullish_phase_e_reaction_without_reaction_point_stays_phase_e(self):
        classifier = HypothesisClassifier()
        first = dual_snapshot(
            structure("bullish", "open", high=1.12, low=1.10),
            [
                {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
            ],
        )
        classifier.classify(first)

        hyp = classifier.classify(
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.109},
                ],
            )
        )

        self.assertEqual(hyp.phase, "E")
        self.assertEqual(hyp.direction, "long")
        self.assertTrue(hyp.debug_facts["reaction_confirmed"])
        self.assertFalse(hyp.debug_facts["phase_d_ready"])

    def test_bearish_phase_e_reaction_without_reaction_point_stays_phase_e(self):
        classifier = HypothesisClassifier()
        classifier.classify(
            dual_snapshot(
                structure("bearish", "open", high=1.12, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.118, "low": 1.10, "close": 1.103},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.103, "high": 1.109, "low": 1.098, "close": 1.100},
                ],
            )
        )

        hyp = classifier.classify(
            dual_snapshot(
                structure("bearish", "open", high=1.12, low=1.098),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.103, "high": 1.109, "low": 1.098, "close": 1.100},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.100, "high": 1.111, "low": 1.099, "close": 1.110},
                ],
            )
        )

        self.assertEqual(hyp.phase, "E")
        self.assertEqual(hyp.direction, "short")
        self.assertTrue(hyp.debug_facts["reaction_confirmed"])
        self.assertFalse(hyp.debug_facts["phase_d_ready"])

    def test_bullish_opposing_htf_sd_and_ltf_counter_sd_classifies_phase_d(self):
        classifier = HypothesisClassifier()
        classifier.classify(
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )

        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        htf["confirmed_by"] = "sd_zone"
        htf["confirmed_zone_id"] = "SD-4h-supply"
        ltf = structure("bearish", "open", high=1.119, low=1.108)
        hyp = classifier.classify(
            dual_snapshot(
                htf,
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.109},
                ],
                ltf=ltf,
                zones=[sd_zone("SD-15m-supply", "supply", "15m")],
            )
        )

        self.assertEqual(hyp.phase, "D")
        self.assertEqual(hyp.direction, "none")
        self.assertEqual(hyp.debug_facts["phase_d_trigger"], "opposing_htf_sd_reaction_with_ltf_counter_sd")
        self.assertFalse(hyp.debug_facts["htf_opposing_sd_resolved"])

    def test_bullish_resolved_htf_sd_and_ltf_counter_sd_classifies_phase_d(self):
        classifier = HypothesisClassifier()
        classifier.classify(
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )

        ltf = structure("bearish", "open", high=1.119, low=1.108)
        hyp = classifier.classify(
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.109},
                ],
                ltf=ltf,
                zones=[sd_zone("SD-15m-supply", "supply", "15m")],
                higher_last_resolved_zone=resolved_zone("SD-4h-supply", "supply", "4h", "bounced"),
            )
        )

        self.assertEqual(hyp.phase, "D")
        self.assertEqual(hyp.direction, "none")
        self.assertTrue(hyp.debug_facts["htf_opposing_sd_resolved"])
        self.assertEqual(hyp.debug_facts["htf_last_resolved_zone_id"], "SD-4h-supply")
        self.assertEqual(hyp.debug_facts["htf_last_resolved_zone_resolution"], "bounced")
        self.assertEqual(hyp.debug_facts["phase_d_trigger"], "opposing_htf_sd_reaction_with_ltf_counter_sd")

    def test_bullish_resolved_htf_liquidity_run_does_not_classify_phase_d(self):
        classifier = HypothesisClassifier()
        classifier.classify(
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )

        ltf = structure("bearish", "open", high=1.119, low=1.108)
        hyp = classifier.classify(
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.109},
                ],
                ltf=ltf,
                zones=[sd_zone("SD-15m-supply", "supply", "15m")],
                higher_last_resolved_zone=resolved_zone("SD-4h-supply", "supply", "4h", "liquidity_run"),
            )
        )

        self.assertEqual(hyp.phase, "E")
        self.assertFalse(hyp.debug_facts["htf_opposing_sd_resolved"])
        self.assertFalse(hyp.debug_facts["phase_d_ready"])

    def test_bearish_new_low_with_ltf_counter_bias_classifies_phase_d(self):
        classifier = HypothesisClassifier()
        classifier.classify(
            dual_snapshot(
                structure("bearish", "open", high=1.12, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.118, "low": 1.10, "close": 1.103},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.103, "high": 1.109, "low": 1.098, "close": 1.100},
                ],
            )
        )

        ltf = structure("bullish", "open", high=1.108, low=1.099)
        hyp = classifier.classify(
            dual_snapshot(
                structure("bearish", "open", high=1.12, low=1.096),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.103, "high": 1.109, "low": 1.098, "close": 1.100},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.100, "high": 1.104, "low": 1.096, "close": 1.101},
                ],
                ltf=ltf,
            )
        )

        self.assertEqual(hyp.phase, "D")
        self.assertEqual(hyp.direction, "none")
        self.assertEqual(hyp.debug_facts["phase_d_trigger"], "new_htf_extreme_with_ltf_counter_bias")

    def test_bullish_phase_d_to_phase_c_watching_when_ltf_counter_story_has_no_poi(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classifier.classify(
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )

        ltf = structure("bearish", "open", high=1.119, low=1.108)
        classifier.classify(
            dual_snapshot(
                structure("bullish", "open", high=1.124, low=1.10),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.124, "low": 1.116, "close": 1.120},
                ],
                ltf=ltf,
            )
        )

        hyp = classifier.classify(
            dual_snapshot(
                structure("bullish", "open", high=1.124, low=1.10),
                [
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.124, "low": 1.116, "close": 1.120},
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.120, "high": 1.121, "low": 1.109, "close": 1.112},
                ],
                ltf=ltf,
            )
        )

        self.assertEqual(hyp.phase, "C")
        self.assertEqual(hyp.status, "watching")
        self.assertEqual(hyp.direction, "short")
        self.assertIsNone(hyp.poi_id)
        self.assertEqual(hyp.entry_policy, "wait")
        self.assertTrue(hyp.debug_facts["phase_c_story_ready"])
        self.assertFalse(hyp.debug_facts["phase_c_armed"])
        self.assertTrue(hyp.debug_facts["phase_c_ltf_counter_pd_break"])

    def test_bullish_phase_d_to_phase_c_armed_when_counter_poi_exists_before_return(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classifier.classify(
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )

        ltf = structure("bearish", "open", high=1.119, low=1.108)
        d_snapshot = dual_snapshot(
            structure("bullish", "open", high=1.123, low=1.10),
            [
                {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.109},
            ],
            ltf=ltf,
            zones=[sd_zone("SD-15m-supply", "supply", "15m", in_zone=False)],
            higher_last_resolved_zone=resolved_zone("SD-4h-supply", "supply", "4h", "bounced"),
        )
        classifier.classify(d_snapshot)

        hyp = classifier.classify(d_snapshot)

        self.assertEqual(hyp.phase, "C")
        self.assertEqual(hyp.status, "armed")
        self.assertEqual(hyp.direction, "short")
        self.assertEqual(hyp.poi_id, "SD-15m-supply")
        self.assertEqual(hyp.entry_policy, "hybrid")
        self.assertTrue(hyp.debug_facts["phase_c_candidate"])
        self.assertTrue(hyp.debug_facts["phase_c_ready"])
        self.assertFalse(hyp.debug_facts["phase_c_selected_poi_touched"])
        self.assertEqual(hyp.debug_facts["phase_c_selected_poi_id"], "SD-15m-supply")

    def test_bullish_phase_c_debug_marks_poi_touch_when_ltf_counter_poi_returns(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        hyp = classify_bullish_phase_c(classifier)

        self.assertEqual(hyp.phase, "C")
        self.assertEqual(hyp.direction, "short")
        self.assertEqual(hyp.status, "armed")
        self.assertEqual(hyp.poi_id, "SD-15m-supply")
        self.assertEqual(hyp.entry_policy, "hybrid")
        self.assertTrue(hyp.debug_facts["phase_c_ready"])
        self.assertTrue(hyp.debug_facts["phase_c_selected_poi_touched"])
        self.assertEqual(hyp.debug_facts["phase_c_ltf_counter_sd_returned"], ["SD-15m-supply"])

    def test_phase_c_collapses_to_phase_e_when_htf_continuation_resumes(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_bullish_phase_c(classifier)

        hyp = classifier.classify(
            dual_snapshot(
                structure("bullish", "open", high=1.124, low=1.10),
                [
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.109, "high": 1.120, "low": 1.107, "close": 1.118},
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.118, "high": 1.125, "low": 1.117, "close": 1.124},
                ],
                ltf=structure("bearish", "open", high=1.119, low=1.108),
                zones=[sd_zone("SD-15m-supply", "supply", "15m", in_zone=False)],
            )
        )

        self.assertEqual(hyp.phase, "E")
        self.assertEqual(hyp.direction, "long")
        self.assertTrue(hyp.debug_facts["phase_c_collapsed"])
        self.assertEqual(
            hyp.debug_facts["phase_c_collapse_rule"],
            "bullish_phase_d_close_above_phase_e_extreme",
        )

    def test_phase_c_to_strict_phase_b_when_htf_demand_reacts_and_ltf_flips_bullish(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_bullish_phase_c(classifier)

        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        htf["pd_pct"] = 40.0
        hyp = classifier.classify(
            dual_snapshot(
                htf,
                [
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.109, "high": 1.120, "low": 1.107, "close": 1.118},
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.118, "high": 1.120, "low": 1.110, "close": 1.116},
                ],
                ltf=structure("bullish", "open", high=1.120, low=1.110),
                zones=[
                    sd_zone("SD-4h-demand", "demand", "4h", in_zone=True),
                    sd_zone("SD-15m-demand", "demand", "15m", in_zone=False),
                ],
            )
        )

        self.assertEqual(hyp.phase, "B")
        self.assertEqual(hyp.status, "armed")
        self.assertEqual(hyp.direction, "long")
        self.assertEqual(hyp.poi_id, "SD-15m-demand")
        self.assertEqual(hyp.entry_policy, "hybrid")
        self.assertTrue(hyp.debug_facts["phase_b_ready"])
        self.assertEqual(hyp.debug_facts["phase_b_candidate_variant"], "strict")

    def test_bearish_strict_phase_b_classifies_from_pullback_context(self):
        classifier = HypothesisClassifier()
        htf = structure("bearish", "pullback_confirmed", high=1.12, low=1.10)
        htf["pd_pct"] = 60.0

        hyp = classifier.classify(
            dual_snapshot(
                htf,
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.103, "high": 1.109, "low": 1.098, "close": 1.100},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.100, "high": 1.111, "low": 1.099, "close": 1.108},
                ],
                ltf=structure("bearish", "open", high=1.111, low=1.099),
                zones=[
                    sd_zone("SD-4h-supply", "supply", "4h", in_zone=True),
                    sd_zone("SD-15m-supply", "supply", "15m", in_zone=False),
                ],
            )
        )

        self.assertEqual(hyp.phase, "B")
        self.assertEqual(hyp.status, "armed")
        self.assertEqual(hyp.direction, "short")
        self.assertEqual(hyp.poi_id, "SD-15m-supply")
        self.assertTrue(hyp.debug_facts["phase_b_ready"])
        self.assertEqual(hyp.debug_facts["phase_b_candidate_variant"], "strict")

    def test_bullish_strict_phase_b_accepts_resolved_htf_demand_bounce(self):
        classifier = HypothesisClassifier()
        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        htf["pd_pct"] = 40.0

        hyp = classifier.classify(
            dual_snapshot(
                htf,
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.112},
                ],
                ltf=structure("bullish", "open", high=1.120, low=1.110),
                zones=[sd_zone("SD-15m-demand", "demand", "15m", in_zone=False)],
                higher_last_resolved_zone=resolved_zone("SD-4h-demand", "demand", "4h", "bounced"),
            )
        )

        self.assertEqual(hyp.phase, "B")
        self.assertEqual(hyp.direction, "long")
        self.assertEqual(hyp.poi_id, "SD-15m-demand")
        self.assertTrue(hyp.debug_facts["phase_b_htf_pro_sd_resolved"])
        self.assertEqual(hyp.debug_facts["phase_b_candidate_variant"], "strict")

    def test_phase_c_holds_and_marks_missing_htf_demand_b_candidate_without_classifying_b(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_bullish_phase_c(classifier)

        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        htf["confirmed_by"] = "sd_zone"
        htf["pd_pct"] = 40.0
        hyp = classifier.classify(
            dual_snapshot(
                htf,
                [
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.109, "high": 1.120, "low": 1.107, "close": 1.118},
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.118, "high": 1.120, "low": 1.110, "close": 1.116},
                ],
                ltf=structure("bullish", "open", high=1.120, low=1.110),
                zones=[sd_zone("SD-15m-demand", "demand", "15m", in_zone=True)],
            )
        )

        self.assertEqual(hyp.phase, "C")
        self.assertTrue(hyp.debug_facts["phase_c_held"])
        self.assertTrue(hyp.debug_facts["phase_b_candidate"])
        self.assertEqual(hyp.debug_facts["phase_b_candidate_variant"], "missing_htf_reaction_zone")
        self.assertEqual(hyp.debug_facts["phase_b_blocked_reason"], "no_htf_demand_reaction")

    def test_phase_c_holds_and_marks_shallow_b_candidate_without_classifying_b(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_bullish_phase_c(classifier)

        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        htf["pd_pct"] = 40.0
        hyp = classifier.classify(
            dual_snapshot(
                htf,
                [
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.109, "high": 1.120, "low": 1.107, "close": 1.118},
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.118, "high": 1.120, "low": 1.110, "close": 1.116},
                ],
                ltf=structure("bullish", "open", high=1.120, low=1.110),
                zones=[
                    sd_zone("SD-4h-demand", "demand", "4h", in_zone=False),
                    sd_zone("SD-15m-demand", "demand", "15m", in_zone=False),
                ],
            )
        )

        self.assertEqual(hyp.phase, "C")
        self.assertTrue(hyp.debug_facts["phase_c_held"])
        self.assertTrue(hyp.debug_facts["phase_b_candidate"])
        self.assertEqual(hyp.debug_facts["phase_b_candidate_variant"], "shallow")
        self.assertEqual(hyp.debug_facts["phase_b_blocked_reason"], "no_htf_demand_reaction")


if __name__ == "__main__":
    unittest.main()
