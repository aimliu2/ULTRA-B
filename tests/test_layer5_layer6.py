from __future__ import annotations

from ultrab.entry.layer5 import (
    CounterEntryEvidence,
    EntryIntent,
    EntryPermissionEngine,
    SkipIntent,
    TriggerEvidence,
)
from ultrab.entry.layer6 import TradeAnalyzer
from ultrab.entry.regime_tags import regime_tags
from ultrab.entry.run_layer5_backtest import summarize_results

_SYM_GEO = {"EURUSD": {"sl_buffer_pips": 2.0, "min_sl_pips": 15.0, "max_sl_pips": 25.0}}


def _engine() -> EntryPermissionEngine:
    return EntryPermissionEngine(symbol_geometry=_SYM_GEO)


def _d_watch_bar(*, close: float = 1.2000, range_high: float = 1.2018) -> dict:
    """D.watch bar: internal counter iChoCh -> internal pro iSB sequence.
    SL = watch_range_extreme + 2 pips; max_sl_pips gate rejects fast flush.
    For range_high=1.2018 and close=1.2000: sl=1.2020, risk=20 pips, RR≥1.75.
    For range_high=1.2003: sl=1.2015 (min floor), risk=15 pips.
    For close=1.1970: risk=50 pips > 25 → SkipIntent (SL_too_wide, non-stale).
    """
    return {
        "symbol": "EURUSD",
        "timeframe": "15M",
        "lower_tf": "15M",
        "higher_tf": "4H",
        "cursor_time": "2026-01-01T10:20:00+00:00",
        "lower_bars": [{"time": "2026-01-01T10:20:00+00:00", "open": 1.1995, "high": 1.2005, "low": 1.1990, "close": close}],
        "lower_structure": {"range_high": range_high, "range_low": 1.1985},
        "higher_structure": {"pd_midpoint": 1.1940, "range_high": 1.2100, "range_low": 1.1780},
        "hypothesis": {
            "hypothesis_id": "hyp-1",
            "phase": "D",
            "phase_sub_status": "watch",
            "direction": "none",
            "debug_facts": {
                "htf_pd_epoch_id": "epoch-1",
                "phase_episode_id": "episode-1",
                "prior_phase_e_direction": "long",
                "active_phase_e_direction": "long",
                "phase_d_node": "D.watch",
                "phase_d_shadow_node": "D.watch",
                "phase_d_shadow_watch_entered_at": "2026-01-01T10:00:00+00:00",
                "phase_d_shadow_watch_range_extreme": range_high,
            },
        },
        "evidence_candidates": [
            {
                "pattern": "ltf_counter_choch",
                "status": "ready",
                "direction": "long",
                "debug_facts": {
                    "ltf_counter_ichoch_isb_sequence_seen": True,
                    "ltf_counter_sequence_trade_direction": "short",
                    "ltf_counter_sequence_ichoch_event_at": "2026-01-01T10:05:00+00:00",
                    "ltf_counter_sequence_isb_event_at": "2026-01-01T10:20:00+00:00",
                    "ltf_counter_sequence_isb_event_id": "isb-1",
                    "ltf_counter_sequence_isb_level": 1.1992,
                    "ltf_counter_sequence_isb_source_level_id": "isb-level-1",
                    "ltf_counter_sequence_source_store": "internal_structure_sequence",
                },
            },
        ],
    }



def _d_watch_zone_bar(
    *,
    close: float = 1.2000,
    zone_low: float = 1.1990,
    itr_high: float | None = 1.2008,
    itr_confirmed_at: str = "2026-01-01T10:15:00+00:00",
) -> dict:
    """D.watch supply-zone context bar: Path B fires after ITR arming + fresh iChoCh.
    prior_direction=long -> trade=short.
    SL = supply zone high + 2 pips, then min floor if compressed.
    """
    lower_structure = {"range_high": 1.2005, "range_low": 1.1985}
    if itr_high is not None:
        lower_structure["latest_itr_high"] = {
            "level_id": "PE03:itr-high-1",
            "event_code": "PE03",
            "tier": "itr",
            "side": "high",
            "price": itr_high,
            "pivot_time": "2026-01-01T10:10:00+00:00",
            "confirmed_at": itr_confirmed_at,
            "relation": None,
        }
    return {
        "symbol": "EURUSD",
        "timeframe": "15M",
        "lower_tf": "15M",
        "higher_tf": "4H",
        "cursor_time": "2026-01-01T10:20:00+00:00",
        "lower_bars": [{"time": "2026-01-01T10:20:00+00:00", "open": 1.1995, "high": 1.2005, "low": 1.1990, "close": close}],
        "lower_structure": lower_structure,
        "higher_structure": {"pd_midpoint": 1.1940, "range_high": 1.2100, "range_low": 1.1780},
        "zones": [
            {
                "zone_id": "supply-1",
                "direction": "supply",
                "timeframe": "4H",
                "high": 1.2010,
                "low": zone_low,
            }
        ],
        "hypothesis": {
            "hypothesis_id": "hyp-1",
            "phase": "D",
            "phase_sub_status": "watch",
            "direction": "none",
            "debug_facts": {
                "htf_pd_epoch_id": "epoch-1",
                "phase_episode_id": "episode-1",
                "prior_phase_e_direction": "long",
                "active_phase_e_direction": "long",
                "phase_d_node": "D.watch",
                "phase_d_shadow_node": "D.watch",
                "phase_d_shadow_watch_entered_at": "2026-01-01T10:00:00+00:00",
                "phase_d_shadow_htf_zone_seen": True,
                "phase_e_shadow_htf_reaction_seen": True,
            },
        },
        "evidence_candidates": [
            {
                "pattern": "ltf_counter_choch",
                "status": "ready",
                "direction": "long",
                "debug_facts": {
                    "ltf_counter_choch_seen": True,
                    "ltf_counter_choch_event_at": "2026-01-01T10:20:00+00:00",
                    "ltf_counter_choch_event_id": "ichoch-1",
                    "ltf_counter_choch_level": 1.1992,
                    "ltf_counter_choch_source_level_id": "itr-high-1",
                    "ltf_counter_choch_source_store": "structure_isc",
                },
            },
            {
                "pattern": "htf_counter_reaction",
                "status": "ready",
                "direction": "long",
                "debug_facts": {
                    "htf_opposing_sd_tapped": True,
                    "htf_opposing_sd_reaction": True,
                    "htf_opposing_sd_tapped_at": "2026-01-01T10:15:00+00:00",
                    "htf_opposing_sd_zone_ids": ["supply-1"],
                },
            },
        ],
    }


def _d_watch_demand_zone_bar(
    *,
    close: float = 1.2000,
    zone_high: float = 1.2010,
    itr_low: float | None = 1.1992,
    itr_confirmed_at: str = "2026-01-01T10:15:00+00:00",
) -> dict:
    """D.watch demand-zone context bar: Path B mirror for long trades."""
    bar = _d_watch_zone_bar(close=close)
    bar["higher_structure"]["pd_midpoint"] = 1.2060
    bar["zones"] = [
        {
            "zone_id": "demand-1",
            "direction": "demand",
            "timeframe": "4H",
            "high": zone_high,
            "low": 1.1990,
        }
    ]
    lower_structure = {"range_high": 1.2015, "range_low": 1.1990}
    if itr_low is not None:
        lower_structure["latest_itr_low"] = {
            "level_id": "PE04:itr-low-1",
            "event_code": "PE04",
            "tier": "itr",
            "side": "low",
            "price": itr_low,
            "pivot_time": "2026-01-01T10:10:00+00:00",
            "confirmed_at": itr_confirmed_at,
            "relation": None,
        }
    bar["lower_structure"] = lower_structure
    debug = bar["hypothesis"]["debug_facts"]
    debug["prior_phase_e_direction"] = "short"
    debug["active_phase_e_direction"] = "short"
    for candidate in bar["evidence_candidates"]:
        candidate["direction"] = "short"
        if candidate["pattern"] == "ltf_counter_choch":
            candidate["debug_facts"]["ltf_counter_choch_level"] = 1.2008
            candidate["debug_facts"]["ltf_counter_choch_source_level_id"] = "itr-low-1"
        if candidate["pattern"] == "htf_counter_reaction":
            candidate["debug_facts"]["htf_opposing_sd_zone_ids"] = ["demand-1"]
    return bar


def _d_watch_no_internal_bar(*, range_high: float = 1.2018) -> dict:
    bar = _d_watch_bar(range_high=range_high)
    bar["evidence_candidates"] = [
        {
            "pattern": "ltf_counter_choch",
            "status": "collecting",
            "direction": "long",
            "debug_facts": {
                "ltf_counter_choch_seen": False,
                "ltf_counter_ichoch_isb_sequence_seen": False,
                "ltf_counter_internal_pressure_seen": False,
                "ltf_counter_internal_pressure_class": "none",
            },
        },
    ]
    return bar


def _c_pullback_transition_bar(
    *,
    pressure_seen: bool,
    pressure_class: str = "none",
    pressure_event_ids: list[str] | None = None,
    pressure_first_at: str | None = None,
    pressure_last_at: str | None = None,
    pressure_invalidated: bool = False,
) -> dict:
    return {
        "symbol": "EURUSD",
        "timeframe": "15M",
        "lower_tf": "15M",
        "higher_tf": "4H",
        "cursor_time": "2026-01-01T10:45:00+00:00",
        "lower_bars": [{"time": "2026-01-01T10:45:00+00:00", "open": 1.2002, "high": 1.2008, "low": 1.1992, "close": 1.2000}],
        "lower_structure": {"range_high": 1.2016, "range_low": 1.1982},
        "higher_structure": {"pd_midpoint": 1.1940, "range_high": 1.2100, "range_low": 1.1780},
        "hypothesis": {
            "hypothesis_id": "hyp-1",
            "phase": "C",
            "phase_sub_status": "pullback",
            "direction": "short",
            "debug_facts": {
                "htf_pd_epoch_id": "epoch-1",
                "phase_episode_id": "episode-c",
                "prior_phase_e_direction": "long",
                "active_phase_e_direction": "long",
                "phase_c_origin_node": "D.watch_mss",
                "phase_c_entry_transition_at": "2026-01-01T10:45:00+00:00",
                "phase_c_entry_transition_event_id": "OF:transition:1",
                "phase_c_entry_transition_origin_node": "D.watch_mss",
                "phase_c_entry_transition_prior_phase": "D.watch",
                "phase_c_entry_transition_prior_direction": "long",
                "phase_c_entry_transition_trade_direction": "short",
                "phase_c_entry_transition_internal_pressure_seen": pressure_seen,
                "phase_c_entry_transition_internal_pressure_class": pressure_class,
                "phase_c_entry_transition_internal_pressure_event_ids": pressure_event_ids or [],
                "phase_c_entry_transition_internal_pressure_first_at": pressure_first_at,
                "phase_c_entry_transition_internal_pressure_last_at": pressure_last_at,
                "phase_c_entry_transition_internal_pressure_invalidated": pressure_invalidated,
                "phase_c_entry_transition_internal_pressure_invalid_reason": (
                    "final_internal_contradiction" if pressure_invalidated else None
                ),
                "phase_d_shadow_watch_range_extreme": 1.2018,
            },
        },
        "evidence_candidates": [],
    }


def _c_pullback_hold_bar() -> dict:
    bar = _c_pullback_transition_bar(pressure_seen=False)
    debug = bar["hypothesis"]["debug_facts"]
    debug.pop("phase_c_entry_transition_at")
    debug.pop("phase_c_entry_transition_event_id")
    debug.pop("phase_c_entry_transition_origin_node")
    debug["phase_c_shadow_origin_node"] = "D.watch_mss"
    debug["phase_c_shadow_entered_at"] = "2026-01-01T10:45:00+00:00"
    bar["cursor_time"] = "2026-01-01T11:00:00+00:00"
    bar["lower_bars"][-1]["time"] = "2026-01-01T11:00:00+00:00"
    return bar


def test_phase_d_lax_emits_entry_intent_from_d_watch_ichoch():
    engine = _engine()

    intent = engine.evaluate(_d_watch_bar())

    assert isinstance(intent, EntryIntent)
    assert intent.phase == "D"
    assert intent.direction == "short"
    assert intent.evidence.evidence_kind == "watch_extreme"
    assert intent.evidence.source_store == "phase_d_shadow"
    assert intent.trigger.trigger_path == "D.watch_pathA"
    assert intent.trigger.trigger_kind == "counter_ichoch_immediate"
    assert round(intent.stop_loss, 4) == 1.2020   # 1.2018 + 2 pips
    assert round(intent.risk_pips, 1) == 20.0
    assert round(intent.target_price, 4) == 1.1940  # pd_midpoint
    assert intent.target_r >= 1.75


def test_d_watch_ichoch_floor_widens_compressed_sl():
    engine = _engine()

    intent = engine.evaluate(_d_watch_bar(range_high=1.2003))

    assert isinstance(intent, EntryIntent)
    assert intent.trigger.trigger_path == "D.watch_pathA"
    assert round(intent.stop_loss, 4) == 1.2015  # min_sl floor: 1.2000 + 15 pips
    assert round(intent.risk_pips, 1) == 15.0


def test_d_watch_zone_context_does_not_create_separate_path():
    engine = _engine()
    bar = _d_watch_bar()
    debug = bar["hypothesis"]["debug_facts"]
    debug["phase_d_shadow_htf_zone_seen"] = True
    debug["phase_e_shadow_htf_reaction_seen"] = True
    bar["zones"] = [
        {
            "zone_id": "supply-1",
            "direction": "supply",
            "timeframe": "4H",
            "high": 1.2010,
            "low": 1.1990,
        }
    ]

    intent = engine.evaluate(bar)

    assert isinstance(intent, EntryIntent)
    assert intent.evidence.evidence_kind == "watch_extreme"
    assert intent.trigger.trigger_path == "D.watch_pathA"


def test_regime_tags_mark_entry_bar_inside_htf_sd_zone_and_itr_context():
    engine = _engine()
    bar = _d_watch_bar()
    bar["lower_structure"]["latest_itr_high"] = {
        "price": 1.2008,
        "confirmed_at": "2026-01-01T10:15:00+00:00",
    }
    bar["zones"] = [
        {
            "zone_id": "supply-1",
            "direction": "supply",
            "timeframe": "4H",
            "high": 1.2010,
            "low": 1.1990,
        }
    ]
    debug = bar["hypothesis"]["debug_facts"]
    debug["phase_d_shadow_htf_zone_seen"] = True
    debug["phase_d_shadow_htf_zone_seen_id"] = "supply-1"
    debug["phase_e_shadow_htf_reaction_seen"] = True

    intent = engine.evaluate(bar)
    assert isinstance(intent, EntryIntent)
    tags = regime_tags(bar, intent)

    assert tags["htf_zone_context"] is True
    assert tags["at_htf_sd_zone"] is True
    assert tags["entry_bar_inside_htf_sd_zone"] is True
    assert tags["htf_sd_zone_id"] == "supply-1"
    assert tags["htf_sd_zone_direction"] == "supply"
    assert tags["htf_sd_zone_touch_timing"] == "at_entry"
    assert tags["itr_inside_htf_sd_zone"] is True
    assert tags["bars_since_itr_confirmed"] == 1
    assert tags["entry_session"] == "london"


def test_regime_tags_leave_non_zone_sa_trade_unmarked():
    engine = _engine()
    bar = _d_watch_bar()

    intent = engine.evaluate(bar)
    assert isinstance(intent, EntryIntent)
    tags = regime_tags(bar, intent)

    assert tags["htf_zone_context"] is False
    assert tags["at_htf_sd_zone"] is False
    assert tags["entry_bar_inside_htf_sd_zone"] is False
    assert tags["htf_sd_zone_id"] == ""
    assert tags["itr_inside_htf_sd_zone"] is False

def test_make_intent_no_longer_emits_risk_too_tight_skip():
    engine = _engine()
    snapshot = _d_watch_bar()
    evidence = CounterEntryEvidence(
        evidence_kind="watch_extreme",
        evidence_id="tight-evidence",
        timeframe=None,
        direction="short",
        presented_at="2026-01-01T10:20:00+00:00",
        source_store="phase_d_shadow",
        level=1.2003,
        sl_side="above",
        sl_price_raw=1.2003,
        sl_buffer_pips=2.0,
        sl_price=1.2005,
    )
    trigger = TriggerEvidence(
        trigger_kind="counter_ichoch_immediate",
        trigger_path="D.watch_pathA",
        event_at="2026-01-01T10:20:00+00:00",
        event_id="tight-trigger",
        level=1.1992,
        source_level_id=None,
        source_store="structure_isc",
    )

    intent = engine._make_intent(  # noqa: SLF001 - targeted regression for removed private branch
        snapshot,
        "epoch-tight",
        "episode-tight",
        "short",
        1.2005,
        evidence,
        trigger,
        0.0001,
        15.0,
        25.0,
        tp_price=1.1940,
        phase_override="D",
    )

    assert isinstance(intent, EntryIntent)
    assert round(intent.risk_pips, 1) == 5.0
    assert intent.skip_reason is None


def test_phase_d_sl_too_wide_is_non_stale_and_retryable():
    engine = _engine()
    # close at 1.1970 → SL = 1.2020 (watch_extreme 1.2018 + 2 pips), risk = 50 pips > 25 → skip
    skip = engine.evaluate(_d_watch_bar(close=1.1970))
    # Same opportunity_key is not stale-marked; it may retry until trigger age-out.
    repeat = engine.evaluate(_d_watch_bar(close=1.1970))

    assert isinstance(skip, SkipIntent)
    assert skip.skip_reason == "SL_too_wide"
    assert skip.stale_marked is False
    assert isinstance(repeat, SkipIntent)
    assert repeat.skip_reason == "SL_too_wide"


def test_layer6_uses_loss_first_when_bar_hits_stop_and_target():
    engine = _engine()
    analyzer = TradeAnalyzer(max_hold_bars=32)
    intent = engine.evaluate(_d_watch_bar())
    assert isinstance(intent, EntryIntent)
    trade = analyzer.open_trade(intent)

    # high=1.2025 hits SL (1.2020) for short; low=1.1930 also hits TP (1.1940)
    # SL is evaluated before TP → loss
    result = analyzer.advance(
        trade,
        {
            "time": "2026-01-01T10:45:00+00:00",
            "open": 1.2000,
            "high": 1.2025,
            "low": 1.1930,
            "close": 1.1990,
        },
    )

    assert result is not None
    assert result.outcome == "loss"
    assert result.r_result == -1.0


def test_epoch_summary_counts_chances_outcomes_and_evidence_frequency():
    engine = _engine()
    analyzer = TradeAnalyzer(max_hold_bars=1)
    intent = engine.evaluate(_d_watch_bar())
    assert isinstance(intent, EntryIntent)
    trade = analyzer.open_trade(intent)
    # high=1.2025 hits SL (1.2020) → loss
    loss = analyzer.advance(
        trade,
        {
            "time": "2026-01-01T10:45:00+00:00",
            "open": 1.2000,
            "high": 1.2025,
            "low": 1.1990,
            "close": 1.2015,
        },
    )
    assert loss is not None
    # Separate engine instance — budget not shared; close=1.1970 → 50 pips → skip
    late = _engine().evaluate(_d_watch_bar(close=1.1970))
    assert isinstance(late, SkipIntent)
    skipped = analyzer.result_from_skip(late)

    summary = summarize_results([loss.to_row(), skipped.to_row()])

    assert summary == [
        {
            "epoch_id": "epoch-1",
            "d_watch_bars": 0,
            "d_watch_bars_with_evidence": 0,
            "d_watch_bars_with_trigger": 0,
            "d_watch_bars_with_evidence_and_trigger": 0,
            "entry_chances": 2,
            "accepted_entries": 1,
            "skipped_entries": 1,
            "wins": 0,
            "losses": 1,
            "timeouts": 0,
            "win_rate_pct": 0.0,
            "avg_r": -1.0,
            "evidence_liquidity_grab": 0,
            "evidence_ltf_sd_zone": 0,
            "evidence_htf_sd_zone": 0,
            "evidence_watch_extreme": 2,
            "trigger_D_watch_pathA": 2,
            "SL_too_wide": 1,
        }
    ]
