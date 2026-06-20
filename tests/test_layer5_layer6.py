from __future__ import annotations

from ultrab.entry.layer5 import (
    CounterEntryEvidence,
    EntryIntent,
    EntryPermissionEngine,
    SkipIntent,
    TriggerEvidence,
)
from ultrab.entry.layer6 import TradeAnalyzer
from ultrab.entry.run_layer5_backtest import summarize_results

_SYM_GEO = {"EURUSD": {"sl_buffer_pips": 2.0, "min_sl_pips": 15.0, "max_sl_pips": 25.0}}


def _engine() -> EntryPermissionEngine:
    return EntryPermissionEngine(symbol_geometry=_SYM_GEO)


def _d_watch_bar(*, close: float = 1.2000, range_high: float = 1.2018) -> dict:
    """D.watch bar: iChoCh seen — D.watch_pathSA fires immediately at bar close.
    SL = watch_range_extreme + 2 pips; max_sl_pips gate rejects fast flush.
    For range_high=1.2018 and close=1.2000: sl=1.2020, risk=20 pips, RR≥1.75.
    For range_high=1.2003: sl=1.2015 (min floor), risk=15 pips.
    For close=1.1970: risk=50 pips > 25 → SkipIntent (stale).
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
                    "ltf_counter_choch_seen": True,
                    "ltf_counter_choch_event_at": "2026-01-01T10:20:00+00:00",
                    "ltf_counter_choch_event_id": "ichoch-1",
                    "ltf_counter_choch_level": 1.1992,
                    "ltf_counter_choch_source_level_id": "itr-high-1",
                    "ltf_counter_choch_source_store": "structure_isc",
                    "ltf_counter_isb_seen": False,
                    "ltf_counter_sb_seen": False,
                },
            },
        ],
    }



def _d_watch_zone_bar(*, close: float = 1.2000, zone_low: float = 1.2003) -> dict:
    """D.watch zone-context bar: Path B fires from fresh iChoCh.
    prior_direction=long -> trade=short.
    supply zone proximal low defaults to 1.2003, plus 2 pips = 1.2005.
    """
    return {
        "symbol": "EURUSD",
        "timeframe": "15M",
        "lower_tf": "15M",
        "higher_tf": "4H",
        "cursor_time": "2026-01-01T10:20:00+00:00",
        "lower_bars": [{"time": "2026-01-01T10:20:00+00:00", "open": 1.1995, "high": 1.2005, "low": 1.1990, "close": close}],
        "lower_structure": {"range_high": 1.2005, "range_low": 1.1985},
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


def _d_watch_no_internal_bar(*, range_high: float = 1.2018) -> dict:
    bar = _d_watch_bar(range_high=range_high)
    bar["evidence_candidates"] = [
        {
            "pattern": "ltf_counter_choch",
            "status": "collecting",
            "direction": "long",
            "debug_facts": {
                "ltf_counter_choch_seen": False,
                "ltf_counter_isb_seen": False,
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
    assert intent.trigger.trigger_path == "D.watch_pathSA"
    assert intent.trigger.trigger_kind == "counter_ichoch_immediate"
    assert round(intent.stop_loss, 4) == 1.2020   # 1.2018 + 2 pips
    assert round(intent.risk_pips, 1) == 20.0
    assert round(intent.target_price, 4) == 1.1940  # pd_midpoint
    assert intent.target_r >= 1.75


def test_d_watch_ichoch_floor_widens_compressed_sl():
    engine = _engine()

    intent = engine.evaluate(_d_watch_bar(range_high=1.2003))

    assert isinstance(intent, EntryIntent)
    assert intent.trigger.trigger_path == "D.watch_pathSA"
    assert round(intent.stop_loss, 4) == 1.2015  # min_sl floor: 1.2000 + 15 pips
    assert round(intent.risk_pips, 1) == 15.0


def test_path_c2_fires_on_plain_d_to_c_transition_without_internal_pressure():
    engine = _engine()
    assert engine.evaluate(_d_watch_no_internal_bar()) is None

    intent = engine.evaluate(_c_pullback_transition_bar(pressure_seen=False))

    assert isinstance(intent, EntryIntent)
    assert intent.phase == "D"
    assert intent.phase_sub_status == "pullback"
    assert intent.trigger.trigger_path == "D.watch_pathC2"
    assert intent.trigger.trigger_kind == "d_watch_mss_plain"
    assert intent.trigger.event_id == "OF:transition:1"
    assert round(intent.risk_pips, 1) == 20.0



def test_path_c_ignores_persistent_c_hold_bar_without_transition_marker():
    engine = _engine()
    assert engine.evaluate(_d_watch_no_internal_bar()) is None

    result = engine.evaluate(_c_pullback_hold_bar())

    assert result is None


def test_path_c_rejects_invalidated_internal_pressure_transition():
    engine = _engine()
    assert engine.evaluate(_d_watch_no_internal_bar()) is None

    result = engine.evaluate(
        _c_pullback_transition_bar(
            pressure_seen=False,
            pressure_class="contradicted",
            pressure_event_ids=["SC05:isb-1"],
            pressure_first_at="2026-01-01T10:05:00+00:00",
            pressure_last_at="2026-01-01T10:05:00+00:00",
            pressure_invalidated=True,
        )
    )

    assert result is None


def test_path_b_floor_widens_compressed_zone_proximal_sl():
    engine = _engine()

    intent = engine.evaluate(_d_watch_zone_bar())

    assert isinstance(intent, EntryIntent)
    assert intent.evidence.evidence_kind == "htf_sd_zone"
    assert intent.trigger.trigger_path == "D.watch_pathB"
    assert round(intent.stop_loss, 4) == 1.2015
    assert round(intent.risk_pips, 1) == 15.0


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
        trigger_path="D.watch_pathSA",
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
        phase_override="D",
    )

    assert isinstance(intent, EntryIntent)
    assert round(intent.risk_pips, 1) == 5.0
    assert intent.skip_reason is None


def test_phase_d_late_entry_is_skipped_and_marked_stale_once():
    engine = _engine()
    # close at 1.1970 → SL = 1.2020 (watch_extreme 1.2018 + 2 pips), risk = 50 pips > 25 → skip
    skip = engine.evaluate(_d_watch_bar(close=1.1970))
    # same opportunity_key (same choch event_id) → stale → None
    repeat = engine.evaluate(_d_watch_bar(close=1.1970))

    assert isinstance(skip, SkipIntent)
    assert skip.skip_reason == "late_entry_risk_too_wide"
    assert skip.stale_marked is True
    assert repeat is None


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
            "trigger_D_watch_pathSA": 2,
            "trigger_D_watch_pathB": 0,
            "trigger_D_watch_pathC2": 0,
            "trigger_D_watch_pathB_express": 0,
            "trigger_D_watch_pathC2_express": 0,
            "late_entry_risk_too_wide": 1,
        }
    ]


def _d_watch_express_bar(
    *,
    close: float = 1.2000,
    express_zone_proximal: float | None = 1.2003,
) -> dict:
    """Express D.watch bar: entry_express=True, iChoCh fired — B_express path.
    prior_direction=long → trade=short.
    express_zone_proximal=1.2003 → sl_raw=1.2003+0.0002=1.2005 (matches min_sl floor).
    express_zone_proximal=None → falls back to watch_range_extreme."""
    bar = _d_watch_bar(close=close, range_high=1.2018)
    bar["hypothesis"]["debug_facts"]["phase_d_shadow_entry_express"] = True
    bar["hypothesis"]["debug_facts"]["phase_d_shadow_express_zone_proximal"] = express_zone_proximal
    return bar


def _c_pullback_express_transition_bar(
    *,
    express_zone_proximal: float | None = 1.2008,
) -> dict:
    """C.pullback transition bar from express D.watch — C2_express path.
    express_zone_proximal=1.2008 → sl_raw=1.2008+0.0002=1.2010, risk=10 pips → floor → 15 pips.
    express_zone_proximal=None → falls back to watch_range_extreme (1.2018 → sl=1.2020, risk=20 pips)."""
    bar = _c_pullback_transition_bar(pressure_seen=False)
    bar["hypothesis"]["debug_facts"]["phase_d_shadow_entry_express"] = True
    bar["hypothesis"]["debug_facts"]["phase_d_shadow_express_zone_proximal"] = express_zone_proximal
    return bar


def test_path_b_express_fires_when_entry_express_true():
    engine = _engine()

    intent = engine.evaluate(_d_watch_express_bar(express_zone_proximal=1.2003))

    assert isinstance(intent, EntryIntent)
    assert intent.trigger.trigger_path == "D.watch_pathB_express"
    assert intent.trigger.trigger_kind == "counter_ichoch"
    assert intent.evidence.evidence_kind == "htf_sd_zone_express"
    assert intent.evidence.source_store == "phase_d_shadow"
    assert round(intent.stop_loss, 4) == 1.2015  # min_sl floor: 1.2000 + 15 pips
    assert round(intent.risk_pips, 1) == 15.0


def test_path_b_express_falls_back_to_watch_range_extreme_when_zone_proximal_none():
    engine = _engine()

    intent = engine.evaluate(_d_watch_express_bar(express_zone_proximal=None))

    assert isinstance(intent, EntryIntent)
    assert intent.trigger.trigger_path == "D.watch_pathB_express"
    # fallback: watch_range_extreme=1.2018 → sl=1.2018+0.0002=1.2020, risk=20 pips
    assert round(intent.stop_loss, 4) == 1.2020
    assert round(intent.risk_pips, 1) == 20.0


def test_path_c2_express_fires_on_express_d_to_c_transition():
    engine = _engine()
    assert engine.evaluate(_d_watch_no_internal_bar()) is None

    intent = engine.evaluate(_c_pullback_express_transition_bar(express_zone_proximal=None))

    assert isinstance(intent, EntryIntent)
    assert intent.trigger.trigger_path == "D.watch_pathC2_express"
    assert intent.trigger.trigger_kind == "d_watch_mss_plain"
    # fallback to watch_range_extreme=1.2018 → sl=1.2020, risk=20 pips
    assert round(intent.stop_loss, 4) == 1.2020
    assert round(intent.risk_pips, 1) == 20.0
