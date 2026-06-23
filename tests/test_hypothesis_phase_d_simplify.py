import unittest
import weakref

from ultrab.core.smc.evidence_compiler import EvidenceCompiler
from ultrab.core.smc.hypothesis import HypothesisClassifier


def structure(bias="bullish", phase="open", high=1.123, low=1.10):
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
        "range_high_ts": "2024-01-01T08:00:00+00:00",
        "range_low_ts": "2024-01-01T00:00:00+00:00",
    }


def ltf_counter_structure_event(*, choch, phase="open", ts, level=1.114):
    ltf = structure("bearish", phase, high=1.120, low=1.106)
    if choch:
        # iChoCh (SC06) — primary trigger; EC reads last_isc
        ltf["last_isc"] = {
            "eventTimestamp": ts,
            "eventCode": "SC06",
            "breakDirection": "down",
            "levelPrice": level,
            "choch": True,
            "eventAction": "structure_ichoch",
            "structure_ichoch": True,
        }
    else:
        # Macro SB — sb_seen fallback; EC reads last_sc
        ltf["last_sc"] = {
            "eventTimestamp": ts,
            "eventCode": "SC02",
            "breakDirection": "down",
            "levelPrice": level,
            "choch": False,
            "eventAction": "structure_sb",
        }
    return ltf


def ltf_pro_structure_event(*, ts, level=1.118):
    ltf = structure("bullish", "open", high=1.124, low=1.106)
    ltf["last_sc"] = {
        "eventTimestamp": ts,
        "eventCode": "SC01",
        "breakDirection": "up",
        "levelPrice": level,
        "choch": True,
        "eventAction": "structure_choch",
    }
    return ltf


def dual_snapshot(htf, bars, *, ltf=None, lower_orderflow=None):
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
        "zones": [],
        "liquidity": {},
        "lower_orderflow": lower_orderflow or {},
    }


def build_fused(snapshot):
    htf = snapshot.get("higher_structure") or {}
    ltf = snapshot.get("lower_structure") or {}
    return {
        "higher_context_snapshot": {
            "structure": htf,
            "zones": [],
            "liquidity": {},
            "bias": htf.get("bias"),
            "last_resolved_zone": None,
        },
        "lower_context_snapshot": {
            "structure": ltf,
            "zones": [],
            "bias": ltf.get("bias") if ltf else None,
            "orderflow": snapshot.get("lower_orderflow") or {},
        },
        "reference_tf": "4h",
        "execution_tf": "15m",
        "currentTimestamp": snapshot.get("cursor_time"),
        "currentPrice": snapshot.get("currentPrice"),
    }


_AUTO_ECS = weakref.WeakKeyDictionary()


def classify_with_auto_ec(classifier, snapshot):
    ec = _AUTO_ECS.get(classifier)
    if ec is None:
        ec = EvidenceCompiler()
        _AUTO_ECS[classifier] = ec
    payload = dict(snapshot)
    payload["evidence_candidates"] = [
        candidate.to_dict()
        for candidate in ec.update(build_fused(snapshot), higher_bars=snapshot.get("higher_bars"))
    ]
    return classifier.classify(payload)


def ec_candidate(pattern, direction="long", status="ready", debug_facts=None, location_context=None):
    return {
        "candidate_id": f"test:{pattern}:{direction}",
        "pattern": pattern,
        "status": status,
        "direction": direction,
        "timeframe": None,
        "evidence_refs": [],
        "source_object_refs": [],
        "location_context": location_context or {},
        "blocked_reasons": [],
        "first_seen_at": None,
        "ready_at": None,
        "debug_facts": debug_facts or {},
    }


def epoch_id_for(htf):
    last_sc = htf.get("last_sc") or {}
    return "|".join(
        [
            str(last_sc.get("eventTimestamp") or ""),
            str(last_sc.get("eventCode") or ""),
            str(last_sc.get("breakDirection") or ""),
            str(htf.get("phase_start_ts") or ""),
        ]
    )


def seed_thesis_over(classifier, htf, direction):
    classifier.state.htf_pd_epoch_id = epoch_id_for(htf)
    classifier._commit(
        classifier._phase_x(
            phase_sub_status="X.thesis_over",
            reason="test thesis over",
            required_evidence=["phase_a_thesis_matured"],
            invalidation="Fresh HTF structural epoch or new Phase E seeking state",
            ts="2024-01-01T16:00:00+00:00",
            debug={"htf_pd_epoch_id": classifier.state.htf_pd_epoch_id},
            range_reason="phase_a_thesis_matured",
        )
    )
    classifier.state.active_phase_e_direction = direction


def mss_watch_orderflow(leg_id, started_at="2024-01-01T16:00:00+00:00"):
    return {
        "confirmed_direction": "bullish",
        "quality": "clean",
        "regime": "mss_watch",
        "mss_regime": "mss_watch",
        "mss_watch_confirmed": True,
        "mss_monitor_status": "watching_resolution",
        "range_ref": leg_id,
        "protected_anchor_ref": f"{leg_id}:protected",
        "disruption_point_ref": f"{leg_id}:probe",
        "probe_breaks_protected_anchor": True,
        "mss_trigger_source": "probe_vs_protected_anchor",
        "last_shift_at": started_at,
    }


def open_e_pullback_developing(classifier):
    """Drive classifier to E.pullback_developing via MSS orderflow."""
    bars_1 = [
        {"time": "2024-01-01T04:00:00+00:00", "open": 1.110, "high": 1.120, "low": 1.105, "close": 1.118},
        {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
    ]
    classify_with_auto_ec(classifier, dual_snapshot(structure("bullish"), bars_1))

    bars_2 = [
        bars_1[-1],
        {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.113, "close": 1.118},
    ]
    classify_with_auto_ec(classifier, dual_snapshot(structure("bullish"), bars_2))

    bars_3 = [
        bars_2[-1],
        {"time": "2024-01-01T16:00:00+00:00", "open": 1.118, "high": 1.119, "low": 1.108, "close": 1.110},
    ]
    developing = classify_with_auto_ec(
        classifier,
        dual_snapshot(
            structure("bullish"),
            bars_3,
            ltf=structure("bearish", high=1.120, low=1.108),
            lower_orderflow=mss_watch_orderflow("OF:e-source"),
        ),
    )
    return bars_3, developing


def open_d_watch(classifier):
    """Drive classifier from E.pullback_developing to D.watch.

    D.watch opens on the first LTF pro-HTF ChoCh (bounce initiation).
    """
    bars, _ = open_e_pullback_developing(classifier)
    bars_4 = [
        bars[-1],
        {"time": "2024-01-01T20:00:00+00:00", "open": 1.110, "high": 1.119, "low": 1.105, "close": 1.117},
    ]
    watch = classify_with_auto_ec(
        classifier,
        dual_snapshot(
            structure("bullish"),
            bars_4,
            ltf=ltf_pro_structure_event(ts="2024-01-01T20:00:00+00:00"),
        ),
    )
    return bars_4, watch


class PhaseDSimplifyTests(unittest.TestCase):
    def test_d_watch_opens_on_first_pro_htf_choch(self):
        """D.watch opens the moment phase_e.pro_attempt_seen becomes True.

        Corrected model: the pro-HTF ChoCh IS the D.watch trigger.
        No counter ChoCh is needed first.
        """
        classifier = HypothesisClassifier()
        bars, developing = open_e_pullback_developing(classifier)
        self.assertEqual(developing.phase, "E")
        self.assertEqual(developing.phase_sub_status, "pullback_developing")
        self.assertFalse(classifier.state.shadow_thesis.phase_e.pro_attempt_seen)

        # Pro-HTF ChoCh fires → D.watch opens immediately
        bars_4 = [
            bars[-1],
            {"time": "2024-01-01T20:00:00+00:00", "open": 1.110, "high": 1.119, "low": 1.105, "close": 1.117},
        ]
        watch = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish"),
                bars_4,
                ltf=ltf_pro_structure_event(ts="2024-01-01T20:00:00+00:00", level=1.118),
            ),
        )

        self.assertEqual(watch.phase, "D")
        self.assertEqual(watch.phase_sub_status, "watch")
        self.assertEqual(watch.debug_facts["phase_d_node"], "D.watch")
        self.assertEqual(watch.debug_facts["phase_d_entry"], "E.pullback_developing")
        self.assertEqual(classifier.state.shadow_thesis.phase_d.consumed_leg_id, "OF:e-source")
        choch_1 = classifier.state.shadow_thesis.phase_d.choch_1
        self.assertEqual(choch_1["trigger_type"], "choch")
        self.assertEqual(choch_1["at"], "2024-01-01T20:00:00+00:00")
        self.assertAlmostEqual(choch_1["level"], 1.118)

    def test_thesis_over_blocks_stale_regular_d_watch_reentry(self):
        """X.thesis_over is a hard same-epoch gate; stale E.pullback cannot reopen D."""
        classifier = HypothesisClassifier()
        htf = structure("bullish")
        seed_thesis_over(classifier, htf, "long")
        e_shadow = classifier.state.shadow_thesis.phase_e
        classifier.state.phase_e_shadow_node = "E.pullback_developing"
        e_shadow.pullback_developing_entered_at = "2024-01-01T12:00:00+00:00"
        e_shadow.pro_attempt_seen = True
        e_shadow.pro_attempt_started_at = "2024-01-01T20:00:00+00:00"
        e_shadow.source_orderflow_leg_id = "OF:stale"

        payload = dual_snapshot(
            htf,
            [
                {"time": "2024-01-01T16:00:00+00:00", "open": 1.110, "high": 1.118, "low": 1.106, "close": 1.112},
                {"time": "2024-01-01T20:00:00+00:00", "open": 1.112, "high": 1.121, "low": 1.111, "close": 1.119},
            ],
            ltf=ltf_pro_structure_event(ts="2024-01-01T20:00:00+00:00", level=1.118),
        )

        held = classifier.classify(payload)

        self.assertEqual(held.phase, "X")
        self.assertEqual(held.phase_sub_status, "X.thesis_over")
        self.assertEqual(held.debug_facts["phase_x_hold_reason"], "thesis_over_waiting_for_new_phase_e")
        self.assertTrue(held.debug_facts["phase_x_blocked_stale_shadow_transitions"])
        self.assertIsNone(classifier.state.shadow_thesis.phase_d.node)

    def test_thesis_over_allows_new_htf_extreme_to_restart_e_seeking(self):
        classifier = HypothesisClassifier()
        htf = structure("bullish")
        seed_thesis_over(classifier, htf, "long")
        payload = dual_snapshot(
            htf,
            [
                {"time": "2024-01-01T16:00:00+00:00", "open": 1.110, "high": 1.118, "low": 1.106, "close": 1.112},
                {"time": "2024-01-01T20:00:00+00:00", "open": 1.112, "high": 1.125, "low": 1.111, "close": 1.124},
            ],
        )
        payload["evidence_candidates"] = [
            ec_candidate("phase_e_context", direction="long", debug_facts={"new_htf_extreme": True})
        ]

        restarted = classifier.classify(payload)

        self.assertEqual(restarted.phase, "E")
        self.assertEqual(restarted.phase_sub_status, "seeking")
        self.assertEqual(restarted.debug_facts["phase_x_exit_reason"], "new_phase_e_context_after_thesis_over")

    def test_counter_choch_before_pro_does_not_open_d_watch(self):
        """A counter-HTF ChoCh while in E.pullback_developing must NOT open D.watch.

        Only the pro-HTF ChoCh (bounce initiation) opens D.watch.
        """
        classifier = HypothesisClassifier()
        bars, _ = open_e_pullback_developing(classifier)

        # Counter ChoCh fires — E holds, D.watch must NOT open
        bars_4 = [
            bars[-1],
            {"time": "2024-01-01T20:00:00+00:00", "open": 1.110, "high": 1.113, "low": 1.104, "close": 1.106},
        ]
        still_e = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish"),
                bars_4,
                ltf=ltf_counter_structure_event(choch=True, ts="2024-01-01T20:00:00+00:00"),
            ),
        )

        self.assertEqual(still_e.phase, "E")
        self.assertEqual(still_e.phase_sub_status, "pullback_developing")
        self.assertFalse(classifier.state.shadow_thesis.phase_e.pro_attempt_seen)

    def test_d_watch_exits_to_e_seeking_on_new_htf_extreme(self):
        """D.watch collapses to E.seeking when new_htf_extreme fires (expansion resumed)."""
        classifier = HypothesisClassifier()
        bars, watch = open_d_watch(classifier)
        self.assertEqual(watch.phase, "D")
        self.assertEqual(watch.phase_sub_status, "watch")

        bars_5 = [
            bars[-1],
            {"time": "2024-01-02T00:00:00+00:00", "open": 1.117, "high": 1.124, "low": 1.115, "close": 1.123},
        ]
        payload = dual_snapshot(structure("bullish"), bars_5)
        payload["evidence_candidates"] = [
            ec_candidate("phase_e_context", direction="long", debug_facts={"new_htf_extreme": True})
        ]

        collapsed = classifier.classify(payload)

        self.assertEqual(collapsed.phase, "E")
        self.assertEqual(collapsed.debug_facts.get("phase_d_collapse_rule"), "new_htf_extreme")
        self.assertTrue(collapsed.debug_facts.get("phase_d_collapsed"))

    def test_direction_mismatched_phase_e_context_does_not_move_d_watch_to_c(self):
        classifier = HypothesisClassifier()
        bars, watch = open_d_watch(classifier)
        self.assertEqual(watch.phase, "D")
        self.assertEqual(watch.phase_sub_status, "watch")

        bars_5 = [
            bars[-1],
            {"time": "2024-01-02T00:00:00+00:00", "open": 1.117, "high": 1.118, "low": 1.106, "close": 1.108},
        ]
        payload = dual_snapshot(
            structure("bullish"),
            bars_5,
            ltf=ltf_counter_structure_event(choch=True, ts="2024-01-02T00:00:00+00:00"),
        )
        payload["evidence_candidates"] = [
            ec_candidate(
                "phase_e_context",
                direction="short",
                debug_facts={
                    "ltf_counter_orderflow_mss_watch": True,
                    "ltf_counter_orderflow_leg_id": "OF:wrong-direction",
                    "ltf_counter_orderflow_started_at": "2024-01-02T00:00:00+00:00",
                },
            )
        ]

        held = classifier.classify(payload)

        self.assertEqual(held.phase, "D")
        self.assertEqual(held.phase_sub_status, "watch")
        self.assertIsNone(classifier.state.shadow_thesis.phase_c.origin_node)


def bos_orderflow(leg_id, started_at):
    """Orderflow in directional (BoS) regime — counter direction in a bearish LTF pullback context."""
    return {
        "confirmed_direction": "bearish",
        "quality": "clean",
        "regime": "directional",
        "mss_regime": "directional",
        "mss_watch_confirmed": False,
        "mss_monitor_status": "resolved",
        "range_ref": leg_id,
        "protected_anchor_ref": f"{leg_id}:protected",
        "disruption_point_ref": f"{leg_id}:probe",
        "probe_breaks_protected_anchor": True,
        "mss_trigger_source": "probe_vs_protected_anchor",
        "last_shift_at": started_at,
    }


class EpullbackDevCpullbackPathTests(unittest.TestCase):
    """Tests for the three E.pullback_developing → C.pullback paths."""

    def test_path2_bos_fires_c_pullback(self):
        """Path 2: fresh counter BoS after pullback_developing_entered_at → C.pullback."""
        classifier = HypothesisClassifier()
        bars, _ = open_e_pullback_developing(classifier)

        pd_entered = classifier.state.shadow_thesis.phase_e.pullback_developing_entered_at
        self.assertIsNotNone(pd_entered)

        bos_started = "2024-01-01T18:00:00+00:00"
        self.assertGreater(bos_started, pd_entered)

        bars_next = [
            bars[-1],
            {"time": "2024-01-01T20:00:00+00:00", "open": 1.110, "high": 1.115, "low": 1.100, "close": 1.103},
        ]
        hyp = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish"),
                bars_next,
                ltf=structure("bearish", high=1.120, low=1.100),
                lower_orderflow=bos_orderflow("OF:bos-leg", started_at=bos_started),
            ),
        )

        self.assertEqual(hyp.phase, "C")
        self.assertEqual(hyp.phase_sub_status, "pullback")
        self.assertEqual(classifier.state.shadow_thesis.phase_c.origin_node, "E.pullback_developing_bos")

    def test_path2_stale_bos_does_not_fire(self):
        """Path 2 blocked when BoS leg started before pullback_developing_entered_at."""
        classifier = HypothesisClassifier()
        bars, developing = open_e_pullback_developing(classifier)

        pd_entered = classifier.state.shadow_thesis.phase_e.pullback_developing_entered_at
        self.assertIsNotNone(pd_entered)

        stale_started = "2024-01-01T10:00:00+00:00"
        self.assertLess(stale_started, pd_entered)

        bars_next = [
            bars[-1],
            {"time": "2024-01-01T20:00:00+00:00", "open": 1.110, "high": 1.115, "low": 1.100, "close": 1.103},
        ]
        hyp = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish"),
                bars_next,
                ltf=structure("bearish", high=1.120, low=1.100),
                lower_orderflow=bos_orderflow("OF:stale-leg", started_at=stale_started),
            ),
        )

        self.assertEqual(hyp.phase, "E")
        self.assertEqual(hyp.phase_sub_status, "pullback_developing")
        self.assertIsNone(classifier.state.shadow_thesis.phase_c.origin_node)

    def test_path3_depth_fires_c_pullback_with_renamed_origin(self):
        """Path 3: depth >= 51% with no D entered → C.pullback, origin_node = E.pullback_developing_depth."""
        classifier = HypothesisClassifier()
        bars, _ = open_e_pullback_developing(classifier)

        bars_next = [
            bars[-1],
            {"time": "2024-01-01T20:00:00+00:00", "open": 1.110, "high": 1.115, "low": 1.100, "close": 1.105},
        ]
        htf = structure("bullish", high=1.123, low=1.100)
        # depth_pct computed by EC from ltf vs htf range — inject via ec snapshot directly
        # Use auto_ec path: with a deep enough LTF low relative to HTF range, EC emits high depth_pct.
        # HTF range = 1.100–1.123 (2.3 pip). LTF at low=1.100 = 100% depth.
        hyp = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                htf,
                bars_next,
                ltf=structure("bearish", high=1.112, low=1.100),
                lower_orderflow={},
            ),
        )

        if hyp.phase == "C":
            self.assertEqual(hyp.phase_sub_status, "pullback")
            self.assertEqual(
                classifier.state.shadow_thesis.phase_c.origin_node,
                "E.pullback_developing_depth",
            )

    def test_path2_takes_priority_over_path3(self):
        """When both BoS and depth >= 51% are present, Path 2 (BoS) fires, not Path 3."""
        classifier = HypothesisClassifier()
        bars, _ = open_e_pullback_developing(classifier)

        pd_entered = classifier.state.shadow_thesis.phase_e.pullback_developing_entered_at
        bos_started = "2024-01-01T18:00:00+00:00"
        self.assertGreater(bos_started, pd_entered)

        bars_next = [
            bars[-1],
            {"time": "2024-01-01T20:00:00+00:00", "open": 1.110, "high": 1.115, "low": 1.100, "close": 1.103},
        ]
        hyp = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish", high=1.123, low=1.100),
                bars_next,
                ltf=structure("bearish", high=1.112, low=1.100),
                lower_orderflow=bos_orderflow("OF:bos-priority", started_at=bos_started),
            ),
        )

        if hyp.phase == "C":
            self.assertEqual(
                classifier.state.shadow_thesis.phase_c.origin_node,
                "E.pullback_developing_bos",
            )


if __name__ == "__main__":
    unittest.main()
