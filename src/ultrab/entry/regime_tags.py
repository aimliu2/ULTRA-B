from __future__ import annotations

from datetime import datetime
from typing import Any


REGIME_TAG_COLUMNS = [
    "htf_zone_context",
    "at_htf_sd_zone",
    "htf_sd_zone_id",
    "htf_sd_zone_direction",
    "htf_sd_zone_touch_timing",
    "htf_pd_liquidity_grab_seen_before_entry",
    "liquidity_grab_at_pd_extreme",
    "bars_since_liquidity_grab",
    "d_watch_duration_bars",
    "bars_since_htf_sd_touch",
    "entry_bar_inside_htf_sd_zone",
    "itr_inside_htf_sd_zone",
    "bars_since_itr_confirmed",
    "htf_pd_range_bucket",
    "entry_session",
    # Phase B analysis tags (populated only when hypothesis.phase == "B")
    "b_watch_origin_node",
    "b_watch_at_extreme_entry",
    "b_watch_htf_sd_zone_tapped",
]


def regime_tags(snapshot: dict[str, Any], decision: Any | None = None) -> dict[str, Any]:
    """Analysis-only regime tags for trade filtering and later policy tightening."""
    hypothesis = snapshot.get("hypothesis") or {}
    debug = hypothesis.get("debug_facts") or {}
    prior_direction = (
        debug.get("prior_phase_e_direction")
        or debug.get("active_phase_e_direction")
        or hypothesis.get("direction")
    )
    trade_direction = getattr(decision, "direction", None) or _opposite(prior_direction)
    zone_direction = _htf_zone_direction(trade_direction, prior_direction)
    zone = _selected_htf_zone(snapshot, debug, zone_direction)
    zone_id = str(zone.get("zone_id") or "") if zone else _debug_zone_id(debug)
    zone_direction_value = str(zone.get("direction") if zone else (zone_direction or ""))

    inside_zone = bool(zone and _current_bar_overlaps_zone(snapshot, zone))
    htf_touch_at = _htf_touch_time(snapshot, debug, prior_direction)
    liquidity_at = _liquidity_grab_time(snapshot, prior_direction)
    itr_confirmed_at, itr_inside = _itr_context(snapshot, trade_direction, zone)

    phase = hypothesis.get("phase")
    b_tags = _phase_b_tags(debug) if phase == "B" else {"b_watch_origin_node": None, "b_watch_at_extreme_entry": None, "b_watch_htf_sd_zone_tapped": None}

    return {
        "htf_zone_context": bool(
            debug.get("phase_e_shadow_htf_reaction_seen")
            or debug.get("phase_d_shadow_htf_zone_seen")
        ),
        "at_htf_sd_zone": inside_zone,
        "htf_sd_zone_id": zone_id,
        "htf_sd_zone_direction": zone_direction_value,
        "htf_sd_zone_touch_timing": _htf_touch_timing(debug, inside_zone),
        "htf_pd_liquidity_grab_seen_before_entry": _htf_pd_liquidity_grab_seen(snapshot, prior_direction),
        "liquidity_grab_at_pd_extreme": _liquidity_grab_at_pd_extreme(snapshot, prior_direction),
        "bars_since_liquidity_grab": _bars_since(snapshot, liquidity_at),
        "d_watch_duration_bars": _bars_since(snapshot, debug.get("phase_d_shadow_watch_entered_at")),
        "bars_since_htf_sd_touch": _bars_since(snapshot, htf_touch_at),
        "entry_bar_inside_htf_sd_zone": inside_zone,
        "itr_inside_htf_sd_zone": itr_inside,
        "bars_since_itr_confirmed": _bars_since(snapshot, itr_confirmed_at),
        "htf_pd_range_bucket": _htf_pd_range_bucket(snapshot),
        "entry_session": _entry_session(snapshot.get("cursor_time")),
        **b_tags,
    }


def _opposite(direction: str | None) -> str | None:
    if direction == "long":
        return "short"
    if direction == "short":
        return "long"
    return None


def _pip_size(symbol: str | None) -> float:
    return 0.01 if str(symbol or "").upper().endswith("JPY") else 0.0001


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _candidate(snapshot: dict[str, Any], pattern: str, direction: str | None) -> dict[str, Any] | None:
    for item in snapshot.get("evidence_candidates") or []:
        if item.get("pattern") == pattern and item.get("direction") == direction:
            return item
    return None


def _candidate_facts(snapshot: dict[str, Any], pattern: str, direction: str | None) -> dict[str, Any]:
    candidate = _candidate(snapshot, pattern, direction) or {}
    return candidate.get("debug_facts") or {}


def _htf_zone_direction(trade_direction: str | None, prior_direction: str | None) -> str | None:
    if trade_direction == "long":
        return "demand"
    if trade_direction == "short":
        return "supply"
    if prior_direction == "long":
        return "supply"
    if prior_direction == "short":
        return "demand"
    return None


def _selected_htf_zone(
    snapshot: dict[str, Any],
    debug: dict[str, Any],
    zone_direction: str | None,
) -> dict[str, Any] | None:
    if not zone_direction:
        return None
    zone_ids = _candidate_facts(
        snapshot,
        "htf_counter_reaction",
        debug.get("prior_phase_e_direction") or debug.get("active_phase_e_direction"),
    ).get("htf_opposing_sd_zone_ids") or []
    debug_ids = [
        debug.get("phase_d_shadow_htf_zone_seen_id"),
        debug.get("phase_e_shadow_htf_reaction_zone_id"),
    ]
    wanted_ids = [str(value) for value in [*zone_ids, *debug_ids] if value]
    zones = snapshot.get("zones") or []
    for zone_id in wanted_ids:
        for zone in zones:
            if zone.get("zone_id") == zone_id and zone.get("direction") == zone_direction:
                return zone
    for zone in zones:
        if zone.get("direction") == zone_direction and _is_higher_tf_zone(snapshot, zone):
            return zone
    return None


def _is_higher_tf_zone(snapshot: dict[str, Any], zone: dict[str, Any]) -> bool:
    higher_tf = str(snapshot.get("higher_tf") or "").lower()
    lower_tf = str(snapshot.get("lower_tf") or snapshot.get("timeframe") or "").lower()
    zone_tf = str(zone.get("timeframe") or "").lower()
    if higher_tf and zone_tf:
        return zone_tf == higher_tf
    return bool(zone_tf and zone_tf != lower_tf)


def _debug_zone_id(debug: dict[str, Any]) -> str:
    for key in (
        "phase_d_shadow_htf_zone_seen_id",
        "phase_e_shadow_htf_reaction_zone_id",
    ):
        value = debug.get(key)
        if value:
            return str(value)
    return ""


def _current_bar_overlaps_zone(snapshot: dict[str, Any], zone: dict[str, Any]) -> bool:
    bars = snapshot.get("lower_bars") or snapshot.get("bars") or []
    if not bars:
        return False
    bar = bars[-1]
    zone_low = _float(zone.get("low"))
    zone_high = _float(zone.get("high"))
    bar_low = _float(bar.get("low", bar.get("close")))
    bar_high = _float(bar.get("high", bar.get("close")))
    if None in (zone_low, zone_high, bar_low, bar_high):
        return False
    return bool(bar_low <= zone_high and bar_high >= zone_low)


def _htf_touch_timing(debug: dict[str, Any], inside_zone: bool) -> str:
    if inside_zone:
        return "at_entry"
    if debug.get("phase_d_shadow_htf_zone_seen"):
        return "during_d"
    if debug.get("phase_e_shadow_htf_reaction_seen"):
        return "before_d"
    return ""




def _htf_touch_time(snapshot: dict[str, Any], debug: dict[str, Any], direction: str | None) -> str | None:
    facts = _candidate_facts(snapshot, "htf_counter_reaction", direction)
    return (
        facts.get("htf_opposing_sd_tapped_at")
        or debug.get("phase_e_shadow_htf_reaction_entered_at")
        or debug.get("phase_d_shadow_watch_entered_at")
    )


def _liquidity_candidates(snapshot: dict[str, Any], direction: str | None) -> list[dict[str, Any]]:
    facts = _candidate_facts(snapshot, "htf_counter_reaction", direction)
    return [
        item for item in facts.get("liquidity_reclaim_candidates") or []
        if isinstance(item, dict) and item.get("pool_kind") == "htf_pd"
    ]


def _htf_pd_liquidity_grab_seen(snapshot: dict[str, Any], direction: str | None) -> bool:
    facts = _candidate_facts(snapshot, "htf_counter_reaction", direction)
    return bool(facts.get("htf_pd_grab_reclaim_ready") or _liquidity_candidates(snapshot, direction))


def _liquidity_grab_at_pd_extreme(snapshot: dict[str, Any], direction: str | None) -> bool:
    for item in _liquidity_candidates(snapshot, direction):
        relation = str(item.get("liquidity_relation_to_htf_expansion_extreme") or "")
        if relation in {"at_active_extreme", "near_active_extreme"}:
            return True
    return False


def _liquidity_grab_time(snapshot: dict[str, Any], direction: str | None) -> str | None:
    times: list[str] = []
    for item in _liquidity_candidates(snapshot, direction):
        for key in ("reclaimed_at", "taken_at"):
            value = item.get(key)
            if value:
                times.append(str(value))
    return max(times) if times else None


def _itr_context(
    snapshot: dict[str, Any],
    trade_direction: str | None,
    zone: dict[str, Any] | None,
) -> tuple[str | None, bool]:
    lower = snapshot.get("lower_structure") or {}
    itr = lower.get("latest_itr_low") if trade_direction == "long" else lower.get("latest_itr_high")
    if not isinstance(itr, dict):
        return None, False
    confirmed_at = itr.get("confirmed_at")
    price = _float(itr.get("price"))
    zone_low = _float(zone.get("low")) if zone else None
    zone_high = _float(zone.get("high")) if zone else None
    inside = bool(
        price is not None
        and zone_low is not None
        and zone_high is not None
        and zone_low <= price <= zone_high
    )
    return str(confirmed_at) if confirmed_at else None, inside


def _bars_since(snapshot: dict[str, Any], event_time: Any) -> int | None:
    event = _parse_time(event_time)
    if event is None:
        return None
    bars = snapshot.get("lower_bars") or snapshot.get("bars") or []
    count = 0
    for bar in bars:
        bar_time = _parse_time(bar.get("time"))
        if bar_time and event < bar_time <= (_parse_time(snapshot.get("cursor_time")) or bar_time):
            count += 1
    if count:
        return count
    current = _parse_time(snapshot.get("cursor_time"))
    if current is None or current < event:
        return None
    return 0


def _htf_pd_range_bucket(snapshot: dict[str, Any]) -> str:
    htf = snapshot.get("higher_structure") or snapshot.get("structure") or {}
    high = _float(htf.get("range_high"))
    low = _float(htf.get("range_low"))
    if high is None or low is None:
        return ""
    range_pips = abs(high - low) / _pip_size(snapshot.get("symbol"))
    if range_pips <= 75.0:
        return "tight"
    if range_pips >= 200.0:
        return "wide"
    return "normal"


def _entry_session(cursor_time: Any) -> str:
    ts = _parse_time(cursor_time)
    if ts is None:
        return ""
    hour = ts.hour
    if 0 <= hour < 7:
        return "asia"
    if 7 <= hour < 13:
        return "london"
    if 13 <= hour < 21:
        return "ny"
    return "rollover"


def _phase_b_tags(debug: dict[str, Any]) -> dict[str, Any]:
    return {
        "b_watch_origin_node": debug.get("phase_b_shadow_origin_node") or debug.get("phase_c_shadow_origin_node"),
        "b_watch_at_extreme_entry": bool(debug.get("phase_b_shadow_at_extreme_entry")),
        "b_watch_htf_sd_zone_tapped": bool(debug.get("phase_b_shadow_htf_sd_zone_tapped")),
    }
