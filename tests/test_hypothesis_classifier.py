import unittest
import weakref

from ultrab.core.smc.evidence_compiler import EvidenceCompiler
from ultrab.core.smc.hypothesis import HypothesisClassifier


PHASE_B_C_A_DISABLED_REASON = (
    "Phase B/C/A gates are temporarily disabled during Phase D simplify migration"
)
LEGACY_PHASE_D_DISABLED_REASON = (
    "Legacy four-node Phase D model is archived during Phase D simplify migration"
)


def structure(bias="bullish", phase="open", high=1.12, low=1.10, choch=False):
    last_sc: dict = {
        "eventTimestamp": "2024-01-01T00:00:00+00:00",
        "eventCode": "SC01" if bias == "bullish" else "SC02",
        "breakDirection": "up" if bias == "bullish" else "down",
    }
    if choch:
        last_sc["choch"] = True
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
        "last_sc": last_sc,
        "phase_start_ts": "2024-01-01T00:00:00+00:00",
        "range_high_ts": "2024-01-01T04:00:00+00:00",
        "range_low_ts": "2024-01-01T00:00:00+00:00",
    }


def dual_snapshot(
    htf,
    bars,
    ltf=None,
    zones=None,
    higher_last_resolved_zone=None,
    liquidity=None,
    lower_orderflow=None,
    current_price=None,
):
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
        "liquidity": liquidity or {},
        "lower_orderflow": lower_orderflow or {},
        "currentPrice": current_price,
    }


def _build_fused(snapshot):
    """Build a minimal DualContextSnapshot from a flat test snapshot for EvidenceCompiler."""
    htf = snapshot.get("higher_structure") or {}
    ltf = snapshot.get("lower_structure") or {}
    higher_tf = snapshot.get("higher_tf", "4h")
    lower_tf = snapshot.get("lower_tf", "15m")
    all_zones = snapshot.get("zones") or []
    return {
        "higher_context_snapshot": {
            "structure": htf,
            "zones": [z for z in all_zones if z.get("timeframe") == higher_tf],
            "liquidity": snapshot.get("liquidity") or {},
            "bias": htf.get("bias"),
            "last_resolved_zone": snapshot.get("higher_last_resolved_zone"),
        },
        "lower_context_snapshot": {
            "structure": ltf,
            "zones": [z for z in all_zones if z.get("timeframe") == lower_tf],
            "bias": ltf.get("bias") if ltf else None,
            "orderflow": snapshot.get("lower_orderflow") or {},
        },
        "reference_tf": higher_tf,
        "execution_tf": lower_tf,
        "currentTimestamp": snapshot.get("cursor_time"),
        "currentPrice": snapshot.get("currentPrice"),
    }


def with_evidence_compiler(ec, snapshot):
    fused = _build_fused(snapshot)
    candidates = ec.update(fused, higher_bars=snapshot.get("higher_bars"))
    payload = dict(snapshot)
    payload["evidence_candidates"] = [c.to_dict() for c in candidates]
    return payload


def classify_with_ec(classifier, ec, snapshot):
    return classifier.classify(with_evidence_compiler(ec, snapshot))


_AUTO_ECS = weakref.WeakKeyDictionary()


def classify_with_auto_ec(classifier, snapshot):
    if "evidence_candidates" in snapshot:
        return classifier.classify(snapshot)
    ec = _AUTO_ECS.get(classifier)
    if ec is None:
        ec = EvidenceCompiler()
        _AUTO_ECS[classifier] = ec
    return classify_with_ec(classifier, ec, snapshot)


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


def liquidity_grab(
    kind="pd",
    direction="bearish",
    pool_id=None,
    epoch_id="2024-01-01T00:00:00+00:00|SC01|up|2024-01-01T00:00:00+00:00",
    taken_at="2024-01-01T11:00:00+00:00",
    reclaimed_at="2024-01-01T11:30:00+00:00",
    level=1.123,
):
    pool_id = pool_id or f"liq-{kind}-{direction}"
    source = "range_high" if kind == "pd" else "eqh"
    side = "buy_side" if direction == "bearish" else "sell_side"
    return {
        "current_triggerable_liquidity_events": [
            {
                "pool_id": pool_id,
                "liquidity_event_id": f"{pool_id}:{reclaimed_at}",
                "pool_kind": f"htf_{kind}",
                "variant": "level" if kind == "pd" else "eq",
                "htf_pd_epoch_id": epoch_id,
                "is_triggerable": True,
                "scope": "active_current_epoch",
                "direction": direction,
                "level": level,
                "source": source,
                "side": side,
                "taken_at": taken_at,
                "reclaimed_at": reclaimed_at,
                "reclaimed_price": 1.115,
            }
        ],
    }


def itr_liquidity_grab(direction="bullish", variant="level", pool_id=None):
    return {
        "htf_itr_grab_reclaim_ready": True,
        "htf_itr_grab_reclaim_variant": variant,
        "htf_itr_grab_reclaim_side": "sell_side" if direction == "bullish" else "buy_side",
        "htf_itr_grab_reclaim_direction": direction,
        "htf_itr_grab_reclaim_level": 1.111,
        "htf_itr_grab_reclaim_source": "htf_itr_low" if direction == "bullish" else "htf_itr_high",
        "htf_itr_grab_reclaim_pool_id": pool_id or f"liq-itr-{variant}-{direction}",
        "htf_itr_grab_reclaim_came_from": "above" if direction == "bullish" else "below",
        "htf_itr_grab_reclaim_left_to": "above" if direction == "bullish" else "below",
        "htf_itr_level_grab_reclaim_ready": variant == "level",
        "htf_itr_eq_grab_reclaim_ready": variant == "eq",
    }


def itr_anchor_run(direction="bullish", variant="level", pool_id=None):
    return {
        "htf_itr_anchor_run_ready": True,
        "htf_itr_anchor_run_variant": variant,
        "htf_itr_anchor_run_side": "sell_side" if direction == "bullish" else "buy_side",
        "htf_itr_anchor_run_direction": direction,
        "htf_itr_anchor_run_level": 1.111,
        "htf_itr_anchor_run_source": "htf_itr_low" if direction == "bullish" else "htf_itr_high",
        "htf_itr_anchor_run_pool_id": pool_id or f"liq-itr-{variant}-{direction}",
        "htf_itr_anchor_run_take_type": "wick_sweep",
        "htf_itr_anchor_run_at": "2024-01-02T04:00:00+00:00",
        "htf_itr_level_anchor_run_ready": variant == "level",
        "htf_itr_eq_anchor_run_ready": variant == "eq",
    }


def structure_attempt(status, anchor_id="PE04:2024-01-01T09:00:00+00:00", direction="bullish"):
    return {
        "attempt_id": f"pro:{anchor_id}",
        "direction": direction,
        "alignment": "pro",
        "origin": "unclean_orderflow_attempt",
        "orderflow_quality": "unclean",
        "anchor_level_id": anchor_id,
        "anchor_price": 1.111,
        "started_at": "2024-01-01T09:00:00+00:00",
        "extreme_price": 1.119,
        "status": status,
        "failed_at": "2024-01-01T10:00:00+00:00" if status == "failed" else None,
        "failure_reason": "traded_below_itr_low" if status == "failed" else None,
    }


def clean_orderflow(direction="bearish", leg_id="OF:bearish:1"):
    return {
        "confirmed_direction": direction,
        "quality": "clean",
        "regime": "directional",
        "range_ref": leg_id,
        "last_shift_at": "2024-01-01T10:00:00+00:00",
    }


def mss_watch_orderflow(direction="bullish", leg_id="OF:mss-watch:1"):
    return {
        "confirmed_direction": direction,
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
        "last_shift_at": "2024-01-01T10:00:00+00:00",
    }


def pro_continuation_orderflow(direction="bullish", leg_id="OF:pro:1"):
    return {
        "confirmed_direction": direction,
        "quality": "clean",
        "regime": "directional",
        "range_ref": leg_id,
        "last_shift_at": "2024-01-01T18:00:00+00:00",
    }


class HypothesisNoneCaseTests(unittest.TestCase):
    def test_first_partial_htf_none_is_marked_waiting_for_first_closed_htf(self):
        classifier = HypothesisClassifier()
        hyp = classify_with_auto_ec(classifier,
            {
                "mode": "dual",
                "combo": "15m_4h",
                "lower_tf": "15m",
                "higher_tf": "4h",
                "cursor_time": "2024-01-01T00:15:00+00:00",
                "higher_structure": {"bias": "neutral", "phase": "neutral"},
                "lower_structure": {"bias": "neutral", "phase": "neutral"},
                "higher_bars": [
                    {
                        "time": "2024-01-01T04:00:00+00:00",
                        "open": 1.1,
                        "high": 1.11,
                        "low": 1.09,
                        "close": 1.105,
                    }
                ],
                "lower_bars": [],
                "zones": [],
            }
        )

        self.assertEqual(hyp.phase, "none")
        self.assertEqual(hyp.none_sub_status, "warmup_waiting_for_first_closed_htf")
        self.assertEqual(hyp.debug_facts["none_sub_status"], "warmup_waiting_for_first_closed_htf")
        self.assertEqual(hyp.to_dict()["none_sub_status"], "warmup_waiting_for_first_closed_htf")

    def test_first_closed_htf_none_is_not_marked_waiting_for_first_closed_htf(self):
        classifier = HypothesisClassifier()
        hyp = classify_with_auto_ec(classifier,
            {
                "mode": "dual",
                "combo": "15m_4h",
                "lower_tf": "15m",
                "higher_tf": "4h",
                "cursor_time": "2024-01-01T04:00:00+00:00",
                "higher_structure": {"bias": "neutral", "phase": "neutral"},
                "lower_structure": {"bias": "neutral", "phase": "neutral"},
                "higher_bars": [
                    {
                        "time": "2024-01-01T04:00:00+00:00",
                        "open": 1.1,
                        "high": 1.11,
                        "low": 1.09,
                        "close": 1.105,
                    }
                ],
                "lower_bars": [],
                "zones": [],
            }
        )

        self.assertEqual(hyp.phase, "none")
        self.assertEqual(hyp.none_sub_status, "htf_neutral")


def classify_bullish_phase_c(classifier):
    classify_with_auto_ec(classifier,
        dual_snapshot(
            structure("bullish", "open", high=1.123, low=1.10),
            [
                {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
            ],
        )
    )
    ltf = structure("bearish", "open", high=1.119, low=1.108)
    classify_with_auto_ec(classifier,
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
    return classify_with_auto_ec(classifier,
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


def classify_bullish_phase_a(classifier):
    htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
    htf["pd_pct"] = 40.0
    classify_with_auto_ec(classifier,
        dual_snapshot(
            htf,
            [
                {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.112},
            ],
            ltf=structure("bullish", "open", high=1.120, low=1.110),
            zones=[
                sd_zone("SD-4h-demand", "demand", "4h", in_zone=True),
                sd_zone("SD-15m-demand", "demand", "15m", in_zone=False),
            ],
        )
    )
    return classify_with_auto_ec(classifier,
        dual_snapshot(
            htf,
            [
                {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.112},
                {"time": "2024-01-01T16:00:00+00:00", "open": 1.112, "high": 1.122, "low": 1.111, "close": 1.121},
            ],
            ltf=structure("bullish", "open", high=1.122, low=1.111),
            zones=[sd_zone("SD-15m-demand-A", "demand", "15m", in_zone=False)],
        )
    )


def classify_bearish_phase_a(classifier):
    htf = structure("bearish", "pullback_confirmed", high=1.12, low=1.10)
    htf["pd_pct"] = 60.0
    classify_with_auto_ec(classifier,
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
    return classify_with_auto_ec(classifier,
        dual_snapshot(
            htf,
            [
                {"time": "2024-01-01T12:00:00+00:00", "open": 1.100, "high": 1.111, "low": 1.099, "close": 1.108},
                {"time": "2024-01-01T16:00:00+00:00", "open": 1.108, "high": 1.109, "low": 1.101, "close": 1.102},
            ],
            ltf=structure("bearish", "open", high=1.109, low=1.101),
            zones=[sd_zone("SD-15m-supply-A", "supply", "15m", in_zone=False)],
        )
    )


class HypothesisClassifierTests(unittest.TestCase):
    def test_bullish_open_htf_classifies_phase_e(self):
        classifier = HypothesisClassifier()
        hyp = classify_with_auto_ec(classifier,
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

    @unittest.skip(LEGACY_PHASE_D_DISABLED_REASON)
    def test_bullish_phase_e_reaction_without_reaction_point_stays_phase_e(self):
        classifier = HypothesisClassifier()
        first = dual_snapshot(
            structure("bullish", "open", high=1.12, low=1.10),
            [
                {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
            ],
        )
        classify_with_auto_ec(classifier, first)

        hyp = classify_with_auto_ec(classifier,
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

    def test_phase_e_holds_on_pullback_confirmed_without_explicit_exit(self):
        classifier = HypothesisClassifier()
        classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            ),
        )

        hyp = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish", "pullback_confirmed", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.113, "close": 1.118},
                ],
                ltf=structure("bullish", "open", high=1.120, low=1.113),
            ),
        )

        self.assertEqual(hyp.phase, "E")
        self.assertEqual(hyp.phase_sub_status, "stalling")
        self.assertEqual(
            hyp.debug_facts["phase_e_hold_reason"],
            "pullback_confirmed_without_explicit_exit",
        )
        self.assertNotEqual(hyp.none_sub_status, "htf_resolve_unclassified")

    def test_phase_e_shadow_moves_from_seeking_to_stalling_to_pullback_developing(self):
        classifier = HypothesisClassifier()
        first = classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )
        self.assertEqual(first.phase, "E")
        self.assertEqual(first.phase_sub_status, "seeking")

        ltf_active = structure("bullish", "open", high=1.120, low=1.110)
        ltf_active["structure_attempt"] = structure_attempt("active")
        stalling = classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.113, "close": 1.118},
                ],
                ltf=ltf_active,
            )
        )
        self.assertEqual(stalling.phase, "E")
        self.assertEqual(stalling.phase_sub_status, "stalling")
        self.assertFalse(stalling.debug_facts["phase_e_context_new_htf_extreme"])
        self.assertTrue(stalling.debug_facts["phase_e_context_htf_pd_stopped_expanding"])
        self.assertEqual(
            stalling.debug_facts["phase_e_shadow_selection_reason"],
            "htf_pd_stopped_expanding",
        )
        self.assertIsNone(stalling.debug_facts["phase_e_shadow_source_attempt_id"])
        self.assertIsNone(stalling.debug_facts["phase_e_context_attempt_status"])
        self.assertEqual(classifier.state.shadow_thesis.phase_e.node, "E.stalling")

        developing = classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.113, "close": 1.118},
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.118, "high": 1.119, "low": 1.108, "close": 1.110},
                ],
                ltf=structure("bearish", "open", high=1.120, low=1.109),
                lower_orderflow=mss_watch_orderflow("bullish", "OF:e-pullback:1"),
            )
        )
        self.assertEqual(developing.phase, "E")
        self.assertEqual(developing.phase_sub_status, "pullback_developing")
        self.assertEqual(
            developing.debug_facts["phase_e_shadow_selection_reason"],
            "ltf_counter_orderflow_mss_after_e_stalling",
        )
        self.assertIsNone(developing.debug_facts["phase_e_shadow_source_attempt_id"])
        self.assertFalse(developing.debug_facts["phase_e_context_ltf_counter_orderflow_clean"])
        self.assertTrue(developing.debug_facts["phase_e_context_ltf_counter_orderflow_mss_watch"])

    def test_phase_e_failed_pro_attempt_without_clean_orderflow_stays_stalling(self):
        classifier = HypothesisClassifier()
        classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )

        ltf_active = structure("bullish", "open", high=1.120, low=1.110)
        ltf_active["structure_attempt"] = structure_attempt("active")
        classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.113, "close": 1.118},
                ],
                ltf=ltf_active,
            )
        )

        held = classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.113, "close": 1.118},
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.118, "high": 1.119, "low": 1.108, "close": 1.110},
                ],
                ltf=structure("bearish", "open", high=1.120, low=1.109, choch=True),
            )
        )

        self.assertEqual(held.phase, "E")
        self.assertEqual(held.phase_sub_status, "stalling")
        self.assertEqual(held.debug_facts["phase_e_shadow_selection_reason"], "phase_e_shadow_held")
        self.assertIsNone(held.debug_facts["phase_e_shadow_source_attempt_id"])

    def test_phase_e_pullback_developing_holds_on_pro_continuation(self):
        classifier = HypothesisClassifier()
        bars_1 = [
            {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
            {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
        ]
        classify_with_auto_ec(classifier, dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_1))

        bars_2 = [
            bars_1[-1],
            {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.113, "close": 1.118},
        ]
        classify_with_auto_ec(classifier, dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_2))

        bars_3 = [
            bars_2[-1],
            {"time": "2024-01-01T16:00:00+00:00", "open": 1.118, "high": 1.119, "low": 1.108, "close": 1.110},
        ]
        developing = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                bars_3,
                ltf=structure("bearish", "open", high=1.120, low=1.109),
                lower_orderflow=mss_watch_orderflow("bullish", "OF:e-pullback:hold"),
            ),
        )
        self.assertEqual(developing.phase_sub_status, "pullback_developing")

        bars_4 = [
            bars_3[-1],
            {"time": "2024-01-01T20:00:00+00:00", "open": 1.110, "high": 1.120, "low": 1.109, "close": 1.118},
        ]
        held = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                bars_4,
                ltf=structure("bullish", "open", high=1.120, low=1.109),
                current_price=1.115,
            ),
        )

        self.assertEqual(held.phase, "E")
        self.assertEqual(held.phase_sub_status, "pullback_developing")
        self.assertEqual(held.debug_facts["phase_e_shadow_selection_reason"], "phase_e_shadow_held")
        self.assertNotIn("phase_e_shadow_pullback_disrupted", held.debug_facts)
        self.assertNotIn("phase_e_shadow_disrupted_orderflow_leg_id", held.debug_facts)

    def test_phase_e_pullback_developing_does_not_return_to_stalling_on_broken_orderflow(self):
        classifier = HypothesisClassifier()
        bars_1 = [
            {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
            {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
        ]
        classify_with_auto_ec(classifier, dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_1))

        bars_2 = [
            bars_1[-1],
            {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.113, "close": 1.118},
        ]
        classify_with_auto_ec(classifier, dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_2))

        bars_3 = [
            bars_2[-1],
            {"time": "2024-01-01T16:00:00+00:00", "open": 1.118, "high": 1.119, "low": 1.108, "close": 1.110},
        ]
        developing = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                bars_3,
                ltf=structure("bearish", "open", high=1.120, low=1.109),
                lower_orderflow=mss_watch_orderflow("bullish", "OF:e-pullback:broken"),
            ),
        )
        self.assertEqual(developing.phase_sub_status, "pullback_developing")

        bars_4 = [
            bars_3[-1],
            {"time": "2024-01-01T20:00:00+00:00", "open": 1.110, "high": 1.120, "low": 1.109, "close": 1.118},
        ]
        held = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                bars_4,
                ltf=structure("bullish", "open", high=1.120, low=1.109),
                lower_orderflow={
                    "confirmed_direction": "bullish",
                    "quality": "broken",
                    "regime": "compression",
                    "range_ref": "OF:e-pullback:broken-return",
                    "last_shift_at": "2024-01-01T18:00:00+00:00",
                },
                current_price=1.115,
            ),
        )

        self.assertEqual(held.phase, "E")
        self.assertEqual(held.phase_sub_status, "pullback_developing")
        self.assertTrue(held.debug_facts["phase_e_context_ltf_counter_orderflow_broken"])
        self.assertEqual(held.debug_facts["phase_e_shadow_selection_reason"], "phase_e_shadow_held")

    def test_phase_e_pullback_developing_resets_to_seeking_on_new_htf_extreme(self):
        classifier = HypothesisClassifier()
        bars_1 = [
            {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
            {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
        ]
        classify_with_auto_ec(classifier, dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_1))

        bars_2 = [
            bars_1[-1],
            {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.113, "close": 1.118},
        ]
        classify_with_auto_ec(classifier, dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_2))

        bars_3 = [
            bars_2[-1],
            {"time": "2024-01-01T16:00:00+00:00", "open": 1.118, "high": 1.119, "low": 1.108, "close": 1.110},
        ]
        developing = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                bars_3,
                ltf=structure("bearish", "open", high=1.120, low=1.109),
                lower_orderflow=mss_watch_orderflow("bullish", "OF:e-pullback:reset"),
            ),
        )
        self.assertEqual(developing.phase_sub_status, "pullback_developing")

        bars_4 = [
            bars_3[-1],
            {"time": "2024-01-01T20:00:00+00:00", "open": 1.110, "high": 1.130, "low": 1.109, "close": 1.128},
        ]
        seeking = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.130, low=1.10),
                bars_4,
                ltf=structure("bullish", "open", high=1.130, low=1.115),
                current_price=1.128,
            ),
        )

        self.assertEqual(seeking.phase, "E")
        self.assertEqual(seeking.phase_sub_status, "seeking")
        self.assertEqual(seeking.debug_facts["phase_e_shadow_selection_reason"], "htf_pd_expanded")

    def test_phase_e_equal_high_retest_moves_to_stalling(self):
        classifier = HypothesisClassifier()
        first = classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )
        self.assertEqual(first.phase_sub_status, "seeking")

        stalling = classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.123, "low": 1.113, "close": 1.118},
                ],
                liquidity={
                    "eq_tolerance": 0.0,
                    "active_htf_eq_pools": [
                        {
                            "pool_id": "EQH:phase-e:1",
                            "source": "eqh",
                            "price": 1.123,
                            "tolerance": 0.0,
                            "status": "active",
                        }
                    ],
                },
            )
        )

        self.assertEqual(stalling.phase, "E")
        self.assertEqual(stalling.phase_sub_status, "stalling")
        self.assertFalse(stalling.debug_facts["phase_e_context_new_htf_extreme"])
        self.assertTrue(stalling.debug_facts["phase_e_context_htf_equal_extreme_retest"])
        self.assertEqual(
            stalling.debug_facts["phase_e_context_htf_equal_extreme_kind"],
            "htf_eqh_at_phase_e_extreme",
        )
        self.assertEqual(stalling.debug_facts["phase_e_context_htf_equal_extreme_pool_id"], "EQH:phase-e:1")
        self.assertEqual(stalling.debug_facts["phase_e_shadow_selection_reason"], "htf_pd_stopped_expanding")

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_fast_phase_e_midpoint_pullback_classifies_c_hard_pullback(self):
        classifier = HypothesisClassifier()
        htf = structure("bullish", "open", high=1.123, low=1.10)
        bars = [
            {"time": "2024-01-01T04:00:00+00:00", "open": 1.116, "high": 1.123, "low": 1.112, "close": 1.121},
            {"time": "2024-01-01T08:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.110},
        ]

        hyp = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                htf,
                bars,
                ltf=structure("bearish", "open", high=1.122, low=1.108),
                lower_orderflow=clean_orderflow("bearish", "OF:fast-hard-pullback"),
                current_price=1.110,
            ),
        )

        self.assertEqual(hyp.phase, "C")
        self.assertEqual(hyp.phase_sub_status, "hard_pullback")
        self.assertEqual(hyp.status, "watching")
        self.assertEqual(hyp.direction, "short")
        self.assertEqual(hyp.debug_facts["phase_c_origin_node"], "E.fast_hard_pullback")
        self.assertEqual(
            hyp.debug_facts["phase_c_selection_reason"],
            "fast_midpoint_pullback_after_phase_e_expansion",
        )
        self.assertEqual(hyp.debug_facts["phase_c_quality"], "choppy_tight_range_fast_pullback")
        self.assertTrue(hyp.debug_facts["phase_c_fast_hard_pullback_ready"])
        self.assertGreaterEqual(hyp.debug_facts["phase_c_fast_hard_pullback_depth_pct"], 50.0)
        self.assertEqual(
            hyp.debug_facts["phase_c_fast_hard_pullback_source_orderflow_leg_id"],
            "OF:fast-hard-pullback",
        )

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_phase_e_pullback_developing_becomes_c_slow_pullback_after_ltf_pd_flip(self):
        classifier = HypothesisClassifier()
        bars_1 = [
            {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
            {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
        ]
        classify_with_auto_ec(classifier, dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_1))

        ltf_active = structure("bullish", "pullback_confirmed", high=1.120, low=1.110)
        ltf_active["structure_attempt"] = structure_attempt("active")
        bars_2 = [
            bars_1[-1],
            {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.113, "close": 1.118},
        ]
        classify_with_auto_ec(classifier, dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_2, ltf=ltf_active))

        bars_3 = [
            bars_2[-1],
            {"time": "2024-01-01T16:00:00+00:00", "open": 1.118, "high": 1.119, "low": 1.108, "close": 1.110},
        ]
        developing = classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                bars_3,
                ltf=structure("bearish", "open", high=1.120, low=1.109),
                lower_orderflow=mss_watch_orderflow("bullish", "OF:e-pullback:slow-c"),
            )
        )
        self.assertEqual(developing.phase, "E")
        self.assertEqual(developing.phase_sub_status, "pullback_developing")

        bars_4 = [
            bars_3[-1],
            {"time": "2024-01-01T20:00:00+00:00", "open": 1.110, "high": 1.111, "low": 1.104, "close": 1.106},
        ]
        slow_c = classify_with_auto_ec(classifier,
            dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_4,
                          ltf=structure("bearish", "open", high=1.120, low=1.108),
                          lower_orderflow=clean_orderflow("bearish"))
        )
        self.assertEqual(slow_c.phase, "C")
        self.assertEqual(slow_c.phase_sub_status, "slow_pullback")
        self.assertEqual(slow_c.direction, "short")
        self.assertEqual(
            slow_c.debug_facts["phase_c_selection_reason"],
            "ltf_pd_flipped_counter_after_failed_e_continuation_attempt",
        )

    def test_e_pullback_developing_blocks_direct_b_until_c_origin(self):
        classifier = HypothesisClassifier()
        bars_1 = [
            {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
            {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
        ]
        classify_with_auto_ec(classifier, dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_1))

        ltf_active = structure("bullish", "pullback_confirmed", high=1.120, low=1.110)
        ltf_active["structure_attempt"] = structure_attempt("active")
        bars_2 = [
            bars_1[-1],
            {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.113, "close": 1.118},
        ]
        classify_with_auto_ec(classifier, dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_2, ltf=ltf_active))

        bars_3 = [
            bars_2[-1],
            {"time": "2024-01-01T16:00:00+00:00", "open": 1.118, "high": 1.119, "low": 1.108, "close": 1.110},
        ]
        developing = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                bars_3,
                ltf=structure("bearish", "open", high=1.120, low=1.109),
                lower_orderflow=mss_watch_orderflow("bullish", "OF:e-pullback:block-b"),
            ),
        )
        self.assertEqual(developing.phase, "E")
        self.assertEqual(developing.phase_sub_status, "pullback_developing")

        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        htf["pd_pct"] = 60.0
        bars_4 = [
            bars_3[-1],
            {"time": "2024-01-01T20:00:00+00:00", "open": 1.110, "high": 1.118, "low": 1.106, "close": 1.116},
        ]
        hyp = classify_with_auto_ec(
            classifier,
            dual_snapshot(
                htf,
                bars_4,
                ltf=structure("bullish", "open", high=1.118, low=1.106),
                zones=[
                    sd_zone("SD-4h-demand", "demand", "4h", in_zone=True),
                    sd_zone("SD-15m-demand", "demand", "15m", in_zone=False),
                ],
            ),
        )

        self.assertNotEqual(hyp.phase, "B")
        self.assertTrue(hyp.debug_facts["phase_b_candidate"])
        self.assertFalse(hyp.debug_facts["phase_b_ready"])
        self.assertTrue(hyp.debug_facts["phase_b_blocked_by_dag"])
        self.assertEqual(
            hyp.debug_facts["phase_b_dag_blocked_reason"],
            "direct_e_to_b_requires_c_origin",
        )

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_c_slow_pullback_promotes_to_b_shallow_reclaim_even_while_htf_open(self):
        classifier = HypothesisClassifier()
        bars_1 = [
            {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
            {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
        ]
        classify_with_auto_ec(classifier, dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_1))

        ltf_active = structure("bullish", "pullback_confirmed", high=1.120, low=1.110)
        ltf_active["structure_attempt"] = structure_attempt("active")
        bars_2 = [
            bars_1[-1],
            {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.113, "close": 1.118},
        ]
        classify_with_auto_ec(classifier, dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_2, ltf=ltf_active))

        bars_3 = [
            bars_2[-1],
            {"time": "2024-01-01T16:00:00+00:00", "open": 1.118, "high": 1.119, "low": 1.108, "close": 1.110},
        ]
        classify_with_auto_ec(
            classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                bars_3,
                ltf=structure("bearish", "open", high=1.120, low=1.109),
                lower_orderflow=mss_watch_orderflow("bullish", "OF:e-pullback:shallow-b"),
            ),
        )

        bars_4 = [
            bars_3[-1],
            {"time": "2024-01-01T20:00:00+00:00", "open": 1.110, "high": 1.111, "low": 1.104, "close": 1.106},
        ]
        slow_c = classify_with_auto_ec(classifier,
            dual_snapshot(structure("bullish", "open", high=1.123, low=1.10), bars_4,
                          ltf=structure("bearish", "open", high=1.120, low=1.108),
                          lower_orderflow=clean_orderflow("bearish"))
        )
        self.assertEqual(slow_c.phase, "C")
        self.assertEqual(slow_c.phase_sub_status, "slow_pullback")

        htf = structure("bullish", "open", high=1.123, low=1.10)
        htf["pd_pct"] = 60.0
        bars_5 = [
            bars_4[-1],
            {"time": "2024-01-02T00:00:00+00:00", "open": 1.106, "high": 1.118, "low": 1.105, "close": 1.116},
        ]
        hyp = classify_with_auto_ec(classifier,
            dual_snapshot(
                htf,
                bars_5,
                ltf=structure("bullish", "open", high=1.118, low=1.105),
                zones=[
                    {
                        **sd_zone("SD-15m-demand-old", "demand", "15m", in_zone=False),
                        "created_at": "2024-01-01T12:00:00+00:00",
                    },
                    {
                        **sd_zone("SD-15m-demand-fresh", "demand", "15m", in_zone=False),
                        "created_at": "2024-01-02T00:00:00+00:00",
                    },
                ],
                higher_last_resolved_zone=resolved_zone("SD-4h-demand", "demand", "4h", "bounced"),
            )
        )

        self.assertEqual(hyp.phase, "B")
        self.assertEqual(hyp.phase_sub_status, "shallow_reclaim")
        self.assertEqual(hyp.direction, "long")
        self.assertEqual(hyp.poi_id, "SD-15m-demand-fresh")
        self.assertEqual(hyp.debug_facts["phase_b_origin_node"], "C.slow_pullback")
        self.assertTrue(hyp.debug_facts["phase_b_from_c"])
        self.assertTrue(hyp.debug_facts["phase_b_htf_pullback_context_ready"])

        held_b = classify_with_auto_ec(classifier,
            dual_snapshot(
                htf,
                [
                    bars_5[-1],
                    {"time": "2024-01-02T04:00:00+00:00", "open": 1.116, "high": 1.121, "low": 1.114, "close": 1.119},
                ],
                ltf=structure("bullish", "open", high=1.121, low=1.114),
                zones=[
                    {
                        **sd_zone("SD-15m-demand-fresh", "demand", "15m", in_zone=False),
                        "created_at": "2024-01-02T00:00:00+00:00",
                    },
                ],
                higher_last_resolved_zone=resolved_zone("SD-4h-demand", "demand", "4h", "bounced"),
            )
        )

        self.assertEqual(held_b.phase, "B")
        self.assertEqual(held_b.phase_sub_status, "shallow_reclaim")
        self.assertEqual(held_b.poi_id, "SD-15m-demand-fresh")
        self.assertTrue(held_b.debug_facts["phase_b_shallow_reclaim_blocks_phase_a"])
        self.assertTrue(held_b.debug_facts["phase_b_shallow_reclaim_held"])
        self.assertEqual(
            held_b.debug_facts["phase_b_held_reason"],
            "shallow_reclaim_does_not_unlock_phase_a_budget",
        )

        contested_b = classify_with_auto_ec(classifier,
            dual_snapshot(
                htf,
                [
                    bars_5[-1],
                    {"time": "2024-01-02T08:00:00+00:00", "open": 1.119, "high": 1.121, "low": 1.115, "close": 1.116},
                ],
                ltf=structure("bearish", "open", high=1.121, low=1.115),
                zones=[
                    {
                        **sd_zone("SD-15m-demand-fresh", "demand", "15m", in_zone=False),
                        "created_at": "2024-01-02T00:00:00+00:00",
                    },
                    {
                        **sd_zone("SD-15m-supply-counter", "supply", "15m", in_zone=True),
                        "created_at": "2024-01-02T08:00:00+00:00",
                    },
                ],
                higher_last_resolved_zone=resolved_zone("SD-4h-demand", "demand", "4h", "bounced"),
            )
        )
        self.assertEqual(contested_b.phase, "B")
        self.assertEqual(contested_b.phase_sub_status, "shallow_reclaim.contested")
        self.assertEqual(contested_b.debug_facts["phase_b_shadow_status"], "contested")
        self.assertEqual(
            contested_b.debug_facts["phase_b_shadow_selection_reason"],
            "ltf_counter_mitigation_contested_shallow_b",
        )

        weakened_b = classify_with_auto_ec(classifier,
            dual_snapshot(
                htf,
                [
                    {"time": "2024-01-02T08:00:00+00:00", "open": 1.119, "high": 1.121, "low": 1.115, "close": 1.116},
                    {"time": "2024-01-02T12:00:00+00:00", "open": 1.116, "high": 1.121, "low": 1.116, "close": 1.118},
                ],
                ltf=structure("bearish", "open", high=1.121, low=1.116),
                zones=[
                    {
                        **sd_zone("SD-15m-demand-fresh", "demand", "15m", in_zone=False),
                        "created_at": "2024-01-02T00:00:00+00:00",
                    },
                    {
                        **sd_zone("SD-15m-supply-counter", "supply", "15m", in_zone=True),
                        "created_at": "2024-01-02T08:00:00+00:00",
                    },
                ],
                higher_last_resolved_zone=resolved_zone("SD-4h-demand", "demand", "4h", "bounced"),
            )
        )
        self.assertEqual(weakened_b.phase, "B")
        self.assertEqual(weakened_b.phase_sub_status, "shallow_reclaim.weakened")
        self.assertEqual(weakened_b.debug_facts["phase_b_shadow_status"], "weakened")
        self.assertEqual(
            weakened_b.debug_facts["phase_b_shadow_weakening_reason"],
            "same_level_return_after_ltf_counter_mitigation",
        )

        d_reclaim = classify_with_auto_ec(classifier,
            dual_snapshot(
                htf,
                [
                    {"time": "2024-01-02T12:00:00+00:00", "open": 1.116, "high": 1.121, "low": 1.116, "close": 1.118},
                    {"time": "2024-01-02T16:00:00+00:00", "open": 1.118, "high": 1.122, "low": 1.114, "close": 1.116},
                ],
                ltf=structure("bearish", "open", high=1.122, low=1.114),
                zones=[
                    {
                        **sd_zone("SD-4h-supply-reclaim", "supply", "4h", in_zone=True),
                        "created_at": "2024-01-02T16:00:00+00:00",
                    },
                    {
                        **sd_zone("SD-15m-supply-counter", "supply", "15m", in_zone=True),
                        "created_at": "2024-01-02T08:00:00+00:00",
                    },
                ],
                higher_last_resolved_zone=resolved_zone("SD-4h-demand", "demand", "4h", "bounced"),
            )
        )
        self.assertEqual(d_reclaim.phase, "D")
        self.assertEqual(d_reclaim.phase_sub_status, "htf_zone_reclaim_test")
        self.assertEqual(d_reclaim.debug_facts["phase_d_origin_node"], "B.shallow_reclaim.weakened")
        self.assertEqual(
            d_reclaim.debug_facts["phase_d_selection_reason"],
            "htf_opposing_zone_reclaim_after_weakened_shallow_b",
        )

    @unittest.skip(LEGACY_PHASE_D_DISABLED_REASON)
    def test_bearish_phase_e_reaction_without_reaction_point_stays_phase_e(self):
        classifier = HypothesisClassifier()
        classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bearish", "open", high=1.12, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.118, "low": 1.10, "close": 1.103},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.103, "high": 1.109, "low": 1.098, "close": 1.100},
                ],
            )
        )

        hyp = classify_with_auto_ec(classifier,
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

    @unittest.skip(LEGACY_PHASE_D_DISABLED_REASON)
    def test_bullish_opposing_htf_sd_and_ltf_counter_sd_classifies_phase_d(self):
        classifier = HypothesisClassifier()
        classify_with_auto_ec(classifier,
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
        hyp = classify_with_auto_ec(classifier,
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
        self.assertEqual(hyp.phase_sub_status, "reaction_point")
        self.assertEqual(hyp.direction, "none")
        self.assertEqual(hyp.debug_facts["phase_d_origin_node"], "E.seeking")
        self.assertEqual(hyp.debug_facts["phase_d_selection_reason"], "first_contact_after_phase_e")
        self.assertEqual(hyp.debug_facts["phase_d_trigger"], "opposing_htf_sd_reaction_with_ltf_counter_sd")
        self.assertFalse(hyp.debug_facts["htf_opposing_sd_resolved"])

    @unittest.skip(LEGACY_PHASE_D_DISABLED_REASON)
    def test_bullish_resolved_htf_sd_and_ltf_counter_sd_classifies_phase_d(self):
        classifier = HypothesisClassifier()
        classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )

        ltf = structure("bearish", "open", high=1.119, low=1.108)
        hyp = classify_with_auto_ec(classifier,
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
        self.assertEqual(hyp.phase_sub_status, "reaction_point")
        self.assertEqual(hyp.direction, "none")
        self.assertTrue(hyp.debug_facts["htf_opposing_sd_resolved"])
        self.assertEqual(hyp.debug_facts["htf_last_resolved_zone_id"], "SD-4h-supply")
        self.assertEqual(hyp.debug_facts["htf_last_resolved_zone_resolution"], "bounced")
        self.assertEqual(hyp.debug_facts["phase_d_trigger"], "opposing_htf_sd_reaction_with_ltf_counter_sd")

    @unittest.skip(LEGACY_PHASE_D_DISABLED_REASON)
    def test_bullish_resolved_htf_liquidity_run_does_not_classify_phase_d(self):
        classifier = HypothesisClassifier()
        classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )

        ltf = structure("bearish", "open", high=1.119, low=1.108)
        hyp = classify_with_auto_ec(classifier,
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

    @unittest.skip(LEGACY_PHASE_D_DISABLED_REASON)
    def test_bullish_htf_pd_grab_reclaim_classifies_phase_d_without_sd_zone(self):
        classifier = HypothesisClassifier()
        classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )

        hyp = classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.109},
                ],
                ltf={
                    "bias": "bearish",
                    "phase": "open",
                    "last_sc": {
                        "choch": True,
                        "breakDirection": "down",
                        "eventTimestamp": "2024-01-01T12:00:00+00:00",
                        "levelPrice": 1.118,
                    },
                },
                liquidity=liquidity_grab("pd", "bearish", pool_id="pd-grab-1"),
            )
        )

        self.assertEqual(hyp.phase, "D")
        self.assertEqual(hyp.phase_sub_status, "htf_pd_grab_reclaim_test")
        self.assertEqual(hyp.poi_id, "pd-grab-1")
        self.assertEqual(hyp.poi_type, "liquidity_pool")
        self.assertEqual(hyp.debug_facts["phase_d_trigger"], "pd_liquidity_grab_reclaim")
        self.assertEqual(hyp.debug_facts["phase_d_selection_reason"], "htf_pd_liquidity_grab_reclaim_ready")

    @unittest.skip(LEGACY_PHASE_D_DISABLED_REASON)
    def test_bullish_htf_eq_grab_reclaim_classifies_phase_d_without_sd_zone(self):
        classifier = HypothesisClassifier()
        classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )

        hyp = classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.109},
                ],
                ltf={
                    "bias": "bearish",
                    "phase": "open",
                    "last_sc": {
                        "choch": True,
                        "breakDirection": "down",
                        "eventTimestamp": "2024-01-01T12:00:00+00:00",
                        "levelPrice": 1.118,
                    },
                },
                liquidity=liquidity_grab("eq", "bearish", pool_id="eq-grab-1", level=1.123),
            )
        )

        self.assertEqual(hyp.phase, "D")
        self.assertEqual(hyp.phase_sub_status, "htf_eq_grab_reclaim_test")
        self.assertEqual(hyp.poi_id, "eq-grab-1")
        self.assertEqual(hyp.poi_type, "liquidity_pool")
        self.assertEqual(hyp.debug_facts["phase_d_trigger"], "eq_liquidity_grab_reclaim")
        self.assertEqual(hyp.debug_facts["phase_d_selection_reason"], "htf_eq_liquidity_grab_reclaim_ready")

    @unittest.skip(LEGACY_PHASE_D_DISABLED_REASON)
    def test_htf_pd_grab_wrong_direction_does_not_classify_phase_d(self):
        classifier = HypothesisClassifier()
        classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )

        hyp = classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.109},
                ],
                liquidity=liquidity_grab("pd", "bullish", pool_id="pd-grab-wrong"),
            )
        )

        self.assertEqual(hyp.phase, "E")
        self.assertFalse(hyp.debug_facts["phase_d_liquidity_ready"])

    @unittest.skip(LEGACY_PHASE_D_DISABLED_REASON)
    def test_bearish_new_low_with_ltf_counter_bias_classifies_phase_d(self):
        classifier = HypothesisClassifier()
        classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bearish", "open", high=1.12, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.118, "low": 1.10, "close": 1.103},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.103, "high": 1.109, "low": 1.098, "close": 1.100},
                ],
            )
        )

        ltf = structure("bullish", "open", high=1.108, low=1.099)
        hyp = classify_with_auto_ec(classifier,
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
        self.assertEqual(hyp.phase_sub_status, "reaction_point")
        self.assertEqual(hyp.direction, "none")
        self.assertEqual(hyp.debug_facts["phase_d_trigger"], "new_htf_extreme_with_ltf_counter_bias")

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_bullish_phase_d_to_phase_c_watching_when_ltf_counter_story_has_no_poi(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T04:00:00+00:00", "open": 1.11, "high": 1.12, "low": 1.105, "close": 1.118},
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                ],
            )
        )

        ltf = structure("bearish", "open", high=1.119, low=1.108)
        classify_with_auto_ec(classifier,
            dual_snapshot(
                structure("bullish", "open", high=1.124, low=1.10),
                [
                    {"time": "2024-01-01T08:00:00+00:00", "open": 1.118, "high": 1.123, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.124, "low": 1.116, "close": 1.120},
                ],
                ltf=ltf,
            )
        )

        hyp = classify_with_auto_ec(classifier,
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
        self.assertEqual(hyp.phase_sub_status, "htf_reaction_pullback")
        self.assertEqual(hyp.status, "watching")
        self.assertEqual(hyp.direction, "short")
        self.assertIsNone(hyp.poi_id)
        self.assertEqual(hyp.entry_policy, "wait")
        self.assertTrue(hyp.debug_facts["phase_c_story_ready"])
        self.assertEqual(hyp.debug_facts["phase_c_origin_node"], "D.reaction_point")
        self.assertEqual(hyp.debug_facts["phase_c_sub_status"], "htf_reaction_pullback")
        self.assertEqual(
            hyp.debug_facts["phase_c_selection_reason"],
            "ltf_counter_story_after_d_reaction",
        )
        self.assertFalse(hyp.debug_facts["phase_c_armed"])
        self.assertTrue(hyp.debug_facts["phase_c_ltf_counter_pd_break"])

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_bullish_phase_d_to_phase_c_armed_when_counter_poi_exists_before_return(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_with_auto_ec(classifier,
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
        classify_with_auto_ec(classifier, d_snapshot)

        hyp = classify_with_auto_ec(classifier, d_snapshot)

        self.assertEqual(hyp.phase, "C")
        self.assertEqual(hyp.phase_sub_status, "htf_reaction_pullback")
        self.assertEqual(hyp.status, "armed")
        self.assertEqual(hyp.direction, "short")
        self.assertEqual(hyp.poi_id, "SD-15m-supply")
        self.assertEqual(hyp.entry_policy, "hybrid")
        self.assertTrue(hyp.debug_facts["phase_c_candidate"])
        self.assertTrue(hyp.debug_facts["phase_c_ready"])
        self.assertEqual(hyp.debug_facts["phase_c_origin_node"], "D.reaction_point")
        self.assertEqual(hyp.debug_facts["phase_c_sub_status"], "htf_reaction_pullback")
        self.assertFalse(hyp.debug_facts["phase_c_selected_poi_touched"])
        self.assertEqual(hyp.debug_facts["phase_c_selected_poi_id"], "SD-15m-supply")

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
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

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_phase_c_collapses_to_phase_e_when_htf_continuation_resumes(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_bullish_phase_c(classifier)

        hyp = classify_with_auto_ec(classifier,
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

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_phase_c_to_strict_phase_b_when_htf_demand_reacts_and_ltf_flips_bullish(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_bullish_phase_c(classifier)

        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        htf["pd_pct"] = 40.0
        hyp = classify_with_auto_ec(classifier,
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

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_phase_c_records_itr_grab_footprint_without_starting_b_initiation(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_bullish_phase_c(classifier)
        ec = EvidenceCompiler()

        hyp = classify_with_ec(
            classifier,
            ec,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.109, "high": 1.120, "low": 1.107, "close": 1.118},
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.118, "high": 1.120, "low": 1.110, "close": 1.116},
                ],
                ltf=structure("bearish", "open", high=1.119, low=1.108),
                zones=[sd_zone("SD-15m-supply", "supply", "15m", in_zone=False)],
                liquidity=itr_liquidity_grab(direction="bullish", variant="level", pool_id="ITR-liq-low"),
            )
        )

        self.assertEqual(hyp.phase, "C")
        self.assertEqual(hyp.phase_sub_status, "htf_reaction_pullback")
        self.assertEqual(hyp.direction, "short")
        self.assertEqual(hyp.entry_policy, "hybrid")
        self.assertFalse(hyp.debug_facts["phase_b_initiation_ready"])
        self.assertTrue(hyp.debug_facts["phase_b_initiation_source_itr_grab_seen"])
        self.assertFalse(hyp.debug_facts["phase_b_initiation_opposite_itr_grab_seen"])
        self.assertFalse(hyp.debug_facts["phase_b_initiation_decision_zone_seen"])
        self.assertEqual(hyp.debug_facts["phase_b_initiation_origin_node"], "C.htf_reaction_pullback")
        self.assertEqual(hyp.debug_facts["htf_itr_grab_reclaim_variant"], "level")

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_b_initiation_watch_counter_itr_grab_becomes_decisive(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_bullish_phase_c(classifier)
        ec = EvidenceCompiler()
        classify_with_ec(
            classifier,
            ec,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.109, "high": 1.120, "low": 1.107, "close": 1.118},
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.118, "high": 1.120, "low": 1.110, "close": 1.116},
                ],
                ltf=structure("bearish", "open", high=1.119, low=1.108),
                zones=[sd_zone("SD-15m-supply", "supply", "15m", in_zone=False)],
                liquidity=itr_liquidity_grab(direction="bullish", variant="eq"),
            )
        )

        decisive = classify_with_ec(
            classifier,
            ec,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.118, "high": 1.120, "low": 1.110, "close": 1.116},
                    {"time": "2024-01-02T00:00:00+00:00", "open": 1.116, "high": 1.121, "low": 1.106, "close": 1.108},
                ],
                ltf=structure("bullish", "open", high=1.121, low=1.106),
                zones=[
                    sd_zone("SD-4h-supply", "supply", "4h", in_zone=True),
                    sd_zone("SD-15m-supply", "supply", "15m", in_zone=False),
                ],
                liquidity=itr_liquidity_grab(direction="bearish", variant="level", pool_id="ITR-liq-high-run"),
            )
        )

        self.assertEqual(decisive.phase, "B")
        self.assertEqual(decisive.phase_sub_status, "initiation_watch.decisive")
        self.assertEqual(decisive.status, "watching")
        self.assertTrue(decisive.debug_facts["phase_b_initiation_opposite_itr_grab_seen"])
        self.assertTrue(decisive.debug_facts["phase_b_initiation_decision_zone_seen"])

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_b_initiation_watch_decisive_failure_evidence_becomes_c_no_followthrough(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_bullish_phase_c(classifier)
        ec = EvidenceCompiler()
        classify_with_ec(
            classifier,
            ec,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.109, "high": 1.120, "low": 1.107, "close": 1.118},
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.118, "high": 1.120, "low": 1.110, "close": 1.116},
                ],
                ltf=structure("bearish", "open", high=1.119, low=1.108),
                zones=[sd_zone("SD-15m-supply", "supply", "15m", in_zone=False)],
                liquidity=itr_liquidity_grab(direction="bullish", variant="eq"),
            )
        )
        classify_with_ec(
            classifier,
            ec,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.118, "high": 1.120, "low": 1.110, "close": 1.116},
                    {"time": "2024-01-02T00:00:00+00:00", "open": 1.116, "high": 1.121, "low": 1.106, "close": 1.108},
                ],
                ltf=structure("bullish", "open", high=1.121, low=1.106),
                zones=[
                    sd_zone("SD-4h-supply", "supply", "4h", in_zone=True),
                    sd_zone("SD-15m-supply", "supply", "15m", in_zone=False),
                ],
                liquidity=itr_liquidity_grab(direction="bearish", variant="level", pool_id="ITR-liq-high-run"),
            )
        )

        failed = classify_with_ec(
            classifier,
            ec,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-02T00:00:00+00:00", "open": 1.116, "high": 1.121, "low": 1.106, "close": 1.108},
                    {"time": "2024-01-02T04:00:00+00:00", "open": 1.108, "high": 1.112, "low": 1.102, "close": 1.103},
                ],
                ltf=structure("bearish", "open", high=1.121, low=1.102),
                zones=[sd_zone("SD-15m-supply", "supply", "15m", in_zone=False)],
            )
        )

        self.assertEqual(failed.phase, "C")
        self.assertEqual(failed.phase_sub_status, "pullback.no_followthrough")
        self.assertEqual(failed.direction, "short")
        self.assertTrue(failed.debug_facts["phase_b_initiation_failure_evidence_seen"])
        self.assertEqual(
            failed.debug_facts["phase_c_selection_reason"],
            "b_initiation_watch_decision_failed_with_ltf_counter_confirmation",
        )

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_b_initiation_watch_source_anchor_run_becomes_c_no_followthrough(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_bullish_phase_c(classifier)
        ec = EvidenceCompiler()
        source_pool_id = "ITR-source-low"
        classify_with_ec(
            classifier,
            ec,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.109, "high": 1.120, "low": 1.107, "close": 1.118},
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.118, "high": 1.120, "low": 1.110, "close": 1.116},
                ],
                ltf=structure("bearish", "open", high=1.119, low=1.108),
                zones=[sd_zone("SD-15m-supply", "supply", "15m", in_zone=False)],
                liquidity=itr_liquidity_grab(direction="bullish", variant="eq", pool_id=source_pool_id),
            )
        )

        decisive = classify_with_ec(
            classifier,
            ec,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.118, "high": 1.120, "low": 1.110, "close": 1.116},
                    {"time": "2024-01-02T00:00:00+00:00", "open": 1.116, "high": 1.119, "low": 1.106, "close": 1.108},
                ],
                ltf=structure("bearish", "open", high=1.119, low=1.106),
                zones=[
                    sd_zone("SD-4h-supply", "supply", "4h", in_zone=True),
                    sd_zone("SD-15m-supply", "supply", "15m", in_zone=False),
                ],
                liquidity=itr_liquidity_grab(direction="bearish", variant="level", pool_id="ITR-counter-high"),
            )
        )

        self.assertEqual(decisive.phase, "B")
        self.assertEqual(decisive.phase_sub_status, "initiation_watch.decisive")
        self.assertEqual(decisive.status, "watching")

        hyp = classify_with_ec(
            classifier,
            ec,
            dual_snapshot(
                structure("bullish", "open", high=1.123, low=1.10),
                [
                    {"time": "2024-01-02T00:00:00+00:00", "open": 1.116, "high": 1.119, "low": 1.106, "close": 1.108},
                    {"time": "2024-01-02T04:00:00+00:00", "open": 1.108, "high": 1.112, "low": 1.102, "close": 1.103},
                ],
                ltf=structure("bearish", "open", high=1.119, low=1.102),
                zones=[sd_zone("SD-15m-supply", "supply", "15m", in_zone=False)],
                liquidity=itr_anchor_run(direction="bullish", variant="eq", pool_id=source_pool_id),
            )
        )

        self.assertEqual(hyp.phase, "C")
        self.assertEqual(hyp.phase_sub_status, "pullback.no_followthrough")
        self.assertEqual(hyp.status, "armed")
        self.assertEqual(hyp.direction, "short")
        self.assertEqual(hyp.poi_id, "SD-15m-supply")
        self.assertEqual(hyp.debug_facts["phase_c_origin_node"], "B.initiation_watch.decisive")
        self.assertEqual(
            hyp.debug_facts["phase_c_selection_reason"],
            "b_initiation_watch_source_itr_anchor_was_run",
        )

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_bearish_strict_phase_b_classifies_from_pullback_context(self):
        classifier = HypothesisClassifier()
        htf = structure("bearish", "pullback_confirmed", high=1.12, low=1.10)
        htf["pd_pct"] = 60.0

        hyp = classify_with_auto_ec(classifier,
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

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_bullish_strict_phase_b_accepts_resolved_htf_demand_bounce(self):
        classifier = HypothesisClassifier()
        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        htf["pd_pct"] = 40.0

        hyp = classify_with_auto_ec(classifier,
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

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_bullish_shallow_phase_b_requires_htf_demand_mitigation(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_bullish_phase_c(classifier)

        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        htf["pd_pct"] = 60.0
        hyp = classify_with_auto_ec(classifier,
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
        self.assertEqual(hyp.direction, "long")
        self.assertEqual(hyp.poi_id, "SD-15m-demand")
        self.assertTrue(hyp.debug_facts["phase_b_ready"])
        self.assertFalse(hyp.debug_facts["phase_b_correct_pd_half"])
        self.assertTrue(hyp.debug_facts["phase_b_shallow_pd_half"])
        self.assertEqual(hyp.debug_facts["phase_b_location"], "shallow")
        self.assertEqual(hyp.debug_facts["phase_b_candidate_variant"], "shallow_htf_sd_mitigation")

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_bearish_shallow_phase_b_uses_direction_normalized_pd_value(self):
        classifier = HypothesisClassifier()
        htf = structure("bearish", "pullback_confirmed", high=1.12, low=1.10)
        htf["pd_pct"] = 35.7

        hyp = classify_with_auto_ec(classifier,
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
        self.assertEqual(hyp.direction, "short")
        self.assertEqual(hyp.poi_id, "SD-15m-supply")
        self.assertTrue(hyp.debug_facts["phase_b_ready"])
        self.assertEqual(hyp.debug_facts["phase_b_htf_pd_value_pct"], 64.3)
        self.assertEqual(hyp.debug_facts["phase_b_location"], "shallow")
        self.assertEqual(hyp.debug_facts["phase_b_candidate_variant"], "shallow_htf_sd_mitigation")

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_phase_c_holds_and_marks_missing_htf_demand_b_candidate_without_classifying_b(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_bullish_phase_c(classifier)

        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        htf["confirmed_by"] = "sd_zone"
        htf["pd_pct"] = 40.0
        hyp = classify_with_auto_ec(classifier,
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

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_phase_c_holds_and_excludes_shallow_pullback_without_htf_mitigation(self):
        classifier = HypothesisClassifier({"allow_pullback_trade": True})
        classify_bullish_phase_c(classifier)

        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        htf["pd_pct"] = 60.0
        hyp = classify_with_auto_ec(classifier,
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
        self.assertFalse(hyp.debug_facts["phase_b_candidate"])
        self.assertIsNone(hyp.debug_facts["phase_b_candidate_variant"])
        self.assertEqual(hyp.debug_facts["phase_b_location"], "shallow")
        self.assertEqual(hyp.debug_facts["phase_b_blocked_reason"], "no_htf_demand_reaction")

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_bullish_phase_a_classifies_only_after_phase_b(self):
        classifier = HypothesisClassifier()
        hyp = classify_bullish_phase_a(classifier)

        self.assertEqual(hyp.phase, "A")
        self.assertEqual(hyp.status, "armed")
        self.assertEqual(hyp.direction, "long")
        self.assertEqual(hyp.swing_alignment, "pro_swing")
        self.assertEqual(hyp.internal_alignment, "pro_internal")
        self.assertEqual(hyp.poi_id, "SD-15m-demand-A")
        self.assertEqual(hyp.entry_policy, "hybrid")
        self.assertEqual(hyp.target_policy, "htf_pd_level")
        self.assertTrue(hyp.debug_facts["phase_a_ready"])
        self.assertTrue(hyp.debug_facts["phase_a_previous_phase_is_b"])
        self.assertEqual(hyp.debug_facts["phase_a_trade_style"], "controlled_chase")

    def test_aligned_continuation_without_prior_phase_b_does_not_classify_phase_a(self):
        classifier = HypothesisClassifier()
        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        htf["pd_pct"] = 80.0

        hyp = classify_with_auto_ec(classifier,
            dual_snapshot(
                htf,
                [
                    {"time": "2024-01-01T12:00:00+00:00", "open": 1.121, "high": 1.122, "low": 1.108, "close": 1.112},
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.112, "high": 1.124, "low": 1.111, "close": 1.123},
                ],
                ltf=structure("bullish", "open", high=1.124, low=1.111),
                zones=[sd_zone("SD-15m-demand-A", "demand", "15m", in_zone=False)],
            )
        )

        self.assertNotEqual(hyp.phase, "A")
        self.assertEqual(hyp.phase, "none")
        self.assertEqual(hyp.required_evidence, ["phase_a_classifier"])

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_phase_a_touch_without_close_beyond_objective_classifies_range(self):
        classifier = HypothesisClassifier()
        classify_bullish_phase_a(classifier)

        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        hyp = classify_with_auto_ec(classifier,
            dual_snapshot(
                htf,
                [
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.112, "high": 1.122, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.121, "high": 1.124, "low": 1.119, "close": 1.122},
                ],
                ltf=structure("bullish", "open", high=1.124, low=1.119),
                zones=[sd_zone("SD-15m-demand-A", "demand", "15m", in_zone=False)],
            )
        )

        self.assertEqual(hyp.phase, "range")
        self.assertEqual(hyp.entry_policy, "skip")
        self.assertEqual(hyp.target_policy, "none")
        self.assertEqual(hyp.debug_facts["range_reason"], "failed_phase_a_finale")
        self.assertEqual(hyp.debug_facts["budget_policy"], "preserve_spent_budget")
        self.assertTrue(hyp.debug_facts["phase_a_finale_touched"])
        self.assertFalse(hyp.debug_facts["phase_a_finale_closed_beyond"])

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_phase_a_close_beyond_objective_classifies_new_phase_e(self):
        classifier = HypothesisClassifier()
        classify_bullish_phase_a(classifier)

        htf = structure("bullish", "pullback_confirmed", high=1.123, low=1.10)
        hyp = classify_with_auto_ec(classifier,
            dual_snapshot(
                htf,
                [
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.112, "high": 1.122, "low": 1.111, "close": 1.121},
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.121, "high": 1.125, "low": 1.119, "close": 1.124},
                ],
                ltf=structure("bullish", "open", high=1.125, low=1.119),
                zones=[sd_zone("SD-15m-demand-A", "demand", "15m", in_zone=False)],
            )
        )

        self.assertEqual(hyp.phase, "E")
        self.assertEqual(hyp.entry_policy, "skip")
        self.assertTrue(hyp.debug_facts["phase_a_finale_touched"])
        self.assertTrue(hyp.debug_facts["phase_a_finale_closed_beyond"])

    @unittest.skip(PHASE_B_C_A_DISABLED_REASON)
    def test_bearish_phase_a_touch_without_close_beyond_objective_classifies_range(self):
        classifier = HypothesisClassifier()
        classify_bearish_phase_a(classifier)

        htf = structure("bearish", "pullback_confirmed", high=1.12, low=1.10)
        hyp = classify_with_auto_ec(classifier,
            dual_snapshot(
                htf,
                [
                    {"time": "2024-01-01T16:00:00+00:00", "open": 1.108, "high": 1.109, "low": 1.101, "close": 1.102},
                    {"time": "2024-01-01T20:00:00+00:00", "open": 1.102, "high": 1.104, "low": 1.099, "close": 1.101},
                ],
                ltf=structure("bearish", "open", high=1.104, low=1.099),
                zones=[sd_zone("SD-15m-supply-A", "supply", "15m", in_zone=False)],
            )
        )

        self.assertEqual(hyp.phase, "range")
        self.assertEqual(hyp.entry_policy, "skip")
        self.assertTrue(hyp.debug_facts["phase_a_finale_touched"])
        self.assertFalse(hyp.debug_facts["phase_a_finale_closed_beyond"])
        self.assertEqual(
            hyp.debug_facts["phase_a_finale_rule"],
            "bearish_phase_a_touch_without_close_below_htf_pd_objective",
        )


if __name__ == "__main__":
    unittest.main()
