from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, field, fields
from typing import Any, Literal
from uuid import uuid4


Phase = Literal["A", "B", "C", "D", "E", "X"]
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
            "debug_facts": self.debug_facts,
        }


@dataclass
class PhaseEShadow:
    """Internal Phase E sub-node memory for expansion monitoring."""
    node: str = "E.seeking"
    previous_node: str | None = None
    bars_in_node: int = 0
    source_orderflow_leg_id: str | None = None
    source_orderflow_started_at: str | None = None
    source_orderflow_anchor_id: str | None = None
    source_orderflow_disruption_id: str | None = None
    source_orderflow_source_store: str | None = None
    pullback_developing_entered_at: str | None = None  # cursor_time when classifier first entered E.pullback_developing
    consumed_orderflow_leg_id: str | None = None
    counter_structure_confirmed_at: str | None = None
    counter_structure_event_id: str | None = None
    counter_structure_source_level_id: str | None = None
    counter_structure_source_store: str | None = None
    counter_structure_level: float | None = None
    pro_attempt_seen: bool = False
    pro_attempt_started_at: str | None = None
    pro_attempt_direction: str | None = None
    pro_attempt_event_id: str | None = None
    pro_attempt_level: float | None = None
    # Journal — epoch-sticky waypoint flags (cleared only on epoch reset)
    htf_reaction_seen: bool = False
    htf_reaction_zone_id: str | None = None
    htf_reaction_entered_at: str | None = None
    htf_reaction_exit_reason: str | None = None  # "ran_zone" | "stalled" | "mss_fired"

    def reset(self) -> None:
        self.node = "E.seeking"
        self.previous_node = None
        self.bars_in_node = 0
        self.source_orderflow_leg_id = None
        self.source_orderflow_started_at = None
        self.source_orderflow_anchor_id = None
        self.source_orderflow_disruption_id = None
        self.source_orderflow_source_store = None
        self.pullback_developing_entered_at = None
        self.consumed_orderflow_leg_id = None
        self.counter_structure_confirmed_at = None
        self.counter_structure_event_id = None
        self.counter_structure_source_level_id = None
        self.counter_structure_source_store = None
        self.counter_structure_level = None
        self.pro_attempt_seen = False
        self.pro_attempt_started_at = None
        self.pro_attempt_direction = None
        self.pro_attempt_event_id = None
        self.pro_attempt_level = None
        self.htf_reaction_seen = False
        self.htf_reaction_zone_id = None
        self.htf_reaction_entered_at = None
        self.htf_reaction_exit_reason = None


@dataclass
class PhaseDShadow:
    """Internal Phase D sub-node memory for D.watch.

    D.speculation and its iChoCh/SB entry paths moved to Layer 5.
    """
    node: str | None = None  # "D.watch"
    consumed_leg_id: str | None = None  # copied from phase_e.source_orderflow_leg_id at D.watch open
    watch_entered_at: str | None = None  # eventTimestamp of choch_1 — freshness floor for Layer 5
    choch_1: dict | None = None  # pro-HTF SC that opened D.watch (Layer 5 reads level for SL)
    pro_attempt: dict | None = None  # quality metadata accumulated while in D.watch
    commitment_extreme_level: float | None = None  # peak of pro-attempt bounce at D.watch open (Layer 5 SL anchor)
    watch_range_extreme: float | None = None  # running LTF range extreme since D.watch open (Layer 5 SL anchor)
    htf_zone_seen: bool = False  # latches True when htf_opposing_sd_tapped fires during D.watch hold
    entry_express: bool = False  # True when D.watch opened via express gate (zone tap during E.stalling/pullback)
    express_zone_proximal: float | None = None  # zone proximal at express open; survives D.watch → C; SL anchor for B/C2_express

    def reset(self) -> None:
        self.node = None
        self.consumed_leg_id = None
        self.watch_entered_at = None
        self.choch_1 = None
        self.pro_attempt = None
        self.commitment_extreme_level = None
        self.watch_range_extreme = None
        self.htf_zone_seen = False
        self.entry_express = False
        self.express_zone_proximal = None


@dataclass
class PhaseCshadow:
    """Internal Phase C sub-node memory across C.pullback / C.pullback_weaken bars."""
    origin_node: str | None = None  # "D.watch_mss" | "D.speculation_mss" | "E.pullback_developing_no_pro"
    entered_at: str | None = None   # eventTimestamp of the MSS/event that opened C.pullback
    weaken_at: str | None = None    # eventTimestamp of the pro-HTF SC that opened C.pullback_weaken
    recover_at: str | None = None   # cursor_time of C.pullback_weaken → C.pullback recovery

    def reset(self) -> None:
        self.origin_node = None
        self.entered_at = None
        self.weaken_at = None
        self.recover_at = None


@dataclass
class PhaseBShadow:
    """Internal Phase B sub-node memory for B.watch.

    Carries commitment pointers only. Layer 3 EC snapshot is the source for
    zone levels, orderflow direction, and prices. Layer 5 resolves IDs.
    """
    entered_at: str | None = None
    htf_sd_zone_tapped: bool = False
    htf_sd_zone_id: str | None = None
    htf_sd_zone_tapped_at: str | None = None
    ltf_sd_zone_tapped: bool = False
    ltf_sd_zone_id: str | None = None
    liquidity_pool_run: bool = False
    liquidity_pool_id: str | None = None
    commitment_extreme_level: float | None = None
    commitment_extreme_event_id: str | None = None
    at_extreme_entry: bool = False

    def reset(self) -> None:
        self.entered_at = None
        self.htf_sd_zone_tapped = False
        self.htf_sd_zone_id = None
        self.htf_sd_zone_tapped_at = None
        self.ltf_sd_zone_tapped = False
        self.ltf_sd_zone_id = None
        self.liquidity_pool_run = False
        self.liquidity_pool_id = None
        self.commitment_extreme_level = None
        self.commitment_extreme_event_id = None
        self.at_extreme_entry = False


@dataclass
class PhaseAShadow:
    """Internal Phase A sub-node memory for A.watch.

    Carries commitment pointers only per shadow invariant.
    Exception: commitment_extreme_level is read from b_shadow (fixed at B entry).
    """
    entered_at: str | None = None
    pro_attempt_weaken: bool = False
    pro_attempt_weaken_at: str | None = None
    pro_extreme_at_weaken: float | None = None
    recover_at: str | None = None
    phase_a_objective_touched: bool = False
    phase_a_objective_touched_at: str | None = None

    def reset(self) -> None:
        self.entered_at = None
        self.pro_attempt_weaken = False
        self.pro_attempt_weaken_at = None
        self.pro_extreme_at_weaken = None
        self.recover_at = None
        self.phase_a_objective_touched = False
        self.phase_a_objective_touched_at = None


@dataclass
class ShadowThesis:
    """Root Layer 4 memory component with phase-owned ledgers.

    Survives D→C→B re-entry and normal phase transitions.
    Only cleared on epoch boundary reset or explicit invalidation.

    phase_e  — Phase E expansion sub-node ledger (PhaseEShadow).
    phase_d  — Phase D watch/speculation sub-node ledger (PhaseDShadow).
    phase_c  — Phase C pullback/weaken sub-node ledger (PhaseCshadow).
    phase_b  — Phase B watch sub-node ledger (PhaseBShadow). Pointer-only.
    phase_a  — Phase A watch sub-node ledger (PhaseAShadow). Pointer-only.
    B-phase flat fields (status, selected_poi_*…) — legacy shallow-reclaim
    commitment fields, kept for dead-code methods. reset() clears only these;
    phase_e/phase_d/phase_c/phase_b have their own .reset() methods.
    """
    phase_e: PhaseEShadow = field(default_factory=PhaseEShadow)
    phase_d: PhaseDShadow = field(default_factory=PhaseDShadow)
    phase_c: PhaseCshadow = field(default_factory=PhaseCshadow)
    phase_b: PhaseBShadow = field(default_factory=PhaseBShadow)
    phase_a: PhaseAShadow = field(default_factory=PhaseAShadow)
    status: str | None = None
    opened_at: str | None = None
    selected_poi_id: str | None = None
    selected_poi_high: float | None = None
    selected_poi_low: float | None = None
    first_counter_mitigation_at: str | None = None
    same_level_return_count: int = 0
    weakening_reason: str | None = None

    def reset(self) -> None:
        """Reset Phase B commitment fields. Does NOT reset phase_e ledger."""
        self.status = None
        self.opened_at = None
        self.selected_poi_id = None
        self.selected_poi_high = None
        self.selected_poi_low = None
        self.first_counter_mitigation_at = None
        self.same_level_return_count = 0
        self.weakening_reason = None


@dataclass
class HypothesisClassifierState:
    hypothesis_id: str = field(default_factory=lambda: uuid4().hex)
    phase_episode_id: str = field(default_factory=lambda: uuid4().hex)
    previous_phase: Phase = "X"
    htf_pd_epoch_id: str | None = None
    active_phase_e_direction: Direction = "none"
    shadow_thesis: ShadowThesis = field(default_factory=ShadowThesis)
    current_hypothesis: Hypothesis | None = None

    @property
    def phase_e_shadow_node(self) -> str:
        return self.shadow_thesis.phase_e.node

    @phase_e_shadow_node.setter
    def phase_e_shadow_node(self, value: str) -> None:
        self.shadow_thesis.phase_e.node = value


def _dataclass_payload(cls: type, payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    names = {item.name for item in fields(cls)}
    return {key: value for key, value in payload.items() if key in names}


def hypothesis_from_dict(payload: dict[str, Any]) -> Hypothesis:
    data = _dataclass_payload(Hypothesis, payload)
    missing = [
        item.name
        for item in fields(Hypothesis)
        if item.default is MISSING
        and item.default_factory is MISSING
        and item.name not in data
    ]
    if missing:
        raise ValueError(f"Missing hypothesis fields: {', '.join(missing)}")
    return Hypothesis(**data)


def shadow_thesis_from_dict(payload: dict[str, Any] | None) -> ShadowThesis:
    data = _dataclass_payload(ShadowThesis, payload)
    shadow = ShadowThesis(
        phase_e=PhaseEShadow(**_dataclass_payload(PhaseEShadow, data.get("phase_e"))),
        phase_d=PhaseDShadow(**_dataclass_payload(PhaseDShadow, data.get("phase_d"))),
        phase_c=PhaseCshadow(**_dataclass_payload(PhaseCshadow, data.get("phase_c"))),
        phase_b=PhaseBShadow(**_dataclass_payload(PhaseBShadow, data.get("phase_b"))),
        phase_a=PhaseAShadow(**_dataclass_payload(PhaseAShadow, data.get("phase_a"))),
    )
    for item in fields(ShadowThesis):
        if item.name.startswith("phase_"):
            continue
        if item.name in data:
            setattr(shadow, item.name, data[item.name])
    return shadow


def hypothesis_state_to_dict(state: HypothesisClassifierState) -> dict[str, Any]:
    return {
        "hypothesis_id": state.hypothesis_id,
        "phase_episode_id": state.phase_episode_id,
        "previous_phase": state.previous_phase,
        "htf_pd_epoch_id": state.htf_pd_epoch_id,
        "active_phase_e_direction": state.active_phase_e_direction,
        "shadow_thesis": asdict(state.shadow_thesis),
        "current_hypothesis": (
            state.current_hypothesis.to_dict()
            if state.current_hypothesis is not None
            else None
        ),
    }


def hypothesis_state_from_dict(payload: dict[str, Any]) -> HypothesisClassifierState:
    data = _dataclass_payload(HypothesisClassifierState, payload)
    current = data.get("current_hypothesis")
    return HypothesisClassifierState(
        hypothesis_id=str(data.get("hypothesis_id") or uuid4().hex),
        phase_episode_id=str(data.get("phase_episode_id") or uuid4().hex),
        previous_phase=data.get("previous_phase") or "X",
        htf_pd_epoch_id=data.get("htf_pd_epoch_id"),
        active_phase_e_direction=data.get("active_phase_e_direction") or "none",
        shadow_thesis=shadow_thesis_from_dict(data.get("shadow_thesis")),
        current_hypothesis=(
            hypothesis_from_dict(current)
            if isinstance(current, dict)
            else None
        ),
    )


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


def _sc_event_id(last_sc: dict[str, Any] | None) -> str | None:
    if not isinstance(last_sc, dict):
        return None
    explicit = last_sc.get("event_id") or last_sc.get("eventId")
    if explicit:
        return str(explicit)
    event_code = last_sc.get("eventCode")
    event_at = last_sc.get("eventTimestamp")
    direction = last_sc.get("breakDirection")
    level = last_sc.get("levelPrice")
    if not (event_code and event_at and direction):
        return None
    return ":".join(
        [
            str(event_code),
            str(event_at),
            str(direction),
            str(level) if level is not None else "NA",
        ]
    )


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


def _ec_candidate_for_direction(
    snapshot: dict[str, Any],
    pattern: str,
    direction: Direction,
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate, debug_facts = _ec_candidate(snapshot, pattern)
    if not candidate or candidate.get("direction") != direction:
        return {}, {}
    return candidate, debug_facts


def _ec_b_initiation_for_direction(
    snapshot: dict[str, Any],
    direction: Direction,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return direction-matched B-initiation EC facts."""
    return _ec_candidate_for_direction(snapshot, "htf_b_initiation", direction)


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

    def _phase_a_objective_progress_threshold(self) -> float:
        phase_a_cfg = self.config.get("phase_a") if isinstance(self.config.get("phase_a"), dict) else {}
        raw_threshold = phase_a_cfg.get(
            "objective_progress_threshold",
            self.config.get("phase_a_objective_progress_threshold", 0.90),
        )
        try:
            threshold = float(raw_threshold)
        except (TypeError, ValueError):
            return 0.90
        if 0.0 < threshold <= 1.0:
            return threshold
        return 0.90

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
            self._reset_phase_d_shadow()
            self._reset_phase_c_shadow()
            self._reset_phase_b_shadow()
            self._reset_phase_a_shadow()

        debug = {
            "mode": snapshot.get("mode", "single"),
            "combo": snapshot.get("combo"),
            "htf_bias": htf.get("bias") if htf else None,
            "htf_phase": htf.get("phase") if htf else None,
            "ltf_bias": ltf.get("bias") if ltf else None,
            "ltf_phase": ltf.get("phase") if ltf else None,
            "htf_pd_epoch_id": self.state.htf_pd_epoch_id,
            "phase_episode_id": self.state.phase_episode_id,
            "previous_phase": self.state.previous_phase,
            "active_phase_e_direction": self.state.active_phase_e_direction,
            "current_htf_bar_time": _bar_time(current_bar),
            "previous_htf_bar_time": _bar_time(previous_bar),
            "cursor_time": cursor_time,
        }

        if not htf:
            hyp = self._phase_x(
                phase_sub_status="X.warm_up",
                reason="waiting_for_htf_structure",
                required_evidence=["htf_structure"],
                invalidation="HTF structure snapshot becomes available",
                ts=cursor_time,
                debug=debug,
            )
            return self._commit(hyp)

        bias = htf.get("bias")
        phase = htf.get("phase")
        direction = _direction_from_bias(bias)

        if phase in {"open", "pullback_confirmed"} and direction != "none":
            reaction = self._phase_e_reaction(snapshot, direction, current_bar, previous_bar)
            debug.update(reaction)

            if self.state.previous_phase == "A" and self.state.active_phase_e_direction == direction:
                a_shadow = self.state.shadow_thesis.phase_a
                b_shadow = self.state.shadow_thesis.phase_b
                self._update_phase_a_shadow(snapshot, direction, debug)
                debug.update(self._phase_a_watch_shadow_debug())

                _cand_a, e_ctx_a = _ec_candidate_for_direction(snapshot, "phase_e_context", direction)
                current_c_sub_a = (
                    self.state.current_hypothesis.phase_sub_status
                    if self.state.current_hypothesis
                    else None
                )

                # A.watch / A.watch_weaken → E.seeking (new HTF extreme)
                _new_htf_extreme_a = bool(
                    debug.get("phase_e_context_new_htf_extreme")
                    or e_ctx_a.get("new_htf_extreme")
                )
                if _new_htf_extreme_a:
                    hyp = self._phase_e(direction, cursor_time, debug, ltf)
                    return self._commit(hyp)

                finale = self._phase_a_finale(snapshot, direction, htf, current_bar)
                debug.update(finale)
                if finale.get("phase_a_thesis_matured"):
                    hyp = self._phase_x(
                        phase_sub_status="X.thesis_over",
                        reason=(
                            "Phase A objective progress reached maturity threshold; "
                            "thesis budget is spent"
                        ),
                        required_evidence=["phase_a_thesis_matured"],
                        invalidation="Fresh HTF structural epoch or new Phase E seeking state",
                        ts=cursor_time,
                        debug=debug,
                        range_reason="phase_a_thesis_matured",
                    )
                    return self._commit(hyp)

                _mss_a = e_ctx_a.get("ltf_counter_orderflow_mss_watch", False)
                _mss_started_a = e_ctx_a.get("ltf_counter_orderflow_started_at")
                _a_floor = a_shadow.entered_at or ""
                _b_level = b_shadow.commitment_extreme_level

                if current_c_sub_a == "watch":
                    # A.watch → A.watch_weaken (counter-HTF MSS breaks pro orderflow)
                    if _mss_a and _mss_started_a and str(_mss_started_a) > str(_a_floor):
                        a_shadow.pro_attempt_weaken = True
                        a_shadow.pro_attempt_weaken_at = cursor_time
                        _pro_extreme_raw = (
                            ltf.get("range_high") if direction == "long"
                            else ltf.get("range_low")
                        ) if ltf else None
                        a_shadow.pro_extreme_at_weaken = (
                            float(_pro_extreme_raw) if _pro_extreme_raw is not None else None
                        )
                        hyp = self._phase_a_watch(
                            direction, cursor_time, debug, phase_sub_status="watch_weaken"
                        )
                        return self._commit(hyp)

                elif current_c_sub_a == "watch_weaken":
                    # A.watch_weaken → C.pullback (B commitment extreme breached — B+A invalidated)
                    # current_price lives in candidate["location_context"], NOT in debug_facts
                    if _b_level is not None:
                        _loc = (_cand_a.get("location_context") or {})
                        _cur_price_raw = _loc.get("current_price")
                        if _cur_price_raw is not None:
                            try:
                                _cur_price = float(_cur_price_raw)
                                _commitment_extreme_breached = (
                                    _cur_price < float(_b_level) if direction == "long"
                                    else _cur_price > float(_b_level)
                                )
                            except (TypeError, ValueError):
                                _commitment_extreme_breached = False
                            if _commitment_extreme_breached:
                                c_shadow = self.state.shadow_thesis.phase_c
                                c_shadow.origin_node = "A.watch_weaken_invalidated"
                                c_shadow.entered_at = cursor_time
                                hyp = self._phase_c(
                                    direction, None, "watching", cursor_time,
                                    {**debug, "phase_a_invalidated": True},
                                    phase_sub_status="pullback",
                                )
                                return self._commit(hyp)

                    # A.watch_weaken → A.watch (pro-HTF SC recovery + pro extreme advance)
                    # Recovery requires the pro-side LTF range extreme to have advanced past the
                    # level locked at weaken time. Prevents oscillation in ranging markets
                    # where micro pro SCs fire without genuine structural progress.
                    pro_break_a = "up" if direction == "long" else "down"
                    _last_sc_a = (ltf.get("last_sc") or {}) if ltf else {}
                    _last_sc_a_at = _last_sc_a.get("eventTimestamp")
                    _weaken_floor = a_shadow.pro_attempt_weaken_at or _a_floor
                    _pro_extreme_floor = a_shadow.pro_extreme_at_weaken
                    _pro_extreme_advance_gate = True
                    if _pro_extreme_floor is not None and ltf:
                        _cur_pro_extreme_raw = ltf.get("range_high") if direction == "long" else ltf.get("range_low")
                        if _cur_pro_extreme_raw is not None:
                            try:
                                _pro_extreme_advance_gate = (
                                    float(_cur_pro_extreme_raw) > _pro_extreme_floor if direction == "long"
                                    else float(_cur_pro_extreme_raw) < _pro_extreme_floor
                                )
                            except (TypeError, ValueError):
                                _pro_extreme_advance_gate = False
                    if (
                        _last_sc_a_at
                        and str(_last_sc_a_at) > str(_weaken_floor)
                        and _last_sc_a.get("breakDirection") == pro_break_a
                        and _pro_extreme_advance_gate
                    ):
                        a_shadow.recover_at = cursor_time
                        hyp = self._phase_a_watch(
                            direction, cursor_time, debug, phase_sub_status="watch"
                        )
                        return self._commit(hyp)

                hyp = self._carry_current_hypothesis(cursor_time, debug)
                return self._commit(hyp)

            if self.state.previous_phase == "C" and self.state.active_phase_e_direction == direction:
                if debug.get("reaction_failed"):
                    debug["phase_c_collapsed"] = True
                    debug["phase_c_collapse_rule"] = debug.get("reaction_failed_rule")
                    hyp = self._phase_e(direction, cursor_time, debug, ltf)
                    return self._commit(hyp)
                if self.state.current_hypothesis:
                    _, e_ctx_facts_c = _ec_candidate_for_direction(
                        snapshot, "phase_e_context", direction
                    )
                    c_shadow = self.state.shadow_thesis.phase_c
                    current_c_sub = self.state.current_hypothesis.phase_sub_status

                    # Any C state → E.seeking on new HTF extreme
                    _new_htf_extreme_c = bool(
                        debug.get("phase_e_context_new_htf_extreme")
                        or e_ctx_facts_c.get("new_htf_extreme")
                    )
                    if _new_htf_extreme_c:
                        debug["phase_c_collapsed"] = True
                        debug["phase_c_collapse_rule"] = "new_htf_extreme"
                        hyp = self._phase_e(direction, cursor_time, debug, ltf)
                        return self._commit(hyp)

                    # C.pullback_weaken → C.pullback: counter MSS re-fires (pro-attempt collapsed)
                    if current_c_sub == "pullback_weaken":
                        _mss_w_c = e_ctx_facts_c.get("ltf_counter_orderflow_mss_watch", False)
                        _mss_started_c = e_ctx_facts_c.get("ltf_counter_orderflow_started_at")
                        _weaken_floor = c_shadow.weaken_at or ""
                        if _mss_w_c and _mss_started_c and str(_mss_started_c) > str(_weaken_floor):
                            c_shadow.recover_at = cursor_time
                            c_shadow.entered_at = _mss_started_c
                            hyp = self._phase_c(
                                direction,
                                None,
                                "watching",
                                cursor_time,
                                {
                                    **debug,
                                    "phase_c_origin_node": c_shadow.origin_node,
                                    "phase_c_recovered": True,
                                },
                                phase_sub_status="pullback",
                            )
                            return self._commit(hyp)

                    # C.pullback → C.pullback_weaken OR B.watch: pro-HTF SC breaks pullback LH
                    # Depth gate at 51%: depth >= 51% → B.watch (discount zone reached);
                    #                   depth <  51% → C.pullback_weaken (still in premium)
                    if current_c_sub in {"pullback", None} and ltf:
                        pro_break_c = "up" if direction == "long" else "down"
                        last_sc_c = ltf.get("last_sc") or {}
                        last_sc_c_at = last_sc_c.get("eventTimestamp")
                        _c_entered_floor = c_shadow.entered_at or ""
                        if (
                            last_sc_c_at
                            and str(last_sc_c_at) > str(_c_entered_floor)
                            and last_sc_c.get("breakDirection") == pro_break_c
                        ):
                            depth_raw = debug.get("phase_e_context_ltf_pullback_depth_pct")
                            try:
                                depth = float(depth_raw) if depth_raw is not None else None
                            except (TypeError, ValueError):
                                depth = None
                            if depth is not None and depth >= 51.0:
                                b_shadow = self.state.shadow_thesis.phase_b
                                b_shadow.entered_at = cursor_time
                                b_shadow.at_extreme_entry = (
                                    c_shadow.origin_node == "A.watch_weaken_invalidated"
                                    and depth >= 90.0
                                )
                                _commitment_extreme_raw = (
                                    ltf.get("range_low") if direction == "long"
                                    else ltf.get("range_high")
                                ) if ltf else None
                                b_shadow.commitment_extreme_level = (
                                    float(_commitment_extreme_raw)
                                    if _commitment_extreme_raw is not None
                                    else None
                                )
                                b_shadow.commitment_extreme_event_id = _sc_event_id(last_sc_c)
                                hyp = self._phase_b_watch(
                                    direction,
                                    cursor_time,
                                    {
                                        **debug,
                                        "phase_b_origin_node": f"C.{c_shadow.origin_node or 'pullback'}",
                                        "phase_b_entry_depth_pct": depth,
                                        "phase_b_at_extreme_entry": b_shadow.at_extreme_entry,
                                        "phase_b_commitment_extreme_level": b_shadow.commitment_extreme_level,
                                    },
                                )
                                return self._commit(hyp)
                            else:
                                c_shadow.weaken_at = str(last_sc_c_at)
                                hyp = self._phase_c(
                                    direction,
                                    None,
                                    "watching",
                                    cursor_time,
                                    {
                                        **debug,
                                        "phase_c_origin_node": c_shadow.origin_node,
                                        "phase_c_weakened": True,
                                    },
                                    phase_sub_status="pullback_weaken",
                                )
                                return self._commit(hyp)

                    phase_c = self._phase_c_setup(snapshot, ltf, direction)
                    phase_d_from_c = self._phase_d_setup(snapshot, htf, ltf, direction, current_bar)
                    debug.update(phase_c)
                    debug.update(phase_d_from_c)
                    debug["phase_c_shadow_origin_node"] = c_shadow.origin_node
                    debug["phase_c_shadow_entered_at"] = c_shadow.entered_at
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
                d_shadow = self.state.shadow_thesis.phase_d
                _, e_ctx_facts = _ec_candidate_for_direction(snapshot, "phase_e_context", direction)

                if d_shadow.node == "D.watch":
                    # Expansion resumed — D.watch invalidated.
                    _new_htf_extreme_d = bool(
                        debug.get("phase_e_context_new_htf_extreme")
                        or e_ctx_facts.get("new_htf_extreme")
                    )
                    if _new_htf_extreme_d:
                        debug["phase_d_collapsed"] = True
                        debug["phase_d_collapse_rule"] = "new_htf_extreme"
                        hyp = self._phase_e(direction, cursor_time, debug, ltf)
                        return self._commit(hyp)

                    # Counter MSS on a fresh leg → C.pullback.
                    # iSB is Layer 5 territory — DAG gates on orderflow MSS only.
                    _mss_dw = e_ctx_facts.get("ltf_counter_orderflow_mss_watch", False)
                    _mss_leg_dw = e_ctx_facts.get("ltf_counter_orderflow_leg_id")
                    if _mss_dw and _mss_leg_dw and _mss_leg_dw != (d_shadow.consumed_leg_id or ""):
                        _, pressure_facts = _ec_candidate_for_direction(
                            snapshot, "ltf_counter_choch", direction
                        )
                        d_shadow.consumed_leg_id = _mss_leg_dw
                        c_shadow = self.state.shadow_thesis.phase_c
                        c_shadow.origin_node = "D.watch_mss"
                        c_shadow.entered_at = cursor_time
                        hyp = self._phase_c(
                            direction,
                            None,
                            "watching",
                            cursor_time,
                            {
                                **debug,
                                **self._phase_d_shadow_debug(),
                                "phase_d_node": "D.watch",
                                "phase_c_origin_node": "D.watch_mss",
                                "phase_c_entry_transition_at": cursor_time,
                                "phase_c_entry_transition_event_id": _mss_leg_dw,
                                "phase_c_entry_transition_origin_node": "D.watch_mss",
                                "phase_c_entry_transition_prior_phase": "D.watch",
                                "phase_c_entry_transition_prior_direction": direction,
                                "phase_c_entry_transition_trade_direction": (
                                    "short" if direction == "long" else "long"
                                ),
                                "phase_c_entry_transition_orderflow_leg_id": _mss_leg_dw,
                                "phase_c_entry_transition_orderflow_anchor_id": e_ctx_facts.get(
                                    "ltf_counter_orderflow_anchor_id"
                                ),
                                "phase_c_entry_transition_orderflow_disruption_id": e_ctx_facts.get(
                                    "ltf_counter_orderflow_disruption_id"
                                ),
                                "phase_c_entry_transition_internal_pressure_seen": bool(
                                    pressure_facts.get("ltf_counter_internal_pressure_seen")
                                ),
                                "phase_c_entry_transition_internal_pressure_class": pressure_facts.get(
                                    "ltf_counter_internal_pressure_class"
                                ),
                                "phase_c_entry_transition_internal_pressure_event_ids": pressure_facts.get(
                                    "ltf_counter_internal_pressure_event_ids"
                                )
                                or [],
                                "phase_c_entry_transition_internal_pressure_first_at": pressure_facts.get(
                                    "ltf_counter_internal_pressure_first_at"
                                ),
                                "phase_c_entry_transition_internal_pressure_last_at": pressure_facts.get(
                                    "ltf_counter_internal_pressure_last_at"
                                ),
                                "phase_c_entry_transition_internal_pressure_invalidated": bool(
                                    pressure_facts.get("ltf_counter_internal_pressure_invalidated")
                                ),
                                "phase_c_entry_transition_internal_pressure_invalid_reason": pressure_facts.get(
                                    "ltf_counter_internal_pressure_invalid_reason"
                                ),
                            },
                            phase_sub_status="pullback",
                        )
                        return self._commit(hyp)

                    # Accumulate quality metadata each bar while watching
                    htf_react, htf_react_facts = _ec_candidate_for_direction(
                        snapshot, "htf_counter_reaction", direction
                    )
                    ltf_story, _ = _ec_candidate_for_direction(
                        snapshot, "ltf_counter_story", direction
                    )
                    d_shadow.pro_attempt = {
                        "htf_reaction_status": htf_react.get("status"),
                        "ltf_story_status": ltf_story.get("status"),
                    }

                    # Running LTF range extreme (SL anchor for Layer 5).
                    # hypothesis direction == "long" → trade = short → SL above → track range_high max.
                    # hypothesis direction == "short" → trade = long → SL below → track range_low min.
                    ltf_struct_dw = (snapshot.get("lower_structure") or snapshot.get("execution_context") or {})
                    if direction == "long":
                        _rh_raw = ltf_struct_dw.get("range_high")
                        _rh = float(_rh_raw) if _rh_raw is not None else None
                        if _rh is not None and (d_shadow.watch_range_extreme is None or _rh > d_shadow.watch_range_extreme):
                            d_shadow.watch_range_extreme = _rh
                    else:
                        _rl_raw = ltf_struct_dw.get("range_low")
                        _rl = float(_rl_raw) if _rl_raw is not None else None
                        if _rl is not None and (d_shadow.watch_range_extreme is None or _rl < d_shadow.watch_range_extreme):
                            d_shadow.watch_range_extreme = _rl

                    # HTF zone latch (Path B context gate for Layer 5)
                    if not d_shadow.htf_zone_seen and htf_react_facts.get("htf_opposing_sd_tapped"):
                        d_shadow.htf_zone_seen = True

                    # Hold in D.watch — Layer 5 owns iChoCh / SB entry timing
                    hyp = self._phase_d(
                        direction,
                        cursor_time,
                        {
                            **debug,
                            "phase_d_node": "D.watch",
                            "phase_e_shadow_htf_reaction_seen": self.state.shadow_thesis.phase_e.htf_reaction_seen,
                        },
                        phase_sub_status="watch",
                    )
                    return self._commit(hyp)

                # Shadow node not set — hold current output unchanged
                hyp = self._carry_current_hypothesis(cursor_time, {**debug, "phase_d_held": True})
                return self._commit(hyp)

            # Express D.watch gate: HTF zone tapped during E.stalling or E.pullback_developing,
            # before pro-attempt fires. not pro_attempt_seen prevents pre-empting regular D.watch.
            if (
                self.state.previous_phase not in {"B", "A"}
                and self._previous_or_active_e(direction)
                and self.state.phase_e_shadow_node in {"E.stalling", "E.pullback_developing"}
                and self.state.shadow_thesis.phase_e.htf_reaction_seen
                and not self.state.shadow_thesis.phase_e.pro_attempt_seen
                and self.state.shadow_thesis.phase_d.node is None
            ):
                phase_e_shadow = self.state.shadow_thesis.phase_e
                _e_node = self.state.phase_e_shadow_node
                d_shadow = self.state.shadow_thesis.phase_d
                d_shadow.node = "D.watch"
                d_shadow.watch_entered_at = cursor_time
                d_shadow.consumed_leg_id = phase_e_shadow.source_orderflow_leg_id
                d_shadow.watch_range_extreme = None
                d_shadow.htf_zone_seen = False
                d_shadow.entry_express = True
                d_shadow.express_zone_proximal = self._express_zone_proximal(snapshot, direction)
                hyp = self._phase_d(
                    direction,
                    cursor_time,
                    {
                        **debug,
                        "phase_d_node": "D.watch",
                        "phase_d_entry": (
                            "E.stalling_zone_tap"
                            if _e_node == "E.stalling"
                            else "E.pullback_developing_zone_tap"
                        ),
                        "phase_d_entry_express": True,
                        "phase_e_shadow_htf_reaction_seen": True,
                    },
                    phase_sub_status="watch",
                )
                return self._commit(hyp)

            # D.watch entry from E.pullback_developing
            if (
                self.state.previous_phase != "B"
                and self.state.previous_phase != "A"
                and self._previous_or_active_e(direction)
                and self.state.phase_e_shadow_node == "E.pullback_developing"
            ):
                phase_e_shadow = self.state.shadow_thesis.phase_e
                self._update_phase_e_pullback_progress(ltf, direction, debug)
                # D.watch opens on the first LTF pro-HTF ChoCh — the bounce initiation.
                # pro_attempt_seen is set by _update_phase_e_pullback_progress when
                # last_sc.breakDirection == pro-HTF and timestamp > pullback_developing_entered_at.
                _pro_at = phase_e_shadow.pro_attempt_started_at
                _entered_at = phase_e_shadow.pullback_developing_entered_at or ""
                if phase_e_shadow.pro_attempt_seen and _pro_at and _pro_at > _entered_at:
                    d_shadow = self.state.shadow_thesis.phase_d
                    d_shadow.node = "D.watch"
                    d_shadow.watch_entered_at = _pro_at
                    d_shadow.consumed_leg_id = phase_e_shadow.source_orderflow_leg_id
                    d_shadow.watch_range_extreme = None
                    d_shadow.htf_zone_seen = False
                    d_shadow.entry_express = False
                    d_shadow.express_zone_proximal = None
                    phase_e_shadow.consumed_orderflow_leg_id = d_shadow.consumed_leg_id
                    _ltf_extreme = (
                        ltf.get("range_high") if direction == "long"
                        else ltf.get("range_low")
                    ) if ltf else None
                    d_shadow.commitment_extreme_level = float(_ltf_extreme) if _ltf_extreme is not None else None
                    d_shadow.choch_1 = {
                        "trigger_type": "choch",
                        "choch": True,
                        "at": _pro_at,
                        "level": phase_e_shadow.pro_attempt_level,
                        "event_id": phase_e_shadow.pro_attempt_event_id,
                    }
                    hyp = self._phase_d(
                        direction,
                        cursor_time,
                        {
                            **debug,
                            "phase_d_node": "D.watch",
                            "phase_d_entry": "E.pullback_developing",
                            "phase_d_entry_pro_attempt_started_at": _pro_at,
                        },
                        phase_sub_status="watch",
                    )
                    return self._commit(hyp)

            phase_c_from_e = self._phase_c_setup(snapshot, ltf, direction)

            # V1: E.pullback_developing, no D entered, depth >= 51% → C.pullback
            if (
                self.state.previous_phase not in {"B", "A"}
                and self.state.phase_e_shadow_node == "E.pullback_developing"
                and self.state.shadow_thesis.phase_d.node is None
            ):
                _depth_v1 = debug.get("phase_e_context_ltf_pullback_depth_pct")
                try:
                    _depth_v1_val = float(_depth_v1) if _depth_v1 is not None else None
                except (TypeError, ValueError):
                    _depth_v1_val = None
                if _depth_v1_val is not None and _depth_v1_val >= 51.0:
                    c_shadow = self.state.shadow_thesis.phase_c
                    c_shadow.origin_node = "E.pullback_developing_no_pro"
                    c_shadow.entered_at = cursor_time
                    _status_v1: HypothesisStatus = (
                        "armed" if phase_c_from_e["phase_c_selected_poi"] else "watching"
                    )
                    debug.update({
                        **phase_c_from_e,
                        "phase_c_origin_node": "E.pullback_developing_no_pro",
                        "phase_c_selection_reason": "no_pro_attempt_depth_threshold_reached",
                    })
                    hyp = self._phase_c(
                        direction,
                        phase_c_from_e["phase_c_selected_poi"],
                        _status_v1,
                        cursor_time,
                        debug,
                        phase_sub_status="pullback",
                    )
                    return self._commit(hyp)

            if self.state.previous_phase == "B":
                b_shadow = self.state.shadow_thesis.phase_b
                self._update_phase_b_watch_shadow(snapshot, direction, debug)
                debug.update(self._phase_b_watch_shadow_debug())

                # B.watch → E.seeking (new HTF extreme)
                _, e_ctx_b = _ec_candidate_for_direction(snapshot, "phase_e_context", direction)
                _new_htf_extreme_b = bool(
                    debug.get("phase_e_context_new_htf_extreme")
                    or e_ctx_b.get("new_htf_extreme")
                )
                if _new_htf_extreme_b:
                    hyp = self._phase_e(direction, cursor_time, debug, ltf)
                    return self._commit(hyp)

                _b_entered_floor = b_shadow.entered_at or ""

                # B.watch → A.watch (pro-HTF BoS fires — price escaped B zone in pro direction)
                pro_break_b = "up" if direction == "long" else "down"
                last_sc_b = (ltf.get("last_sc") or {}) if ltf else {}
                last_sc_b_at = last_sc_b.get("eventTimestamp")
                if (
                    last_sc_b_at
                    and str(last_sc_b_at) > str(_b_entered_floor)
                    and last_sc_b.get("breakDirection") == pro_break_b
                ):
                    a_shadow = self.state.shadow_thesis.phase_a
                    a_shadow.entered_at = cursor_time
                    hyp = self._phase_a_watch(
                        direction, cursor_time,
                        {
                            **debug,
                            "phase_a_origin_node": "B.watch",
                            "phase_b_commitment_extreme_level": b_shadow.commitment_extreme_level,
                        },
                    )
                    return self._commit(hyp)

                # B.watch → C.pullback (B commitment extreme breached)
                _b_commitment_extreme = b_shadow.commitment_extreme_level
                if _b_commitment_extreme is not None and ltf:
                    _cur_extreme_raw = ltf.get("range_low") if direction == "long" else ltf.get("range_high")
                    if _cur_extreme_raw is not None:
                        try:
                            _commitment_extreme_breached = (
                                float(_cur_extreme_raw) < _b_commitment_extreme if direction == "long"
                                else float(_cur_extreme_raw) > _b_commitment_extreme
                            )
                        except (TypeError, ValueError):
                            _commitment_extreme_breached = False
                        if _commitment_extreme_breached:
                            c_shadow = self.state.shadow_thesis.phase_c
                            c_shadow.origin_node = "B.watch_commitment_extreme_breached"
                            c_shadow.entered_at = cursor_time
                            hyp = self._phase_c(
                                direction, None, "watching", cursor_time,
                                {
                                    **debug,
                                    "phase_b_commitment_extreme_breached": True,
                                    "phase_b_commitment_extreme_level": _b_commitment_extreme,
                                },
                                phase_sub_status="pullback",
                            )
                            return self._commit(hyp)

                # B.watch → C.pullback (counter MSS fires — freshness-guarded)
                _mss_b = e_ctx_b.get("ltf_counter_orderflow_mss_watch", False)
                _mss_b_started = e_ctx_b.get("ltf_counter_orderflow_started_at")
                if (
                    _mss_b
                    and _mss_b_started
                    and str(_mss_b_started) > str(_b_entered_floor)
                ):
                    c_shadow = self.state.shadow_thesis.phase_c
                    c_shadow.origin_node = "B.watch_mss_failed"
                    c_shadow.entered_at = _mss_b_started
                    hyp = self._phase_c(
                        direction,
                        None,
                        "watching",
                        cursor_time,
                        {**debug, "phase_b_failed_to_c": True},
                        phase_sub_status="pullback",
                    )
                    return self._commit(hyp)

                if b_shadow.commitment_extreme_level is not None:
                    debug["phase_b_commitment_extreme_level"] = b_shadow.commitment_extreme_level
                hyp = self._carry_current_hypothesis(cursor_time, debug)
                return self._commit(hyp)

            # DAG guard: direct E→B is blocked; B entry requires C.pullback depth gate
            if self._phase_b_blocked_by_dag(direction):
                debug.update({
                    "phase_b_candidate": True,
                    "phase_b_ready": False,
                    "phase_b_blocked_by_dag": True,
                    "phase_b_dag_blocked_reason": "direct_e_to_b_requires_c_origin",
                })

            if phase == "open" or (
                phase == "pullback_confirmed"
                and self.state.previous_phase == "E"
            ):
                if phase == "pullback_confirmed":
                    debug["phase_e_hold_reason"] = "pullback_confirmed_without_explicit_exit"
                hyp = self._phase_e(direction, cursor_time, debug, ltf)
                return self._commit(hyp)

        if (
            self.state.previous_phase == "X"
            and self.state.current_hypothesis
            and self.state.current_hypothesis.phase_sub_status == "X.thesis_over"
        ):
            debug["phase_x_hold_reason"] = "thesis_over_waiting_for_new_phase_e"
            hyp = self._carry_current_hypothesis(cursor_time, debug)
            return self._commit(hyp)

        if bias == "neutral" or direction == "none":
            hyp = self._phase_x(
                phase_sub_status=("X.warm_up" if waiting_for_first_closed_htf else "X.no_direction"),
                reason="HTF bias is neutral; no directional hypothesis",
                required_evidence=["directional_htf_bias"],
                invalidation="HTF bias becomes directional",
                ts=cursor_time,
                debug=debug,
            )
            return self._commit(hyp)

        debug = self._x_none_debug(debug, phase)
        hyp = self._phase_x(
            phase_sub_status="X.none",
            reason="E/D/C/B classifier slice found no tradable hypothesis; waiting for A classifier",
            required_evidence=["phase_a_classifier"],
            invalidation="Next classifier slice defines this pullback/continuation state",
            ts=cursor_time,
            debug=debug,
        )
        return self._commit(hyp)

    def _x_none_debug(self, debug: dict[str, Any], htf_phase: str | None) -> dict[str, Any]:
        """Explain a directional fallthrough without turning every DAG gate into error codes."""
        previous_phase = self.state.previous_phase
        blocked_candidates: dict[str, str] = {}

        if htf_phase == "pullback_confirmed" and previous_phase not in {"E", "D", "C", "B", "A"}:
            blocked_candidates["DAG"] = "pullback_confirmed_without_active_phase_context"
            blocked_candidates["E"] = "pullback_confirmed_hold_requires_previous_phase_E"

        if debug.get("phase_b_blocked_by_dag"):
            blocked_candidates["B"] = str(
                debug.get("phase_b_dag_blocked_reason") or "blocked_by_dag"
            )
        elif previous_phase != "C":
            blocked_candidates["B"] = "requires_previous_phase_C_depth_gate"

        if previous_phase != "B":
            blocked_candidates["A"] = "requires_previous_phase_B_fresh_pro_bos"

        return {
            **debug,
            "blocked_transition_reason": "directional_bias_but_no_phase_claimed",
            "blocked_transition_context": {
                "htf_phase": htf_phase,
                "previous_phase": previous_phase,
                "active_phase_e_direction": self.state.active_phase_e_direction,
            },
            "blocked_phase_candidates": blocked_candidates,
        }

    def _phase_d_setup(
        self,
        snapshot: dict[str, Any],
        htf: dict[str, Any],
        ltf: dict[str, Any] | None,
        direction: Direction,
        current_bar: dict[str, Any] | None,
    ) -> dict[str, Any]:
        _, facts = _ec_candidate_for_direction(snapshot, "htf_counter_reaction", direction)
        _, choch_facts = _ec_candidate_for_direction(snapshot, "ltf_counter_choch", direction)
        return {
            "phase_d_ready": False,
            "phase_d_trigger": None,
            "phase_d_legacy_disabled": True,
            "phase_d_disabled_reason": "phase_d_simplified_to_watch_speculation",
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
            "phase_d_liquidity_ready": False,
            "phase_d_liquidity_test_status": None,
            "phase_d_reaction_confirmed": False,
            "phase_d_liquidity_trigger": None,
            "phase_d_liquidity_candidate_nodes": [],
            "phase_d_liquidity_selected_node": None,
            "phase_d_liquidity_selection_reason": None,
            "phase_d_liquidity_expected_direction": facts.get("liquidity_reclaim_expected_direction"),
            "phase_d_liquidity_pool_id": None,
            "phase_d_liquidity_level": None,
            "phase_d_liquidity_source": None,
            "phase_d_liquidity_side": None,
            "phase_d_liquidity_direction": None,
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
            "ltf_counter_sb_seen": bool(choch_facts.get("ltf_counter_sb_seen")),
            "ltf_counter_sb_level": choch_facts.get("ltf_counter_sb_level"),
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
        c_gate, facts = _ec_candidate_for_direction(snapshot, "ltf_counter_story", prior_direction)
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
            "phase_c_ltf_counter_bos_confirmed": bool(facts.get("ltf_counter_bos_confirmed")),
            "phase_c_selected_poi_touched": touched,
        }

    def _phase_b_initiation_setup(
        self,
        snapshot: dict[str, Any],
        direction: Direction,
    ) -> dict[str, Any]:
        liquidity = _liquidity_snapshot(snapshot)
        b_init, b_initiation = _ec_b_initiation_for_direction(snapshot, direction)
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
        b_gate, facts = _ec_candidate_for_direction(snapshot, "htf_b_phase_setup", direction)
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
        threshold = self._phase_a_objective_progress_threshold()
        facts = {
            "phase_a_finale_touched": False,
            "phase_a_finale_closed_beyond": False,
            "phase_a_finale_direction": direction,
            "phase_a_finale_objective": objective,
            "phase_a_finale_rule": None,
            "phase_a_objective_progress_threshold": threshold,
            "phase_a_objective_progress_threshold_pct": threshold * 100.0,
            "phase_a_objective_progress_pct": None,
            "phase_a_thesis_matured": False,
            "phase_a_thesis_maturity_rule": "objective_progress_reaches_configured_threshold",
        }
        range_high_raw = htf.get("range_high")
        range_low_raw = htf.get("range_low")
        bar_high_raw = current_bar.get("high") if current_bar else None
        bar_low_raw = current_bar.get("low") if current_bar else None
        try:
            range_high = float(range_high_raw)
            range_low = float(range_low_raw)
            bar_high = float(bar_high_raw)
            bar_low = float(bar_low_raw)
            span = range_high - range_low
        except (TypeError, ValueError):
            span = 0.0
            bar_high = bar_low = range_high = range_low = 0.0

        if span > 0.0:
            raw_progress = (
                (bar_high - range_low) / span
                if direction == "long"
                else (range_high - bar_low) / span
            )
            progress = max(0.0, min(1.0, raw_progress))
            facts.update(
                {
                    "phase_a_objective_progress_pct": progress * 100.0,
                    "phase_a_objective_progress_raw_pct": raw_progress * 100.0,
                    "phase_a_thesis_matured": progress + 1e-12 >= threshold,
                    "phase_a_finale_bar_high": bar_high,
                    "phase_a_finale_bar_low": bar_low,
                    "phase_a_finale_bar_close": current_bar.get("close") if current_bar else None,
                }
            )
        else:
            facts["phase_a_objective_progress_blocked_reason"] = "missing_or_invalid_htf_range"

        objective_candidate, objective_facts = _ec_candidate_for_direction(
            snapshot, "htf_pd_objective", direction
        )
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
        # ChoCh stream is independent of phase_e_context — always read it first.
        _choch_ec, choch_facts = _ec_candidate_for_direction(
            snapshot, "ltf_counter_choch", direction
        )
        facts.update(
            {
                "phase_e_context_ltf_counter_choch_seen": bool(
                    choch_facts.get("ltf_counter_choch_seen")
                ),
                "phase_e_context_ltf_counter_choch_event_at": choch_facts.get(
                    "ltf_counter_choch_event_at"
                ),
                "phase_e_context_ltf_counter_choch_direction": choch_facts.get(
                    "ltf_counter_choch_direction"
                ),
                "phase_e_context_ltf_counter_choch_level": choch_facts.get(
                    "ltf_counter_choch_level"
                ),
                "phase_e_context_ltf_counter_choch_event_id": choch_facts.get(
                    "ltf_counter_choch_event_id"
                ),
                "phase_e_context_ltf_counter_choch_source_level_id": choch_facts.get(
                    "ltf_counter_choch_source_level_id"
                ),
                "phase_e_context_ltf_counter_choch_source_store": choch_facts.get(
                    "ltf_counter_choch_source_store"
                ),
                "phase_e_context_ltf_counter_sb_seen": bool(
                    choch_facts.get("ltf_counter_sb_seen")
                ),
                "phase_e_context_ltf_counter_sb_event_at": choch_facts.get(
                    "ltf_counter_sb_event_at"
                ),
                "phase_e_context_ltf_counter_sb_level": choch_facts.get(
                    "ltf_counter_sb_level"
                ),
                "phase_e_context_ltf_counter_sb_event_id": choch_facts.get(
                    "ltf_counter_sb_event_id"
                ),
                "phase_e_context_ltf_counter_sb_source_level_id": choch_facts.get(
                    "ltf_counter_sb_source_level_id"
                ),
                "phase_e_context_ltf_counter_sb_source_store": choch_facts.get(
                    "ltf_counter_sb_source_store"
                ),
            }
        )
        phase_e, phase_e_facts = _ec_candidate_for_direction(
            snapshot, "phase_e_context", direction
        )
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
                    "phase_e_context_ltf_pd_counter_range_breached": bool(
                        phase_e_facts.get("ltf_pd_counter_range_breached")
                    ),
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
                    "phase_e_context_ltf_counter_orderflow_mss_watch": bool(
                        phase_e_facts.get("ltf_counter_orderflow_mss_watch")
                    ),
                    "phase_e_context_ltf_swing_orderflow_mss_watch": bool(
                        phase_e_facts.get("ltf_swing_orderflow_mss_watch")
                    ),
                    "phase_e_context_ltf_counter_orderflow_mss_regime": phase_e_facts.get(
                        "ltf_counter_orderflow_mss_regime"
                    ),
                    "phase_e_context_ltf_counter_orderflow_mss_monitor_status": phase_e_facts.get(
                        "ltf_counter_orderflow_mss_monitor_status"
                    ),
                    "phase_e_context_ltf_counter_orderflow_mss_trigger_source": phase_e_facts.get(
                        "ltf_counter_orderflow_mss_trigger_source"
                    ),
                    "phase_e_context_ltf_counter_orderflow_probe_breaks_protected_anchor": bool(
                        phase_e_facts.get("ltf_counter_orderflow_probe_breaks_protected_anchor")
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
                    "phase_e_context_ltf_counter_orderflow_anchor_id": phase_e_facts.get(
                        "ltf_counter_orderflow_anchor_id"
                    ),
                    "phase_e_context_ltf_counter_orderflow_disruption_id": phase_e_facts.get(
                        "ltf_counter_orderflow_disruption_id"
                    ),
                    "phase_e_context_ltf_counter_orderflow_source_store": phase_e_facts.get(
                        "ltf_counter_orderflow_source_store"
                    ),
                    "phase_e_context_ltf_probe_at_htf_opposing_zone": bool(
                        phase_e_facts.get("ltf_probe_at_htf_opposing_zone")
                    ),
                    "phase_e_context_ltf_probe_htf_opposing_zone_id": phase_e_facts.get(
                        "ltf_probe_htf_opposing_zone_id"
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
        self.state.shadow_thesis.phase_e.reset()

    def _reset_phase_d_shadow(self) -> None:
        self.state.shadow_thesis.phase_d.reset()

    def _phase_d_shadow_debug(self) -> dict[str, Any]:
        s = self.state.shadow_thesis.phase_d
        choch_1 = s.choch_1 or {}
        pro_attempt = s.pro_attempt or {}
        return {
            "phase_d_shadow_node": s.node,
            "phase_d_shadow_consumed_leg_id": s.consumed_leg_id,
            "phase_d_shadow_watch_entered_at": s.watch_entered_at,
            "phase_d_shadow_choch_1_at": choch_1.get("at"),
            "phase_d_shadow_choch_1_level": choch_1.get("level"),
            "phase_d_shadow_choch_1_event_id": choch_1.get("event_id"),
            "phase_d_shadow_choch_1_trigger_type": choch_1.get("trigger_type"),
            "phase_d_shadow_pro_attempt_htf_reaction_status": pro_attempt.get("htf_reaction_status"),
            "phase_d_shadow_pro_attempt_ltf_story_status": pro_attempt.get("ltf_story_status"),
            "phase_d_shadow_commitment_extreme_level": s.commitment_extreme_level,
            "phase_d_shadow_watch_range_extreme": s.watch_range_extreme,
            "phase_d_shadow_htf_zone_seen": s.htf_zone_seen,
            "phase_d_shadow_entry_express": s.entry_express,
            "phase_d_shadow_express_zone_proximal": s.express_zone_proximal,
        }

    def _express_zone_proximal(self, snapshot: dict[str, Any], direction: Direction) -> float | None:
        """Return zone proximal price for express D.watch SL.
        direction=long (hypothesis) → trade=short → supply zone → proximal=zone.low.
        direction=short (hypothesis) → trade=long → demand zone → proximal=zone.high.
        Mirrors _htf_proximal_zone in layer5.py including supply/demand direction filter."""
        _, rfacts = _ec_candidate_for_direction(snapshot, "htf_counter_reaction", direction)
        zone_ids = rfacts.get("htf_opposing_sd_zone_ids") or []
        zone_dir = "supply" if direction == "long" else "demand"
        for zid in zone_ids:
            for z in snapshot.get("zones") or []:
                if z.get("zone_id") == zid and z.get("direction") == zone_dir:
                    v = z.get("low") if direction == "long" else z.get("high")
                    try:
                        return float(v) if v is not None else None
                    except (TypeError, ValueError):
                        return None
        return None

    def _reset_phase_c_shadow(self) -> None:
        self.state.shadow_thesis.phase_c.reset()

    def _reset_phase_b_shadow(self) -> None:
        self.state.shadow_thesis.phase_b.reset()
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

    def _update_phase_e_pullback_progress(
        self,
        ltf: dict[str, Any] | None,
        direction: Direction,
        debug: dict[str, Any],
    ) -> None:
        s = self.state.shadow_thesis.phase_e
        if s.node != "E.pullback_developing" or direction == "none":
            return

        counter_at = debug.get("phase_e_context_ltf_counter_choch_event_at")
        if (
            s.counter_structure_confirmed_at is None
            and debug.get("phase_e_context_ltf_counter_choch_seen")
            and counter_at
            and (
                s.pullback_developing_entered_at is None
                or str(counter_at) > str(s.pullback_developing_entered_at)
            )
        ):
            s.counter_structure_confirmed_at = str(counter_at)
            s.counter_structure_event_id = debug.get("phase_e_context_ltf_counter_choch_event_id")
            s.counter_structure_source_level_id = debug.get(
                "phase_e_context_ltf_counter_choch_source_level_id"
            )
            s.counter_structure_source_store = debug.get(
                "phase_e_context_ltf_counter_choch_source_store"
            )
            s.counter_structure_level = debug.get("phase_e_context_ltf_counter_choch_level")

        if s.pro_attempt_seen or not ltf:
            return

        _floor = s.pullback_developing_entered_at or ""
        pro_break = "up" if direction == "long" else "down"

        # DAG uses macro ChoCh (last_sc) only; iChoCh (last_isc) is Layer 5 territory
        last_sc = ltf.get("last_sc") or {}
        last_sc_at = last_sc.get("eventTimestamp")
        if (
            last_sc_at
            and str(last_sc_at) > _floor
            and last_sc.get("breakDirection") == pro_break
        ):
            s.pro_attempt_seen = True
            s.pro_attempt_started_at = str(last_sc_at)
            s.pro_attempt_direction = pro_break
            s.pro_attempt_event_id = _sc_event_id(last_sc)
            s.pro_attempt_level = last_sc.get("levelPrice")
            return

        pullback_confirmed_at = ltf.get("pullback_confirmed_ts")
        ltf_bias = ltf.get("bias")
        pro_bias = "bullish" if direction == "long" else "bearish"
        if (
            pullback_confirmed_at
            and str(pullback_confirmed_at) > _floor
            and ltf_bias == pro_bias
        ):
            s.pro_attempt_seen = True
            s.pro_attempt_started_at = str(pullback_confirmed_at)
            s.pro_attempt_direction = pro_break

    def _phase_e_shadow_facts(
        self,
        ltf: dict[str, Any] | None,
        direction: Direction,
        debug: dict[str, Any],
    ) -> dict[str, Any]:
        s = self.state.shadow_thesis.phase_e
        previous_node = s.node
        selected_node = previous_node
        selection_reason = "phase_e_shadow_held"
        candidate_nodes: list[str] = []
        if "phase_e_context_new_htf_extreme" in debug:
            pd_expanding = bool(debug.get("phase_e_context_new_htf_extreme"))
        else:
            pd_expanding = bool(debug.get("new_htf_extreme"))
        ltf_counter_orderflow_mss_watch = bool(
            debug.get("phase_e_context_ltf_counter_orderflow_mss_watch")
        )
        ltf_probe_at_htf_opposing_zone = bool(
            debug.get("phase_e_context_ltf_probe_at_htf_opposing_zone")
        )

        if self.state.previous_phase != "E" or self.state.active_phase_e_direction != direction:
            selected_node = "E.seeking"
            selection_reason = "phase_e_shadow_initialized"
        elif pd_expanding:
            if s.htf_reaction_seen:
                s.htf_reaction_exit_reason = s.htf_reaction_exit_reason or "ran_zone"
            selected_node = "E.seeking"
            selection_reason = "htf_pd_expanded"
        elif previous_node == "E.seeking":
            if ltf_probe_at_htf_opposing_zone:
                # E.HTF_reaction folded into shadow: record zone probe without sub-status change
                if not s.htf_reaction_seen:
                    s.htf_reaction_seen = True
                    s.htf_reaction_zone_id = debug.get(
                        "phase_e_context_ltf_probe_htf_opposing_zone_id"
                    )
                    s.htf_reaction_entered_at = debug.get("current_htf_bar_time")
                if ltf_counter_orderflow_mss_watch:
                    selected_node = "E.pullback_developing"
                    selection_reason = "ltf_counter_orderflow_mss_during_htf_zone_probe"
                    s.htf_reaction_exit_reason = "mss_fired"
                else:
                    selected_node = "E.stalling"
                    selection_reason = "htf_pd_stopped_expanding"
            else:
                selected_node = "E.stalling"
                selection_reason = "htf_pd_stopped_expanding"
        elif previous_node == "E.stalling":
            if ltf_counter_orderflow_mss_watch:
                selected_node = "E.pullback_developing"
                selection_reason = "ltf_counter_orderflow_mss_after_e_stalling"
                if s.htf_reaction_seen and not s.htf_reaction_exit_reason:
                    s.htf_reaction_exit_reason = "mss_fired"
            else:
                selected_node = "E.stalling"
        elif previous_node == "E.pullback_developing":
            selected_node = "E.pullback_developing"

        if selected_node == "E.pullback_developing" and previous_node != "E.pullback_developing":
            s.source_orderflow_leg_id = debug.get("phase_e_context_ltf_counter_orderflow_leg_id")
            s.source_orderflow_started_at = debug.get("phase_e_context_ltf_counter_orderflow_started_at")
            s.source_orderflow_anchor_id = debug.get("phase_e_context_ltf_counter_orderflow_anchor_id")
            s.source_orderflow_disruption_id = debug.get(
                "phase_e_context_ltf_counter_orderflow_disruption_id"
            )
            s.source_orderflow_source_store = debug.get(
                "phase_e_context_ltf_counter_orderflow_source_store"
            )
            s.pullback_developing_entered_at = debug.get("cursor_time")
            # Do NOT reset counter_structure or pro_attempt fields here.
            # DAG transitions are continuous within an epoch; accumulated shadow state
            # (counter_structure_confirmed_at, pro_attempt_seen, etc.) must carry forward
            # across E.pullback_developing re-entries. Only thesis.over / epoch reset clears them.

        candidate_nodes.append(selected_node)
        if selected_node != previous_node:
            s.previous_node = previous_node
            s.bars_in_node = 0
        else:
            s.bars_in_node += 1
        s.node = selected_node
        self._update_phase_e_pullback_progress(ltf, direction, debug)

        phase_sub_status = selected_node.split(".", 1)[1] if "." in selected_node else None
        return {
            "phase_sub_status": phase_sub_status,
            "phase_e_shadow_node": selected_node,
            "phase_e_shadow_previous_node": previous_node,
            "phase_e_shadow_candidate_nodes": candidate_nodes,
            "phase_e_shadow_selected_node": selected_node,
            "phase_e_shadow_selection_reason": selection_reason,
            "phase_e_shadow_bars_in_node": s.bars_in_node,
            "phase_e_shadow_htf_reaction_seen": s.htf_reaction_seen,
            "phase_e_shadow_htf_reaction_zone_id": s.htf_reaction_zone_id,
            "phase_e_shadow_htf_reaction_entered_at": s.htf_reaction_entered_at,
            "phase_e_shadow_htf_reaction_exit_reason": s.htf_reaction_exit_reason,
            "phase_e_shadow_source_attempt_id": None,  # Deprecated.
            "phase_e_shadow_source_itr_level_id": None,  # Deprecated.
            "phase_e_shadow_source_orderflow_leg_id": s.source_orderflow_leg_id,
            "phase_e_shadow_source_orderflow_started_at": s.source_orderflow_started_at,
            "phase_e_shadow_source_orderflow_anchor_id": s.source_orderflow_anchor_id,
            "phase_e_shadow_source_orderflow_disruption_id": s.source_orderflow_disruption_id,
            "phase_e_shadow_source_orderflow_source_store": s.source_orderflow_source_store,
            "phase_e_shadow_consumed_orderflow_leg_id": s.consumed_orderflow_leg_id,
            "phase_e_shadow_counter_structure_confirmed_at": s.counter_structure_confirmed_at,
            "phase_e_shadow_counter_structure_event_id": s.counter_structure_event_id,
            "phase_e_shadow_counter_structure_source_level_id": s.counter_structure_source_level_id,
            "phase_e_shadow_counter_structure_source_store": s.counter_structure_source_store,
            "phase_e_shadow_counter_structure_level": s.counter_structure_level,
            "phase_e_shadow_pro_attempt_seen": s.pro_attempt_seen,
            "phase_e_shadow_pro_attempt_started_at": s.pro_attempt_started_at,
            "phase_e_shadow_pro_attempt_direction": s.pro_attempt_direction,
            "phase_e_shadow_pro_attempt_event_id": s.pro_attempt_event_id,
            "phase_e_shadow_pro_attempt_level": s.pro_attempt_level,
            "phase_e_context_attempt_id": None,  # Deprecated.
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
        debug = {**debug, "prior_phase_e_direction": prior_direction, **self._phase_d_shadow_debug()}
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

    def _phase_b_watch(
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
            poi_id=None,
            poi_type=None,
            reason=(
                "Bullish B.watch: price reached discount zone; depth gate fired from C.pullback"
                if bullish
                else "Bearish B.watch: price reached premium zone; depth gate fired from C.pullback"
            ),
            required_evidence=["ltf_pro_sd_confirmation", "entry_protocol_permission"],
            invalidation="Counter MSS fires (B failed; pullback resumed) or new HTF extreme",
            target_policy="htf_pd_level",
            fallback_target_policy="fixed_rr",
            entry_policy="wait",
            created_at=self.state.current_hypothesis.created_at if self.state.current_hypothesis else ts,
            updated_at=ts,
            phase_sub_status="watch",
            debug_facts=debug,
        )

    def _update_phase_b_watch_shadow(
        self, snapshot: dict[str, Any], direction: Direction, debug: dict[str, Any]
    ) -> None:
        s = self.state.shadow_thesis.phase_b
        _, b_facts = _ec_candidate_for_direction(snapshot, "htf_b_phase_setup", direction)
        if (b_facts.get("htf_pro_sd_tapped") or b_facts.get("htf_pro_sd_resolved")) and not s.htf_sd_zone_tapped:
            s.htf_sd_zone_tapped = True
            s.htf_sd_zone_id = b_facts.get("htf_last_resolved_zone_id")
            s.htf_sd_zone_tapped_at = debug.get("cursor_time")
        ltf_zones = b_facts.get("ltf_pro_sd_zone_ids") or []
        if ltf_zones and not s.ltf_sd_zone_tapped:
            s.ltf_sd_zone_tapped = True
            s.ltf_sd_zone_id = ltf_zones[0] if isinstance(ltf_zones, list) else ltf_zones
        pool_id = debug.get("htf_itr_grab_reclaim_pool_id")
        if pool_id and not s.liquidity_pool_run:
            s.liquidity_pool_run = True
            s.liquidity_pool_id = pool_id

    def _phase_b_watch_shadow_debug(self) -> dict[str, Any]:
        s = self.state.shadow_thesis.phase_b
        return {
            "phase_b_shadow_entered_at": s.entered_at,
            "phase_b_shadow_htf_sd_zone_tapped": s.htf_sd_zone_tapped,
            "phase_b_shadow_htf_sd_zone_id": s.htf_sd_zone_id,
            "phase_b_shadow_htf_sd_zone_tapped_at": s.htf_sd_zone_tapped_at,
            "phase_b_shadow_ltf_sd_zone_tapped": s.ltf_sd_zone_tapped,
            "phase_b_shadow_ltf_sd_zone_id": s.ltf_sd_zone_id,
            "phase_b_shadow_liquidity_pool_run": s.liquidity_pool_run,
            "phase_b_shadow_liquidity_pool_id": s.liquidity_pool_id,
            "phase_b_shadow_commitment_extreme_level": s.commitment_extreme_level,
            "phase_b_shadow_commitment_extreme_event_id": s.commitment_extreme_event_id,
            "phase_b_shadow_at_extreme_entry": s.at_extreme_entry,
        }

    def _reset_phase_a_shadow(self) -> None:
        self.state.shadow_thesis.phase_a.reset()

    def _phase_a_watch(
        self,
        direction: Direction,
        ts: str | None,
        debug: dict[str, Any],
        phase_sub_status: str = "watch",
    ) -> Hypothesis:
        bullish = direction == "long"
        return Hypothesis(
            hypothesis_id=self.state.hypothesis_id,
            status="watching",
            phase="A",
            phase_sub_status=phase_sub_status,
            direction=direction,
            swing_alignment="pro_swing",
            internal_alignment="pro_internal",
            poi_id=None,
            poi_type=None,
            reason=(
                "Bullish A.watch: pro-HTF BoS fired from B zone; watching for HTF objective"
                if bullish
                else "Bearish A.watch: pro-HTF BoS fired from B zone; watching for HTF objective"
            ),
            required_evidence=["entry_protocol_permission"],
            invalidation="Counter MSS breaches B commitment extreme → C.pullback; new HTF extreme → E.seeking",
            target_policy="htf_pd_level",
            fallback_target_policy="fixed_rr",
            entry_policy="wait",
            created_at=self.state.current_hypothesis.created_at if self.state.current_hypothesis else ts,
            updated_at=ts,
            debug_facts=debug,
        )

    def _update_phase_a_shadow(
        self, snapshot: dict[str, Any], direction: Direction, debug: dict[str, Any]
    ) -> None:
        s = self.state.shadow_thesis.phase_a
        _, a_facts = _ec_candidate_for_direction(snapshot, "htf_pd_objective", direction)
        if a_facts.get("phase_a_finale_touched") and not s.phase_a_objective_touched:
            s.phase_a_objective_touched = True
            s.phase_a_objective_touched_at = debug.get("cursor_time")

    def _phase_a_watch_shadow_debug(self) -> dict[str, Any]:
        s = self.state.shadow_thesis.phase_a
        return {
            "phase_a_shadow_entered_at": s.entered_at,
            "phase_a_shadow_pro_attempt_weaken": s.pro_attempt_weaken,
            "phase_a_shadow_pro_attempt_weaken_at": s.pro_attempt_weaken_at,
            "phase_a_shadow_pro_extreme_at_weaken": s.pro_extreme_at_weaken,
            "phase_a_shadow_recover_at": s.recover_at,
            "phase_a_shadow_objective_touched": s.phase_a_objective_touched,
            "phase_a_shadow_objective_touched_at": s.phase_a_objective_touched_at,
        }

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
            return self._phase_x(
                phase_sub_status="X.warm_up",
                reason="waiting_for_hypothesis_state",
                required_evidence=["current_hypothesis"],
                invalidation="A hypothesis exists before it can be carried forward",
                ts=ts,
                debug=debug,
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
            debug_facts=debug,
        )

    def _phase_x(
        self,
        phase_sub_status: str,
        reason: str,
        required_evidence: list[str],
        invalidation: str,
        ts: str | None,
        debug: dict[str, Any],
        range_reason: str | None = None,
    ) -> Hypothesis:
        extra: dict[str, Any] = {}
        if range_reason is not None:
            extra = {"range_reason": range_reason, "budget_policy": "preserve_spent_budget"}
        return Hypothesis(
            hypothesis_id=self.state.hypothesis_id,
            status="watching",
            phase="X",
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
            entry_policy="skip" if phase_sub_status == "X.thesis_over" else "wait",
            created_at=self.state.current_hypothesis.created_at if self.state.current_hypothesis else ts,
            updated_at=ts,
            phase_sub_status=phase_sub_status,
            debug_facts={**debug, **extra},
        )

    def _commit(self, hypothesis: Hypothesis) -> Hypothesis:
        if hypothesis.phase != self.state.previous_phase and hypothesis.phase in {"E", "D", "C", "B", "A"}:
            self.state.phase_episode_id = uuid4().hex
        hypothesis.debug_facts = {
            **hypothesis.debug_facts,
            "phase_episode_id": self.state.phase_episode_id,
        }
        self.state.previous_phase = hypothesis.phase
        self.state.current_hypothesis = hypothesis
        return hypothesis
