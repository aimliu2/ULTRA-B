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
    phase_sub_status: str | None = None
    none_sub_status: str | None = None
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
            "phase_sub_status": self.phase_sub_status,
            "none_sub_status": self.none_sub_status,
            "debug_facts": self.debug_facts,
        }


@dataclass
class ShadowThesis:
    """Commitment memory for Phase B shallow-reclaim tracking.

    Survives D→C→B re-entry and normal phase transitions.
    Only cleared on epoch boundary reset or explicit invalidation.
    """
    status: str | None = None
    opened_at: str | None = None
    selected_poi_id: str | None = None
    selected_poi_high: float | None = None
    selected_poi_low: float | None = None
    first_counter_mitigation_at: str | None = None
    same_level_return_count: int = 0
    weakening_reason: str | None = None

    def reset(self) -> None:
        self.status = None
        self.opened_at = None
        self.selected_poi_id = None
        self.selected_poi_high = None
        self.selected_poi_low = None
        self.first_counter_mitigation_at = None
        self.same_level_return_count = 0
        self.weakening_reason = None


@dataclass
class PhaseEShadow:
    """Internal Phase E sub-node memory for expansion monitoring."""
    node: str = "E.seeking"
    previous_node: str | None = None
    bars_in_node: int = 0
    source_orderflow_leg_id: str | None = None
    source_orderflow_started_at: str | None = None
    consumed_orderflow_leg_id: str | None = None
    pullback_disrupted: bool = False
    disrupted_orderflow_leg_id: str | None = None

    def reset(self) -> None:
        self.node = "E.seeking"
        self.previous_node = None
        self.bars_in_node = 0
        self.source_orderflow_leg_id = None
        self.source_orderflow_started_at = None
        self.consumed_orderflow_leg_id = None
        self.pullback_disrupted = False
        self.disrupted_orderflow_leg_id = None


@dataclass
class HypothesisClassifierState:
    hypothesis_id: str = field(default_factory=lambda: uuid4().hex)
    phase_episode_id: str = field(default_factory=lambda: uuid4().hex)
    previous_phase: Phase = "none"
    htf_pd_epoch_id: str | None = None
    active_phase_e_direction: Direction = "none"
    phase_e_shadow: PhaseEShadow = field(default_factory=PhaseEShadow)
    shadow_thesis: ShadowThesis = field(default_factory=ShadowThesis)
    current_hypothesis: Hypothesis | None = None

    @property
    def phase_e_shadow_node(self) -> str:
        return self.phase_e_shadow.node

    @phase_e_shadow_node.setter
    def phase_e_shadow_node(self, value: str) -> None:
        self.phase_e_shadow.node = value


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


def _cursor_bar(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    lower_bars = snapshot.get("lower_bars") or []
    if lower_bars:
        return lower_bars[-1]
    higher_bars = snapshot.get("higher_bars") or snapshot.get("bars") or []
    return higher_bars[-1] if higher_bars else None


def _liquidity_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    liquidity = snapshot.get("liquidity")
    return liquidity if isinstance(liquidity, dict) else {}


def _ec_candidates(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates = snapshot.get("evidence_candidates") or []
    return {
        str(c.get("pattern")): c
        for c in candidates
        if isinstance(c, dict) and c.get("pattern")
    }


def _ec_candidate(snapshot: dict[str, Any], pattern: str) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = _ec_candidates(snapshot).get(pattern) or {}
    debug_facts = candidate.get("debug_facts") or {}
    return candidate, debug_facts if isinstance(debug_facts, dict) else {}


def _ec_b_initiation(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (b_init_candidate, b_init_debug_facts) from evidence_candidates."""
    return _ec_candidate(snapshot, "htf_b_initiation")


def _waiting_for_first_closed_htf(
    cursor_time: str | None,
    current_bar: dict[str, Any] | None,
    previous_bar: dict[str, Any] | None,
) -> bool:
    current_time = _bar_time(current_bar)
    return bool(
        cursor_time
        and current_time
        and previous_bar is None
        and current_time > cursor_time
    )


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
        waiting_for_first_closed_htf = _waiting_for_first_closed_htf(cursor_time, current_bar, previous_bar)

        epoch_id = _epoch_id(htf)
        if epoch_id and epoch_id != self.state.htf_pd_epoch_id:
            self.state.phase_episode_id = uuid4().hex
            self.state.htf_pd_epoch_id = epoch_id
            self.state.active_phase_e_direction = "none"
            self._reset_phase_e_shadow()
            self._reset_phase_b_shadow()

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
                none_sub_status=(
                    "warmup_waiting_for_first_closed_htf"
                    if waiting_for_first_closed_htf else "waiting_for_htf_structure"
                ),
            )
            return self._commit(hyp)

        bias = htf.get("bias")
        phase = htf.get("phase")
        direction = _direction_from_bias(bias)

        if phase in {"open", "pullback_confirmed"} and direction != "none":
            reaction = self._phase_e_reaction(snapshot, direction, current_bar, previous_bar)
            debug.update(reaction)

            if self.state.previous_phase == "A":
                finale = self._phase_a_finale(snapshot, direction, htf, current_bar)
                debug.update(finale)
                if finale["phase_a_finale_touched"]:
                    if finale["phase_a_finale_closed_beyond"]:
                        hyp = self._phase_e(direction, cursor_time, debug, ltf)
                    else:
                        hyp = self._range(
                            "Phase A reached the HTF P/D objective but failed to close beyond it",
                            "failed_phase_a_finale",
                            cursor_time,
                            debug,
                        )
                    return self._commit(hyp)

            if self.state.previous_phase == "C" and self.state.active_phase_e_direction == direction:
                if debug.get("reaction_failed"):
                    debug["phase_c_collapsed"] = True
                    debug["phase_c_collapse_rule"] = debug.get("reaction_failed_rule")
                    hyp = self._phase_e(direction, cursor_time, debug, ltf)
                    return self._commit(hyp)
                if self.state.current_hypothesis:
                    phase_c = self._phase_c_setup(snapshot, ltf, direction)
                    phase_b = self._phase_b_setup(snapshot, htf, ltf, direction)
                    phase_d_from_c = self._phase_d_setup(snapshot, htf, ltf, direction, current_bar)
                    debug.update(phase_c)
                    debug.update(phase_b)
                    debug.update(phase_d_from_c)
                    if phase_b["phase_b_ready"]:
                        hyp = self._phase_b(direction, phase_b["phase_b_selected_poi"], cursor_time, debug)
                        return self._commit(hyp)
                    phase_b_initiation = self._phase_b_initiation_setup(snapshot, direction)
                    debug.update(phase_b_initiation)
                    if phase_b_initiation["phase_b_initiation_ready"]:
                        hyp = self._phase_b_initiation_watch(direction, cursor_time, debug)
                        return self._commit(hyp)
                    if phase_d_from_c["phase_d_liquidity_ready"]:
                        phase_d_sub_status = self._phase_d_sub_status(phase_d_from_c)
                        hyp = self._phase_d(
                            direction,
                            cursor_time,
                            {
                                **debug,
                                "phase_d_sub_status": phase_d_sub_status,
                                "phase_d_origin_node": (
                                    f"C.{self.state.current_hypothesis.phase_sub_status}"
                                    if self.state.current_hypothesis.phase_sub_status
                                    else "C"
                                ),
                                "phase_d_selection_reason": self._phase_d_selection_reason(phase_d_from_c),
                            },
                            phase_sub_status=phase_d_sub_status,
                        )
                        return self._commit(hyp)
                    if phase_c["phase_c_story_ready"] and phase_c["phase_c_selected_poi"]:
                        phase_c_sub_status = (
                            self.state.current_hypothesis.phase_sub_status
                            if self.state.current_hypothesis and self.state.current_hypothesis.phase == "C"
                            else None
                        )
                        hyp = self._phase_c(
                            direction,
                            phase_c["phase_c_selected_poi"],
                            "armed",
                            cursor_time,
                            debug,
                            phase_sub_status=phase_c_sub_status,
                        )
                        return self._commit(hyp)
                    if (
                        self.state.current_hypothesis.status == "watching"
                        and phase_c["phase_c_story_ready"]
                    ):
                        phase_c_sub_status = (
                            self.state.current_hypothesis.phase_sub_status
                            if self.state.current_hypothesis and self.state.current_hypothesis.phase == "C"
                            else None
                        )
                        hyp = self._phase_c(
                            direction,
                            None,
                            "watching",
                            cursor_time,
                            debug,
                            phase_sub_status=phase_c_sub_status,
                        )
                        return self._commit(hyp)
                    hyp = self._carry_current_hypothesis(cursor_time, {**debug, "phase_c_held": True})
                    return self._commit(hyp)

            if self.state.previous_phase == "D" and self.state.active_phase_e_direction == direction:
                if not debug.get("reaction_failed"):
                    phase_c = self._phase_c_setup(snapshot, ltf, direction)
                    debug.update(phase_c)
                    if phase_c["phase_c_story_ready"] and self._phase_d_reaction_confirmed(phase_c):
                        status: HypothesisStatus = "armed" if phase_c["phase_c_selected_poi"] else "watching"
                        phase_c_sub_status = self._phase_c_sub_status_from_current_d()
                        debug.update(
                            self._phase_c_origin_debug_from_current_d(
                                phase_c_sub_status,
                                "ltf_counter_story_after_d_reaction",
                            )
                        )
                        hyp = self._phase_c(
                            direction,
                            phase_c["phase_c_selected_poi"],
                            status,
                            cursor_time,
                            debug,
                            phase_sub_status=phase_c_sub_status,
                        )
                        return self._commit(hyp)
                    phase_d_sub_status = (
                        self.state.current_hypothesis.phase_sub_status
                        if self.state.current_hypothesis
                        and self.state.current_hypothesis.phase == "D"
                        else None
                    )
                    if phase_d_sub_status:
                        debug["phase_d_sub_status"] = phase_d_sub_status
                        debug["phase_d_held"] = True
                    hyp = self._phase_d(
                        direction,
                        cursor_time,
                        debug,
                        phase_sub_status=phase_d_sub_status,
                    )
                    return self._commit(hyp)

            phase_d = self._phase_d_setup(snapshot, htf, ltf, direction, current_bar)
            debug.update(phase_d)

            if (
                self.state.previous_phase != "B"
                and self.state.previous_phase != "A"
                and self._previous_or_active_e(direction)
                and phase_d["phase_d_ready"]
            ):
                phase_d_sub_status = self._phase_d_sub_status(phase_d)
                hyp = self._phase_d(
                    direction,
                    cursor_time,
                    {
                        **debug,
                        "phase_d_sub_status": phase_d_sub_status,
                        "phase_d_origin_node": self._phase_d_origin_node(phase_d),
                        "phase_d_selection_reason": self._phase_d_selection_reason(phase_d),
                    },
                    phase_sub_status=phase_d_sub_status,
                )
                return self._commit(hyp)

            phase_c_from_e = self._phase_c_setup(snapshot, ltf, direction)
            fast_hard_pullback = self._phase_c_fast_hard_pullback_setup(debug, phase_c_from_e)
            if (
                self.state.previous_phase != "B"
                and fast_hard_pullback["phase_c_fast_hard_pullback_ready"]
            ):
                debug.update({**phase_c_from_e, **fast_hard_pullback})
                status: HypothesisStatus = (
                    "armed"
                    if phase_c_from_e["phase_c_selected_poi"]
                    else "watching"
                )
                hyp = self._phase_c(
                    direction,
                    phase_c_from_e["phase_c_selected_poi"],
                    status,
                    cursor_time,
                    debug,
                    phase_sub_status="hard_pullback",
                )
                return self._commit(hyp)

            if (
                self.state.previous_phase != "B"
                and self.state.phase_e_shadow_node == "E.pullback_developing"
                and phase_c_from_e["phase_c_story_ready"]
            ):
                debug.update(
                    {
                        **phase_c_from_e,
                        "phase_c_origin_node": "E.pullback_developing",
                        "phase_c_sub_status": "slow_pullback",
                        "phase_c_selection_reason": "ltf_pd_flipped_counter_after_failed_e_continuation_attempt",
                    }
                )
                status: HypothesisStatus = "armed" if phase_c_from_e["phase_c_selected_poi"] else "watching"
                hyp = self._phase_c(
                    direction,
                    phase_c_from_e["phase_c_selected_poi"],
                    status,
                    cursor_time,
                    debug,
                    phase_sub_status="slow_pullback",
                )
                return self._commit(hyp)

            if self.state.previous_phase == "B":
                previous_b_sub_status = (
                    self.state.current_hypothesis.phase_sub_status
                    if self.state.current_hypothesis
                    and self.state.current_hypothesis.phase == "B"
                    else None
                )
                if previous_b_sub_status and previous_b_sub_status.startswith("initiation_watch"):
                    phase_c = self._phase_c_setup(snapshot, ltf, direction)
                    phase_d = self._phase_d_setup(snapshot, htf, ltf, direction, current_bar)
                    phase_b_initiation = self._phase_b_initiation_setup(snapshot, direction)
                    debug.update(phase_c)
                    debug.update(phase_d)
                    debug.update(phase_b_initiation)
                    debug["phase_b_initiation_counter_itr_grab_seen"] = (
                        self._phase_b_initiation_counter_itr_grab_seen(phase_b_initiation)
                    )
                    debug["phase_b_initiation_failure_evidence_seen"] = (
                        self._phase_b_initiation_failure_evidence_seen(phase_c, phase_d)
                    )
                    debug["phase_b_initiation_source_anchor_run_seen"] = (
                        self._phase_b_initiation_source_anchor_run_seen(phase_b_initiation)
                    )
                    if self._phase_b_initiation_no_followthrough(previous_b_sub_status, phase_b_initiation):
                        debug.update(
                            {
                                "phase_c_origin_node": (
                                    f"B.{previous_b_sub_status}"
                                    if previous_b_sub_status
                                    else "B.initiation_watch"
                                ),
                                "phase_c_sub_status": "pullback.no_followthrough",
                                "phase_c_selection_reason": "b_initiation_watch_source_itr_anchor_was_run",
                            }
                        )
                        status: HypothesisStatus = "armed" if phase_c["phase_c_selected_poi"] else "watching"
                        hyp = self._phase_c(
                            direction,
                            phase_c["phase_c_selected_poi"],
                            status,
                            cursor_time,
                            debug,
                            phase_sub_status="pullback.no_followthrough",
                        )
                    elif self._phase_b_initiation_failed_to_c(previous_b_sub_status, phase_c, phase_d):
                        debug.update(
                            {
                                "phase_c_origin_node": (
                                    f"B.{previous_b_sub_status}"
                                    if previous_b_sub_status
                                    else "B.initiation_watch"
                                ),
                                "phase_c_sub_status": "pullback.no_followthrough",
                                "phase_c_selection_reason": "b_initiation_watch_decision_failed_with_ltf_counter_confirmation",
                            }
                        )
                        status: HypothesisStatus = "armed" if phase_c["phase_c_selected_poi"] else "watching"
                        hyp = self._phase_c(
                            direction,
                            phase_c["phase_c_selected_poi"],
                            status,
                            cursor_time,
                            debug,
                            phase_sub_status="pullback.no_followthrough",
                        )
                    elif self._phase_b_initiation_rejected(previous_b_sub_status, phase_c, phase_d):
                        debug.update(
                            {
                                "phase_c_origin_node": "B.initiation_watch",
                                "phase_c_sub_status": "pullback.after_inducement",
                                "phase_c_selection_reason": "b_initiation_watch_rejected_by_htf_reaction_and_ltf_counter_flow",
                            }
                        )
                        status: HypothesisStatus = "armed" if phase_c["phase_c_selected_poi"] else "watching"
                        hyp = self._phase_c(
                            direction,
                            phase_c["phase_c_selected_poi"],
                            status,
                            cursor_time,
                            debug,
                            phase_sub_status="pullback.after_inducement",
                        )
                    elif debug.get("new_htf_extreme"):
                        hyp = self._phase_e(
                            direction,
                            cursor_time,
                            {
                                **debug,
                                "phase_b_initiation_resolved_to_e": True,
                                "phase_b_initiation_resolution_reason": "new_htf_extreme_after_initiation_watch",
                            },
                            ltf,
                        )
                    else:
                        next_b_sub_status = self._phase_b_initiation_next_sub_status(
                            previous_b_sub_status,
                            phase_b_initiation,
                            phase_c,
                            phase_d,
                        )
                        hyp = self._carry_current_hypothesis(
                            cursor_time,
                            {
                                **debug,
                                "phase_b_initiation_held": True,
                                "phase_b_held_reason": "initiation_watch_waiting_for_market_to_reveal_branch",
                                "phase_b_initiation_previous_sub_status": previous_b_sub_status,
                                "phase_b_initiation_next_sub_status": next_b_sub_status,
                            },
                            phase_sub_status=next_b_sub_status,
                        )
                    return self._commit(hyp)

                if previous_b_sub_status and previous_b_sub_status.startswith("shallow_reclaim"):
                    phase_d = self._phase_d_setup(snapshot, htf, ltf, direction, current_bar)
                    phase_b = self._phase_b_setup(snapshot, htf, ltf, direction)
                    phase_b_shadow = self._phase_b_shallow_shadow_facts(
                        snapshot,
                        direction,
                        cursor_time,
                        phase_d,
                    )
                    debug.update(
                        {
                            **phase_d,
                            **phase_b,
                            **phase_b_shadow,
                            "phase_b_shallow_reclaim_blocks_phase_a": True,
                            "phase_b_shallow_reclaim_held": True,
                        }
                    )
                    if debug.get("new_htf_extreme"):
                        hyp = self._phase_e(direction, cursor_time, debug, ltf)
                    elif phase_d["phase_d_ready"] and (
                        phase_d["htf_opposing_sd_reaction"]
                        or phase_d["phase_d_liquidity_ready"]
                    ):
                        phase_d_sub_status = (
                            self._phase_d_sub_status(phase_d)
                            if phase_d["phase_d_liquidity_ready"]
                            else "htf_zone_reclaim_test"
                        )
                        hyp = self._phase_d(
                            direction,
                            cursor_time,
                            {
                                **debug,
                                "phase_d_sub_status": phase_d_sub_status,
                                "phase_d_origin_node": f"B.shallow_reclaim.{phase_b_shadow['phase_b_shadow_status']}",
                                "phase_d_selection_reason": (
                                    self._phase_d_selection_reason(phase_d)
                                    if phase_d["phase_d_liquidity_ready"]
                                    else "htf_opposing_zone_reclaim_after_weakened_shallow_b"
                                    if phase_b_shadow["phase_b_shadow_status"] == "weakened"
                                    else "htf_opposing_zone_reclaim_after_shallow_b"
                                ),
                            },
                            phase_sub_status=phase_d_sub_status,
                        )
                    else:
                        hyp = self._carry_current_hypothesis(
                            cursor_time,
                            {
                                **debug,
                                "phase_b_held_reason": "shallow_reclaim_does_not_unlock_phase_a_budget",
                            },
                            phase_sub_status=phase_b_shadow["phase_b_shadow_phase_sub_status"],
                        )
                    return self._commit(hyp)

                phase_a = self._phase_a_setup(snapshot, htf, ltf, direction)
                debug.update(phase_a)
                if phase_a["phase_a_ready"]:
                    hyp = self._phase_a(direction, phase_a["phase_a_selected_poi"], cursor_time, debug)
                    return self._commit(hyp)

            phase_b_dag_blocked = self._phase_b_blocked_by_dag(direction)
            phase_b = self._phase_b_setup(snapshot, htf, ltf, direction)
            if phase_b_dag_blocked:
                phase_b = {
                    **phase_b,
                    "phase_b_ready": False,
                    "phase_b_blocked_by_dag": True,
                    "phase_b_dag_blocked_reason": "direct_e_to_b_requires_c_origin",
                }
            debug.update(phase_b)
            if phase_b["phase_b_ready"]:
                hyp = self._phase_b(direction, phase_b["phase_b_selected_poi"], cursor_time, debug)
                return self._commit(hyp)

            phase_b_initiation = self._phase_b_initiation_setup(snapshot, direction)
            if phase_b_dag_blocked:
                phase_b_initiation = {
                    **phase_b_initiation,
                    "phase_b_initiation_ready": False,
                    "phase_b_initiation_blocked_by_dag": True,
                    "phase_b_initiation_dag_blocked_reason": "direct_e_to_b_requires_c_origin",
                }
            debug.update(phase_b_initiation)
            if phase_b_initiation["phase_b_initiation_ready"]:
                hyp = self._phase_b_initiation_watch(direction, cursor_time, debug)
                return self._commit(hyp)

            if phase == "open" or (
                phase == "pullback_confirmed"
                and self.state.previous_phase == "E"
            ):
                if phase == "pullback_confirmed":
                    debug["phase_e_hold_reason"] = "pullback_confirmed_without_explicit_exit"
                hyp = self._phase_e(direction, cursor_time, debug, ltf)
                return self._commit(hyp)

        if bias == "neutral" or direction == "none":
            hyp = self._none(
                "HTF bias is neutral; no directional hypothesis",
                ["directional_htf_bias"],
                "HTF bias becomes directional",
                cursor_time,
                debug,
                none_sub_status=(
                    "warmup_waiting_for_first_closed_htf"
                    if waiting_for_first_closed_htf else "htf_neutral"
                ),
            )
            return self._commit(hyp)

        hyp = self._none(
            "E/D/C/B classifier slice found no tradable hypothesis; waiting for A classifier",
            ["phase_a_classifier"],
            "Next classifier slice defines this pullback/continuation state",
            cursor_time,
            debug,
            none_sub_status="htf_resolve_unclassified",
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
        d_gate, facts = _ec_candidate(snapshot, "htf_counter_reaction")
        ready = d_gate.get("status") == "ready"
        choch_gate, choch_facts = _ec_candidate(snapshot, "ltf_counter_choch")

        # Derive liquidity selection from EC candidates (Layer 4 owns this decision).
        _candidates = facts.get("liquidity_reclaim_candidates") or []
        _ready_ids = set(facts.get("liquidity_reclaim_ready_event_ids") or [])
        _first_ready = next(
            (c for c in _candidates if c.get("liquidity_event_id") in _ready_ids),
            None,
        )
        _kind = _first_ready.get("pool_kind") if _first_ready else None
        _kind_to_node = {"htf_pd": "D.htf_pd_grab_reclaim_test", "htf_eq": "D.htf_eq_grab_reclaim_test"}
        _kind_to_trigger = {"htf_pd": "pd_liquidity_grab_reclaim", "htf_eq": "eq_liquidity_grab_reclaim"}
        liq_selected_node = _kind_to_node.get(_kind or "")
        liq_trigger = _kind_to_trigger.get(_kind or "")
        liq_ready = bool(_first_ready)

        return {
            "phase_d_ready": ready,
            "phase_d_trigger": liq_trigger or facts.get("trigger"),
            "htf_pd_stopped_expanding": bool(facts.get("htf_pd_stopped_expanding")),
            "new_htf_extreme": bool(facts.get("new_htf_extreme")),
            "htf_opposing_sd_reaction": bool(facts.get("htf_opposing_sd_reaction")),
            "htf_sd_confirmed_pullback": bool(facts.get("htf_sd_confirmed_pullback")),
            "htf_opposing_sd_tapped": bool(facts.get("htf_opposing_sd_tapped")),
            "htf_opposing_sd_resolved": bool(facts.get("htf_opposing_sd_resolved")),
            "htf_last_resolved_zone_id": facts.get("htf_last_resolved_zone_id"),
            "htf_last_resolved_zone_direction": facts.get("htf_last_resolved_zone_direction"),
            "htf_last_resolved_zone_resolution": facts.get("htf_last_resolved_zone_resolution"),
            "htf_opposing_sd_zone_ids": facts.get("htf_opposing_sd_zone_ids") or [],
            "ltf_counter_sd_created": bool(facts.get("ltf_counter_sd_created")),
            "ltf_counter_sd_zone_ids": facts.get("ltf_counter_sd_zone_ids") or [],
            "ltf_bias_counter_htf": bool(facts.get("ltf_bias_counter_htf")),
            "phase_d_liquidity_ready": liq_ready,
            "phase_d_liquidity_test_status": "pending_outcome" if liq_ready else None,
            "phase_d_reaction_confirmed": False,
            "phase_d_liquidity_trigger": liq_trigger,
            "phase_d_liquidity_candidate_nodes": [n for n in [liq_selected_node] if n],
            "phase_d_liquidity_selected_node": liq_selected_node,
            "phase_d_liquidity_selection_reason": facts.get("phase_d_liquidity_selection_reason"),
            "phase_d_liquidity_expected_direction": facts.get("liquidity_reclaim_expected_direction"),
            "phase_d_liquidity_pool_id": _first_ready.get("pool_id") if _first_ready else None,
            "phase_d_liquidity_level": _first_ready.get("level") if _first_ready else None,
            "phase_d_liquidity_source": _first_ready.get("source") if _first_ready else None,
            "phase_d_liquidity_side": _first_ready.get("side") if _first_ready else None,
            "phase_d_liquidity_direction": _first_ready.get("direction") if _first_ready else None,
            "phase_d_liquidity_confirmed_by": facts.get("phase_d_liquidity_confirmed_by"),
            "phase_d_liquidity_confirmed_at": facts.get("phase_d_liquidity_confirmed_at"),
            "htf_pd_grab_reclaim_ready": facts.get("htf_pd_grab_reclaim_ready"),
            "htf_pd_grab_reclaim_direction": facts.get("htf_pd_grab_reclaim_direction"),
            "htf_pd_grab_reclaim_pool_id": facts.get("htf_pd_grab_reclaim_pool_id"),
            "htf_eq_grab_reclaim_ready": facts.get("htf_eq_grab_reclaim_ready"),
            "htf_eq_grab_reclaim_direction": facts.get("htf_eq_grab_reclaim_direction"),
            "htf_eq_grab_reclaim_pool_id": facts.get("htf_eq_grab_reclaim_pool_id"),
            "ltf_counter_choch_seen": bool(choch_facts.get("ltf_counter_choch_seen")),
            "ltf_counter_choch_event_at": choch_facts.get("ltf_counter_choch_event_at"),
            "ltf_counter_choch_direction": choch_facts.get("ltf_counter_choch_direction"),
            "ltf_counter_choch_level": choch_facts.get("ltf_counter_choch_level"),
        }

    def _phase_d_liquidity_grab_setup(
        self,
        snapshot: dict[str, Any],
        direction: Direction,
    ) -> dict[str, Any]:
        liquidity = _liquidity_snapshot(snapshot)
        expected_grab_direction = (
            "bearish"
            if direction == "long"
            else "bullish"
            if direction == "short"
            else None
        )
        candidates: list[str] = []

        pd_ready = bool(
            expected_grab_direction
            and liquidity.get("htf_pd_grab_reclaim_ready")
            and liquidity.get("htf_pd_grab_reclaim_direction") == expected_grab_direction
        )
        eq_ready = bool(
            expected_grab_direction
            and liquidity.get("htf_eq_grab_reclaim_ready")
            and liquidity.get("htf_eq_grab_reclaim_direction") == expected_grab_direction
        )
        if pd_ready:
            candidates.append("D.htf_pd_grab_reclaim_test")
        if eq_ready:
            candidates.append("D.htf_eq_grab_reclaim_test")

        selected_node = candidates[0] if candidates else None
        selected_kind = (
            "pd"
            if selected_node == "D.htf_pd_grab_reclaim_test"
            else "eq"
            if selected_node == "D.htf_eq_grab_reclaim_test"
            else None
        )
        prefix = f"htf_{selected_kind}_grab_reclaim" if selected_kind else None
        return {
            "phase_d_liquidity_ready": bool(selected_node),
            "phase_d_liquidity_test_status": "pending_outcome" if selected_node else None,
            "phase_d_reaction_confirmed": False,
            "phase_d_liquidity_trigger": (
                f"{selected_kind}_liquidity_grab_reclaim"
                if selected_kind
                else None
            ),
            "phase_d_liquidity_candidate_nodes": candidates,
            "phase_d_liquidity_selected_node": selected_node,
            "phase_d_liquidity_selection_reason": (
                "layer3_liquidity_grab_reclaim_ready"
                if selected_node
                else None
            ),
            "phase_d_liquidity_expected_direction": expected_grab_direction,
            "phase_d_liquidity_pool_id": liquidity.get(f"{prefix}_pool_id") if prefix else None,
            "phase_d_liquidity_level": liquidity.get(f"{prefix}_level") if prefix else None,
            "phase_d_liquidity_source": liquidity.get(f"{prefix}_source") if prefix else None,
            "phase_d_liquidity_side": liquidity.get(f"{prefix}_side") if prefix else None,
            "phase_d_liquidity_direction": liquidity.get(f"{prefix}_direction") if prefix else None,
            "phase_d_liquidity_confirmed_by": liquidity.get(f"{prefix}_confirmed_by") if prefix else None,
            "phase_d_liquidity_confirmed_at": liquidity.get(f"{prefix}_confirmed_at") if prefix else None,
            "htf_pd_grab_reclaim_ready": liquidity.get("htf_pd_grab_reclaim_ready"),
            "htf_pd_grab_reclaim_direction": liquidity.get("htf_pd_grab_reclaim_direction"),
            "htf_pd_grab_reclaim_pool_id": liquidity.get("htf_pd_grab_reclaim_pool_id"),
            "htf_eq_grab_reclaim_ready": liquidity.get("htf_eq_grab_reclaim_ready"),
            "htf_eq_grab_reclaim_direction": liquidity.get("htf_eq_grab_reclaim_direction"),
            "htf_eq_grab_reclaim_pool_id": liquidity.get("htf_eq_grab_reclaim_pool_id"),
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

    def _phase_b_blocked_by_dag(self, direction: Direction) -> bool:
        """Block new B evaluation from active E; E must mature through C first."""
        return self._previous_or_active_e(direction) and self.state.previous_phase != "C"

    def _phase_d_reaction_point_origin_node(self) -> str:
        current = self.state.current_hypothesis
        if current and current.phase == "E" and current.phase_sub_status:
            return f"E.{current.phase_sub_status}"
        return "E"

    def _phase_d_sub_status(self, phase_d: dict[str, Any]) -> str:
        selected_node = phase_d.get("phase_d_liquidity_selected_node")
        if selected_node == "D.htf_pd_grab_reclaim_test":
            return "htf_pd_grab_reclaim_test"
        if selected_node == "D.htf_eq_grab_reclaim_test":
            return "htf_eq_grab_reclaim_test"
        return "reaction_point"

    def _phase_d_origin_node(self, phase_d: dict[str, Any]) -> str:
        if phase_d.get("phase_d_liquidity_ready"):
            current = self.state.current_hypothesis
            if current and current.phase in {"E", "B", "C"}:
                return f"{current.phase}.{current.phase_sub_status}" if current.phase_sub_status else current.phase
        return self._phase_d_reaction_point_origin_node()

    def _phase_d_selection_reason(self, phase_d: dict[str, Any]) -> str:
        if phase_d.get("phase_d_liquidity_ready"):
            selected = phase_d.get("phase_d_liquidity_selected_node")
            if selected == "D.htf_pd_grab_reclaim_test":
                return "htf_pd_liquidity_grab_reclaim_ready"
            if selected == "D.htf_eq_grab_reclaim_test":
                return "htf_eq_liquidity_grab_reclaim_ready"
            return "layer3_liquidity_grab_reclaim_ready"
        return "first_contact_after_phase_e"

    def _phase_c_sub_status_from_current_d(self) -> str | None:
        current = self.state.current_hypothesis
        if not current or current.phase != "D":
            return None
        if current.phase_sub_status in {
            "reaction_point",
            "htf_zone_reclaim_test",
            "htf_pd_level_reclaim_test",
        }:
            return "htf_reaction_pullback"
        if current.phase_sub_status in {
            "htf_pd_grab_reclaim_test",
            "htf_eq_grab_reclaim_test",
        }:
            return "htf_reaction_pullback"
        return None

    def _phase_d_reaction_confirmed(self, phase_c: dict[str, Any]) -> bool:
        current = self.state.current_hypothesis
        if not current or current.phase != "D":
            return False
        if current.phase_sub_status not in {
            "htf_pd_grab_reclaim_test",
            "htf_eq_grab_reclaim_test",
        }:
            return True
        return bool(
            phase_c.get("phase_c_ltf_counter_pd_break")
            or phase_c.get("phase_c_ltf_counter_pullback_confirmed")
            or phase_c.get("phase_c_selected_poi_touched")
        )

    def _phase_c_origin_debug_from_current_d(
        self,
        phase_c_sub_status: str | None,
        selection_reason: str,
    ) -> dict[str, Any]:
        current = self.state.current_hypothesis
        phase_d_sub_status = (
            current.phase_sub_status
            if current and current.phase == "D"
            else None
        )
        return {
            "phase_c_origin_node": (
                f"D.{phase_d_sub_status}"
                if phase_d_sub_status
                else "D"
            ),
            "phase_c_sub_status": phase_c_sub_status,
            "phase_c_selection_reason": selection_reason,
            "phase_d_reaction_confirmed": True,
        }

    def _phase_c_fast_hard_pullback_setup(
        self,
        debug: dict[str, Any],
        phase_c: dict[str, Any],
    ) -> dict[str, Any]:
        depth = debug.get("phase_e_context_ltf_pullback_depth_pct")
        try:
            depth_value = float(depth) if depth is not None else None
        except (TypeError, ValueError):
            depth_value = None
        ready = bool(
            debug.get("phase_e_context_status") == "ready"
            and not debug.get("phase_e_context_new_htf_extreme")
            and debug.get("phase_e_context_htf_pd_stopped_expanding")
            and debug.get("phase_e_context_ltf_counter_orderflow_clean")
            and not debug.get("phase_e_context_ltf_counter_orderflow_broken")
            and depth_value is not None
            and depth_value >= 50.0
        )
        return {
            "phase_c_fast_hard_pullback_ready": ready,
            "phase_c_fast_hard_pullback_depth_pct": depth_value,
            "phase_c_fast_hard_pullback_threshold_pct": 50.0,
            "phase_c_fast_hard_pullback_source_orderflow_leg_id": debug.get(
                "phase_e_context_ltf_counter_orderflow_leg_id"
            ),
            "phase_c_origin_node": "E.fast_hard_pullback",
            "phase_c_sub_status": "hard_pullback" if ready else phase_c.get("phase_c_sub_status"),
            "phase_c_selection_reason": (
                "fast_midpoint_pullback_after_phase_e_expansion"
                if ready
                else phase_c.get("phase_c_selection_reason")
            ),
            "phase_c_quality": (
                "choppy_tight_range_fast_pullback"
                if ready
                else phase_c.get("phase_c_quality")
            ),
        }

    def _phase_c_setup(
        self,
        snapshot: dict[str, Any],
        ltf: dict[str, Any] | None,
        prior_direction: Direction,
    ) -> dict[str, Any]:
        counter_zone_direction = "supply" if prior_direction == "long" else "demand"
        ltf_counter_break_direction = "down" if prior_direction == "long" else "up"
        c_gate, facts = _ec_candidate(snapshot, "ltf_counter_story")
        selected_poi = facts.get("selected_poi")
        story_ready = c_gate.get("status") == "ready"
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
            "phase_c_ltf_counter_sd_zone_ids": facts.get("ltf_counter_sd_zone_ids") or [],
            "phase_c_ltf_counter_sd_returned": facts.get("ltf_counter_sd_returned_zone_ids") or [],
            "phase_c_selected_poi_id": selected_poi.get("zone_id") if selected_poi else None,
            "phase_c_selected_poi": selected_poi,
            "phase_c_ltf_bias_counter_htf": bool(facts.get("ltf_bias_counter_htf")),
            "phase_c_ltf_counter_pd_break": bool(facts.get("ltf_counter_pd_break")),
            "phase_c_ltf_counter_break_direction": ltf_counter_break_direction,
            "phase_c_ltf_counter_pullback_confirmed": bool(facts.get("ltf_counter_pullback_confirmed")),
            "phase_c_selected_poi_touched": touched,
        }

    def _phase_b_initiation_setup(
        self,
        snapshot: dict[str, Any],
        direction: Direction,
    ) -> dict[str, Any]:
        liquidity = _liquidity_snapshot(snapshot)
        b_init, b_initiation = _ec_b_initiation(snapshot)
        expected_direction = (
            "bullish"
            if direction == "long"
            else "bearish"
            if direction == "short"
            else None
        )
        previous_c_node = (
            f"C.{self.state.current_hypothesis.phase_sub_status}"
            if self.state.previous_phase == "C"
            and self.state.current_hypothesis
            and self.state.current_hypothesis.phase == "C"
            and self.state.current_hypothesis.phase_sub_status
            else "C"
            if self.state.previous_phase == "C"
            else None
        )
        valid_origin = previous_c_node in {
            "C.htf_reaction_pullback",
            "C.slow_pullback",
            "C.hard_pullback",
            "C.pullback.no_followthrough",
            "C.pullback.after_inducement",
        }
        source_seen = bool(b_initiation.get("source_itr_grab_seen"))
        opposite_seen = bool(b_initiation.get("opposite_itr_grab_seen"))
        decision_zones = [
            str(zone_id)
            for zone_id in b_initiation.get("decision_zone_ids") or []
            if zone_id
        ]
        ready = bool(valid_origin and b_init.get("status") == "ready")
        facts = {
            "phase_b_initiation_ready": ready,
            "phase_b_initiation_candidate": bool(b_initiation.get("htf_itr_grab_reclaim_ready")),
            "phase_b_initiation_origin_node": previous_c_node,
            "phase_b_initiation_valid_origin": valid_origin,
            "phase_b_initiation_expected_direction": expected_direction,
            "phase_b_initiation_ec_present": bool(b_init),
            "phase_b_initiation_source_itr_grab_seen": source_seen,
            "phase_b_initiation_opposite_itr_grab_seen": opposite_seen,
            "phase_b_initiation_decision_zone_seen": bool(
                b_initiation.get("decision_zone_seen")
            ),
            "phase_b_initiation_decision_zone_ids": decision_zones,
            "phase_b_initiation_decision_zone_stack_index": b_initiation.get(
                "decision_zone_stack_index"
            ),
            "phase_b_initiation_source_pool_id": b_initiation.get("source_pool_id"),
            "phase_b_initiation_opposite_pool_id": b_initiation.get("opposite_pool_id"),
            "phase_b_initiation_source_anchor_run_seen": bool(
                b_initiation.get("source_anchor_run_seen")
            ),
            "phase_b_initiation_selection_reason": (
                "source_and_opposite_itr_grabs_with_htf_decision_zone"
                if ready
                else None
            ),
            "htf_itr_grab_reclaim_ready": b_initiation.get("htf_itr_grab_reclaim_ready", liquidity.get("htf_itr_grab_reclaim_ready")),
            "htf_itr_grab_reclaim_variant": b_initiation.get("htf_itr_grab_reclaim_variant", liquidity.get("htf_itr_grab_reclaim_variant")),
            "htf_itr_grab_reclaim_direction": b_initiation.get("htf_itr_grab_reclaim_direction", liquidity.get("htf_itr_grab_reclaim_direction")),
            "htf_itr_grab_reclaim_side": b_initiation.get("htf_itr_grab_reclaim_side", liquidity.get("htf_itr_grab_reclaim_side")),
            "htf_itr_grab_reclaim_source": b_initiation.get("htf_itr_grab_reclaim_source", liquidity.get("htf_itr_grab_reclaim_source")),
            "htf_itr_grab_reclaim_level": b_initiation.get("htf_itr_grab_reclaim_level", liquidity.get("htf_itr_grab_reclaim_level")),
            "htf_itr_grab_reclaim_pool_id": b_initiation.get("htf_itr_grab_reclaim_pool_id", liquidity.get("htf_itr_grab_reclaim_pool_id")),
            "htf_itr_grab_reclaim_came_from": b_initiation.get("htf_itr_grab_reclaim_came_from", liquidity.get("htf_itr_grab_reclaim_came_from")),
            "htf_itr_grab_reclaim_left_to": b_initiation.get("htf_itr_grab_reclaim_left_to", liquidity.get("htf_itr_grab_reclaim_left_to")),
            "htf_itr_level_grab_reclaim_ready": b_initiation.get("htf_itr_level_grab_reclaim_ready", liquidity.get("htf_itr_level_grab_reclaim_ready")),
            "htf_itr_eq_grab_reclaim_ready": b_initiation.get("htf_itr_eq_grab_reclaim_ready", liquidity.get("htf_itr_eq_grab_reclaim_ready")),
            "htf_itr_anchor_run_ready": b_initiation.get("htf_itr_anchor_run_ready", liquidity.get("htf_itr_anchor_run_ready")),
            "htf_itr_anchor_run_variant": b_initiation.get("htf_itr_anchor_run_variant", liquidity.get("htf_itr_anchor_run_variant")),
            "htf_itr_anchor_run_direction": b_initiation.get("htf_itr_anchor_run_direction", liquidity.get("htf_itr_anchor_run_direction")),
            "htf_itr_anchor_run_side": b_initiation.get("htf_itr_anchor_run_side", liquidity.get("htf_itr_anchor_run_side")),
            "htf_itr_anchor_run_source": b_initiation.get("htf_itr_anchor_run_source", liquidity.get("htf_itr_anchor_run_source")),
            "htf_itr_anchor_run_level": b_initiation.get("htf_itr_anchor_run_level", liquidity.get("htf_itr_anchor_run_level")),
            "htf_itr_anchor_run_pool_id": b_initiation.get("htf_itr_anchor_run_pool_id", liquidity.get("htf_itr_anchor_run_pool_id")),
            "htf_itr_anchor_run_take_type": b_initiation.get("htf_itr_anchor_run_take_type", liquidity.get("htf_itr_anchor_run_take_type")),
            "htf_itr_anchor_run_at": b_initiation.get("htf_itr_anchor_run_at", liquidity.get("htf_itr_anchor_run_at")),
            "htf_itr_level_anchor_run_ready": b_initiation.get("htf_itr_level_anchor_run_ready", liquidity.get("htf_itr_level_anchor_run_ready")),
            "htf_itr_eq_anchor_run_ready": b_initiation.get("htf_itr_eq_anchor_run_ready", liquidity.get("htf_itr_eq_anchor_run_ready")),
        }
        if ready:
            facts.update(
                {
                    "phase_b_candidate_variant": "initiation_watch",
                    "phase_b_sub_status": "initiation_watch.decisive",
                    "phase_b_origin_node": previous_c_node,
                }
            )
        return facts

    def _phase_b_initiation_rejected(
        self,
        previous_b_sub_status: str | None,
        phase_c: dict[str, Any],
        phase_d: dict[str, Any],
    ) -> bool:
        return bool(
            previous_b_sub_status == "initiation_watch.weakened"
            and phase_c.get("phase_c_story_ready")
            and phase_d.get("htf_opposing_sd_resolved")
        )

    def _phase_b_initiation_failure_evidence_seen(
        self,
        phase_c: dict[str, Any],
        phase_d: dict[str, Any],
    ) -> bool:
        return bool(
            phase_c.get("phase_c_ltf_counter_pd_break")
            or phase_c.get("phase_c_ltf_counter_pullback_confirmed")
            or phase_d.get("htf_opposing_sd_tapped")
            or phase_d.get("htf_opposing_sd_resolved")
        )

    def _phase_b_initiation_no_followthrough(
        self,
        previous_b_sub_status: str | None,
        phase_b_initiation: dict[str, Any],
    ) -> bool:
        return bool(
            previous_b_sub_status in {
                "initiation_watch.decisive",
                "initiation_watch.stalled",
            }
            and self._phase_b_initiation_source_anchor_run_seen(phase_b_initiation)
        )

    def _phase_b_initiation_failed_to_c(
        self,
        previous_b_sub_status: str | None,
        phase_c: dict[str, Any],
        phase_d: dict[str, Any],
    ) -> bool:
        return bool(
            previous_b_sub_status in {
                "initiation_watch.decisive",
                "initiation_watch.stalled",
            }
            and phase_c.get("phase_c_story_ready")
            and self._phase_b_initiation_failure_evidence_seen(phase_c, phase_d)
        )

    def _phase_b_initiation_next_sub_status(
        self,
        previous_b_sub_status: str | None,
        phase_b_initiation: dict[str, Any],
        phase_c: dict[str, Any],
        phase_d: dict[str, Any],
    ) -> str:
        if previous_b_sub_status == "initiation_watch.weakened":
            return "initiation_watch.weakened"
        if previous_b_sub_status == "initiation_watch.contested":
            if phase_d.get("htf_opposing_sd_tapped") or phase_d.get("htf_opposing_sd_resolved"):
                return "initiation_watch.weakened"
            return "initiation_watch.contested"
        if previous_b_sub_status == "initiation_watch.stalled":
            return "initiation_watch.stalled"
        if previous_b_sub_status == "initiation_watch.decisive":
            if self._phase_b_initiation_failure_evidence_seen(phase_c, phase_d):
                return "initiation_watch.stalled"
            return "initiation_watch.decisive"
        if self._phase_b_initiation_counter_itr_grab_seen(phase_b_initiation):
            return "initiation_watch.decisive"
        return "initiation_watch.active"

    def _phase_b_initiation_counter_itr_grab_seen(
        self,
        phase_b_initiation: dict[str, Any],
    ) -> bool:
        if phase_b_initiation.get("phase_b_initiation_opposite_itr_grab_seen"):
            return True
        current = self.state.current_hypothesis
        if not current or current.phase != "B":
            return False
        expected_direction = "bearish" if current.direction == "long" else "bullish"
        expected_sources = (
            {"htf_itr_high", "htf_itr_eqh"}
            if current.direction == "long"
            else {"htf_itr_low", "htf_itr_eql"}
        )
        return bool(
            phase_b_initiation.get("htf_itr_grab_reclaim_ready")
            and phase_b_initiation.get("htf_itr_grab_reclaim_direction") == expected_direction
            and phase_b_initiation.get("htf_itr_grab_reclaim_source") in expected_sources
        )

    def _phase_b_initiation_source_anchor_run_seen(
        self,
        phase_b_initiation: dict[str, Any],
    ) -> bool:
        if phase_b_initiation.get("phase_b_initiation_source_anchor_run_seen"):
            return True
        current = self.state.current_hypothesis
        if not current or current.phase != "B" or not current.poi_id:
            return False
        return bool(
            phase_b_initiation.get("htf_itr_anchor_run_ready")
            and phase_b_initiation.get("htf_itr_anchor_run_pool_id") == current.poi_id
        )

    def _phase_b_setup(
        self,
        snapshot: dict[str, Any],
        htf: dict[str, Any],
        ltf: dict[str, Any] | None,
        direction: Direction,
    ) -> dict[str, Any]:
        pro_zone_direction = "demand" if direction == "long" else "supply"
        b_gate, facts = _ec_candidate(snapshot, "htf_b_phase_setup")
        location = b_gate.get("location_context") or {}
        selected_poi = facts.get("selected_poi")
        htf_pd_value_pct = location.get("htf_pd_value_pct")
        htf_range_position_pct = htf.get("range_position_pct", htf.get("pd_pct"))
        strict_pd_half = bool(facts.get("strict_pd_half"))
        shallow_pd_half = bool(facts.get("shallow_pd_half"))
        phase_b_location = (
            "strict"
            if strict_pd_half
            else "shallow"
            if shallow_pd_half
            else "invalid"
        )

        phase_b_from_c = self.state.previous_phase == "C"
        htf_pullback_context_ready = bool(facts.get("htf_pullback_context_ready") or phase_b_from_c)
        htf_pullback_evidence = bool(facts.get("htf_pullback_evidence"))
        ltf_turns_back_toward_htf = bool(facts.get("ltf_turns_back_toward_htf"))
        htf_pro_sd_tapped = bool(facts.get("htf_pro_sd_tapped"))
        htf_pro_sd_resolved = bool(facts.get("htf_pro_sd_resolved"))
        htf_pro_sd_reaction = htf_pro_sd_tapped or htf_pro_sd_resolved
        ltf_pro_sd_selected = selected_poi is not None
        base_candidate = (
            htf_pullback_context_ready
            and (strict_pd_half or shallow_pd_half)
            and ltf_turns_back_toward_htf
            and ltf_pro_sd_selected
        )
        strict_ready = (
            base_candidate
            and strict_pd_half
            and htf_pro_sd_reaction
        )
        shallow_ready = (
            base_candidate
            and shallow_pd_half
            and htf_pro_sd_reaction
        )
        if b_gate.get("status") != "ready":
            strict_ready = False
            shallow_ready = False
            if phase_b_from_c and base_candidate and htf_pro_sd_reaction:
                strict_ready = strict_pd_half
                shallow_ready = shallow_pd_half
        candidate_variant = None
        blocked_reason = None
        if strict_ready:
            candidate_variant = "strict"
        elif shallow_ready:
            candidate_variant = "shallow_htf_sd_mitigation"
        elif base_candidate and strict_pd_half and not htf_pro_sd_reaction:
            if not facts.get("htf_pro_sd_zone_ids"):
                candidate_variant = "missing_htf_reaction_zone"
            else:
                candidate_variant = "missing_htf_reaction"
            blocked_reason = (
                "no_htf_demand_reaction"
                if direction == "long"
                else "no_htf_supply_reaction"
            )
        elif base_candidate and shallow_pd_half and not htf_pro_sd_reaction:
            blocked_reason = (
                "no_htf_demand_reaction"
                if direction == "long"
                else "no_htf_supply_reaction"
            )
        elif base_candidate:
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
            "phase_b_ready": strict_ready or shallow_ready,
            "phase_b_candidate": bool(candidate_variant),
            "phase_b_candidate_variant": candidate_variant,
            "phase_b_blocked_reason": blocked_reason,
            "phase_b_direction": direction,
            "phase_b_pro_zone_direction": pro_zone_direction,
            "phase_b_htf_not_clean_phase_e": htf.get("phase") != "open",
            "phase_b_from_c": phase_b_from_c,
            "phase_b_origin_node": (
                f"C.{self.state.current_hypothesis.phase_sub_status}"
                if phase_b_from_c
                and self.state.current_hypothesis
                and self.state.current_hypothesis.phase_sub_status
                else "C"
                if phase_b_from_c
                else None
            ),
            "phase_b_htf_pullback_context_ready": htf_pullback_context_ready,
            "phase_b_htf_pullback_evidence": htf_pullback_evidence,
            "phase_b_correct_pd_half": strict_pd_half,
            "phase_b_strict_pd_half": strict_pd_half,
            "phase_b_shallow_pd_half": shallow_pd_half,
            "phase_b_sub_status": (
                "strict_reclaim"
                if strict_ready
                else "shallow_reclaim"
                if shallow_ready
                else None
            ),
            "phase_b_location": phase_b_location,
            "phase_b_htf_pd_value_pct": htf_pd_value_pct,
            "phase_b_htf_range_position_pct": htf_range_position_pct,
            "phase_b_htf_pd_pct": htf_range_position_pct,
            "phase_b_htf_pro_sd_reaction": htf_pro_sd_reaction,
            "phase_b_htf_pro_sd_tapped": htf_pro_sd_tapped,
            "phase_b_htf_pro_sd_resolved": htf_pro_sd_resolved,
            "phase_b_htf_pro_sd_zone_ids": facts.get("htf_pro_sd_zone_ids") or [],
            "phase_b_htf_last_resolved_zone_id": facts.get("htf_last_resolved_zone_id"),
            "phase_b_htf_last_resolved_zone_direction": facts.get("htf_last_resolved_zone_direction"),
            "phase_b_htf_last_resolved_zone_resolution": facts.get("htf_last_resolved_zone_resolution"),
            "phase_b_ltf_turns_back_toward_htf": ltf_turns_back_toward_htf,
            "phase_b_ltf_pro_sd_selected": ltf_pro_sd_selected,
            "phase_b_ltf_pro_sd_zone_ids": facts.get("ltf_pro_sd_zone_ids") or [],
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

    def _phase_a_setup(
        self,
        snapshot: dict[str, Any],
        htf: dict[str, Any],
        ltf: dict[str, Any] | None,
        direction: Direction,
    ) -> dict[str, Any]:
        pro_zone_direction = "demand" if direction == "long" else "supply"
        lower_tf = str(snapshot.get("lower_tf") or "")
        zones = snapshot.get("zones") or []
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

        ltf_bias_aligned = bool(
            ltf
            and ltf.get("bias") == htf.get("bias")
            and _direction_from_bias(ltf.get("bias")) == direction
        )
        ltf_last_sc = ltf.get("last_sc") if ltf else None
        expected_break_direction = "up" if direction == "long" else "down"
        ltf_pd_expands_with_htf = bool(
            ltf_bias_aligned
            and isinstance(ltf_last_sc, dict)
            and ltf_last_sc.get("breakDirection") == expected_break_direction
        )
        selected_poi = lower_pro_zones[0] if lower_pro_zones else None
        ready = bool(
            self.state.previous_phase == "B"
            and ltf_bias_aligned
            and ltf_pd_expands_with_htf
            and selected_poi
        )

        return {
            "phase_a_ready": ready,
            "phase_a_candidate": bool(ltf_bias_aligned and ltf_pd_expands_with_htf),
            "phase_a_direction": direction,
            "phase_a_trade_style": "controlled_chase",
            "phase_a_requires_previous_b": True,
            "phase_a_previous_phase_is_b": self.state.previous_phase == "B",
            "phase_a_pro_zone_direction": pro_zone_direction,
            "phase_a_ltf_bias_aligned": ltf_bias_aligned,
            "phase_a_ltf_pd_expands_with_htf": ltf_pd_expands_with_htf,
            "phase_a_expected_break_direction": expected_break_direction,
            "phase_a_ltf_pro_sd_selected": selected_poi is not None,
            "phase_a_ltf_pro_sd_zone_ids": [zone.get("zone_id") for zone in lower_pro_zones],
            "phase_a_selected_poi_id": selected_poi.get("zone_id") if selected_poi else None,
            "phase_a_selected_poi": selected_poi,
        }

    def _phase_a_finale(
        self,
        snapshot: dict[str, Any],
        direction: Direction,
        htf: dict[str, Any],
        current_bar: dict[str, Any] | None,
    ) -> dict[str, Any]:
        objective = htf.get("range_high") if direction == "long" else htf.get("range_low")
        facts = {
            "phase_a_finale_touched": False,
            "phase_a_finale_closed_beyond": False,
            "phase_a_finale_direction": direction,
            "phase_a_finale_objective": objective,
            "phase_a_finale_rule": None,
        }
        objective_candidate, objective_facts = _ec_candidate(snapshot, "htf_pd_objective")
        if objective_candidate.get("status") == "ready":
            facts.update(
                {
                    "phase_a_finale_touched": bool(objective_facts.get("phase_a_finale_touched")),
                    "phase_a_finale_closed_beyond": bool(objective_facts.get("phase_a_finale_closed_beyond")),
                    "phase_a_finale_direction": objective_facts.get("phase_a_finale_direction", direction),
                    "phase_a_finale_objective": objective_facts.get("phase_a_finale_objective", objective),
                    "phase_a_finale_rule": objective_facts.get("phase_a_finale_rule"),
                    "phase_a_finale_bar_high": objective_facts.get("current_htf_high"),
                    "phase_a_finale_bar_low": objective_facts.get("current_htf_low"),
                    "phase_a_finale_bar_close": objective_facts.get("current_htf_close"),
                }
            )
            return facts
        return facts

    def _phase_e_reaction(
        self,
        snapshot: dict[str, Any],
        direction: Direction,
        current_bar: dict[str, Any] | None,
        previous_bar: dict[str, Any] | None,
    ) -> dict[str, Any]:
        facts = {
            "reaction_confirmed": False,
            "reaction_warning": False,
            "reaction_rule": None,
            "reaction_failed": False,
            "reaction_failed_rule": None,
        }
        phase_e, phase_e_facts = _ec_candidate(snapshot, "phase_e_context")
        if phase_e.get("status") == "ready":
            facts.update(
                {
                    "phase_e_context_status": phase_e.get("status"),
                    "phase_e_context_new_htf_extreme": bool(phase_e_facts.get("new_htf_extreme")),
                    "phase_e_context_htf_pd_stopped_expanding": bool(
                        phase_e_facts.get("htf_pd_stopped_expanding")
                    ),
                    "phase_e_context_ltf_bias_counter_htf": bool(
                        phase_e_facts.get("ltf_bias_counter_htf")
                    ),
                    "phase_e_context_ltf_probe_outside_htf_pd_range": bool(
                        phase_e_facts.get("ltf_probe_outside_htf_pd_range")
                    ),
                    "phase_e_context_ltf_probe_direction": phase_e_facts.get("ltf_probe_direction"),
                    "phase_e_context_htf_equal_extreme_retest": bool(
                        phase_e_facts.get("htf_equal_extreme_retest")
                    ),
                    "phase_e_context_htf_equal_extreme_kind": phase_e_facts.get(
                        "htf_equal_extreme_kind"
                    ),
                    "phase_e_context_htf_equal_extreme_source": phase_e_facts.get(
                        "htf_equal_extreme_source"
                    ),
                    "phase_e_context_htf_equal_extreme_level": phase_e_facts.get(
                        "htf_equal_extreme_level"
                    ),
                    "phase_e_context_htf_equal_extreme_pool_id": phase_e_facts.get(
                        "htf_equal_extreme_pool_id"
                    ),
                    "phase_e_context_htf_equal_extreme_pool_status": phase_e_facts.get(
                        "htf_equal_extreme_pool_status"
                    ),
                    "phase_e_context_htf_eqh_at_phase_e_extreme": bool(
                        phase_e_facts.get("htf_eqh_at_phase_e_extreme")
                    ),
                    "phase_e_context_htf_eql_at_phase_e_extreme": bool(
                        phase_e_facts.get("htf_eql_at_phase_e_extreme")
                    ),
                    "phase_e_context_ltf_counter_orderflow_direction": phase_e_facts.get(
                        "ltf_counter_orderflow_direction"
                    ),
                    "phase_e_context_ltf_counter_orderflow_clean": bool(
                        phase_e_facts.get("ltf_counter_orderflow_clean")
                    ),
                    "phase_e_context_ltf_counter_orderflow_broken": bool(
                        phase_e_facts.get("ltf_counter_orderflow_broken")
                    ),
                    "phase_e_context_ltf_counter_orderflow_leg_id": phase_e_facts.get(
                        "ltf_counter_orderflow_leg_id"
                    ),
                    "phase_e_context_ltf_counter_orderflow_started_at": phase_e_facts.get(
                        "ltf_counter_orderflow_started_at"
                    ),
                    "phase_e_context_ltf_counter_orderflow_quality": phase_e_facts.get(
                        "ltf_counter_orderflow_quality"
                    ),
                    "phase_e_context_ltf_counter_orderflow_regime": phase_e_facts.get(
                        "ltf_counter_orderflow_regime"
                    ),
                    "phase_e_context_ltf_pullback_depth_pct": phase_e_facts.get(
                        "ltf_pullback_depth_pct"
                    ),
                    "new_htf_extreme": bool(phase_e_facts.get("new_htf_extreme")),
                    "htf_pd_stopped_expanding": bool(phase_e_facts.get("htf_pd_stopped_expanding")),
                    "reaction_confirmed": bool(phase_e_facts.get("reaction_confirmed")),
                    "reaction_warning": bool(phase_e_facts.get("reaction_warning")),
                    "reaction_rule": phase_e_facts.get("reaction_rule"),
                    "reaction_failed": bool(phase_e_facts.get("reaction_failed")),
                    "reaction_failed_rule": phase_e_facts.get("reaction_failed_rule"),
                    "previous_htf_low": phase_e_facts.get("previous_htf_low"),
                    "current_htf_low": phase_e_facts.get("current_htf_low"),
                    "previous_htf_high": phase_e_facts.get("previous_htf_high"),
                    "current_htf_high": phase_e_facts.get("current_htf_high"),
                    "current_htf_close": phase_e_facts.get("current_htf_close"),
                }
            )
            return facts
        return facts

    def _reset_phase_e_shadow(self) -> None:
        self.state.phase_e_shadow.reset()

    def _reset_phase_b_shadow(self) -> None:
        self.state.shadow_thesis.reset()

    def _open_phase_b_shallow_shadow(
        self,
        selected_poi: dict[str, Any],
        ts: str | None,
    ) -> dict[str, Any]:
        s = self.state.shadow_thesis
        s.status = "active"
        s.opened_at = ts
        s.selected_poi_id = selected_poi.get("zone_id")
        s.selected_poi_high = (
            float(selected_poi["high"]) if selected_poi.get("high") is not None else None
        )
        s.selected_poi_low = (
            float(selected_poi["low"]) if selected_poi.get("low") is not None else None
        )
        s.first_counter_mitigation_at = None
        s.same_level_return_count = 0
        s.weakening_reason = None
        return self._phase_b_shadow_debug("shallow_b_shadow_opened")

    def _phase_b_shadow_debug(self, selection_reason: str) -> dict[str, Any]:
        s = self.state.shadow_thesis
        return {
            "phase_b_shadow_status": s.status,
            "phase_b_shadow_opened_at": s.opened_at,
            "phase_b_shadow_selected_poi_id": s.selected_poi_id,
            "phase_b_shadow_selected_poi_high": s.selected_poi_high,
            "phase_b_shadow_selected_poi_low": s.selected_poi_low,
            "phase_b_shadow_first_counter_mitigation_at": s.first_counter_mitigation_at,
            "phase_b_shadow_same_level_return_count": s.same_level_return_count,
            "phase_b_shadow_weakening_reason": s.weakening_reason,
            "phase_b_shadow_selection_reason": selection_reason,
            "phase_b_shadow_phase_sub_status": (
                "shallow_reclaim"
                if s.status in {None, "active"}
                else f"shallow_reclaim.{s.status}"
            ),
        }

    def _phase_b_shallow_shadow_facts(
        self,
        snapshot: dict[str, Any],
        direction: Direction,
        cursor_time: str | None,
        phase_d: dict[str, Any],
    ) -> dict[str, Any]:
        s = self.state.shadow_thesis
        if s.status is None:
            s.status = "active"

        previous_status = s.status
        selection_reason = "shallow_b_shadow_held"
        counter_evidence = bool(
            phase_d.get("ltf_counter_sd_created")
            or phase_d.get("ltf_bias_counter_htf")
        )
        had_counter_mitigation = s.first_counter_mitigation_at is not None
        if (
            counter_evidence
            and previous_status == "active"
            and s.first_counter_mitigation_at is None
        ):
            s.status = "contested"
            s.first_counter_mitigation_at = cursor_time
            selection_reason = "ltf_counter_mitigation_contested_shallow_b"

        same_level_return = self._phase_b_same_level_return(snapshot)
        if (
            same_level_return
            and had_counter_mitigation
            and s.status in {"active", "contested"}
        ):
            s.status = "weakened"
            s.same_level_return_count += 1
            s.weakening_reason = "same_level_return_after_ltf_counter_mitigation"
            selection_reason = "same_level_return_weakened_shallow_b"

        return {
            **self._phase_b_shadow_debug(selection_reason),
            "phase_b_shadow_previous_status": previous_status,
            "phase_b_shadow_ltf_counter_evidence": counter_evidence,
            "phase_b_shadow_same_level_return": same_level_return,
        }

    def _phase_b_same_level_return(self, snapshot: dict[str, Any]) -> bool:
        zone_high = self.state.shadow_thesis.selected_poi_high
        zone_low = self.state.shadow_thesis.selected_poi_low
        if zone_high is None or zone_low is None:
            return False

        bar = _cursor_bar(snapshot)
        if not bar:
            return False
        bar_high = float(bar.get("high", bar.get("close", 0.0)))
        bar_low = float(bar.get("low", bar.get("close", 0.0)))
        zone_height = abs(zone_high - zone_low)
        tolerance = max(zone_height, 0.0)
        return bar_low <= zone_high + tolerance and bar_high >= zone_low - tolerance

    def _phase_e_shadow_facts(
        self,
        ltf: dict[str, Any] | None,
        direction: Direction,
        debug: dict[str, Any],
    ) -> dict[str, Any]:
        s = self.state.phase_e_shadow
        previous_node = s.node
        selected_node = previous_node
        selection_reason = "phase_e_shadow_held"
        candidate_nodes: list[str] = []
        # Deprecated: Phase E no longer reads LTF structure_attempt. Clean/broken
        # orderflow facts own E.stalling <-> E.pullback_developing transitions.
        if "phase_e_context_new_htf_extreme" in debug:
            pd_expanding = bool(debug.get("phase_e_context_new_htf_extreme"))
        else:
            pd_expanding = bool(debug.get("new_htf_extreme"))
        orderflow_source_id = debug.get("phase_e_context_ltf_counter_orderflow_leg_id")
        orderflow_clean = bool(debug.get("phase_e_context_ltf_counter_orderflow_clean"))
        orderflow_broken = bool(debug.get("phase_e_context_ltf_counter_orderflow_broken"))
        clean_counter_orderflow = bool(
            orderflow_clean
            and not orderflow_broken
            and orderflow_source_id
            and orderflow_source_id != s.consumed_orderflow_leg_id
        )

        if self.state.previous_phase != "E" or self.state.active_phase_e_direction != direction:
            selected_node = "E.seeking"
            selection_reason = "phase_e_shadow_initialized"
            s.pullback_disrupted = False
            s.disrupted_orderflow_leg_id = None
        elif pd_expanding:
            selected_node = "E.seeking"
            selection_reason = "htf_pd_expanded"
            s.pullback_disrupted = False
            s.disrupted_orderflow_leg_id = None
        elif previous_node == "E.seeking":
            selected_node = "E.stalling"
            selection_reason = "htf_pd_stopped_expanding"
        elif previous_node == "E.stalling":
            if clean_counter_orderflow and not s.pullback_disrupted:
                selected_node = "E.pullback_developing"
                selection_reason = "clean_ltf_counter_orderflow_after_e_stalling"
            elif clean_counter_orderflow and s.pullback_disrupted:
                selected_node = "E.stalling"
                selection_reason = "second_counter_pullback_requires_phase_d_boundary"
            else:
                selected_node = "E.stalling"
        elif previous_node == "E.pullback_developing":
            if orderflow_broken:
                selected_node = "E.stalling"
                selection_reason = "counter_orderflow_disrupted_after_pullback_developing"
                s.pullback_disrupted = True
                s.disrupted_orderflow_leg_id = str(orderflow_source_id) if orderflow_source_id else None
            else:
                selected_node = "E.pullback_developing"

        candidate_nodes.append(selected_node)
        if selected_node != previous_node:
            s.previous_node = previous_node
            s.bars_in_node = 0
        else:
            s.bars_in_node += 1
        s.node = selected_node

        if clean_counter_orderflow:
            source_orderflow_leg_id = str(orderflow_source_id)
            s.source_orderflow_leg_id = source_orderflow_leg_id
            s.source_orderflow_started_at = debug.get("phase_e_context_ltf_counter_orderflow_started_at")
            s.consumed_orderflow_leg_id = source_orderflow_leg_id

        phase_sub_status = selected_node.split(".", 1)[1] if "." in selected_node else None
        return {
            "phase_sub_status": phase_sub_status,
            "phase_e_shadow_node": selected_node,
            "phase_e_shadow_previous_node": previous_node,
            "phase_e_shadow_candidate_nodes": candidate_nodes,
            "phase_e_shadow_selected_node": selected_node,
            "phase_e_shadow_selection_reason": selection_reason,
            "phase_e_shadow_bars_in_node": s.bars_in_node,
            "phase_e_shadow_source_orderflow_leg_id": s.source_orderflow_leg_id,
            "phase_e_shadow_source_orderflow_started_at": s.source_orderflow_started_at,
            "phase_e_shadow_consumed_orderflow_leg_id": s.consumed_orderflow_leg_id,
            "phase_e_shadow_pullback_disrupted": s.pullback_disrupted,
            "phase_e_shadow_disrupted_orderflow_leg_id": s.disrupted_orderflow_leg_id,
            "phase_e_shadow_source_attempt_id": None,  # Deprecated: use source_orderflow_leg_id.
            "phase_e_shadow_source_itr_level_id": None,  # Deprecated: Phase E no longer uses structure_attempt.
            "phase_e_context_attempt_id": None,  # Deprecated: Phase E no longer uses structure_attempt.
            "phase_e_context_attempt_status": None,
            "phase_e_context_attempt_origin": None,
            "phase_e_context_attempt_orderflow_quality": None,
            "phase_e_context_attempt_failure_reason": None,
            "phase_e_context_attempt_anchor_level_id": None,
        }

    def _phase_e(
        self,
        direction: Direction,
        ts: str | None,
        debug: dict[str, Any],
        ltf: dict[str, Any] | None = None,
    ) -> Hypothesis:
        bullish = direction == "long"
        shadow = self._phase_e_shadow_facts(ltf, direction, debug)
        self.state.active_phase_e_direction = direction
        debug = {**debug, **shadow}
        phase_sub_status = shadow["phase_sub_status"]
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
            phase_sub_status=phase_sub_status,
            debug_facts=debug,
        )

    def _phase_d(
        self,
        prior_direction: Direction,
        ts: str | None,
        debug: dict[str, Any],
        phase_sub_status: str | None = None,
    ) -> Hypothesis:
        debug = {**debug, "prior_phase_e_direction": prior_direction}
        is_liquidity_grab = phase_sub_status in {
            "htf_pd_grab_reclaim_test",
            "htf_eq_grab_reclaim_test",
        }
        reason = (
            "HTF liquidity grab/reclaim footprint opened a pending D decision test"
            if is_liquidity_grab
            else "price is at reaction point after ERL / opposing POI interaction"
        )
        if is_liquidity_grab:
            debug = {
                **debug,
                "phase_d_liquidity_test_status": debug.get("phase_d_liquidity_test_status") or "pending_outcome",
                "phase_d_reaction_confirmed": debug.get("phase_d_reaction_confirmed", False),
            }
        return Hypothesis(
            hypothesis_id=self.state.hypothesis_id,
            status="watching",
            phase="D",
            direction="none",
            swing_alignment="none",
            internal_alignment="none",
            poi_id=debug.get("phase_d_liquidity_pool_id") if is_liquidity_grab else None,
            poi_type="liquidity_pool" if is_liquidity_grab else None,
            reason=reason,
            required_evidence=["ltf_counter_internal_story_for_phase_c", "htf_pullback_evidence_for_phase_b"],
            invalidation="Reaction fails and price resumes the original HTF direction",
            target_policy="none",
            fallback_target_policy=None,
            entry_policy="skip",
            created_at=self.state.current_hypothesis.created_at if self.state.current_hypothesis else ts,
            updated_at=ts,
            phase_sub_status=phase_sub_status,
            debug_facts=debug,
        )

    def _phase_c(
        self,
        prior_direction: Direction,
        selected_poi: dict[str, Any] | None,
        status: Literal["watching", "armed"],
        ts: str | None,
        debug: dict[str, Any],
        phase_sub_status: str | None = None,
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
            phase_sub_status=phase_sub_status,
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
        variant = str(debug.get("phase_b_candidate_variant") or "strict")
        if variant == "shallow_htf_sd_mitigation":
            reason = (
                "Shallow bullish B: HTF demand mitigation in shallow natural P/D and LTF flipped back bullish"
                if bullish
                else "Shallow bearish B: HTF supply mitigation in shallow natural P/D and LTF flipped back bearish"
            )
            debug = {
                **debug,
                **self._open_phase_b_shallow_shadow(selected_poi, ts),
            }
        else:
            reason = (
                "Strict bullish B: HTF demand reaction in discount and LTF flipped back bullish"
                if bullish
                else "Strict bearish B: HTF supply reaction in discount and LTF flipped back bearish"
            )
        return Hypothesis(
            hypothesis_id=self.state.hypothesis_id,
            status="armed",
            phase="B",
            direction=direction,
            swing_alignment="pro_swing",
            internal_alignment="counter_internal",
            poi_id=selected_poi.get("zone_id"),
            poi_type="sd_zone",
            reason=reason,
            required_evidence=["entry_protocol_permission", "risk_rr_valid"],
            invalidation="HTF pullback fails to resolve back toward HTF bias",
            target_policy="htf_pd_level",
            fallback_target_policy="fixed_rr",
            entry_policy="hybrid",
            created_at=self.state.current_hypothesis.created_at if self.state.current_hypothesis else ts,
            updated_at=ts,
            phase_sub_status=debug.get("phase_b_sub_status"),
            debug_facts=debug,
        )

    def _phase_b_initiation_watch(
        self,
        direction: Direction,
        ts: str | None,
        debug: dict[str, Any],
    ) -> Hypothesis:
        bullish = direction == "long"
        return Hypothesis(
            hypothesis_id=self.state.hypothesis_id,
            status="watching",
            phase="B",
            direction=direction,
            swing_alignment="pro_swing",
            internal_alignment="counter_internal",
            poi_id=debug.get("phase_b_initiation_source_pool_id") or debug.get("htf_itr_grab_reclaim_pool_id"),
            poi_type=(
                "liquidity_pool"
                if debug.get("phase_b_initiation_source_pool_id") or debug.get("htf_itr_grab_reclaim_pool_id")
                else None
            ),
            reason=(
                "Bullish B.initiation_watch: HTF ITR sell-side liquidity was grabbed/reclaimed; outcome is unresolved"
                if bullish
                else "Bearish B.initiation_watch: HTF ITR buy-side liquidity was grabbed/reclaimed; outcome is unresolved"
            ),
            required_evidence=[
                "fresh_reclaim_for_confirmed_b",
                "opposing_htf_reaction_for_inducement_pullback",
                "market_reveals_branch",
            ],
            invalidation="Initiation loses its protected liquidity anchor or opposing HTF reaction rejects it",
            target_policy="liquidity_target",
            fallback_target_policy="fixed_rr",
            entry_policy="wait",
            created_at=self.state.current_hypothesis.created_at if self.state.current_hypothesis else ts,
            updated_at=ts,
            phase_sub_status=debug.get("phase_b_sub_status") or "initiation_watch.active",
            debug_facts={
                **debug,
                "phase_b_budget_policy": "casino_ticket",
                "phase_b_entry_policy_detail": "probe_or_skip",
                "phase_b_confidence": "low",
            },
        )

    def _phase_a(
        self,
        direction: Direction,
        selected_poi: dict[str, Any],
        ts: str | None,
        debug: dict[str, Any],
    ) -> Hypothesis:
        bullish = direction == "long"
        reason = (
            "Bullish A: pullback resolved after Phase B and LTF P/D expands with HTF"
            if bullish
            else "Bearish A: pullback resolved after Phase B and LTF P/D expands with HTF"
        )
        return Hypothesis(
            hypothesis_id=self.state.hypothesis_id,
            status="armed",
            phase="A",
            direction=direction,
            swing_alignment="pro_swing",
            internal_alignment="pro_internal",
            poi_id=selected_poi.get("zone_id"),
            poi_type="sd_zone",
            reason=reason,
            required_evidence=["entry_protocol_permission", "usable_pro_direction_poi", "risk_rr_valid"],
            invalidation="Phase A reaches the HTF P/D objective and either opens Phase E or falls into range",
            target_policy="htf_pd_level",
            fallback_target_policy="fixed_rr",
            entry_policy="hybrid",
            created_at=self.state.current_hypothesis.created_at if self.state.current_hypothesis else ts,
            updated_at=ts,
            debug_facts=debug,
        )

    def _carry_current_hypothesis(
        self,
        ts: str | None,
        debug: dict[str, Any],
        phase_sub_status: str | None = None,
    ) -> Hypothesis:
        current = self.state.current_hypothesis
        if current is None:
            return self._none(
                "waiting_for_hypothesis_state",
                ["current_hypothesis"],
                "A hypothesis exists before it can be carried forward",
                ts,
                debug,
                none_sub_status="waiting_for_hypothesis_state",
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
            phase_sub_status=phase_sub_status if phase_sub_status is not None else current.phase_sub_status,
            none_sub_status=current.none_sub_status,
            debug_facts=debug,
        )

    def _none(
        self,
        reason: str,
        required_evidence: list[str],
        invalidation: str,
        ts: str | None,
        debug: dict[str, Any],
        none_sub_status: str | None = None,
    ) -> Hypothesis:
        debug = {**debug, "none_sub_status": none_sub_status} if none_sub_status else debug
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
            none_sub_status=none_sub_status,
            debug_facts=debug,
        )

    def _range(
        self,
        reason: str,
        range_reason: str,
        ts: str | None,
        debug: dict[str, Any],
    ) -> Hypothesis:
        return Hypothesis(
            hypothesis_id=self.state.hypothesis_id,
            status="watching",
            phase="range",
            direction="none",
            swing_alignment="none",
            internal_alignment="none",
            poi_id=None,
            poi_type=None,
            reason=reason,
            required_evidence=["fresh_htf_structural_epoch"],
            invalidation="Fresh HTF structural epoch or new Phase E resets the P/D range episode",
            target_policy="none",
            fallback_target_policy=None,
            entry_policy="skip",
            created_at=self.state.current_hypothesis.created_at if self.state.current_hypothesis else ts,
            updated_at=ts,
            debug_facts={
                **debug,
                "range_reason": range_reason,
                "budget_policy": "preserve_spent_budget",
            },
        )

    def _commit(self, hypothesis: Hypothesis) -> Hypothesis:
        if hypothesis.phase != self.state.previous_phase and hypothesis.phase in {"E", "D", "C", "B", "A"}:
            self.state.phase_episode_id = uuid4().hex
        self.state.previous_phase = hypothesis.phase
        self.state.current_hypothesis = hypothesis
        return hypothesis
