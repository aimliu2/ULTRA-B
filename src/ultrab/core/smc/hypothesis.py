from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4


Phase = Literal["A", "B", "C", "D", "E", "range", "none"]
Direction = Literal["long", "short", "none"]
HypothesisStatus = Literal["watching", "armed", "invalidated", "fired", "missed"]
EntryPolicy = Literal["limit", "mp_after_confirmation", "hybrid", "wait", "skip"]


@dataclass
class Hypothesis:
    hypothesis_id: str
    status: HypothesisStatus
    phase: Phase
    direction: Direction
    swing_alignment: Literal["pro_swing", "counter_swing", "none"]
    internal_alignment: Literal["pro_internal", "counter_internal", "none"]
    poi_id: str | None
    poi_type: Literal["sd_zone", "pd_level", "liquidity_pool", "manual"] | None
    reason: str
    required_evidence: list[str]
    invalidation: str
    target_policy: Literal["htf_pd_level", "liquidity_target", "fixed_rr", "none"]
    fallback_target_policy: Literal["fixed_rr"] | None
    entry_policy: EntryPolicy
    created_at: str | None
    updated_at: str | None
    debug_facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "status": self.status,
            "phase": self.phase,
            "direction": self.direction,
            "swing_alignment": self.swing_alignment,
            "internal_alignment": self.internal_alignment,
            "poi_id": self.poi_id,
            "poi_type": self.poi_type,
            "reason": self.reason,
            "required_evidence": self.required_evidence,
            "invalidation": self.invalidation,
            "target_policy": self.target_policy,
            "fallback_target_policy": self.fallback_target_policy,
            "entry_policy": self.entry_policy,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "debug_facts": self.debug_facts,
        }


@dataclass
class HypothesisClassifierState:
    hypothesis_id: str = field(default_factory=lambda: uuid4().hex)
    phase_episode_id: str = field(default_factory=lambda: uuid4().hex)
    previous_phase: Phase = "none"
    htf_pd_epoch_id: str | None = None
    active_phase_e_direction: Direction = "none"
    active_phase_e_extreme_price: float | None = None
    active_phase_e_extreme_time: str | None = None
    current_hypothesis: Hypothesis | None = None


def _direction_from_bias(bias: str | None) -> Direction:
    if bias == "bullish":
        return "long"
    if bias == "bearish":
        return "short"
    return "none"


def _epoch_id(structure: dict[str, Any] | None) -> str | None:
    if not structure:
        return None
    last_sc = structure.get("last_sc") or {}
    parts = [
        str(last_sc.get("eventTimestamp") or ""),
        str(last_sc.get("eventCode") or ""),
        str(last_sc.get("breakDirection") or ""),
        str(structure.get("phase_start_ts") or ""),
    ]
    if not any(parts):
        return None
    return "|".join(parts)


def _bar_time(bar: dict[str, Any] | None) -> str | None:
    return str(bar.get("time")) if bar and bar.get("time") else None


def _zone_timeframe(zone: dict[str, Any]) -> str:
    return str(zone.get("timeframe") or zone.get("tf") or "")


def _htf_last_resolved_zone(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    zone = snapshot.get("higher_last_resolved_zone") or snapshot.get("last_resolved_zone")
    return zone if isinstance(zone, dict) else None


def _current_and_previous_htf_bars(snapshot: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    bars = snapshot.get("higher_bars") or snapshot.get("bars") or []
    if not bars:
        return None, None
    current = bars[-1]
    previous = bars[-2] if len(bars) >= 2 else None
    return current, previous


class HypothesisClassifier:
    """Stateful System C phase classifier for the early E/D/C/B slices."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.state = HypothesisClassifierState()

    def classify(self, snapshot: dict[str, Any]) -> Hypothesis:
        htf = snapshot.get("higher_structure") or snapshot.get("structure")
        ltf = snapshot.get("lower_structure")
        cursor_time = snapshot.get("cursor_time")
        current_bar, previous_bar = _current_and_previous_htf_bars(snapshot)

        epoch_id = _epoch_id(htf)
        if epoch_id and epoch_id != self.state.htf_pd_epoch_id:
            self.state.phase_episode_id = uuid4().hex
            self.state.htf_pd_epoch_id = epoch_id

        debug = {
            "mode": snapshot.get("mode", "single"),
            "combo": snapshot.get("combo"),
            "htf_bias": htf.get("bias") if htf else None,
            "htf_phase": htf.get("phase") if htf else None,
            "ltf_bias": ltf.get("bias") if ltf else None,
            "ltf_phase": ltf.get("phase") if ltf else None,
            "htf_pd_epoch_id": self.state.htf_pd_epoch_id,
            "previous_phase": self.state.previous_phase,
            "active_phase_e_direction": self.state.active_phase_e_direction,
            "active_phase_e_extreme_price": self.state.active_phase_e_extreme_price,
            "active_phase_e_extreme_time": self.state.active_phase_e_extreme_time,
            "current_htf_bar_time": _bar_time(current_bar),
            "previous_htf_bar_time": _bar_time(previous_bar),
        }

        if not htf:
            hyp = self._none(
                "waiting_for_htf_structure",
                ["htf_structure"],
                "HTF structure snapshot becomes available",
                cursor_time,
                debug,
            )
            return self._commit(hyp)

        bias = htf.get("bias")
        phase = htf.get("phase")
        direction = _direction_from_bias(bias)

        if phase in {"open", "pullback_confirmed"} and direction != "none":
            reaction = self._phase_e_reaction(direction, current_bar, previous_bar)
            debug.update(reaction)

            if self.state.previous_phase == "C" and self.state.active_phase_e_direction == direction:
                reaction_failed = self._phase_d_reaction_failed(direction, current_bar)
                debug.update(reaction_failed)
                if reaction_failed["reaction_failed"]:
                    debug["phase_c_collapsed"] = True
                    debug["phase_c_collapse_rule"] = reaction_failed["reaction_failed_rule"]
                    self._refresh_phase_e_extreme(htf, direction, current_bar)
                    hyp = self._phase_e(direction, cursor_time, debug)
                    return self._commit(hyp)
                if self.state.current_hypothesis:
                    phase_c = self._phase_c_setup(snapshot, ltf, direction)
                    phase_b = self._phase_b_setup(snapshot, htf, ltf, direction)
                    debug.update(phase_c)
                    debug.update(phase_b)
                    if phase_b["phase_b_ready"]:
                        hyp = self._phase_b(direction, phase_b["phase_b_selected_poi"], cursor_time, debug)
                        return self._commit(hyp)
                    if phase_c["phase_c_story_ready"] and phase_c["phase_c_selected_poi"]:
                        hyp = self._phase_c(
                            direction,
                            phase_c["phase_c_selected_poi"],
                            "armed",
                            cursor_time,
                            debug,
                        )
                        return self._commit(hyp)
                    if (
                        self.state.current_hypothesis.status == "watching"
                        and phase_c["phase_c_story_ready"]
                    ):
                        hyp = self._phase_c(direction, None, "watching", cursor_time, debug)
                        return self._commit(hyp)
                    hyp = self._carry_current_hypothesis(cursor_time, {**debug, "phase_c_held": True})
                    return self._commit(hyp)

            if self.state.previous_phase == "D" and self.state.active_phase_e_direction == direction:
                reaction_failed = self._phase_d_reaction_failed(direction, current_bar)
                debug.update(reaction_failed)
                if not reaction_failed["reaction_failed"]:
                    phase_c = self._phase_c_setup(snapshot, ltf, direction)
                    debug.update(phase_c)
                    if phase_c["phase_c_story_ready"]:
                        status: HypothesisStatus = "armed" if phase_c["phase_c_selected_poi"] else "watching"
                        hyp = self._phase_c(
                            direction,
                            phase_c["phase_c_selected_poi"],
                            status,
                            cursor_time,
                            debug,
                        )
                        return self._commit(hyp)
                    hyp = self._phase_d(direction, cursor_time, debug)
                    return self._commit(hyp)

            phase_d = self._phase_d_setup(snapshot, htf, ltf, direction, current_bar)
            debug.update(phase_d)

            if self._previous_or_active_e(direction) and phase_d["phase_d_ready"]:
                hyp = self._phase_d(direction, cursor_time, debug)
                return self._commit(hyp)

            phase_b = self._phase_b_setup(snapshot, htf, ltf, direction)
            debug.update(phase_b)
            if phase_b["phase_b_ready"]:
                hyp = self._phase_b(direction, phase_b["phase_b_selected_poi"], cursor_time, debug)
                return self._commit(hyp)

            if phase == "open":
                self._refresh_phase_e_extreme(htf, direction, current_bar)
                hyp = self._phase_e(direction, cursor_time, debug)
                return self._commit(hyp)

        if bias == "neutral" or direction == "none":
            hyp = self._none(
                "HTF bias is neutral; no directional hypothesis",
                ["directional_htf_bias"],
                "HTF bias becomes directional",
                cursor_time,
                debug,
            )
            return self._commit(hyp)

        hyp = self._none(
            "E/D/C/B classifier slice found no tradable hypothesis; waiting for A classifier",
            ["phase_a_classifier"],
            "Next classifier slice defines this pullback/continuation state",
            cursor_time,
            debug,
        )
        return self._commit(hyp)

    def _phase_d_setup(
        self,
        snapshot: dict[str, Any],
        htf: dict[str, Any],
        ltf: dict[str, Any] | None,
        direction: Direction,
        current_bar: dict[str, Any] | None,
    ) -> dict[str, Any]:
        counter_zone_direction = "supply" if direction == "long" else "demand"
        counter_ltf_bias = "bearish" if direction == "long" else "bullish"
        higher_tf = str(snapshot.get("higher_tf") or snapshot.get("timeframe") or "")
        lower_tf = str(snapshot.get("lower_tf") or "")
        zones = snapshot.get("zones") or []
        higher_counter_zones = [
            zone
            for zone in zones
            if zone.get("direction") == counter_zone_direction
            and _zone_timeframe(zone) == higher_tf
        ]
        lower_counter_zones = [
            zone
            for zone in zones
            if zone.get("direction") == counter_zone_direction
            and lower_tf
            and _zone_timeframe(zone) == lower_tf
        ]
        htf_last_resolved_zone = _htf_last_resolved_zone(snapshot)
        htf_opposing_sd_resolved = self._is_opposing_htf_sd_reaction(
            htf_last_resolved_zone,
            counter_zone_direction,
            higher_tf,
        )

        new_htf_extreme = self._new_phase_e_extreme(direction, current_bar)
        htf_pd_stopped_expanding = not new_htf_extreme
        htf_sd_confirmed_pullback = (
            htf.get("phase") == "pullback_confirmed"
            and htf.get("confirmed_by") == "sd_zone"
        )
        htf_opposing_sd_tapped = any(bool(zone.get("in_zone")) for zone in higher_counter_zones)
        htf_opposing_sd_reaction = (
            htf_sd_confirmed_pullback
            or htf_opposing_sd_tapped
            or htf_opposing_sd_resolved
        )
        ltf_counter_sd_created = bool(lower_counter_zones)
        ltf_bias_counter_htf = bool(ltf and ltf.get("bias") == counter_ltf_bias)
        normal_ready = (
            htf_pd_stopped_expanding
            and htf_opposing_sd_reaction
            and ltf_counter_sd_created
        )
        special_new_extreme_ready = (
            new_htf_extreme
            and not htf_opposing_sd_reaction
            and ltf_bias_counter_htf
        )
        trigger = None
        if normal_ready:
            trigger = "opposing_htf_sd_reaction_with_ltf_counter_sd"
        elif special_new_extreme_ready:
            trigger = "new_htf_extreme_with_ltf_counter_bias"

        return {
            "phase_d_ready": normal_ready or special_new_extreme_ready,
            "phase_d_trigger": trigger,
            "htf_pd_stopped_expanding": htf_pd_stopped_expanding,
            "new_htf_extreme": new_htf_extreme,
            "htf_opposing_sd_reaction": htf_opposing_sd_reaction,
            "htf_sd_confirmed_pullback": htf_sd_confirmed_pullback,
            "htf_opposing_sd_tapped": htf_opposing_sd_tapped,
            "htf_opposing_sd_resolved": htf_opposing_sd_resolved,
            "htf_last_resolved_zone_id": htf_last_resolved_zone.get("zone_id") if htf_last_resolved_zone else None,
            "htf_last_resolved_zone_direction": htf_last_resolved_zone.get("direction") if htf_last_resolved_zone else None,
            "htf_last_resolved_zone_resolution": htf_last_resolved_zone.get("resolution") if htf_last_resolved_zone else None,
            "htf_opposing_sd_zone_ids": [zone.get("zone_id") for zone in higher_counter_zones],
            "ltf_counter_sd_created": ltf_counter_sd_created,
            "ltf_counter_sd_zone_ids": [zone.get("zone_id") for zone in lower_counter_zones],
            "ltf_bias_counter_htf": ltf_bias_counter_htf,
        }

    def _is_opposing_htf_sd_reaction(
        self,
        zone: dict[str, Any] | None,
        counter_zone_direction: str,
        higher_tf: str,
    ) -> bool:
        if not zone:
            return False
        if zone.get("direction") != counter_zone_direction:
            return False
        if higher_tf and _zone_timeframe(zone) != higher_tf:
            return False
        return zone.get("resolution") in {"bounced", "liquidity_swept"}

    def _previous_or_active_e(self, direction: Direction) -> bool:
        return (
            self.state.previous_phase == "E"
            or self.state.active_phase_e_direction == direction
        )

    def _phase_c_setup(
        self,
        snapshot: dict[str, Any],
        ltf: dict[str, Any] | None,
        prior_direction: Direction,
    ) -> dict[str, Any]:
        counter_zone_direction = "supply" if prior_direction == "long" else "demand"
        counter_ltf_bias = "bearish" if prior_direction == "long" else "bullish"
        lower_tf = str(snapshot.get("lower_tf") or "")
        zones = snapshot.get("zones") or []
        lower_counter_zones = [
            zone
            for zone in zones
            if zone.get("direction") == counter_zone_direction
            and lower_tf
            and _zone_timeframe(zone) == lower_tf
        ]
        lower_counter_zones.sort(
            key=lambda zone: (
                str(zone.get("created_at") or ""),
                str(zone.get("zone_id") or ""),
            )
        )
        returned_zones = [zone for zone in lower_counter_zones if bool(zone.get("in_zone"))]
        selected_poi = returned_zones[0] if returned_zones else (lower_counter_zones[0] if lower_counter_zones else None)
        ltf_bias_counter_htf = bool(ltf and ltf.get("bias") == counter_ltf_bias)
        ltf_last_sc = ltf.get("last_sc") if ltf else None
        ltf_counter_break_direction = "down" if prior_direction == "long" else "up"
        ltf_counter_pd_break = bool(
            ltf_bias_counter_htf
            and isinstance(ltf_last_sc, dict)
            and ltf_last_sc.get("breakDirection") == ltf_counter_break_direction
        )
        ltf_counter_pullback_confirmed = bool(
            ltf
            and ltf.get("phase") == "pullback_confirmed"
            and ltf.get("bias") == counter_ltf_bias
        )
        story_ready = ltf_bias_counter_htf
        armed = bool(story_ready and selected_poi)
        touched = bool(armed and selected_poi and selected_poi.get("in_zone"))

        return {
            "phase_c_candidate": story_ready,
            "phase_c_story_ready": story_ready,
            "phase_c_armed": armed,
            "phase_c_ready": armed,
            "phase_c_status": "armed" if armed else ("watching" if story_ready else None),
            "phase_c_direction": "short" if prior_direction == "long" else "long",
            "phase_c_counter_zone_direction": counter_zone_direction,
            "phase_c_ltf_counter_sd_zone_ids": [zone.get("zone_id") for zone in lower_counter_zones],
            "phase_c_ltf_counter_sd_returned": [zone.get("zone_id") for zone in returned_zones],
            "phase_c_selected_poi_id": selected_poi.get("zone_id") if selected_poi else None,
            "phase_c_selected_poi": selected_poi,
            "phase_c_ltf_bias_counter_htf": ltf_bias_counter_htf,
            "phase_c_ltf_counter_pd_break": ltf_counter_pd_break,
            "phase_c_ltf_counter_break_direction": ltf_counter_break_direction,
            "phase_c_ltf_counter_pullback_confirmed": ltf_counter_pullback_confirmed,
            "phase_c_selected_poi_touched": touched,
        }

    def _phase_b_setup(
        self,
        snapshot: dict[str, Any],
        htf: dict[str, Any],
        ltf: dict[str, Any] | None,
        direction: Direction,
    ) -> dict[str, Any]:
        pro_zone_direction = "demand" if direction == "long" else "supply"
        higher_tf = str(snapshot.get("higher_tf") or snapshot.get("timeframe") or "")
        lower_tf = str(snapshot.get("lower_tf") or "")
        zones = snapshot.get("zones") or []
        higher_pro_zones = [
            zone
            for zone in zones
            if zone.get("direction") == pro_zone_direction
            and _zone_timeframe(zone) == higher_tf
        ]
        lower_pro_zones = [
            zone
            for zone in zones
            if zone.get("direction") == pro_zone_direction
            and lower_tf
            and _zone_timeframe(zone) == lower_tf
        ]
        lower_pro_zones.sort(
            key=lambda zone: (
                str(zone.get("created_at") or ""),
                str(zone.get("zone_id") or ""),
            )
        )

        htf_pd_value_pct = htf.get("pd_value_pct")
        htf_range_position_pct = htf.get("range_position_pct", htf.get("pd_pct"))
        if htf_pd_value_pct is None and htf_range_position_pct is not None:
            if htf.get("bias") == "bullish":
                htf_pd_value_pct = htf_range_position_pct
            elif htf.get("bias") == "bearish":
                htf_pd_value_pct = 100.0 - float(htf_range_position_pct)
        if htf_pd_value_pct is None:
            correct_pd_half = False
        else:
            correct_pd_half = float(htf_pd_value_pct) < 50.0

        htf_not_clean_phase_e = htf.get("phase") != "open"
        htf_pullback_evidence = htf.get("phase") == "pullback_confirmed"
        ltf_turns_back_toward_htf = bool(
            ltf
            and ltf.get("bias") == htf.get("bias")
            and _direction_from_bias(ltf.get("bias")) == direction
        )
        htf_pro_sd_tapped = any(bool(zone.get("in_zone")) for zone in higher_pro_zones)
        htf_last_resolved_zone = _htf_last_resolved_zone(snapshot)
        htf_pro_sd_resolved = self._is_htf_sd_reaction(
            htf_last_resolved_zone,
            pro_zone_direction,
            higher_tf,
        )
        htf_pro_sd_reaction = htf_pro_sd_tapped or htf_pro_sd_resolved
        selected_poi = lower_pro_zones[0] if lower_pro_zones else None
        ltf_pro_sd_selected = selected_poi is not None
        strict_ready = (
            htf_not_clean_phase_e
            and correct_pd_half
            and htf_pro_sd_reaction
            and ltf_turns_back_toward_htf
            and ltf_pro_sd_selected
        )
        candidate = (
            htf_not_clean_phase_e
            and correct_pd_half
            and ltf_turns_back_toward_htf
            and ltf_pro_sd_selected
        )
        candidate_variant = None
        blocked_reason = None
        if candidate and not strict_ready:
            if not higher_pro_zones:
                candidate_variant = "missing_htf_reaction_zone"
            elif not htf_pro_sd_reaction:
                candidate_variant = "shallow"
            if not htf_pro_sd_reaction:
                blocked_reason = (
                    "no_htf_demand_reaction"
                    if direction == "long"
                    else "no_htf_supply_reaction"
                )
            elif not ltf_pro_sd_selected:
                blocked_reason = (
                    "no_ltf_demand_poi"
                    if direction == "long"
                    else "no_ltf_supply_poi"
                )

        return {
            "phase_b_ready": strict_ready,
            "phase_b_candidate": candidate or strict_ready,
            "phase_b_candidate_variant": "strict" if strict_ready else candidate_variant,
            "phase_b_blocked_reason": blocked_reason,
            "phase_b_direction": direction,
            "phase_b_pro_zone_direction": pro_zone_direction,
            "phase_b_htf_not_clean_phase_e": htf_not_clean_phase_e,
            "phase_b_htf_pullback_evidence": htf_pullback_evidence,
            "phase_b_correct_pd_half": correct_pd_half,
            "phase_b_htf_pd_value_pct": htf_pd_value_pct,
            "phase_b_htf_range_position_pct": htf_range_position_pct,
            "phase_b_htf_pd_pct": htf_range_position_pct,
            "phase_b_htf_pro_sd_reaction": htf_pro_sd_reaction,
            "phase_b_htf_pro_sd_tapped": htf_pro_sd_tapped,
            "phase_b_htf_pro_sd_resolved": htf_pro_sd_resolved,
            "phase_b_htf_pro_sd_zone_ids": [zone.get("zone_id") for zone in higher_pro_zones],
            "phase_b_htf_last_resolved_zone_id": htf_last_resolved_zone.get("zone_id") if htf_last_resolved_zone else None,
            "phase_b_htf_last_resolved_zone_direction": htf_last_resolved_zone.get("direction") if htf_last_resolved_zone else None,
            "phase_b_htf_last_resolved_zone_resolution": htf_last_resolved_zone.get("resolution") if htf_last_resolved_zone else None,
            "phase_b_ltf_turns_back_toward_htf": ltf_turns_back_toward_htf,
            "phase_b_ltf_pro_sd_selected": ltf_pro_sd_selected,
            "phase_b_ltf_pro_sd_zone_ids": [zone.get("zone_id") for zone in lower_pro_zones],
            "phase_b_selected_poi_id": selected_poi.get("zone_id") if selected_poi else None,
            "phase_b_selected_poi": selected_poi,
        }

    def _is_htf_sd_reaction(
        self,
        zone: dict[str, Any] | None,
        direction: str,
        higher_tf: str,
    ) -> bool:
        if not zone:
            return False
        if zone.get("direction") != direction:
            return False
        if higher_tf and _zone_timeframe(zone) != higher_tf:
            return False
        return zone.get("resolution") in {"bounced", "liquidity_swept"}

    def _new_phase_e_extreme(
        self,
        direction: Direction,
        current_bar: dict[str, Any] | None,
    ) -> bool:
        extreme = self.state.active_phase_e_extreme_price
        if current_bar is None or extreme is None:
            return False
        if direction == "long" and current_bar.get("high") is not None:
            return float(current_bar["high"]) > extreme
        if direction == "short" and current_bar.get("low") is not None:
            return float(current_bar["low"]) < extreme
        return False

    def _phase_d_reaction_failed(
        self,
        direction: Direction,
        current_bar: dict[str, Any] | None,
    ) -> dict[str, Any]:
        facts = {
            "reaction_failed": False,
            "reaction_failed_rule": None,
        }
        extreme = self.state.active_phase_e_extreme_price
        if current_bar is None or extreme is None:
            return facts

        close = float(current_bar["close"])
        if direction == "long":
            facts.update(
                {
                    "reaction_failed": close > extreme,
                    "reaction_failed_rule": "bullish_phase_d_close_above_phase_e_extreme",
                    "current_htf_close": close,
                }
            )
        elif direction == "short":
            facts.update(
                {
                    "reaction_failed": close < extreme,
                    "reaction_failed_rule": "bearish_phase_d_close_below_phase_e_extreme",
                    "current_htf_close": close,
                }
            )
        return facts

    def _refresh_phase_e_extreme(
        self,
        htf: dict[str, Any],
        direction: Direction,
        current_bar: dict[str, Any] | None,
    ) -> None:
        if direction == "long":
            price = htf.get("range_high")
            ts = htf.get("range_high_ts")
            if current_bar and current_bar.get("high") is not None:
                price = max(float(price), float(current_bar["high"])) if price is not None else float(current_bar["high"])
                if price == float(current_bar["high"]):
                    ts = current_bar.get("time")
        elif direction == "short":
            price = htf.get("range_low")
            ts = htf.get("range_low_ts")
            if current_bar and current_bar.get("low") is not None:
                price = min(float(price), float(current_bar["low"])) if price is not None else float(current_bar["low"])
                if price == float(current_bar["low"]):
                    ts = current_bar.get("time")
        else:
            return

        self.state.active_phase_e_direction = direction
        self.state.active_phase_e_extreme_price = float(price) if price is not None else None
        self.state.active_phase_e_extreme_time = str(ts) if ts else None

    def _phase_e_reaction(
        self,
        direction: Direction,
        current_bar: dict[str, Any] | None,
        previous_bar: dict[str, Any] | None,
    ) -> dict[str, Any]:
        facts = {
            "reaction_confirmed": False,
            "reaction_warning": False,
            "reaction_rule": None,
        }
        if not current_bar or not previous_bar:
            return facts

        if direction == "long":
            prev_low = float(previous_bar["low"])
            cur_low = float(current_bar["low"])
            cur_close = float(current_bar["close"])
            facts.update(
                {
                    "previous_htf_low": prev_low,
                    "current_htf_low": cur_low,
                    "current_htf_close": cur_close,
                    "reaction_warning": cur_low < prev_low,
                    "reaction_confirmed": cur_close < prev_low,
                    "reaction_rule": "bullish_phase_e_close_below_previous_htf_low",
                }
            )
        elif direction == "short":
            prev_high = float(previous_bar["high"])
            cur_high = float(current_bar["high"])
            cur_close = float(current_bar["close"])
            facts.update(
                {
                    "previous_htf_high": prev_high,
                    "current_htf_high": cur_high,
                    "current_htf_close": cur_close,
                    "reaction_warning": cur_high > prev_high,
                    "reaction_confirmed": cur_close > prev_high,
                    "reaction_rule": "bearish_phase_e_close_above_previous_htf_high",
                }
            )
        return facts

    def _phase_e(self, direction: Direction, ts: str | None, debug: dict[str, Any]) -> Hypothesis:
        bullish = direction == "long"
        reason = (
            "HTF bullish open leg is seeking buy-side ERL; continuation opted out"
            if bullish
            else "HTF bearish open leg is seeking sell-side ERL; continuation opted out"
        )
        return Hypothesis(
            hypothesis_id=self.state.hypothesis_id,
            status="watching",
            phase="E",
            direction=direction,
            swing_alignment="pro_swing",
            internal_alignment="none",
            poi_id=None,
            poi_type=None,
            reason=reason,
            required_evidence=["htf_pullback_confirmation"],
            invalidation="HTF leg stops being open, or HTF bias returns neutral",
            target_policy="none",
            fallback_target_policy=None,
            entry_policy="skip",
            created_at=self.state.current_hypothesis.created_at if self.state.current_hypothesis else ts,
            updated_at=ts,
            debug_facts=debug,
        )

    def _phase_d(self, prior_direction: Direction, ts: str | None, debug: dict[str, Any]) -> Hypothesis:
        debug = {**debug, "prior_phase_e_direction": prior_direction}
        return Hypothesis(
            hypothesis_id=self.state.hypothesis_id,
            status="watching",
            phase="D",
            direction="none",
            swing_alignment="none",
            internal_alignment="none",
            poi_id=None,
            poi_type=None,
            reason="price is at reaction point after ERL / opposing POI interaction",
            required_evidence=["ltf_counter_internal_story_for_phase_c", "htf_pullback_evidence_for_phase_b"],
            invalidation="Reaction fails and price resumes the original HTF direction",
            target_policy="none",
            fallback_target_policy=None,
            entry_policy="skip",
            created_at=self.state.current_hypothesis.created_at if self.state.current_hypothesis else ts,
            updated_at=ts,
            debug_facts=debug,
        )

    def _phase_c(
        self,
        prior_direction: Direction,
        selected_poi: dict[str, Any] | None,
        status: Literal["watching", "armed"],
        ts: str | None,
        debug: dict[str, Any],
    ) -> Hypothesis:
        trade_direction: Direction = "short" if prior_direction == "long" else "long"
        entry_policy: EntryPolicy = (
            "hybrid"
            if status == "armed"
            and (self.config.get("allow_pullback_trade") or self.config.get("phase_c_allow_pullback_trade"))
            else "skip"
        )
        if status == "watching":
            entry_policy = "wait"
        debug = {**debug, "prior_phase_e_direction": prior_direction}
        return Hypothesis(
            hypothesis_id=self.state.hypothesis_id,
            status=status,
            phase="C",
            direction=trade_direction,
            swing_alignment="counter_swing",
            internal_alignment="pro_internal",
            poi_id=selected_poi.get("zone_id") if selected_poi else None,
            poi_type="sd_zone" if selected_poi else None,
            reason=(
                "LTF counter-internal story formed at HTF reaction point; waiting for counter POI"
                if status == "watching"
                else "LTF counter-internal story formed and counter POI is selected"
            ),
            required_evidence=(
                ["selected_ltf_counter_poi"]
                if status == "watching"
                else ["entry_protocol_permission", "risk_rr_valid"]
            ),
            invalidation="HTF reaction fails and price resumes the original Phase E direction",
            target_policy="fixed_rr",
            fallback_target_policy=None,
            entry_policy=entry_policy,
            created_at=self.state.current_hypothesis.created_at if self.state.current_hypothesis else ts,
            updated_at=ts,
            debug_facts=debug,
        )

    def _phase_b(
        self,
        direction: Direction,
        selected_poi: dict[str, Any],
        ts: str | None,
        debug: dict[str, Any],
    ) -> Hypothesis:
        bullish = direction == "long"
        return Hypothesis(
            hypothesis_id=self.state.hypothesis_id,
            status="armed",
            phase="B",
            direction=direction,
            swing_alignment="pro_swing",
            internal_alignment="counter_internal",
            poi_id=selected_poi.get("zone_id"),
            poi_type="sd_zone",
            reason=(
                "Strict bullish B: HTF demand reaction in discount and LTF flipped back bullish"
                if bullish
                else "Strict bearish B: HTF supply reaction in discount and LTF flipped back bearish"
            ),
            required_evidence=["entry_protocol_permission", "risk_rr_valid"],
            invalidation="HTF pullback fails to resolve back toward HTF bias",
            target_policy="htf_pd_level",
            fallback_target_policy="fixed_rr",
            entry_policy="hybrid",
            created_at=self.state.current_hypothesis.created_at if self.state.current_hypothesis else ts,
            updated_at=ts,
            debug_facts=debug,
        )

    def _carry_current_hypothesis(self, ts: str | None, debug: dict[str, Any]) -> Hypothesis:
        current = self.state.current_hypothesis
        if current is None:
            return self._none(
                "waiting_for_hypothesis_state",
                ["current_hypothesis"],
                "A hypothesis exists before it can be carried forward",
                ts,
                debug,
            )
        return Hypothesis(
            hypothesis_id=current.hypothesis_id,
            status=current.status,
            phase=current.phase,
            direction=current.direction,
            swing_alignment=current.swing_alignment,
            internal_alignment=current.internal_alignment,
            poi_id=current.poi_id,
            poi_type=current.poi_type,
            reason=current.reason,
            required_evidence=current.required_evidence,
            invalidation=current.invalidation,
            target_policy=current.target_policy,
            fallback_target_policy=current.fallback_target_policy,
            entry_policy=current.entry_policy,
            created_at=current.created_at,
            updated_at=ts,
            debug_facts=debug,
        )

    def _none(
        self,
        reason: str,
        required_evidence: list[str],
        invalidation: str,
        ts: str | None,
        debug: dict[str, Any],
    ) -> Hypothesis:
        return Hypothesis(
            hypothesis_id=self.state.hypothesis_id,
            status="watching",
            phase="none",
            direction="none",
            swing_alignment="none",
            internal_alignment="none",
            poi_id=None,
            poi_type=None,
            reason=reason,
            required_evidence=required_evidence,
            invalidation=invalidation,
            target_policy="none",
            fallback_target_policy=None,
            entry_policy="wait",
            created_at=self.state.current_hypothesis.created_at if self.state.current_hypothesis else ts,
            updated_at=ts,
            debug_facts=debug,
        )

    def _commit(self, hypothesis: Hypothesis) -> Hypothesis:
        if hypothesis.phase != self.state.previous_phase and hypothesis.phase in {"E", "D", "C", "B"}:
            self.state.phase_episode_id = uuid4().hex
        self.state.previous_phase = hypothesis.phase
        self.state.current_hypothesis = hypothesis
        return hypothesis
