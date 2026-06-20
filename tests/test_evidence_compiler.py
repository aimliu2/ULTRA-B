"""Tests for EvidenceCompiler — Layer 3 final stage."""
from __future__ import annotations

from typing import Any

import pytest

from ultrab.core.smc.evidence_compiler import (
    EvidenceCandidate,
    EvidenceCompiler,
    EvidenceRef,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _fused(
    *,
    htf_bias: str = "bullish",
    htf_phase: str = "open",
    htf_range_high: float = 51000.0,
    htf_range_low: float = 48000.0,
    current_price: float = 50000.0,
    ltf_bias: str | None = None,
    ltf_phase: str | None = None,
    ltf_last_sc_dir: str | None = None,
    ltf_last_sc: dict | None = None,
    ltf_last_isc: dict | None = None,
    ltf_internal_structure_sequence: list[dict] | None = None,
    ltf_orderflow: dict | None = None,
    htf_zones: list[dict] | None = None,
    ltf_zones: list[dict] | None = None,
    liquidity: dict | None = None,
    htf_last_resolved_zone: dict | None = None,
) -> dict[str, Any]:
    return {
        "mode": "dual",
        "reference_tf": "4H",
        "execution_tf": "15m",
        "currentTimestamp": "2025-01-01T12:00:00",
        "currentPrice": current_price,
        "higher_context_snapshot": {
            "bias": htf_bias,
            "structure": {
                "bias": htf_bias,
                "phase": htf_phase,
                "range_high": htf_range_high,
                "range_low": htf_range_low,
                "range_high_ts": "2025-01-01T08:00:00",
                "range_low_ts": "2025-01-01T04:00:00",
                "last_sc": {
                    "eventTimestamp": "2025-01-01T00:00:00",
                    "eventCode": "BOS",
                    "breakDirection": "up",
                },
                "phase_start_ts": "2025-01-01T00:00:00",
            },
            "zones": htf_zones or [],
            "liquidity": liquidity or {},
            "last_resolved_zone": htf_last_resolved_zone,
        },
        "lower_context_snapshot": {
            "bias": ltf_bias,
            "structure": (
                {
                    "bias": ltf_bias,
                    "phase": ltf_phase or "open",
                    "last_sc": (
                        ltf_last_sc
                        or ({"breakDirection": ltf_last_sc_dir} if ltf_last_sc_dir else None)
                    ),
                    "last_isc": ltf_last_isc,
                    "internal_structure_sequence": ltf_internal_structure_sequence or [],
                }
                if ltf_bias
                else None
            ),
            "zones": ltf_zones or [],
            "liquidity": {},
            "orderflow": ltf_orderflow or {},
        },
    }


def _htf_bars(*, last_high: float = 50900.0, last_low: float = 50200.0, last_close: float = 50250.0) -> list[dict]:
    return [
        {"time": "2025-01-01T08:00:00", "open": 49500, "high": 50800, "low": 49400, "close": 50700},
        {"time": "2025-01-01T12:00:00", "open": 50700, "high": last_high, "low": last_low, "close": last_close},
    ]


def _candidate(candidates: list[EvidenceCandidate], pattern: str) -> EvidenceCandidate | None:
    return next((c for c in candidates if c.pattern == pattern), None)


def _current_liquidity_event(
    *,
    event_id: str = "liq-pd-1|2025-01-01T10:15:00",
    pool_id: str = "liq-pd-1",
    pool_kind: str = "htf_pd",
    source: str = "range_high",
    side: str = "buy_side",
    direction: str = "bearish",
    level: float = 51000.0,
) -> dict[str, Any]:
    return {
        "liquidity_event_id": event_id,
        "pool_id": pool_id,
        "pool_kind": pool_kind,
        "variant": "level" if pool_kind == "htf_pd" else "eq",
        "source": source,
        "side": side,
        "direction": direction,
        "level": level,
        "tolerance": 1.0,
        "scope": "active_current_epoch",
        "htf_pd_epoch_id": "2025-01-01T00:00:00|BOS|up|2025-01-01T00:00:00",
        "is_triggerable": True,
        "taken_at": "2025-01-01T10:00:00",
        "reclaimed_at": "2025-01-01T10:15:00",
        "reclaimed_price": 50950.0,
        "confirmed_at": "2025-01-01T10:15:00",
        "confirmed_by": "ltf_close_reclaim",
    }


# ---------------------------------------------------------------------------
# Basic contract
# ---------------------------------------------------------------------------

class TestBasicContract:
    def test_empty_when_no_direction(self):
        ec = EvidenceCompiler()
        fused = _fused(htf_bias=None)
        fused["higher_context_snapshot"]["bias"] = None
        fused["higher_context_snapshot"]["structure"] = None
        candidates = ec.update(fused, higher_bars=[])
        assert candidates == []

    def test_returns_list_of_evidence_candidates(self):
        ec = EvidenceCompiler()
        fused = _fused()
        candidates = ec.update(fused, higher_bars=_htf_bars())
        assert isinstance(candidates, list)
        assert all(isinstance(c, EvidenceCandidate) for c in candidates)

    def test_to_dict_is_serializable(self):
        ec = EvidenceCompiler()
        fused = _fused()
        candidates = ec.update(fused, higher_bars=_htf_bars())
        for c in candidates:
            d = c.to_dict()
            assert isinstance(d, dict)
            assert d["pattern"] == c.pattern
            assert d["status"] == c.status
            assert d["direction"] == c.direction

    def test_phase_e_context_always_emitted_when_direction_known(self):
        ec = EvidenceCompiler()
        fused = _fused()
        candidates = ec.update(fused, higher_bars=_htf_bars())
        patterns = [c.pattern for c in candidates]
        assert "htf_expansion_context" in patterns
        assert "phase_e_context" in patterns

    def test_reset_clears_state(self):
        ec = EvidenceCompiler()
        fused = _fused()
        # First call — establishes extreme
        ec.update(fused, higher_bars=_htf_bars(last_high=50900))
        assert ec.active_phase_e_extreme_price is not None
        # Reset
        ec.reset()
        assert ec.active_phase_e_extreme_price is None
        assert ec.active_phase_e_direction == "none"
        assert ec.htf_pd_epoch_id is None


# ---------------------------------------------------------------------------
# Phase-E context
# ---------------------------------------------------------------------------

class TestPhaseEContext:
    def test_tracks_running_extreme_bullish(self):
        ec = EvidenceCompiler()
        fused = _fused()
        ec.update(fused, higher_bars=_htf_bars(last_high=50900))
        # HTF struct range_high=51000, bar high=50900 → extreme = 51000
        assert ec.active_phase_e_extreme_price == 51000.0
        assert ec.active_phase_e_direction == "long"

    def test_new_extreme_flag_when_bar_exceeds_struct(self):
        ec = EvidenceCompiler()
        fused = _fused(htf_range_high=50800.0)
        # Bar high = 50900 > struct range_high 50800 → new extreme
        ec.update(fused, higher_bars=_htf_bars(last_high=50900))
        assert ec.active_phase_e_extreme_price == 50900.0

    def test_reaction_signal_two_bar(self):
        """Previous bar low > current bar low AND current close < prev low → confirmed."""
        ec = EvidenceCompiler()
        fused = _fused()
        bars = [
            {"time": "08:00", "open": 50600, "high": 50800, "low": 50300, "close": 50700},  # prev
            {"time": "12:00", "open": 50700, "high": 50900, "low": 50100, "close": 50050},  # current: low < prev_low, close < prev_low
        ]
        candidates = ec.update(fused, higher_bars=bars)
        e_ctx = _candidate(candidates, "phase_e_context")
        assert e_ctx is not None
        assert e_ctx.debug_facts["reaction_confirmed"] is True

    def test_reaction_warning_close_back_above(self):
        """Bar low breaks below prev but close recovers → warning only."""
        ec = EvidenceCompiler()
        fused = _fused()
        bars = [
            {"time": "08:00", "open": 50600, "high": 50800, "low": 50300, "close": 50700},
            {"time": "12:00", "open": 50700, "high": 50900, "low": 50100, "close": 50400},  # close > prev_low
        ]
        candidates = ec.update(fused, higher_bars=bars)
        e_ctx = _candidate(candidates, "phase_e_context")
        assert e_ctx.debug_facts["reaction_confirmed"] is False
        assert e_ctx.debug_facts["reaction_warning"] is True

    def test_reaction_failed_signal_bullish(self):
        """Current bar close above the running E extreme → reaction failed (D collapses)."""
        ec = EvidenceCompiler()
        fused = _fused(htf_range_high=50800.0)
        # Set extreme to 50800 first
        ec.update(fused, higher_bars=[{"time": "08:00", "high": 50700, "low": 50200, "close": 50600, "open": 50300}])
        # Now current bar closes above 50800
        bars2 = [
            {"time": "08:00", "high": 50700, "low": 50200, "close": 50600, "open": 50300},
            {"time": "12:00", "high": 50900, "low": 50300, "close": 50850, "open": 50650},
        ]
        candidates = ec.update(fused, higher_bars=bars2)
        e_ctx = _candidate(candidates, "phase_e_context")
        assert e_ctx.debug_facts["reaction_failed"] is True

    def test_phase_e_context_emits_stalling_facts(self):
        ec = EvidenceCompiler()
        fused = _fused(
            ltf_bias="bearish",
            current_price=51100.0,
            ltf_orderflow={
                "confirmed_direction": "bearish",
                "quality": "clean",
                "regime": "directional",
                "range_ref": "OF:bearish:1",
                "last_shift_at": "2025-01-01T11:00:00",
            },
        )
        candidates = ec.update(fused, higher_bars=_htf_bars(last_high=50900))
        e_ctx = _candidate(candidates, "phase_e_context")
        assert e_ctx is not None
        assert e_ctx.debug_facts["new_htf_extreme"] is False
        assert e_ctx.debug_facts["htf_pd_stopped_expanding"] is True
        assert e_ctx.debug_facts["ltf_bias_counter_htf"] is True
        assert e_ctx.debug_facts["ltf_probe_outside_htf_pd_range"] is True
        assert e_ctx.debug_facts["ltf_probe_direction"] == "pro"
        assert e_ctx.debug_facts["ltf_counter_orderflow_clean"] is True
        assert e_ctx.debug_facts["ltf_counter_orderflow_broken"] is False
        assert e_ctx.debug_facts["ltf_counter_orderflow_leg_id"] == "OF:bearish:1"
        assert e_ctx.debug_facts["ltf_pullback_depth_pct"] == 0.0

    def test_phase_e_context_flags_counter_orderflow_mss_watch_before_direction_flip(self):
        ec = EvidenceCompiler()
        ec.update(_fused(), higher_bars=_htf_bars(last_high=51000))

        candidates = ec.update(
            _fused(
                ltf_bias="bearish",
                ltf_orderflow={
                    "confirmed_direction": "bullish",
                    "quality": "clean",
                    "regime": "mss_watch",
                    "mss_regime": "mss_watch",
                    "mss_monitor_status": "watching_resolution",
                    "probe_breaks_protected_anchor": True,
                    "mss_trigger_source": "probe_vs_protected_anchor",
                    "range_ref": "OF:mss-watch:1",
                    "protected_anchor_ref": "OFANCH:L3",
                    "disruption_point_ref": "OFPROBE:low",
                    "source_store": "orderflow_anchor_sequence",
                    "last_shift_at": "2025-01-01T11:00:00",
                },
            ),
            higher_bars=_htf_bars(last_high=50900),
        )

        e_ctx = _candidate(candidates, "phase_e_context")
        assert e_ctx is not None
        assert e_ctx.debug_facts["ltf_counter_orderflow_mss_watch"] is True
        assert e_ctx.debug_facts["ltf_counter_orderflow_clean"] is False
        assert e_ctx.debug_facts["ltf_counter_orderflow_direction"] == "bullish"
        assert e_ctx.debug_facts["ltf_counter_orderflow_mss_trigger_source"] == "probe_vs_protected_anchor"
        assert e_ctx.debug_facts["ltf_counter_orderflow_anchor_id"] == "OFANCH:L3"
        assert e_ctx.debug_facts["ltf_counter_orderflow_disruption_id"] == "OFPROBE:low"
        assert e_ctx.debug_facts["ltf_counter_orderflow_source_store"] == "orderflow_anchor_sequence"

    def test_phase_e_equal_high_enriches_stalling_not_new_extreme(self):
        ec = EvidenceCompiler()
        ec.update(_fused(htf_range_high=51000.0), higher_bars=_htf_bars(last_high=51000.0))

        candidates = ec.update(
            _fused(
                htf_range_high=51000.0,
                liquidity={
                    "eq_tolerance": 1.0,
                    "active_htf_eq_pools": [
                        {
                            "pool_id": "EQH:phase-e:1",
                            "source": "eqh",
                            "price": 51000.0,
                            "tolerance": 1.0,
                            "status": "active",
                        }
                    ],
                },
            ),
            higher_bars=_htf_bars(last_high=51000.0),
        )
        e_ctx = _candidate(candidates, "phase_e_context")

        assert e_ctx.debug_facts["new_htf_extreme"] is False
        assert e_ctx.debug_facts["htf_pd_stopped_expanding"] is True
        assert e_ctx.debug_facts["htf_equal_extreme_retest"] is True
        assert e_ctx.debug_facts["htf_equal_extreme_kind"] == "htf_eqh_at_phase_e_extreme"
        assert e_ctx.debug_facts["htf_equal_expansion_extreme_kind"] == "htf_eqh_at_expansion_extreme"
        assert e_ctx.debug_facts["htf_eqh_at_expansion_extreme"] is True
        assert e_ctx.debug_facts["htf_eqh_at_phase_e_extreme"] is True
        assert e_ctx.debug_facts["htf_equal_extreme_pool_id"] == "EQH:phase-e:1"


# ---------------------------------------------------------------------------
# HTF counter-reaction gate
# ---------------------------------------------------------------------------

class TestHtfCounterReaction:
    def test_ready_when_htf_sd_tapped_and_ltf_counter_sd_present(self):
        ec = EvidenceCompiler()
        fused = _fused(
            htf_zones=[{"zone_id": "htf-s1", "direction": "supply", "timeframe": "4H", "in_zone": True}],
            ltf_zones=[{"zone_id": "ltf-s1", "direction": "supply", "timeframe": "15m", "in_zone": False, "created_at": "2025-01-01T10:00:00"}],
        )
        candidates = ec.update(fused, higher_bars=_htf_bars())
        cr = _candidate(candidates, "htf_counter_reaction")
        assert cr is not None
        assert cr.status == "ready"
        assert cr.debug_facts["trigger"] == "opposing_htf_sd_reaction_with_ltf_counter_sd"

    def test_collecting_when_only_htf_sd_tapped_no_ltf_zone(self):
        ec = EvidenceCompiler()
        fused = _fused(
            htf_zones=[{"zone_id": "htf-s1", "direction": "supply", "timeframe": "4H", "in_zone": True}],
            ltf_zones=[],
        )
        candidates = ec.update(fused, higher_bars=_htf_bars())
        cr = _candidate(candidates, "htf_counter_reaction")
        assert cr is not None
        assert cr.status == "collecting"
        assert "no_ltf_counter_sd_zone" in cr.blocked_reasons

    def test_absent_when_no_htf_sd_reaction(self):
        ec = EvidenceCompiler()
        fused = _fused(htf_zones=[], ltf_zones=[])
        candidates = ec.update(fused, higher_bars=_htf_bars())
        cr = _candidate(candidates, "htf_counter_reaction")
        assert cr is None

    def test_ready_when_htf_last_resolved_zone_is_opposing(self):
        ec = EvidenceCompiler()
        fused = _fused(
            ltf_zones=[{"zone_id": "ltf-s1", "direction": "supply", "timeframe": "15m", "in_zone": False, "created_at": "2025-01-01T10:00:00"}],
            htf_last_resolved_zone={
                "zone_id": "htf-s-resolved",
                "direction": "supply",
                "timeframe": "4H",
                "resolution": "mitigated",
            },
        )
        candidates = ec.update(fused, higher_bars=_htf_bars())
        cr = _candidate(candidates, "htf_counter_reaction")
        assert cr is not None
        assert cr.debug_facts["htf_opposing_sd_resolved"] is True
        assert cr.status == "ready"

    def test_liquidity_grab_alone_collects_without_post_reclaim_choch(self):
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                liquidity={
                    "current_triggerable_liquidity_events": [_current_liquidity_event()],
                },
            ),
            higher_bars=_htf_bars(),
        )
        cr = _candidate(candidates, "htf_counter_reaction")

        assert cr is not None
        assert cr.status == "collecting"
        event = cr.debug_facts["liquidity_reclaim_candidates"][0]
        assert event["pro_attempt_failed_to_establish_continuation"] is True
        assert event["ltf_counter_choch_after_reclaim"] is False
        assert "post_reclaim_counter_choch_not_seen" in event["blocked_reasons"]

    def test_liquidity_reclaim_ready_after_fresh_counter_choch(self):
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                ltf_bias="bearish",
                ltf_last_sc={
                    "choch": True,
                    "breakDirection": "down",
                    "eventTimestamp": "2025-01-01T11:00:00",
                    "levelPrice": 50750.0,
                    "biasFlip": True,
                },
                liquidity={
                    "current_triggerable_liquidity_events": [_current_liquidity_event()],
                },
            ),
            higher_bars=_htf_bars(),
        )
        cr = _candidate(candidates, "htf_counter_reaction")

        assert cr is not None
        assert cr.status == "ready"
        assert cr.debug_facts["trigger"] == "qualified_liquidity_grab_reclaim"
        event = cr.debug_facts["liquidity_reclaim_candidates"][0]
        assert event["status"] == "ready"
        assert event["liquidity_relation_to_htf_expansion_extreme"] == "at_active_extreme"
        assert event["price_reclaimed_inside_active_htf_pd"] is True
        assert event["ltf_counter_choch_event_at"] == "2025-01-01T11:00:00"

    def test_liquidity_reclaim_reads_target_structure_choch_alias(self):
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                ltf_bias="bearish",
                ltf_last_sc={
                    "structure_choch": True,
                    "eventAction": "structure_choch",
                    "breakDirection": "down",
                    "eventTimestamp": "2025-01-01T11:00:00",
                    "levelPrice": 50750.0,
                    "biasFlip": True,
                },
                liquidity={
                    "current_triggerable_liquidity_events": [_current_liquidity_event()],
                },
            ),
            higher_bars=_htf_bars(),
        )
        cr = _candidate(candidates, "htf_counter_reaction")

        assert cr is not None
        event = cr.debug_facts["liquidity_reclaim_candidates"][0]
        assert event["status"] == "ready"
        assert event["ltf_counter_choch_after_reclaim"] is True

    def test_ltf_counter_choch_stream_reads_target_structure_ichoch(self):
        # iChoCh (SC06) in last_isc is the new primary trigger — status ready
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                ltf_bias="bearish",
                ltf_last_isc={
                    "structure_ichoch": True,
                    "eventAction": "structure_ichoch",
                    "eventCode": "SC06",
                    "breakDirection": "down",
                    "eventTimestamp": "2025-01-01T11:00:00",
                    "levelTimestamp": "2025-01-01T10:30:00",
                    "levelSide": "low",
                    "levelPrice": 50750.0,
                },
            ),
            higher_bars=_htf_bars(),
        )
        choch = _candidate(candidates, "ltf_counter_choch")

        assert choch is not None
        assert choch.status == "ready"
        assert choch.debug_facts["ltf_counter_choch_seen"] is True
        assert choch.debug_facts["ltf_counter_structure_choch_seen"] is True
        assert choch.debug_facts["ltf_counter_choch_event_id"] == (
            "SC06:2025-01-01T11:00:00:down:50750.0"
        )
        assert choch.debug_facts["ltf_counter_choch_source_level_id"] == (
            "structure_level:low:2025-01-01T10:30:00:50750.0"
        )
        assert choch.debug_facts["ltf_counter_choch_source_store"] == "structure_isc"
        assert not any(key.startswith("phase_d_") for key in choch.debug_facts)

    def test_ltf_counter_ichoch_fires_before_macro_choch(self):
        # iChoCh in last_isc triggers ready even when last_sc is absent
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                ltf_bias="bearish",
                ltf_last_isc={
                    "structure_ichoch": True,
                    "eventAction": "structure_ichoch",
                    "eventCode": "SC06",
                    "breakDirection": "down",
                    "eventTimestamp": "2025-01-01T10:30:00",
                    "levelTimestamp": "2025-01-01T10:00:00",
                    "levelSide": "low",
                    "levelPrice": 50600.0,
                },
                ltf_last_sc=None,
            ),
            higher_bars=_htf_bars(),
        )
        choch = _candidate(candidates, "ltf_counter_choch")

        assert choch is not None
        assert choch.status == "ready"
        assert choch.debug_facts["ltf_counter_choch_seen"] is True
        assert choch.debug_facts["ltf_counter_choch_source_store"] == "structure_isc"
        assert choch.debug_facts["ltf_counter_sb_seen"] is False

    def test_ltf_counter_choch_stream_reads_counter_structure_sb(self):
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                ltf_bias="bearish",
                ltf_last_sc={
                    "structure_sb": True,
                    "eventAction": "structure_sb",
                    "eventCode": "SC02",
                    "breakDirection": "down",
                    "eventTimestamp": "2025-01-01T11:00:00",
                    "levelTimestamp": "2025-01-01T10:45:00",
                    "levelSide": "low",
                    "levelPrice": 50725.0,
                    "choch": False,
                },
            ),
            higher_bars=_htf_bars(),
        )
        choch = _candidate(candidates, "ltf_counter_choch")

        assert choch is not None
        assert choch.status == "collecting"
        assert choch.debug_facts["ltf_counter_choch_seen"] is False
        assert choch.debug_facts["ltf_counter_structure_choch_seen"] is False
        assert choch.debug_facts["ltf_counter_sb_seen"] is True
        assert choch.debug_facts["ltf_counter_sb_level"] == 50725.0
        assert choch.debug_facts["ltf_counter_sb_event_id"] == (
            "SC02:2025-01-01T11:00:00:down:50725.0"
        )
        assert choch.debug_facts["ltf_counter_sb_source_level_id"] == (
            "structure_level:low:2025-01-01T10:45:00:50725.0"
        )
        assert choch.debug_facts["ltf_counter_sb_source_store"] == "structure_sequence"
        assert not any(key.startswith("phase_d_") for key in choch.debug_facts)

    def test_ltf_counter_ichoch_isb_sequence_accepts_level_valid_pair(self):
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                htf_bias="bearish",
                ltf_bias="bullish",
                ltf_internal_structure_sequence=[
                    {
                        "structure_ichoch": True,
                        "eventAction": "structure_ichoch",
                        "eventCode": "SC06",
                        "breakDirection": "up",
                        "eventTimestamp": "2025-01-01T10:00:00",
                        "levelTimestamp": "2025-01-01T09:45:00",
                        "levelSide": "high",
                        "levelPrice": 1.13117,
                    },
                    {
                        "structure_isb": True,
                        "eventAction": "structure_isb",
                        "eventCode": "SC05",
                        "breakDirection": "down",
                        "eventTimestamp": "2025-01-01T10:15:00",
                        "levelTimestamp": "2025-01-01T10:00:00",
                        "levelSide": "low",
                        "levelPrice": 1.1312,
                    },
                ],
            ),
            higher_bars=_htf_bars(),
        )
        choch = _candidate(candidates, "ltf_counter_choch")

        assert choch is not None
        assert choch.debug_facts["ltf_counter_ichoch_isb_sequence_seen"] is True
        assert choch.debug_facts["ltf_counter_sequence_trade_direction"] == "long"
        assert choch.debug_facts["ltf_counter_sequence_ichoch_level"] == 1.13117
        assert choch.debug_facts["ltf_counter_sequence_isb_level"] == 1.1312
        assert choch.debug_facts["ltf_counter_sequence_invalidated"] is False

    def test_ltf_counter_ichoch_isb_sequence_rejects_2019_level_shape(self):
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                htf_bias="bearish",
                ltf_bias="bullish",
                ltf_internal_structure_sequence=[
                    {
                        "structure_ichoch": True,
                        "eventAction": "structure_ichoch",
                        "eventCode": "SC06",
                        "breakDirection": "up",
                        "eventTimestamp": "2019-03-07T02:00:00+00:00",
                        "levelTimestamp": "2019-03-07T01:45:00+00:00",
                        "levelSide": "high",
                        "levelPrice": 1.13117,
                    },
                    {
                        "structure_isb": True,
                        "eventAction": "structure_isb",
                        "eventCode": "SC05",
                        "breakDirection": "down",
                        "eventTimestamp": "2019-03-07T09:00:00+00:00",
                        "levelTimestamp": "2019-03-07T08:45:00+00:00",
                        "levelSide": "low",
                        "levelPrice": 1.13022,
                    },
                ],
            ),
            higher_bars=_htf_bars(),
        )
        choch = _candidate(candidates, "ltf_counter_choch")

        assert choch is not None
        assert choch.debug_facts["ltf_counter_ichoch_isb_sequence_seen"] is False
        assert choch.debug_facts["ltf_counter_sequence_invalidated"] is True
        assert choch.debug_facts["ltf_counter_sequence_invalid_reason"] == "isb_level_not_beyond_ichoch"

    def test_ltf_counter_ichoch_isb_sequence_rejects_intervening_opposite_ichoch(self):
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                htf_bias="bearish",
                ltf_bias="bullish",
                ltf_internal_structure_sequence=[
                    {
                        "structure_ichoch": True,
                        "eventAction": "structure_ichoch",
                        "eventCode": "SC06",
                        "breakDirection": "up",
                        "eventTimestamp": "2025-01-01T10:00:00",
                        "levelTimestamp": "2025-01-01T09:45:00",
                        "levelSide": "high",
                        "levelPrice": 1.13117,
                    },
                    {
                        "structure_ichoch": True,
                        "eventAction": "structure_ichoch",
                        "eventCode": "SC06",
                        "breakDirection": "down",
                        "eventTimestamp": "2025-01-01T10:10:00",
                        "levelTimestamp": "2025-01-01T10:00:00",
                        "levelSide": "low",
                        "levelPrice": 1.1305,
                    },
                    {
                        "structure_isb": True,
                        "eventAction": "structure_isb",
                        "eventCode": "SC05",
                        "breakDirection": "down",
                        "eventTimestamp": "2025-01-01T10:15:00",
                        "levelTimestamp": "2025-01-01T10:05:00",
                        "levelSide": "low",
                        "levelPrice": 1.1313,
                    },
                ],
            ),
            higher_bars=_htf_bars(),
        )
        choch = _candidate(candidates, "ltf_counter_choch")

        assert choch is not None
        assert choch.debug_facts["ltf_counter_ichoch_isb_sequence_seen"] is False
        assert choch.debug_facts["ltf_counter_sequence_invalidated"] is True
        assert choch.debug_facts["ltf_counter_sequence_invalid_reason"] == "opposite_ichoch_between"

    def test_ltf_counter_internal_pressure_classifies_none(self):
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                htf_bias="bullish",
                ltf_bias="bearish",
                ltf_internal_structure_sequence=[
                    {
                        "structure_ichoch": True,
                        "eventAction": "structure_ichoch",
                        "eventCode": "SC06",
                        "breakDirection": "up",
                        "eventTimestamp": "2025-01-01T10:00:00",
                        "levelTimestamp": "2025-01-01T09:45:00",
                        "levelSide": "high",
                        "levelPrice": 1.1020,
                    },
                ],
            ),
            higher_bars=_htf_bars(),
        )
        choch = _candidate(candidates, "ltf_counter_choch")

        assert choch is not None
        assert choch.debug_facts["ltf_counter_internal_pressure_seen"] is False
        assert choch.debug_facts["ltf_counter_internal_pressure_class"] == "none"

    def test_ltf_counter_internal_pressure_accepts_single_ichoch(self):
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                htf_bias="bullish",
                ltf_bias="bearish",
                ltf_internal_structure_sequence=[
                    {
                        "structure_ichoch": True,
                        "eventAction": "structure_ichoch",
                        "eventCode": "SC06",
                        "breakDirection": "down",
                        "eventTimestamp": "2025-01-01T10:00:00",
                        "levelTimestamp": "2025-01-01T09:45:00",
                        "levelSide": "low",
                        "levelPrice": 1.1000,
                    },
                ],
            ),
            higher_bars=_htf_bars(),
        )
        choch = _candidate(candidates, "ltf_counter_choch")

        assert choch is not None
        assert choch.debug_facts["ltf_counter_internal_pressure_seen"] is True
        assert choch.debug_facts["ltf_counter_internal_pressure_class"] == "single_ichoch"
        assert choch.debug_facts["ltf_counter_internal_pressure_event_count"] == 1

    def test_ltf_counter_internal_pressure_accepts_repeated_isb(self):
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                htf_bias="bullish",
                ltf_bias="bearish",
                ltf_internal_structure_sequence=[
                    {
                        "structure_isb": True,
                        "eventAction": "structure_isb",
                        "eventCode": "SC05",
                        "breakDirection": "down",
                        "eventTimestamp": "2025-01-01T10:00:00",
                        "levelTimestamp": "2025-01-01T09:45:00",
                        "levelSide": "low",
                        "levelPrice": 1.1000,
                    },
                    {
                        "structure_isb": True,
                        "eventAction": "structure_isb",
                        "eventCode": "SC05",
                        "breakDirection": "down",
                        "eventTimestamp": "2025-01-01T10:15:00",
                        "levelTimestamp": "2025-01-01T10:00:00",
                        "levelSide": "low",
                        "levelPrice": 1.0990,
                    },
                ],
            ),
            higher_bars=_htf_bars(),
        )
        choch = _candidate(candidates, "ltf_counter_choch")

        assert choch is not None
        assert choch.debug_facts["ltf_counter_internal_pressure_seen"] is True
        assert choch.debug_facts["ltf_counter_internal_pressure_class"] == "repeated_isb"
        assert choch.debug_facts["ltf_counter_internal_pressure_event_count"] == 2

    def test_ltf_counter_internal_pressure_accepts_messy_reassertion(self):
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                htf_bias="bullish",
                ltf_bias="bearish",
                ltf_internal_structure_sequence=[
                    {
                        "structure_isb": True,
                        "eventAction": "structure_isb",
                        "eventCode": "SC05",
                        "breakDirection": "down",
                        "eventTimestamp": "2025-01-01T10:00:00",
                        "levelTimestamp": "2025-01-01T09:45:00",
                        "levelSide": "low",
                        "levelPrice": 1.1000,
                    },
                    {
                        "structure_ichoch": True,
                        "eventAction": "structure_ichoch",
                        "eventCode": "SC06",
                        "breakDirection": "up",
                        "eventTimestamp": "2025-01-01T10:15:00",
                        "levelTimestamp": "2025-01-01T10:00:00",
                        "levelSide": "high",
                        "levelPrice": 1.1020,
                    },
                    {
                        "structure_isb": True,
                        "eventAction": "structure_isb",
                        "eventCode": "SC05",
                        "breakDirection": "down",
                        "eventTimestamp": "2025-01-01T10:30:00",
                        "levelTimestamp": "2025-01-01T10:15:00",
                        "levelSide": "low",
                        "levelPrice": 1.0990,
                    },
                ],
            ),
            higher_bars=_htf_bars(),
        )
        choch = _candidate(candidates, "ltf_counter_choch")

        assert choch is not None
        assert choch.debug_facts["ltf_counter_internal_pressure_seen"] is True
        assert choch.debug_facts["ltf_counter_internal_pressure_class"] == "messy_reasserted"
        assert choch.debug_facts["ltf_counter_internal_pressure_last_at"] == "2025-01-01T10:30:00"

    def test_ltf_counter_internal_pressure_rejects_final_contradiction(self):
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                htf_bias="bullish",
                ltf_bias="bearish",
                ltf_internal_structure_sequence=[
                    {
                        "structure_isb": True,
                        "eventAction": "structure_isb",
                        "eventCode": "SC05",
                        "breakDirection": "down",
                        "eventTimestamp": "2025-01-01T10:00:00",
                        "levelTimestamp": "2025-01-01T09:45:00",
                        "levelSide": "low",
                        "levelPrice": 1.1000,
                    },
                    {
                        "structure_ichoch": True,
                        "eventAction": "structure_ichoch",
                        "eventCode": "SC06",
                        "breakDirection": "up",
                        "eventTimestamp": "2025-01-01T10:15:00",
                        "levelTimestamp": "2025-01-01T10:00:00",
                        "levelSide": "high",
                        "levelPrice": 1.1020,
                    },
                ],
            ),
            higher_bars=_htf_bars(),
        )
        choch = _candidate(candidates, "ltf_counter_choch")

        assert choch is not None
        assert choch.debug_facts["ltf_counter_internal_pressure_seen"] is False
        assert choch.debug_facts["ltf_counter_internal_pressure_class"] == "contradicted"
        assert choch.debug_facts["ltf_counter_internal_pressure_invalid_reason"] == "final_internal_contradiction"

    def test_pd_and_eq_candidates_are_preserved_without_layer4_selection(self):
        ec = EvidenceCompiler()
        eq_event = _current_liquidity_event(
            event_id="liq-eq-1|2025-01-01T10:20:00",
            pool_id="liq-eq-1",
            pool_kind="htf_eq",
            source="eqh",
        )
        candidates = ec.update(
            _fused(
                ltf_bias="bearish",
                ltf_last_sc={
                    "choch": True,
                    "breakDirection": "down",
                    "eventTimestamp": "2025-01-01T11:00:00",
                    "levelPrice": 50750.0,
                },
                liquidity={
                    "current_triggerable_liquidity_events": [
                        _current_liquidity_event(),
                        eq_event,
                    ],
                },
            ),
            higher_bars=_htf_bars(),
        )
        cr = _candidate(candidates, "htf_counter_reaction")

        assert cr is not None
        assert len(cr.debug_facts["liquidity_reclaim_candidates"]) == 2
        assert len(cr.debug_facts["liquidity_reclaim_ready_event_ids"]) == 2
        assert not any(key.startswith("phase_d_") for key in cr.debug_facts)

    def test_wrong_side_eq_and_pre_reclaim_choch_do_not_qualify(self):
        ec = EvidenceCompiler()
        eq_event = _current_liquidity_event(
            event_id="liq-eq-wrong|2025-01-01T10:20:00",
            pool_id="liq-eq-wrong",
            pool_kind="htf_eq",
            source="eql",
            side="sell_side",
        )
        candidates = ec.update(
            _fused(
                ltf_bias="bearish",
                ltf_last_sc={
                    "choch": True,
                    "breakDirection": "down",
                    "eventTimestamp": "2025-01-01T10:10:00",
                },
                liquidity={"current_triggerable_liquidity_events": [eq_event]},
            ),
            higher_bars=_htf_bars(),
        )
        cr = _candidate(candidates, "htf_counter_reaction")

        assert cr is not None
        assert cr.status == "collecting"
        event = cr.debug_facts["liquidity_reclaim_candidates"][0]
        assert event["liquidity_relation_is_relevant"] is False
        assert event["ltf_counter_choch_after_reclaim"] is False

    def test_outside_htf_close_marks_continuation_accepted(self):
        ec = EvidenceCompiler()
        candidates = ec.update(
            _fused(
                ltf_bias="bearish",
                ltf_last_sc={
                    "choch": True,
                    "breakDirection": "down",
                    "eventTimestamp": "2025-01-01T11:00:00",
                },
                liquidity={
                    "current_triggerable_liquidity_events": [_current_liquidity_event()],
                },
            ),
            higher_bars=_htf_bars(last_high=51200.0, last_close=51100.0),
        )
        cr = _candidate(candidates, "htf_counter_reaction")

        assert cr is not None
        event = cr.debug_facts["liquidity_reclaim_candidates"][0]
        assert event["status"] == "invalidated"
        assert event["continuation_accepted"] is True
        assert cr.debug_facts["liquidity_continuation_accepted_event_ids"] == [
            "liq-pd-1|2025-01-01T10:15:00"
        ]


# ---------------------------------------------------------------------------
# LTF counter-story gate
# ---------------------------------------------------------------------------

class TestLtfCounterStory:
    def test_ready_when_ltf_flipped_and_zone_available(self):
        ec = EvidenceCompiler()
        fused = _fused(
            ltf_bias="bearish",
            ltf_last_sc_dir="down",
            ltf_zones=[{"zone_id": "ltf-s1", "direction": "supply", "timeframe": "15m", "in_zone": False, "created_at": "2025-01-01T10:00:00"}],
        )
        candidates = ec.update(fused, higher_bars=_htf_bars())
        ls = _candidate(candidates, "ltf_counter_story")
        assert ls is not None
        assert ls.status == "ready"
        assert ls.location_context["selected_poi_id"] == "ltf-s1"

    def test_ready_when_ltf_flipped_but_no_zone(self):
        ec = EvidenceCompiler()
        fused = _fused(ltf_bias="bearish", ltf_zones=[])
        candidates = ec.update(fused, higher_bars=_htf_bars())
        ls = _candidate(candidates, "ltf_counter_story")
        assert ls is not None
        assert ls.status == "ready"
        assert "no_ltf_counter_sd_zone_available" in ls.blocked_reasons

    def test_absent_when_ltf_not_flipped(self):
        ec = EvidenceCompiler()
        fused = _fused(ltf_bias="bullish")  # same as HTF, not counter
        candidates = ec.update(fused, higher_bars=_htf_bars())
        ls = _candidate(candidates, "ltf_counter_story")
        assert ls is None

    def test_in_zone_poi_preferred_over_unvisited(self):
        ec = EvidenceCompiler()
        fused = _fused(
            ltf_bias="bearish",
            ltf_zones=[
                {"zone_id": "ltf-s-old", "direction": "supply", "timeframe": "15m", "in_zone": True, "created_at": "2025-01-01T09:00:00"},
                {"zone_id": "ltf-s-new", "direction": "supply", "timeframe": "15m", "in_zone": False, "created_at": "2025-01-01T11:00:00"},
            ],
        )
        candidates = ec.update(fused, higher_bars=_htf_bars())
        ls = _candidate(candidates, "ltf_counter_story")
        assert ls.location_context["selected_poi_id"] == "ltf-s-old"
        assert ls.location_context["selected_poi_touched"] is True

    def test_ltf_counter_bos_confirmed_true_when_orderflow_direction_and_regime_match(self):
        ec = EvidenceCompiler()
        fused = _fused(
            ltf_bias="bearish",
            ltf_orderflow={
                "confirmed_direction": "bearish",
                "regime": "directional",
                "quality": "clean",
            },
        )
        candidates = ec.update(fused, higher_bars=_htf_bars())
        ls = _candidate(candidates, "ltf_counter_story")
        assert ls is not None
        assert ls.debug_facts["ltf_counter_bos_confirmed"] is True

    def test_ltf_counter_bos_confirmed_false_when_orderflow_not_directional(self):
        ec = EvidenceCompiler()
        fused = _fused(
            ltf_bias="bearish",
            ltf_orderflow={
                "confirmed_direction": "bearish",
                "regime": "mss_watch",
                "quality": "weak",
            },
        )
        candidates = ec.update(fused, higher_bars=_htf_bars())
        ls = _candidate(candidates, "ltf_counter_story")
        assert ls is not None
        assert ls.debug_facts["ltf_counter_bos_confirmed"] is False


# ---------------------------------------------------------------------------
# HTF P/D objective gate
# ---------------------------------------------------------------------------

class TestHtfPdObjective:
    def test_fires_when_bar_touches_range_high(self):
        ec = EvidenceCompiler()
        fused = _fused(htf_range_high=50800.0)
        bars = [
            {"time": "08:00", "open": 50600, "high": 50700, "low": 50200, "close": 50650},
            {"time": "12:00", "open": 50700, "high": 50850, "low": 50300, "close": 50780},  # high touches 50800
        ]
        candidates = ec.update(fused, higher_bars=bars)
        obj = _candidate(candidates, "htf_pd_objective")
        assert obj is not None
        assert obj.debug_facts["phase_a_finale_touched"] is True
        assert obj.debug_facts["phase_a_finale_closed_beyond"] is False  # close 50780 < 50800

    def test_fires_closed_beyond_when_close_exceeds(self):
        ec = EvidenceCompiler()
        fused = _fused(htf_range_high=50800.0)
        bars = [
            {"time": "08:00", "open": 50600, "high": 50700, "low": 50200, "close": 50650},
            {"time": "12:00", "open": 50700, "high": 50900, "low": 50300, "close": 50820},
        ]
        candidates = ec.update(fused, higher_bars=bars)
        obj = _candidate(candidates, "htf_pd_objective")
        assert obj is not None
        assert obj.debug_facts["phase_a_finale_closed_beyond"] is True

    def test_absent_when_bar_does_not_touch_objective(self):
        ec = EvidenceCompiler()
        fused = _fused(htf_range_high=51000.0)
        candidates = ec.update(fused, higher_bars=_htf_bars(last_high=50900))
        obj = _candidate(candidates, "htf_pd_objective")
        assert obj is None


# ---------------------------------------------------------------------------
# B-initiation chain
# ---------------------------------------------------------------------------

class TestBInitiationChain:
    def _liquidity_with_source_grab(self, direction: str = "long") -> dict:
        if direction == "long":
            return {
                "htf_itr_grab_reclaim_ready": True,
                "htf_itr_grab_reclaim_direction": "bullish",
                "htf_itr_grab_reclaim_source": "htf_itr_low",
                "htf_itr_grab_reclaim_pool_id": "pool-src-1",
                "htf_itr_grab_reclaim_level": 48500.0,
                "htf_itr_grab_reclaim_confirmed_at": "2025-01-01T10:00:00",
            }
        return {
            "htf_itr_grab_reclaim_ready": True,
            "htf_itr_grab_reclaim_direction": "bearish",
            "htf_itr_grab_reclaim_source": "htf_itr_high",
            "htf_itr_grab_reclaim_pool_id": "pool-src-1",
            "htf_itr_grab_reclaim_level": 51500.0,
        }

    def _liquidity_with_opposite_grab(self) -> dict:
        return {
            "htf_itr_grab_reclaim_ready": True,
            "htf_itr_grab_reclaim_direction": "bearish",
            "htf_itr_grab_reclaim_source": "htf_itr_high",
            "htf_itr_grab_reclaim_pool_id": "pool-opp-1",
            "htf_itr_grab_reclaim_level": 51500.0,
        }

    def test_absent_before_step_1(self):
        ec = EvidenceCompiler()
        fused = _fused(liquidity={})
        candidates = ec.update(fused, higher_bars=_htf_bars())
        b = _candidate(candidates, "htf_b_initiation")
        assert b is None

    def test_collecting_after_step_1_source_grab(self):
        ec = EvidenceCompiler()
        fused = _fused(liquidity=self._liquidity_with_source_grab())
        candidates = ec.update(fused, higher_bars=_htf_bars())
        b = _candidate(candidates, "htf_b_initiation")
        assert b is not None
        assert b.status == "collecting"
        assert b.debug_facts["source_itr_grab_seen"] is True
        assert b.debug_facts["opposite_itr_grab_seen"] is False

    def test_collecting_after_step_2_opposite_grab(self):
        ec = EvidenceCompiler()
        # Step 1
        ec.update(_fused(liquidity=self._liquidity_with_source_grab()), higher_bars=_htf_bars())
        # Step 2
        candidates = ec.update(_fused(liquidity=self._liquidity_with_opposite_grab()), higher_bars=_htf_bars())
        b = _candidate(candidates, "htf_b_initiation")
        assert b is not None
        assert b.debug_facts["source_itr_grab_seen"] is True
        assert b.debug_facts["opposite_itr_grab_seen"] is True
        assert b.status == "collecting"  # still collecting — no decision zone yet

    def test_ready_after_step_3_decision_zone(self):
        ec = EvidenceCompiler()
        # Step 1
        ec.update(_fused(liquidity=self._liquidity_with_source_grab()), higher_bars=_htf_bars())
        # Step 2
        ec.update(_fused(liquidity=self._liquidity_with_opposite_grab()), higher_bars=_htf_bars())
        # Step 3 — HTF supply zone entered (counter to bullish)
        fused3 = _fused(
            htf_zones=[{"zone_id": "htf-s1", "direction": "supply", "timeframe": "4H", "in_zone": True}]
        )
        candidates = ec.update(fused3, higher_bars=_htf_bars())
        b = _candidate(candidates, "htf_b_initiation")
        assert b is not None
        assert b.status == "ready"
        assert "htf-s1" in b.debug_facts["decision_zone_ids"]

    def test_candidate_id_stable_across_bars(self):
        ec = EvidenceCompiler()
        # Step 1
        c1 = ec.update(_fused(liquidity=self._liquidity_with_source_grab()), higher_bars=_htf_bars())
        b1 = _candidate(c1, "htf_b_initiation")
        # Step 2
        c2 = ec.update(_fused(liquidity=self._liquidity_with_opposite_grab()), higher_bars=_htf_bars())
        b2 = _candidate(c2, "htf_b_initiation")
        assert b1 is not None
        assert b2 is not None
        assert b1.candidate_id == b2.candidate_id  # stable ID across bars

    def test_resets_on_epoch_change(self):
        ec = EvidenceCompiler()
        # Step 1
        ec.update(_fused(liquidity=self._liquidity_with_source_grab()), higher_bars=_htf_bars())
        assert ec._b_init.source_itr_grab is not None

        # New epoch — change active P/D phase start
        fused_new_epoch = _fused(liquidity={})
        fused_new_epoch["higher_context_snapshot"]["structure"]["phase_start_ts"] = "2025-02-01T00:00:00"
        ec.update(fused_new_epoch, higher_bars=_htf_bars())
        assert ec._b_init.source_itr_grab is None  # chain reset


# ---------------------------------------------------------------------------
# Epoch boundary detection
# ---------------------------------------------------------------------------

class TestEpochBoundary:
    def test_epoch_id_set_on_first_update(self):
        ec = EvidenceCompiler()
        fused = _fused()
        ec.update(fused, higher_bars=_htf_bars())
        assert ec.htf_pd_epoch_id is not None

    def test_epoch_change_resets_e_extreme(self):
        ec = EvidenceCompiler()
        fused1 = _fused()
        ec.update(fused1, higher_bars=_htf_bars(last_high=50900))
        assert ec.active_phase_e_extreme_price is not None

        # New epoch
        fused2 = _fused()
        fused2["higher_context_snapshot"]["structure"]["last_sc"]["eventTimestamp"] = "2025-03-01T00:00:00"
        ec.update(fused2, higher_bars=_htf_bars())
        assert ec.active_phase_e_extreme_price is None or ec.active_phase_e_extreme_price == 51000.0


# ---------------------------------------------------------------------------
# Serialisation round-trip
# ---------------------------------------------------------------------------

class TestSerialisation:
    def test_all_candidates_serialize_without_error(self):
        ec = EvidenceCompiler()
        fused = _fused(
            ltf_bias="bearish",
            ltf_zones=[{"zone_id": "ltf-s1", "direction": "supply", "timeframe": "15m", "in_zone": False, "created_at": "2025-01-01T10:00:00"}],
            htf_zones=[{"zone_id": "htf-s1", "direction": "supply", "timeframe": "4H", "in_zone": True}],
        )
        candidates = ec.update(fused, higher_bars=_htf_bars())
        for c in candidates:
            d = c.to_dict()
            # All expected keys present
            for key in ("candidate_id", "pattern", "status", "direction", "timeframe",
                        "evidence_refs", "source_object_refs", "location_context",
                        "blocked_reasons", "first_seen_at", "ready_at", "debug_facts"):
                assert key in d, f"Missing key {key!r} in {c.pattern}"
