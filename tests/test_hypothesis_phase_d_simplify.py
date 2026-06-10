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

    def test_second_ltf_counter_choch_promotes_d_watch_to_speculation(self):
        """D.watch → D.speculation on first counter-HTF ChoCh (bounce failed, Path A)."""
        classifier = HypothesisClassifier()
        bars, watch = open_d_watch(classifier)
        self.assertEqual(watch.phase, "D")
        self.assertEqual(watch.phase_sub_status, "watch")

        bars_5 = [
            bars[-1],
            {"time": "2024-01-02T00:00:00+00:00", "open": 1.117, "high": 1.118, "low": 1.102, "close": 1.104},
        ]
        speculation = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish"),
                bars_5,
                ltf=ltf_counter_structure_event(
                    choch=True,
                    ts="2024-01-02T00:00:00+00:00",
                    level=1.107,
                ),
            ),
        )

        self.assertEqual(speculation.phase, "D")
        self.assertEqual(speculation.phase_sub_status, "speculation")
        self.assertEqual(speculation.debug_facts["phase_d_node"], "D.speculation")
        self.assertEqual(speculation.debug_facts["phase_d_transition"], "choch_2")
        self.assertEqual(
            classifier.state.shadow_thesis.phase_d.choch_2,
            {
                "trigger_type": "choch",
                "choch": True,
                "at": "2024-01-02T00:00:00+00:00",
                "level": 1.107,
            },
        )

    def test_d_speculation_requires_fresh_mss_leg_before_c_pullback(self):
        """D.speculation → C.pullback only on a fresh MSS leg (not the E source leg)."""
        classifier = HypothesisClassifier()
        bars, _ = open_d_watch(classifier)

        bars_5 = [
            bars[-1],
            {"time": "2024-01-02T00:00:00+00:00", "open": 1.117, "high": 1.118, "low": 1.102, "close": 1.104},
        ]
        classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish"),
                bars_5,
                ltf=ltf_counter_structure_event(choch=True, ts="2024-01-02T00:00:00+00:00"),
            ),
        )

        # Stale E-source leg — must not promote to C
        bars_6 = [
            bars_5[-1],
            {"time": "2024-01-02T04:00:00+00:00", "open": 1.104, "high": 1.110, "low": 1.100, "close": 1.102},
        ]
        still_d = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish"),
                bars_6,
                ltf=structure("bearish", high=1.110, low=1.101),
                lower_orderflow=mss_watch_orderflow("OF:e-source"),
            ),
        )
        self.assertEqual(still_d.phase, "D")
        self.assertEqual(still_d.phase_sub_status, "speculation")

        # Fresh leg → C.pullback
        bars_7 = [
            bars_6[-1],
            {"time": "2024-01-02T08:00:00+00:00", "open": 1.102, "high": 1.108, "low": 1.099, "close": 1.101},
        ]
        c_pullback = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish"),
                bars_7,
                ltf=structure("bearish", high=1.108, low=1.100),
                lower_orderflow=mss_watch_orderflow("OF:d-fresh", started_at="2024-01-02T04:00:00+00:00"),
            ),
        )

        self.assertEqual(c_pullback.phase, "C")
        self.assertEqual(c_pullback.phase_sub_status, "pullback")
        self.assertEqual(c_pullback.status, "watching")
        self.assertEqual(c_pullback.direction, "short")

    def test_ltf_counter_sb_after_pullback_confirmed_promotes_d_watch_to_speculation(self):
        """D.watch → D.speculation via Path B: counter SB after pullback_confirmed."""
        classifier = HypothesisClassifier()
        bars, _ = open_d_watch(classifier)

        bars_5 = [
            bars[-1],
            {"time": "2024-01-02T00:00:00+00:00", "open": 1.117, "high": 1.118, "low": 1.102, "close": 1.104},
        ]
        speculation = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish"),
                bars_5,
                ltf=ltf_counter_structure_event(
                    choch=False,
                    phase="pullback_confirmed",
                    ts="2024-01-02T00:00:00+00:00",
                    level=1.107,
                ),
            ),
        )

        self.assertEqual(speculation.phase, "D")
        self.assertEqual(speculation.phase_sub_status, "speculation")
        self.assertEqual(speculation.debug_facts["phase_d_transition"], "sb_pullback")
        self.assertEqual(
            classifier.state.shadow_thesis.phase_d.choch_2,
            {"trigger_type": "sb", "choch": False, "at": "2024-01-02T00:00:00+00:00", "level": 1.107},
        )


if __name__ == "__main__":
    unittest.main()
