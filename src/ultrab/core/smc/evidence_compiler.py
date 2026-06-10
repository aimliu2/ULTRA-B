"""Evidence Compiler — Layer 3 final stage.

Reads DualContextSnapshot (Fusion output) bar-by-bar.
Accumulates multi-bar evidence chains.
Emits EvidenceCandidate objects for Layer 4 (DAG Navigator) consumption.

Boundary contracts
------------------
- EC reads from ``fused["context_snapshot"]`` (DualContextSnapshot) and HTF OHLCV bars.
  It does NOT re-read raw channel snapshots.
- EC asks "what did the market do?" — it emits facts, not phase decisions.
- DAG Navigator (Layer 4) holds the ``previous_phase`` / ``current_node`` state
  and decides which phase applies given the current candidate list.
- Shadow Thesis (Layer 4) tracks commitment memory and POI persistence.

Candidate patterns
------------------
``htf_b_initiation``
    Three-step accumulation: source HTF ITR grab → opposite HTF ITR grab →
    HTF decision zone touched.  Status ``collecting`` until all three fire,
    then ``ready``.  Reset on epoch boundary.

``htf_counter_reaction``
    Per-bar gate: HTF P/D stopped expanding AND (opposing SD tapped/resolved
    OR HTF pullback confirmed) AND LTF counter SD created.
    Also fires on liquidity-grab variant.  Status ``ready`` when met.

``ltf_counter_choch``
    Per-bar gate: LTF structure emitted a change-of-character (choch=True)
    in the counter direction relative to the hypothesis direction.
    Standalone stream — does not require a liquidity sequence.
    Layer 4 can read it independently of ``htf_counter_reaction``.
    Status ``ready`` when last_sc.choch is True and breakDirection matches.

``ltf_counter_story``
    Per-bar gate: LTF bias flipped counter to HTF direction.
    Status ``ready`` when flip confirmed; emits selected POI if a counter
    LTF SD zone is available.

``htf_b_phase_setup``
    Per-bar gate: LTF turned back toward HTF direction with a pro-trend
    LTF SD zone inside HTF P/D half.  Status ``ready`` when all conditions met.
    Includes ``strict`` vs ``shallow`` location sub-type.

``htf_pd_objective``
    Per-bar gate: current HTF bar touched the P/D range extreme (objective
    price).  ``phase_a_finale_closed_beyond`` sub-flag indicates a confirmed
    close past the objective.

``htf_expansion_context``
    Neutral stateful tracking of the current HTF P/D expansion. Emits running
    extreme price, direction, and reaction facts. ``phase_e_context`` remains
    as a compatibility alias for the current Layer 4 consumer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Direction = Literal["long", "short", "none"]
CandidateStatus = Literal["collecting", "ready", "invalidated", "expired"]


# ---------------------------------------------------------------------------
# Shared reference types
# ---------------------------------------------------------------------------

@dataclass
class EvidenceRef:
    """A pointer to a specific piece of market evidence."""

    ref_id: str | None
    kind: str  # "liquidity_pool" | "sd_zone" | "pd_level" | "structure_event"
    source: str | None
    direction: str | None
    price: float | None
    seen_at: str | None
    variant: str | None = None
    side: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "kind": self.kind,
            "source": self.source,
            "direction": self.direction,
            "price": self.price,
            "seen_at": self.seen_at,
            "variant": self.variant,
            "side": self.side,
        }


@dataclass
class EvidenceCandidate:
    """A structured evidence pattern emitted once per bar by EvidenceCompiler."""

    candidate_id: str
    pattern: str
    status: CandidateStatus
    direction: Direction
    timeframe: str | None
    evidence_refs: list[EvidenceRef]
    source_object_refs: list[dict[str, Any]]   # zone_ids, pool_ids, level prices, etc.
    location_context: dict[str, Any]           # price, timestamp, pd_position
    blocked_reasons: list[str]
    first_seen_at: str | None
    ready_at: str | None
    debug_facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "pattern": self.pattern,
            "status": self.status,
            "direction": self.direction,
            "timeframe": self.timeframe,
            "evidence_refs": [r.to_dict() for r in self.evidence_refs],
            "source_object_refs": list(self.source_object_refs),
            "location_context": dict(self.location_context),
            "blocked_reasons": list(self.blocked_reasons),
            "first_seen_at": self.first_seen_at,
            "ready_at": self.ready_at,
            "debug_facts": dict(self.debug_facts),
        }


# ---------------------------------------------------------------------------
# Internal multi-bar accumulator
# ---------------------------------------------------------------------------

@dataclass
class _ITRGrabRef:
    """Lightweight reference to a recorded ITR grab event."""

    pool_id: str | None
    kind: str
    source: str | None
    direction: str | None
    level: float | None
    seen_at: str | None
    variant: str | None = None
    side: str | None = None

    def to_evidence_ref(self) -> EvidenceRef:
        return EvidenceRef(
            ref_id=self.pool_id,
            kind=self.kind,
            source=self.source,
            direction=self.direction,
            price=self.level,
            seen_at=self.seen_at,
            variant=self.variant,
            side=self.side,
        )


@dataclass
class _BInitiationState:
    """
    Multi-bar accumulator for the HTF B-initiation sequence.

    Step 1 — source ITR grab: HTF ITR level grabbed in the P/D direction.
    Step 2 — opposite ITR grab: after step 1, an ITR level grabbed counter-direction.
    Step 3 — decision zone: an HTF counter-direction SD zone is entered while
              steps 1 + 2 are confirmed.

    Candidate ID is stable once step 1 fires and survives until epoch reset.
    """

    candidate_id: str = field(default_factory=lambda: uuid4().hex)
    source_itr_grab: _ITRGrabRef | None = None
    opposite_itr_grab: _ITRGrabRef | None = None
    decision_zone_ids: list[str] = field(default_factory=list)
    decision_zone_stack_index: int = 0
    first_seen_at: str | None = None

    def reset(self) -> None:
        self.candidate_id = uuid4().hex
        self.source_itr_grab = None
        self.opposite_itr_grab = None
        self.decision_zone_ids.clear()
        self.decision_zone_stack_index = 0
        self.first_seen_at = None

    @property
    def ready(self) -> bool:
        return bool(
            self.source_itr_grab
            and self.opposite_itr_grab
            and self.decision_zone_ids
        )


# ---------------------------------------------------------------------------
# DualContextSnapshot accessors
# ---------------------------------------------------------------------------

def _htf_ctx(fused: dict[str, Any]) -> dict[str, Any]:
    return fused.get("higher_context_snapshot") or fused.get("reference_context") or {}


def _ltf_ctx(fused: dict[str, Any]) -> dict[str, Any]:
    return fused.get("lower_context_snapshot") or fused.get("execution_context") or {}


def _htf_struct(fused: dict[str, Any]) -> dict[str, Any] | None:
    return _htf_ctx(fused).get("structure")


def _ltf_struct(fused: dict[str, Any]) -> dict[str, Any] | None:
    return _ltf_ctx(fused).get("structure")


def _ltf_orderflow(fused: dict[str, Any]) -> dict[str, Any]:
    orderflow = _ltf_ctx(fused).get("orderflow") or fused.get("lower_orderflow") or {}
    return orderflow if isinstance(orderflow, dict) else {}


def _structure_event_action(last_sc: dict[str, Any]) -> str:
    action = str(last_sc.get("eventAction") or "")
    if action in {"structure_sb", "structure_choch"}:
        return action
    if last_sc.get("structure_choch") is True or last_sc.get("choch") is True:
        return "structure_choch"
    if last_sc.get("structure_sb") is True:
        return "structure_sb"
    return "unknown"


def _structure_choch_seen(last_sc: dict[str, Any]) -> bool:
    return _structure_event_action(last_sc) == "structure_choch"


def _structure_ichoch_seen(last_isc: dict[str, Any]) -> bool:
    action = str(last_isc.get("eventAction") or "")
    if action == "structure_ichoch":
        return True
    return last_isc.get("structure_ichoch") is True


def _structure_event_id(last_sc: dict[str, Any]) -> str | None:
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


def _structure_source_level_id(last_sc: dict[str, Any]) -> str | None:
    explicit = last_sc.get("source_level_id") or last_sc.get("level_id") or last_sc.get("levelId")
    if explicit:
        return str(explicit)
    level_ts = last_sc.get("levelTimestamp")
    level_side = last_sc.get("levelSide")
    level_price = last_sc.get("levelPrice")
    if not (level_ts and level_side and level_price is not None):
        return None
    return ":".join(["structure_level", str(level_side), str(level_ts), str(level_price)])


def _htf_zones(fused: dict[str, Any]) -> list[dict[str, Any]]:
    return _htf_ctx(fused).get("zones") or []


def _ltf_zones(fused: dict[str, Any]) -> list[dict[str, Any]]:
    return _ltf_ctx(fused).get("zones") or []


def _htf_liquidity(fused: dict[str, Any]) -> dict[str, Any]:
    liq = _htf_ctx(fused).get("liquidity")
    return liq if isinstance(liq, dict) else {}


def _htf_last_resolved_zone(fused: dict[str, Any]) -> dict[str, Any] | None:
    zone = _htf_ctx(fused).get("last_resolved_zone")
    return zone if isinstance(zone, dict) else None


def _reference_tf(fused: dict[str, Any]) -> str:
    return str(fused.get("reference_tf") or "")


def _execution_tf(fused: dict[str, Any]) -> str:
    return str(fused.get("execution_tf") or "")


def _current_timestamp(fused: dict[str, Any]) -> str | None:
    return fused.get("currentTimestamp")


def _current_price(fused: dict[str, Any]) -> float | None:
    p = fused.get("currentPrice")
    try:
        return float(p) if p is not None else None
    except (TypeError, ValueError):
        return None


def _clamp_pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(100.0, value)), 4)


def _htf_bars_current_and_previous(
    higher_bars: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not higher_bars:
        return None, None
    current = higher_bars[-1]
    previous = higher_bars[-2] if len(higher_bars) >= 2 else None
    return current, previous


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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


def _timestamp_at_or_after(value: str | None, floor: str | None) -> bool:
    if not value or not floor:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) >= datetime.fromisoformat(
            floor.replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return value >= floor


def _inside_range(price: Any, low: Any, high: Any) -> bool:
    try:
        return float(low) <= float(price) <= float(high)
    except (TypeError, ValueError):
        return False


def _compat_candidate(candidate: EvidenceCandidate, pattern: str) -> EvidenceCandidate:
    return EvidenceCandidate(
        candidate_id=candidate.candidate_id,
        pattern=pattern,
        status=candidate.status,
        direction=candidate.direction,
        timeframe=candidate.timeframe,
        evidence_refs=list(candidate.evidence_refs),
        source_object_refs=list(candidate.source_object_refs),
        location_context=dict(candidate.location_context),
        blocked_reasons=list(candidate.blocked_reasons),
        first_seen_at=candidate.first_seen_at,
        ready_at=candidate.ready_at,
        debug_facts=dict(candidate.debug_facts),
    )


def _zone_tf(zone: dict[str, Any]) -> str:
    return str(zone.get("timeframe") or zone.get("tf") or "")


def _is_opposing_htf_sd_resolved(
    last_resolved: dict[str, Any] | None,
    counter_zone_direction: str,
    htf_label: str,
) -> bool:
    if not last_resolved:
        return False
    return bool(
        last_resolved.get("direction") == counter_zone_direction
        and _zone_tf(last_resolved) == htf_label
        and last_resolved.get("resolution") in {"bounced", "liquidity_swept", "broken", "mitigated"}
    )


def _is_htf_pro_sd_resolved(
    last_resolved: dict[str, Any] | None,
    pro_zone_direction: str,
    htf_label: str,
) -> bool:
    if not last_resolved:
        return False
    return bool(
        last_resolved.get("direction") == pro_zone_direction
        and _zone_tf(last_resolved) == htf_label
        and last_resolved.get("resolution") in {"bounced", "liquidity_swept", "broken", "mitigated"}
    )


def _liquidity_grab_ref(
    liquidity: dict[str, Any],
    prefix: str,
) -> _ITRGrabRef:
    return _ITRGrabRef(
        pool_id=liquidity.get(f"{prefix}_pool_id"),
        kind="itr",
        source=liquidity.get(f"{prefix}_source"),
        direction=liquidity.get(f"{prefix}_direction"),
        level=liquidity.get(f"{prefix}_level"),
        seen_at=(
            liquidity.get(f"{prefix}_confirmed_at")
            or liquidity.get(f"{prefix}_taken_at")
        ),
        variant=liquidity.get(f"{prefix}_variant"),
        side=liquidity.get(f"{prefix}_side"),
    )


# ---------------------------------------------------------------------------
# EvidenceCompiler
# ---------------------------------------------------------------------------

class EvidenceCompiler:
    """
    Stateful per-instrument Evidence Compiler.

    Call ``update(fused, higher_bars=...)`` once per bar.
    Returns the full candidate list for that bar — one object per pattern.

    Caller (dual_smc / replayer) is responsible for storing the result in
    ``payload["evidence_candidates"]`` so the DAG Navigator can consume it.
    """

    def __init__(self) -> None:
        # Epoch boundary — reset on new HTF P/D leg
        self.htf_pd_epoch_id: str | None = None

        # Neutral HTF expansion state. Layer 4 decides whether it means Phase E.
        self.htf_expansion_direction: Direction = "none"
        self.htf_expansion_extreme_price: float | None = None
        self.htf_expansion_extreme_at: str | None = None

        # Multi-bar accumulator for B-initiation chain
        self._b_init = _BInitiationState()

    def reset(self) -> None:
        self.htf_pd_epoch_id = None
        self.htf_expansion_direction = "none"
        self.htf_expansion_extreme_price = None
        self.htf_expansion_extreme_at = None
        self._b_init.reset()

    @property
    def active_phase_e_direction(self) -> Direction:
        """Compatibility alias. Phase E meaning belongs to Layer 4."""
        return self.htf_expansion_direction

    @property
    def active_phase_e_extreme_price(self) -> float | None:
        """Compatibility alias for the neutral HTF expansion watermark."""
        return self.htf_expansion_extreme_price

    @property
    def active_phase_e_extreme_time(self) -> str | None:
        """Compatibility alias for the neutral HTF expansion timestamp."""
        return self.htf_expansion_extreme_at

    def update(
        self,
        fused: dict[str, Any],
        *,
        higher_bars: list[dict[str, Any]] | None = None,
    ) -> list[EvidenceCandidate]:
        """
        Evaluate one bar.  Returns current EvidenceCandidate list.

        Parameters
        ----------
        fused:
            Output of ``Fusion.fuse_dual()`` — the DualContextSnapshot.
        higher_bars:
            Recent HTF OHLCV bars (last N bars).  At minimum, pass the last
            two closed bars so reaction signals can be computed.
        """
        htf_struct = _htf_struct(fused)
        htf_ctx = _htf_ctx(fused)
        direction = _direction_from_bias(htf_ctx.get("bias"))
        timestamp = _current_timestamp(fused)

        # Epoch boundary detection — resets accumulator chains
        epoch_id = _epoch_id(htf_struct)
        if epoch_id and epoch_id != self.htf_pd_epoch_id:
            self.htf_pd_epoch_id = epoch_id
            self._b_init.reset()
            self.htf_expansion_direction = "none"
            self.htf_expansion_extreme_price = None
            self.htf_expansion_extreme_at = None

        htf_bar, htf_prev_bar = _htf_bars_current_and_previous(higher_bars)
        candidates: list[EvidenceCandidate] = []

        if direction == "none" or htf_struct is None:
            return candidates

        # Snapshot the extreme BEFORE updating it this bar so expansion context
        # can compute reaction_failed against the previous bar's watermark.
        pre_update_extreme = self.htf_expansion_extreme_price

        # Update neutral expansion tracker — other detectors read it
        self._update_htf_expansion_extreme(fused, htf_struct, direction, htf_bar)

        # 1. B-initiation chain (multi-bar stateful)
        b_init = self._compile_b_initiation(fused, direction, timestamp)
        if b_init is not None:
            candidates.append(b_init)

        # 2. HTF counter-reaction gate (D-phase gate)
        counter_reaction = self._compile_htf_counter_reaction(
            fused,
            htf_struct,
            direction,
            htf_bar,
            timestamp,
            pre_update_extreme=pre_update_extreme,
        )
        if counter_reaction is not None:
            candidates.append(counter_reaction)

        # 2.5. LTF counter choch (standalone structure choch stream)
        ltf_choch = self._compile_ltf_counter_choch(fused, direction, timestamp)
        if ltf_choch is not None:
            candidates.append(ltf_choch)

        # 3. LTF counter-story gate (C-phase gate)
        ltf_story = self._compile_ltf_counter_story(fused, direction, timestamp)
        if ltf_story is not None:
            candidates.append(ltf_story)

        # 4. HTF B-phase setup gate (B-phase direct entry)
        b_setup = self._compile_htf_b_phase_setup(fused, htf_struct, direction, timestamp)
        if b_setup is not None:
            candidates.append(b_setup)

        # 5. HTF P/D objective gate (A-phase finale)
        pd_objective = self._compile_htf_pd_objective(
            fused, htf_struct, direction, htf_bar, timestamp
        )
        if pd_objective is not None:
            candidates.append(pd_objective)

        # 6. Phase-E context (always emitted when direction is known)
        expansion = self._compile_htf_expansion_context(
            fused, htf_struct, direction, htf_bar, htf_prev_bar, timestamp,
            pre_update_extreme=pre_update_extreme,
        )
        if expansion is not None:
            candidates.append(expansion)
            candidates.append(_compat_candidate(expansion, "phase_e_context"))

        return candidates

    # ------------------------------------------------------------------
    # Neutral HTF expansion extreme tracker
    # ------------------------------------------------------------------

    def _update_htf_expansion_extreme(
        self,
        fused: dict[str, Any],
        htf_struct: dict[str, Any],
        direction: Direction,
        htf_bar: dict[str, Any] | None,
    ) -> None:
        """Track the running HTF P/D expansion extreme price for this epoch."""
        if direction == "long":
            struct_price = htf_struct.get("range_high")
            struct_ts = htf_struct.get("range_high_ts")
            bar_price = float(htf_bar["high"]) if htf_bar and htf_bar.get("high") is not None else None
            if struct_price is not None or bar_price is not None:
                candidate = max(
                    float(struct_price) if struct_price is not None else float("-inf"),
                    bar_price if bar_price is not None else float("-inf"),
                )
                ts = struct_ts
                if bar_price is not None and bar_price >= candidate:
                    ts = str(htf_bar.get("time", "")) if htf_bar else struct_ts
                if (
                    self.active_phase_e_extreme_price is None
                    or candidate > self.active_phase_e_extreme_price
                ):
                    self.htf_expansion_direction = direction
                    self.htf_expansion_extreme_price = candidate
                    self.htf_expansion_extreme_at = str(ts) if ts else None

        elif direction == "short":
            struct_price = htf_struct.get("range_low")
            struct_ts = htf_struct.get("range_low_ts")
            bar_price = float(htf_bar["low"]) if htf_bar and htf_bar.get("low") is not None else None
            if struct_price is not None or bar_price is not None:
                candidate = min(
                    float(struct_price) if struct_price is not None else float("inf"),
                    bar_price if bar_price is not None else float("inf"),
                )
                ts = struct_ts
                if bar_price is not None and bar_price <= candidate:
                    ts = str(htf_bar.get("time", "")) if htf_bar else struct_ts
                if (
                    self.active_phase_e_extreme_price is None
                    or candidate < self.active_phase_e_extreme_price
                ):
                    self.htf_expansion_direction = direction
                    self.htf_expansion_extreme_price = candidate
                    self.htf_expansion_extreme_at = str(ts) if ts else None

    def _new_htf_expansion_extreme(
        self,
        direction: Direction,
        htf_bar: dict[str, Any] | None,
        previous_extreme: float | None = None,
        *,
        tolerance: float = 0.0,
    ) -> bool:
        """Return True only when the current bar strictly extends the prior watermark."""
        extreme = previous_extreme
        if extreme is None:
            extreme = self.htf_expansion_extreme_price
        if htf_bar is None or extreme is None:
            return False
        if direction == "long":
            h = htf_bar.get("high")
            return h is not None and float(h) > float(extreme) + tolerance
        if direction == "short":
            lo = htf_bar.get("low")
            return lo is not None and float(lo) < float(extreme) - tolerance
        return False

    def _htf_expansion_equal_extreme_facts(
        self,
        fused: dict[str, Any],
        direction: Direction,
        htf_bar: dict[str, Any] | None,
        previous_extreme: float | None,
        *,
        tolerance: float = 0.0,
    ) -> dict[str, Any]:
        facts = {
            "htf_equal_extreme_retest": False,
            "htf_equal_extreme_kind": None,
            "htf_equal_expansion_extreme_kind": None,
            "htf_equal_extreme_source": None,
            "htf_equal_extreme_level": None,
            "htf_equal_extreme_pool_id": None,
            "htf_equal_extreme_pool_status": None,
            "htf_eqh_at_expansion_extreme": False,
            "htf_eql_at_expansion_extreme": False,
            "htf_eqh_at_phase_e_extreme": False,
            "htf_eql_at_phase_e_extreme": False,
        }
        if htf_bar is None or previous_extreme is None:
            return facts

        source = "eqh" if direction == "long" else "eql"
        bar_key = "high" if direction == "long" else "low"
        bar_level = htf_bar.get(bar_key)
        if bar_level is None:
            return facts

        level = float(previous_extreme)
        equal_retest = abs(float(bar_level) - level) <= tolerance
        liquidity = _htf_liquidity(fused)
        matching_pool = None
        for pool in liquidity.get("active_htf_eq_pools") or []:
            if not isinstance(pool, dict) or pool.get("source") != source:
                continue
            pool_level = pool.get("price", pool.get("level_price"))
            if pool_level is None:
                continue
            pool_tolerance = float(pool.get("tolerance") or tolerance or 0.0)
            if abs(float(pool_level) - level) <= max(tolerance, pool_tolerance):
                matching_pool = pool
                equal_retest = True
                break

        if not equal_retest:
            return facts

        kind = "htf_eqh_at_expansion_extreme" if source == "eqh" else "htf_eql_at_expansion_extreme"
        compatibility_kind = "htf_eqh_at_phase_e_extreme" if source == "eqh" else "htf_eql_at_phase_e_extreme"
        facts.update(
            {
                "htf_equal_extreme_retest": True,
                "htf_equal_extreme_kind": compatibility_kind,
                "htf_equal_expansion_extreme_kind": kind,
                "htf_equal_extreme_source": source,
                "htf_equal_extreme_level": level,
                "htf_equal_extreme_pool_id": matching_pool.get("pool_id") if matching_pool else None,
                "htf_equal_extreme_pool_status": matching_pool.get("status") if matching_pool else None,
                "htf_eqh_at_expansion_extreme": kind == "htf_eqh_at_expansion_extreme",
                "htf_eql_at_expansion_extreme": kind == "htf_eql_at_expansion_extreme",
                # Compatibility aliases for the current Layer 4 consumer.
                "htf_eqh_at_phase_e_extreme": kind == "htf_eqh_at_expansion_extreme",
                "htf_eql_at_phase_e_extreme": kind == "htf_eql_at_expansion_extreme",
            }
        )
        return facts

    # ------------------------------------------------------------------
    # 1.  B-initiation chain
    # ------------------------------------------------------------------

    def _compile_b_initiation(
        self,
        fused: dict[str, Any],
        direction: Direction,
        timestamp: str | None,
    ) -> EvidenceCandidate | None:
        """Multi-bar accumulator: source ITR grab → opposite ITR grab → decision zone."""
        liquidity = _htf_liquidity(fused)
        htf_label = _reference_tf(fused)

        self._observe_b_init_source_grab(liquidity, direction, timestamp)
        self._observe_b_init_opposite_grab(liquidity, direction, timestamp)
        current_decision_zones = self._observe_b_init_decision_zones(
            fused, direction, htf_label
        )

        b = self._b_init
        source = b.source_itr_grab
        opposite = b.opposite_itr_grab

        status: CandidateStatus = (
            "ready"
            if b.ready
            else "collecting"
            if source
            else "collecting"
        )

        if not source and not opposite and not b.decision_zone_ids:
            return None  # Nothing seen yet — suppress until step 1 fires

        evidence_refs: list[EvidenceRef] = []
        if source:
            evidence_refs.append(source.to_evidence_ref())
        if opposite:
            evidence_refs.append(opposite.to_evidence_ref())

        source_object_refs = [
            {"kind": "sd_zone", "zone_id": zid, "timeframe": htf_label}
            for zid in b.decision_zone_ids
        ]

        return EvidenceCandidate(
            candidate_id=b.candidate_id,
            pattern="htf_b_initiation",
            status=status,
            direction=direction,
            timeframe=htf_label,
            evidence_refs=evidence_refs,
            source_object_refs=source_object_refs,
            location_context={
                "timestamp": timestamp,
                "current_price": _current_price(fused),
            },
            blocked_reasons=(
                []
                if b.ready
                else [
                    r
                    for r in [
                        None if source else "source_itr_grab_not_seen",
                        None if (not source or opposite) else "opposite_itr_grab_not_seen",
                        None if (not (source and opposite) or b.decision_zone_ids) else "decision_zone_not_seen",
                    ]
                    if r is not None
                ]
            ),
            first_seen_at=b.first_seen_at,
            ready_at=timestamp if b.ready else None,
            debug_facts={
                "source_itr_grab_seen": bool(source),
                "opposite_itr_grab_seen": bool(opposite),
                "decision_zone_seen": bool(b.decision_zone_ids),
                "decision_zone_ids": list(b.decision_zone_ids),
                "current_decision_zone_ids": list(current_decision_zones),
                "decision_zone_stack_index": b.decision_zone_stack_index,
                "source_pool_id": source.pool_id if source else None,
                "opposite_pool_id": opposite.pool_id if opposite else None,
                "source_anchor_run_seen": self._b_init_source_anchor_run_seen(liquidity),
                "source_anchor_run_pool_id": liquidity.get("htf_itr_anchor_run_pool_id"),
                **self._b_init_liquidity_passthrough(liquidity),
            },
        )

    def _observe_b_init_source_grab(
        self,
        liquidity: dict[str, Any],
        direction: Direction,
        timestamp: str | None,
    ) -> bool:
        if self._b_init.source_itr_grab is not None:
            return True
        expected_direction = "bullish" if direction == "long" else "bearish"
        expected_sources = (
            {"htf_itr_low", "htf_itr_eql"}
            if direction == "long"
            else {"htf_itr_high", "htf_itr_eqh"}
        )
        if not (
            liquidity.get("htf_itr_grab_reclaim_ready")
            and liquidity.get("htf_itr_grab_reclaim_direction") == expected_direction
            and liquidity.get("htf_itr_grab_reclaim_source") in expected_sources
        ):
            return False
        self._b_init.source_itr_grab = _liquidity_grab_ref(liquidity, "htf_itr_grab_reclaim")
        if self._b_init.first_seen_at is None:
            self._b_init.first_seen_at = timestamp
        return True

    def _observe_b_init_opposite_grab(
        self,
        liquidity: dict[str, Any],
        direction: Direction,
        timestamp: str | None,
    ) -> bool:
        if not self._b_init.source_itr_grab:
            return False
        if self._b_init.opposite_itr_grab is not None:
            return True
        expected_direction = "bearish" if direction == "long" else "bullish"
        expected_sources = (
            {"htf_itr_high", "htf_itr_eqh"}
            if direction == "long"
            else {"htf_itr_low", "htf_itr_eql"}
        )
        if not (
            liquidity.get("htf_itr_grab_reclaim_ready")
            and liquidity.get("htf_itr_grab_reclaim_direction") == expected_direction
            and liquidity.get("htf_itr_grab_reclaim_source") in expected_sources
        ):
            return False
        self._b_init.opposite_itr_grab = _liquidity_grab_ref(liquidity, "htf_itr_grab_reclaim")
        return True

    def _observe_b_init_decision_zones(
        self,
        fused: dict[str, Any],
        direction: Direction,
        htf_label: str,
    ) -> list[str]:
        if not self._b_init.opposite_itr_grab:
            return []
        counter_zone_dir = "supply" if direction == "long" else "demand"
        htf_zones_in = [
            str(z.get("zone_id"))
            for z in _htf_zones(fused)
            if z.get("zone_id")
            and z.get("direction") == counter_zone_dir
            and _zone_tf(z) == htf_label
            and bool(z.get("in_zone"))
        ]
        for zid in htf_zones_in:
            if zid not in self._b_init.decision_zone_ids:
                self._b_init.decision_zone_ids.append(zid)
        self._b_init.decision_zone_stack_index = len(self._b_init.decision_zone_ids)
        return htf_zones_in

    def _b_init_source_anchor_run_seen(self, liquidity: dict[str, Any]) -> bool:
        source = self._b_init.source_itr_grab
        return bool(
            source
            and source.pool_id
            and liquidity.get("htf_itr_anchor_run_ready")
            and liquidity.get("htf_itr_anchor_run_pool_id") == source.pool_id
        )

    def _b_init_liquidity_passthrough(self, liquidity: dict[str, Any]) -> dict[str, Any]:
        keys = [
            "htf_itr_grab_reclaim_ready",
            "htf_itr_grab_reclaim_variant",
            "htf_itr_grab_reclaim_direction",
            "htf_itr_grab_reclaim_side",
            "htf_itr_grab_reclaim_source",
            "htf_itr_grab_reclaim_level",
            "htf_itr_grab_reclaim_pool_id",
            "htf_itr_grab_reclaim_came_from",
            "htf_itr_grab_reclaim_left_to",
            "htf_itr_level_grab_reclaim_ready",
            "htf_itr_eq_grab_reclaim_ready",
            "htf_itr_anchor_run_ready",
            "htf_itr_anchor_run_variant",
            "htf_itr_anchor_run_direction",
            "htf_itr_anchor_run_side",
            "htf_itr_anchor_run_source",
            "htf_itr_anchor_run_level",
            "htf_itr_anchor_run_pool_id",
            "htf_itr_anchor_run_take_type",
            "htf_itr_anchor_run_at",
            "htf_itr_level_anchor_run_ready",
            "htf_itr_eq_anchor_run_ready",
        ]
        return {k: liquidity.get(k) for k in keys}

    # ------------------------------------------------------------------
    # 2.  HTF counter-reaction gate  (D-phase gate)
    # ------------------------------------------------------------------

    def _compile_htf_counter_reaction(
        self,
        fused: dict[str, Any],
        htf_struct: dict[str, Any],
        direction: Direction,
        htf_bar: dict[str, Any] | None,
        timestamp: str | None,
        *,
        pre_update_extreme: float | None = None,
    ) -> EvidenceCandidate | None:
        htf_label = _reference_tf(fused)
        ltf_label = _execution_tf(fused)
        counter_zone_dir = "supply" if direction == "long" else "demand"
        counter_ltf_bias = "bearish" if direction == "long" else "bullish"

        htf_counter_zones = [
            z for z in _htf_zones(fused)
            if z.get("direction") == counter_zone_dir and _zone_tf(z) == htf_label
        ]
        ltf_counter_zones = [
            z for z in _ltf_zones(fused)
            if z.get("direction") == counter_zone_dir and _zone_tf(z) == ltf_label
        ]

        last_resolved = _htf_last_resolved_zone(fused)
        htf_opposing_sd_resolved = _is_opposing_htf_sd_resolved(
            last_resolved, counter_zone_dir, htf_label
        )

        eq_tolerance = float((_htf_liquidity(fused).get("eq_tolerance") or 0.0))
        new_extreme = self._new_htf_expansion_extreme(
            direction,
            htf_bar,
            pre_update_extreme,
            tolerance=eq_tolerance,
        )
        htf_pd_stopped_expanding = not new_extreme
        htf_sd_confirmed_pullback = (
            htf_struct.get("phase") == "pullback_confirmed"
            and htf_struct.get("confirmed_by") == "sd_zone"
        )
        htf_opposing_sd_tapped = any(bool(z.get("in_zone")) for z in htf_counter_zones)
        htf_opposing_sd_reaction = (
            htf_sd_confirmed_pullback
            or htf_opposing_sd_tapped
            or htf_opposing_sd_resolved
        )
        ltf_counter_sd_created = bool(ltf_counter_zones)
        ltf_bias_counter = bool(
            _ltf_struct(fused) and _ltf_struct(fused).get("bias") == counter_ltf_bias
        )

        normal_ready = (
            htf_pd_stopped_expanding
            and htf_opposing_sd_reaction
            and ltf_counter_sd_created
        )
        special_ready = new_extreme and not htf_opposing_sd_reaction and ltf_bias_counter

        # Liquidity-grab variant
        liq_grab = self._htf_counter_reaction_liquidity_variant(
            fused,
            htf_struct,
            direction,
            htf_bar,
            pre_update_extreme=pre_update_extreme,
        )
        liq_ready = liq_grab.get("ready", False)
        liq_seen = bool(liq_grab.get("liquidity_reclaim_candidates"))

        ready = normal_ready or special_ready or liq_ready

        trigger: str | None = None
        if liq_ready:
            trigger = liq_grab.get("trigger")
        elif normal_ready:
            trigger = "opposing_htf_sd_reaction_with_ltf_counter_sd"
        elif special_ready:
            trigger = "new_htf_extreme_with_ltf_counter_bias"

        if not ready and not (
            htf_opposing_sd_reaction
            or ltf_counter_sd_created
            or special_ready
            or liq_seen
        ):
            return None  # Nothing meaningful — suppress

        blocked_reasons: list[str] = []
        if not ready:
            blocked_reasons = list(
                dict.fromkeys(
                    reason
                    for reason in (
                        None if htf_pd_stopped_expanding else "htf_pd_still_expanding",
                        None if htf_opposing_sd_reaction else "no_htf_opposing_sd_reaction",
                        None if ltf_counter_sd_created else "no_ltf_counter_sd_zone",
                        *liq_grab.get("liquidity_reclaim_blocked_reasons", []),
                    )
                    if reason is not None
                )
            )

        return EvidenceCandidate(
            candidate_id=uuid4().hex,
            pattern="htf_counter_reaction",
            status="ready" if ready else "collecting",
            direction=direction,
            timeframe=htf_label,
            evidence_refs=[],
            source_object_refs=[
                {"kind": "sd_zone", "zone_id": z.get("zone_id"), "timeframe": htf_label}
                for z in htf_counter_zones
            ] + [
                {"kind": "sd_zone", "zone_id": z.get("zone_id"), "timeframe": ltf_label}
                for z in ltf_counter_zones
            ] + [
                {
                    "kind": "liquidity_event",
                    "liquidity_event_id": event.get("liquidity_event_id"),
                    "pool_id": event.get("pool_id"),
                }
                for event in liq_grab.get("liquidity_reclaim_candidates", [])
            ],
            location_context={
                "timestamp": timestamp,
                "current_price": _current_price(fused),
            },
            blocked_reasons=blocked_reasons,
            first_seen_at=timestamp if (htf_opposing_sd_reaction or liq_seen) else None,
            ready_at=timestamp if ready else None,
            debug_facts={
                **liq_grab,  # spread first so named keys below take precedence
                "trigger": trigger,
                "htf_pd_stopped_expanding": htf_pd_stopped_expanding,
                "new_htf_extreme": new_extreme,
                "htf_opposing_sd_reaction": htf_opposing_sd_reaction,
                "htf_sd_confirmed_pullback": htf_sd_confirmed_pullback,
                "htf_opposing_sd_tapped": htf_opposing_sd_tapped,
                "htf_opposing_sd_resolved": htf_opposing_sd_resolved,
                "htf_last_resolved_zone_id": last_resolved.get("zone_id") if last_resolved else None,
                "htf_last_resolved_zone_direction": last_resolved.get("direction") if last_resolved else None,
                "htf_last_resolved_zone_resolution": last_resolved.get("resolution") if last_resolved else None,
                "htf_opposing_sd_zone_ids": [z.get("zone_id") for z in htf_counter_zones],
                "ltf_counter_sd_created": ltf_counter_sd_created,
                "ltf_counter_sd_zone_ids": [z.get("zone_id") for z in ltf_counter_zones],
                "ltf_bias_counter_htf": ltf_bias_counter,
            },
        )

    def _htf_counter_reaction_liquidity_variant(
        self,
        fused: dict[str, Any],
        htf_struct: dict[str, Any],
        direction: Direction,
        htf_bar: dict[str, Any] | None,
        *,
        pre_update_extreme: float | None = None,
    ) -> dict[str, Any]:
        liquidity = _htf_liquidity(fused)
        expected_grab_dir = "bearish" if direction == "long" else "bullish"
        expected_eq_source = "eqh" if direction == "long" else "eql"
        expected_eq_side = "buy_side" if direction == "long" else "sell_side"
        range_high = htf_struct.get("range_high")
        range_low = htf_struct.get("range_low")
        current_price = _current_price(fused)
        current_probe_inside = _inside_range(current_price, range_low, range_high)
        htf_close = htf_bar.get("close") if htf_bar else None
        htf_close_inside = _inside_range(htf_close, range_low, range_high)
        htf_close_outside = htf_close is not None and not htf_close_inside
        ltf_struct = _ltf_struct(fused) or {}
        last_sc = ltf_struct.get("last_sc") or {}
        expected_counter_break = "down" if direction == "long" else "up"
        expansion_extreme = (
            pre_update_extreme
            if pre_update_extreme is not None
            else self.htf_expansion_extreme_price
        )
        default_tolerance = float(liquidity.get("eq_tolerance") or 0.0)

        candidates: list[dict[str, Any]] = []
        for event in liquidity.get("current_triggerable_liquidity_events") or []:
            if not isinstance(event, dict) or event.get("pool_kind") not in {"htf_pd", "htf_eq"}:
                continue

            event_current = bool(
                event.get("is_triggerable")
                and event.get("scope") in {"active_current_epoch", "carryover_recent"}
                and event.get("htf_pd_epoch_id") == self.htf_pd_epoch_id
            )
            matching_direction = event.get("direction") == expected_grab_dir
            tolerance = max(
                default_tolerance,
                float(event.get("tolerance") or 0.0),
            )
            level = event.get("level")
            relation = "unknown"
            if level is not None and expansion_extreme is not None:
                distance = abs(float(level) - float(expansion_extreme))
                if distance <= 1e-9:
                    relation = "at_active_extreme"
                elif distance <= tolerance:
                    relation = "near_active_extreme"
                else:
                    external_boundary = range_high if direction == "long" else range_low
                    if (
                        external_boundary is not None
                        and abs(float(level) - float(external_boundary)) <= tolerance
                    ):
                        relation = "pro_side_external_range"
                    else:
                        relation = "unrelated"
            if event.get("pool_kind") == "htf_pd":
                relevant_relation = matching_direction and event_current
            else:
                pro_side_eq = bool(
                    event.get("source") == expected_eq_source
                    and event.get("side") == expected_eq_side
                )
                relevant_relation = bool(
                    event_current
                    and pro_side_eq
                    and relation in {
                        "at_active_extreme",
                        "near_active_extreme",
                        "pro_side_external_range",
                    }
                )

            taken_at = event.get("taken_at")
            reclaimed_at = event.get("reclaimed_at")
            fresh_pro_attempt = bool(event_current and matching_direction and taken_at)
            reached_event = bool(fresh_pro_attempt and taken_at)
            failed_continuation = bool(
                reached_event
                and reclaimed_at
                and _timestamp_at_or_after(reclaimed_at, taken_at)
            )
            reclaimed_inside = _inside_range(
                event.get("reclaimed_price"),
                range_low,
                range_high,
            )
            choch_at = last_sc.get("eventTimestamp")
            counter_choch_after_reclaim = bool(
                _structure_choch_seen(last_sc)
                and last_sc.get("breakDirection") == expected_counter_break
                and _timestamp_at_or_after(choch_at, reclaimed_at)
            )

            required = {
                "liquidity_event_is_current": event_current,
                "liquidity_relation_is_relevant": relevant_relation,
                "liquidity_direction_matches_counter_reclaim": matching_direction,
                "fresh_pro_htf_continuation_attempt": fresh_pro_attempt,
                "pro_attempt_reached_liquidity_event": reached_event,
                "pro_attempt_failed_to_establish_continuation": failed_continuation,
                "price_reclaimed_inside_active_htf_pd": reclaimed_inside,
                "ltf_counter_choch_after_reclaim": counter_choch_after_reclaim,
                "htf_close_inside_active_htf_pd": htf_close_inside,
            }
            ready = all(required.values())
            continuation_accepted = bool(
                event_current
                and matching_direction
                and reached_event
                and htf_close_outside
            )
            blocked_reasons = [
                reason
                for fact, reason in (
                    ("liquidity_event_is_current", "liquidity_event_not_current"),
                    ("liquidity_relation_is_relevant", "liquidity_event_not_relevant_to_active_expansion"),
                    ("liquidity_direction_matches_counter_reclaim", "liquidity_direction_mismatch"),
                    ("fresh_pro_htf_continuation_attempt", "fresh_pro_htf_continuation_attempt_not_seen"),
                    ("pro_attempt_reached_liquidity_event", "pro_attempt_did_not_reach_liquidity_event"),
                    ("pro_attempt_failed_to_establish_continuation", "pro_attempt_failure_not_seen"),
                    ("price_reclaimed_inside_active_htf_pd", "price_not_reclaimed_inside_active_htf_pd"),
                    ("ltf_counter_choch_after_reclaim", "post_reclaim_counter_choch_not_seen"),
                    ("htf_close_inside_active_htf_pd", "htf_close_not_inside_active_htf_pd"),
                )
                if not required[fact]
            ]
            candidates.append(
                {
                    **event,
                    "status": "ready" if ready else "invalidated" if continuation_accepted else "collecting",
                    "liquidity_event_is_current": event_current,
                    "liquidity_relation_to_htf_expansion_extreme": relation,
                    # Compatibility alias for the earlier draft contract.
                    "liquidity_relation_to_active_htf_expansion_extreme": relation,
                    "liquidity_relation_is_relevant": relevant_relation,
                    "fresh_pro_htf_continuation_attempt": fresh_pro_attempt,
                    "pro_attempt_reached_liquidity_event": reached_event,
                    "pro_attempt_failed_to_establish_continuation": failed_continuation,
                    "price_reclaimed_inside_active_htf_pd": reclaimed_inside,
                    "current_probe_inside_active_htf_pd": current_probe_inside,
                    "htf_close_inside_active_htf_pd": htf_close_inside,
                    "htf_close_outside_active_htf_pd": htf_close_outside,
                    "ltf_counter_choch_after_reclaim": counter_choch_after_reclaim,
                    "ltf_counter_choch_event_at": choch_at if counter_choch_after_reclaim else None,
                    "ltf_counter_choch_direction": last_sc.get("breakDirection") if counter_choch_after_reclaim else None,
                    "ltf_counter_choch_level": last_sc.get("levelPrice") if counter_choch_after_reclaim else None,
                    "continuation_accepted": continuation_accepted,
                    "blocked_reasons": blocked_reasons,
                }
            )

        ready_ids = [
            event.get("liquidity_event_id")
            for event in candidates
            if event.get("status") == "ready"
        ]
        continuation_ids = [
            event.get("liquidity_event_id")
            for event in candidates
            if event.get("continuation_accepted")
        ]
        return {
            "ready": bool(ready_ids),
            "trigger": "qualified_liquidity_grab_reclaim" if ready_ids else None,
            "liquidity_reclaim_candidates": candidates,
            "liquidity_reclaim_ready_event_ids": ready_ids,
            "liquidity_continuation_accepted_event_ids": continuation_ids,
            "liquidity_reclaim_blocked_reasons": list(
                dict.fromkeys(
                    reason
                    for event in candidates
                    for reason in event.get("blocked_reasons", [])
                )
            ),
            "liquidity_reclaim_expected_direction": expected_grab_dir,
        }

    # ------------------------------------------------------------------
    # 2.5.  LTF counter choch  (standalone structure choch stream)
    # ------------------------------------------------------------------

    def _compile_ltf_counter_choch(
        self,
        fused: dict[str, Any],
        direction: Direction,
        timestamp: str | None,
    ) -> EvidenceCandidate | None:
        ltf_struct = _ltf_struct(fused) or {}
        last_isc = ltf_struct.get("last_isc") or {}  # internal iChoCh (SC06) — primary
        last_sc  = ltf_struct.get("last_sc")  or {}  # macro SC — kept for sb_seen fallback
        if not last_isc and not last_sc:
            return None

        ltf_label = _execution_tf(fused)
        expected_counter_break = "down" if direction == "long" else "up"

        # PRIMARY: internal iChoCh (SC06) against confirmed ITR pivot
        choch_seen = bool(
            _structure_ichoch_seen(last_isc)
            and last_isc.get("breakDirection") == expected_counter_break
        )
        choch_at              = last_isc.get("eventTimestamp")      if choch_seen else None
        choch_level           = last_isc.get("levelPrice")          if choch_seen else None
        choch_direction       = last_isc.get("breakDirection")      if choch_seen else None
        choch_event_id        = _structure_event_id(last_isc)       if choch_seen else None
        choch_source_level_id = _structure_source_level_id(last_isc) if choch_seen else None

        # FALLBACK: macro counter SB from last_sc (Path B — pullback_confirmed gate in DAG)
        sb_seen = bool(
            not choch_seen
            and _structure_event_action(last_sc) == "structure_sb"
            and last_sc.get("breakDirection") == expected_counter_break
        )
        sb_level           = last_sc.get("levelPrice")      if sb_seen else None
        sb_at              = last_sc.get("eventTimestamp")  if sb_seen else None
        sb_event_id        = _structure_event_id(last_sc)   if sb_seen else None
        sb_source_level_id = _structure_source_level_id(last_sc) if sb_seen else None

        return EvidenceCandidate(
            candidate_id=uuid4().hex,
            pattern="ltf_counter_choch",
            status="ready" if choch_seen else "collecting",
            direction=direction,
            timeframe=ltf_label,
            evidence_refs=[],
            source_object_refs=[],
            location_context={"timestamp": timestamp, "current_price": _current_price(fused)},
            blocked_reasons=[] if choch_seen else ["no_ltf_counter_ichoch"],
            first_seen_at=choch_at,
            ready_at=timestamp if choch_seen else None,
            debug_facts={
                "ltf_counter_choch_seen": choch_seen,
                "ltf_counter_structure_choch_seen": choch_seen,
                "ltf_counter_choch_event_at": choch_at,
                "ltf_counter_choch_direction": choch_direction,
                "ltf_counter_choch_level": choch_level,
                "ltf_counter_choch_event_id": choch_event_id,
                "ltf_counter_choch_source_level_id": choch_source_level_id,
                "ltf_counter_choch_source_store": "structure_isc" if choch_seen else None,
                "ltf_counter_sb_seen": sb_seen,
                "ltf_counter_sb_level": sb_level,
                "ltf_counter_sb_event_at": sb_at,
                "ltf_counter_sb_event_id": sb_event_id,
                "ltf_counter_sb_source_level_id": sb_source_level_id,
                "ltf_counter_sb_source_store": "structure_sequence" if sb_seen else None,
            },
        )

    # ------------------------------------------------------------------
    # 3.  LTF counter-story gate  (C-phase gate)
    # ------------------------------------------------------------------

    def _compile_ltf_counter_story(
        self,
        fused: dict[str, Any],
        direction: Direction,
        timestamp: str | None,
    ) -> EvidenceCandidate | None:
        ltf_struct = _ltf_struct(fused)
        ltf_label = _execution_tf(fused)
        counter_zone_dir = "supply" if direction == "long" else "demand"
        counter_ltf_bias = "bearish" if direction == "long" else "bullish"

        ltf_counter_zones = [
            z for z in _ltf_zones(fused)
            if z.get("direction") == counter_zone_dir and _zone_tf(z) == ltf_label
        ]
        ltf_counter_zones.sort(
            key=lambda z: (str(z.get("created_at") or ""), str(z.get("zone_id") or ""))
        )
        returned_zones = [z for z in ltf_counter_zones if bool(z.get("in_zone"))]
        selected_poi = returned_zones[0] if returned_zones else (
            ltf_counter_zones[0] if ltf_counter_zones else None
        )

        ltf_bias_counter = bool(ltf_struct and ltf_struct.get("bias") == counter_ltf_bias)
        ltf_last_sc = ltf_struct.get("last_sc") if ltf_struct else None
        ltf_counter_break_dir = "down" if direction == "long" else "up"
        ltf_counter_pd_break = bool(
            ltf_bias_counter
            and isinstance(ltf_last_sc, dict)
            and ltf_last_sc.get("breakDirection") == ltf_counter_break_dir
        )
        ltf_counter_pullback_confirmed = bool(
            ltf_struct
            and ltf_struct.get("phase") == "pullback_confirmed"
            and ltf_struct.get("bias") == counter_ltf_bias
        )

        ltf_orderflow = _ltf_orderflow(fused)
        orderflow_direction = ltf_orderflow.get("confirmed_direction")
        orderflow_regime = ltf_orderflow.get("regime")
        ltf_counter_bos_confirmed = bool(
            orderflow_direction == counter_ltf_bias
            and orderflow_regime == "directional"
        )

        story_ready = ltf_bias_counter
        armed = bool(story_ready and selected_poi)
        touched = bool(armed and selected_poi and selected_poi.get("in_zone"))

        if not story_ready:
            return None

        return EvidenceCandidate(
            candidate_id=uuid4().hex,
            pattern="ltf_counter_story",
            status="ready",
            direction=direction,
            timeframe=ltf_label,
            evidence_refs=[],
            source_object_refs=[
                {"kind": "sd_zone", "zone_id": z.get("zone_id"), "timeframe": ltf_label}
                for z in ltf_counter_zones
            ],
            location_context={
                "timestamp": timestamp,
                "current_price": _current_price(fused),
                "selected_poi_id": selected_poi.get("zone_id") if selected_poi else None,
                "selected_poi_touched": touched,
            },
            blocked_reasons=(
                []
                if armed
                else ["no_ltf_counter_sd_zone_available"]
            ),
            first_seen_at=timestamp if ltf_bias_counter else None,
            ready_at=timestamp,
            debug_facts={
                "ltf_bias_counter_htf": ltf_bias_counter,
                "ltf_counter_pd_break": ltf_counter_pd_break,
                "ltf_counter_break_direction": ltf_counter_break_dir,
                "ltf_counter_pullback_confirmed": ltf_counter_pullback_confirmed,
                "ltf_counter_sd_zone_ids": [z.get("zone_id") for z in ltf_counter_zones],
                "ltf_counter_sd_returned_zone_ids": [z.get("zone_id") for z in returned_zones],
                "selected_poi_id": selected_poi.get("zone_id") if selected_poi else None,
                "selected_poi": selected_poi,
                "ltf_counter_bos_confirmed": ltf_counter_bos_confirmed,
            },
        )

    # ------------------------------------------------------------------
    # 4.  HTF B-phase setup  (B-phase direct entry gate)
    # ------------------------------------------------------------------

    def _compile_htf_b_phase_setup(
        self,
        fused: dict[str, Any],
        htf_struct: dict[str, Any],
        direction: Direction,
        timestamp: str | None,
    ) -> EvidenceCandidate | None:
        htf_label = _reference_tf(fused)
        ltf_label = _execution_tf(fused)
        pro_zone_dir = "demand" if direction == "long" else "supply"

        htf_pro_zones = [
            z for z in _htf_zones(fused)
            if z.get("direction") == pro_zone_dir and _zone_tf(z) == htf_label
        ]
        ltf_pro_zones = [
            z for z in _ltf_zones(fused)
            if z.get("direction") == pro_zone_dir and _zone_tf(z) == ltf_label
        ]
        ltf_pro_zones.sort(
            key=lambda z: (str(z.get("created_at") or ""), str(z.get("zone_id") or ""))
        )

        # HTF P/D position — how deep in the pullback are we
        htf_pd_value_pct = htf_struct.get("pd_value_pct")
        htf_range_pos_pct = htf_struct.get("range_position_pct", htf_struct.get("pd_pct"))
        if htf_pd_value_pct is None and htf_range_pos_pct is not None:
            if htf_struct.get("bias") == "bullish":
                htf_pd_value_pct = htf_range_pos_pct
            elif htf_struct.get("bias") == "bearish":
                htf_pd_value_pct = 100.0 - float(htf_range_pos_pct)
        htf_pd_value = float(htf_pd_value_pct) if htf_pd_value_pct is not None else None

        strict_pd_half = htf_pd_value is not None and htf_pd_value < 50.0
        shallow_pd_half = htf_pd_value is not None and 50.0 <= htf_pd_value <= 70.0
        location_sub = (
            "strict" if strict_pd_half
            else "shallow" if shallow_pd_half
            else "invalid"
        )

        ltf_struct = _ltf_struct(fused)
        ltf_turns_back = bool(
            ltf_struct
            and ltf_struct.get("bias") == htf_struct.get("bias")
            and _direction_from_bias(ltf_struct.get("bias")) == direction
        )

        htf_pro_sd_tapped = any(bool(z.get("in_zone")) for z in htf_pro_zones)
        last_resolved = _htf_last_resolved_zone(fused)
        htf_pro_sd_resolved = _is_htf_pro_sd_resolved(last_resolved, pro_zone_dir, htf_label)
        htf_pro_sd_reaction = htf_pro_sd_tapped or htf_pro_sd_resolved

        htf_pullback_evidence = htf_struct.get("phase") == "pullback_confirmed"
        htf_pullback_context_ready = htf_struct.get("phase") != "open"

        selected_poi = ltf_pro_zones[-1] if ltf_pro_zones else None
        ltf_pro_sd_selected = selected_poi is not None

        market_candidate = (
            (strict_pd_half or shallow_pd_half)
            and ltf_turns_back
            and ltf_pro_sd_selected
        )
        base_candidate = market_candidate and htf_pullback_context_ready
        strict_ready = base_candidate and strict_pd_half and htf_pro_sd_reaction
        shallow_ready = base_candidate and shallow_pd_half and htf_pro_sd_reaction
        ready = strict_ready or shallow_ready

        if not market_candidate:
            return None

        return EvidenceCandidate(
            candidate_id=uuid4().hex,
            pattern="htf_b_phase_setup",
            status="ready" if ready else "collecting",
            direction=direction,
            timeframe=htf_label,
            evidence_refs=[],
            source_object_refs=[
                {"kind": "sd_zone", "zone_id": z.get("zone_id"), "timeframe": ltf_label}
                for z in ltf_pro_zones
            ],
            location_context={
                "timestamp": timestamp,
                "current_price": _current_price(fused),
                "selected_poi_id": selected_poi.get("zone_id") if selected_poi else None,
                "location_sub": location_sub,
                "htf_pd_value_pct": htf_pd_value,
            },
            blocked_reasons=(
                []
                if ready
                else [
                    r
                    for r in [
                        None if htf_pullback_context_ready else "no_htf_pullback_context",
                        None if (strict_pd_half or shallow_pd_half) else "htf_pd_position_invalid",
                        None if ltf_turns_back else "ltf_not_turned_back_toward_htf",
                        None if ltf_pro_sd_selected else "no_ltf_pro_sd_zone",
                        None if htf_pro_sd_reaction else "no_htf_pro_sd_reaction",
                    ]
                    if r is not None
                ]
            ),
            first_seen_at=timestamp if market_candidate else None,
            ready_at=timestamp if ready else None,
            debug_facts={
                "location_sub": location_sub,
                "htf_pd_value_pct": htf_pd_value,
                "htf_range_position_pct": htf_range_pos_pct,
                "strict_pd_half": strict_pd_half,
                "shallow_pd_half": shallow_pd_half,
                "htf_pullback_context_ready": htf_pullback_context_ready,
                "htf_pullback_evidence": htf_pullback_evidence,
                "htf_pro_sd_tapped": htf_pro_sd_tapped,
                "htf_pro_sd_resolved": htf_pro_sd_resolved,
                "htf_last_resolved_zone_id": last_resolved.get("zone_id") if last_resolved else None,
                "htf_last_resolved_zone_direction": last_resolved.get("direction") if last_resolved else None,
                "htf_last_resolved_zone_resolution": last_resolved.get("resolution") if last_resolved else None,
                "ltf_turns_back_toward_htf": ltf_turns_back,
                "htf_pro_sd_zone_ids": [z.get("zone_id") for z in htf_pro_zones],
                "ltf_pro_sd_zone_ids": [z.get("zone_id") for z in ltf_pro_zones],
                "selected_poi": selected_poi,
                "strict_ready": strict_ready,
                "shallow_ready": shallow_ready,
            },
        )

    # ------------------------------------------------------------------
    # 5.  HTF P/D objective gate  (A-phase finale)
    # ------------------------------------------------------------------

    def _compile_htf_pd_objective(
        self,
        fused: dict[str, Any],
        htf_struct: dict[str, Any],
        direction: Direction,
        htf_bar: dict[str, Any] | None,
        timestamp: str | None,
    ) -> EvidenceCandidate | None:
        objective = (
            htf_struct.get("range_high") if direction == "long"
            else htf_struct.get("range_low")
        )
        if objective is None or htf_bar is None:
            return None

        objective_price = float(objective)
        high = float(htf_bar.get("high", 0))
        low = float(htf_bar.get("low", 0))
        close = float(htf_bar.get("close", 0))

        if direction == "long":
            touched = high >= objective_price
            closed_beyond = close > objective_price
            rule = (
                "bullish_phase_a_close_above_htf_pd_objective"
                if closed_beyond
                else "bullish_phase_a_touch_without_close_above_htf_pd_objective"
            )
        else:
            touched = low <= objective_price
            closed_beyond = close < objective_price
            rule = (
                "bearish_phase_a_close_below_htf_pd_objective"
                if closed_beyond
                else "bearish_phase_a_touch_without_close_below_htf_pd_objective"
            )

        if not touched:
            return None

        return EvidenceCandidate(
            candidate_id=uuid4().hex,
            pattern="htf_pd_objective",
            status="ready",
            direction=direction,
            timeframe=_reference_tf(fused),
            evidence_refs=[],
            source_object_refs=[],
            location_context={
                "timestamp": timestamp,
                "objective_price": objective_price,
                "current_price": _current_price(fused),
            },
            blocked_reasons=[],
            first_seen_at=timestamp,
            ready_at=timestamp,
            debug_facts={
                "phase_a_finale_touched": touched,
                "phase_a_finale_closed_beyond": closed_beyond,
                "phase_a_finale_direction": direction,
                "phase_a_finale_objective": objective_price,
                "phase_a_finale_rule": rule,
                "current_htf_high": high,
                "current_htf_low": low,
                "current_htf_close": close,
            },
        )

    # ------------------------------------------------------------------
    # 6.  Neutral HTF expansion context  (always emitted when direction is known)
    # ------------------------------------------------------------------

    def _compile_htf_expansion_context(
        self,
        fused: dict[str, Any],
        htf_struct: dict[str, Any],
        direction: Direction,
        htf_bar: dict[str, Any] | None,
        htf_prev_bar: dict[str, Any] | None,
        timestamp: str | None,
        *,
        pre_update_extreme: float | None = None,
    ) -> EvidenceCandidate | None:
        """
        Emits neutral HTF expansion context every bar when direction is known.

        Layer 4 may interpret this as Phase E, but Layer 3 does not read phase state.
        """
        htf_bias = htf_struct.get("bias") if htf_struct else None
        if not htf_bias:
            return None

        htf_phase = htf_struct.get("phase") if htf_struct else None
        ltf_struct = _ltf_struct(fused)
        ltf_orderflow = _ltf_orderflow(fused)
        counter_ltf_bias = "bearish" if direction == "long" else "bullish"
        ltf_bias_counter = bool(
            ltf_struct and ltf_struct.get("bias") == counter_ltf_bias
        )
        orderflow_direction = ltf_orderflow.get("confirmed_direction")
        orderflow_quality = ltf_orderflow.get("quality")
        orderflow_regime = ltf_orderflow.get("regime")
        orderflow_mss_regime = ltf_orderflow.get("mss_regime") or orderflow_regime
        orderflow_mss_monitor_status = ltf_orderflow.get("mss_monitor_status")
        orderflow_mss_trigger_source = ltf_orderflow.get("mss_trigger_source")
        orderflow_probe_breaks_protected_anchor = bool(
            ltf_orderflow.get("probe_breaks_protected_anchor")
        )
        ltf_counter_orderflow_direction = (
            orderflow_direction if orderflow_direction in {"bullish", "bearish"} else None
        )
        pro_ltf_bias = "bullish" if direction == "long" else "bearish"
        ltf_counter_orderflow_mss_watch = bool(
            ltf_counter_orderflow_direction == pro_ltf_bias
            and orderflow_mss_regime == "mss_watch"
            and orderflow_mss_monitor_status == "watching_resolution"
            and orderflow_mss_trigger_source == "probe_vs_protected_anchor"
            and orderflow_probe_breaks_protected_anchor
        )
        ltf_swing_orderflow_mss_watch = bool(
            ltf_counter_orderflow_direction == pro_ltf_bias
            and ltf_orderflow.get("mss_watch_confirmed", False)
        )
        ltf_counter_orderflow_clean = bool(
            ltf_counter_orderflow_direction == counter_ltf_bias
            and orderflow_quality == "clean"
            and orderflow_regime == "directional"
        )
        ltf_counter_orderflow_broken = bool(
            orderflow_regime in {"compression", "sweep_range"}
            or orderflow_quality == "broken"
            or (
                ltf_counter_orderflow_direction
                and ltf_counter_orderflow_direction != counter_ltf_bias
            )
        )
        ltf_counter_orderflow_leg_id = (
            ltf_orderflow.get("range_ref")
            or ltf_orderflow.get("protected_anchor_ref")
            or ltf_orderflow.get("last_shift_at")
        )
        ltf_counter_orderflow_started_at = ltf_orderflow.get("last_shift_at")
        ltf_counter_orderflow_anchor_id = ltf_orderflow.get("protected_anchor_ref")
        ltf_counter_orderflow_disruption_id = (
            ltf_orderflow.get("disruption_point_ref")
            or ltf_orderflow.get("probe_ref")
        )
        ltf_counter_orderflow_source_store = (
            ltf_orderflow.get("source_store")
            or ltf_orderflow.get("source")
        )
        current_price = _current_price(fused)
        range_high = htf_struct.get("range_high")
        range_low = htf_struct.get("range_low")
        ltf_probe_outside_htf_pd_range = False
        ltf_probe_direction: str | None = None
        ltf_pullback_depth_pct: float | None = None
        if current_price is not None and range_high is not None and range_low is not None:
            price = float(current_price)
            high = float(range_high)
            low = float(range_low)
            span = abs(high - low)
            if span > 0:
                if direction == "long":
                    ltf_pullback_depth_pct = _clamp_pct(((high - price) / span) * 100.0)
                elif direction == "short":
                    ltf_pullback_depth_pct = _clamp_pct(((price - low) / span) * 100.0)
            if price > high:
                ltf_probe_outside_htf_pd_range = True
                ltf_probe_direction = "pro" if direction == "long" else "counter"
            elif price < low:
                ltf_probe_outside_htf_pd_range = True
                ltf_probe_direction = "pro" if direction == "short" else "counter"

        ltf_pd_counter_range_breached = False
        if current_price is not None and ltf_struct:
            ltf_range_low = ltf_struct.get("range_low")
            ltf_range_high = ltf_struct.get("range_high")
            try:
                price = float(current_price)
                if direction == "long" and ltf_range_low is not None:
                    ltf_pd_counter_range_breached = price < float(ltf_range_low)
                elif direction == "short" and ltf_range_high is not None:
                    ltf_pd_counter_range_breached = price > float(ltf_range_high)
            except (TypeError, ValueError):
                pass

        # HTF opposing zone probe — only meaningful during active expansion (new_htf_extreme guard
        # applied after new_extreme is computed below; set defaults here, updated after).
        _htf_label_ec = _reference_tf(fused)
        _opposing_dir = "supply" if direction == "long" else "demand"
        _htf_opp_zones = [
            z for z in _htf_zones(fused)
            if z.get("direction") == _opposing_dir and _zone_tf(z) == _htf_label_ec
        ]
        _opp_zone_entered = any(bool(z.get("in_zone")) for z in _htf_opp_zones)
        _opp_zone_id: str | None = next(
            (str(z["zone_id"]) for z in _htf_opp_zones if bool(z.get("in_zone")) and z.get("zone_id")),
            None,
        )

        # Two-bar reaction signal (previous HTF bar vs current HTF bar close)
        reaction_confirmed = False
        reaction_warning = False
        reaction_rule: str | None = None

        if htf_bar and htf_prev_bar:
            if direction == "long":
                prev_low = float(htf_prev_bar.get("low", 0))
                cur_low = float(htf_bar.get("low", 0))
                cur_close = float(htf_bar.get("close", 0))
                reaction_confirmed = cur_close < prev_low
                reaction_warning = cur_low < prev_low
                reaction_rule = "bullish_phase_e_close_below_previous_htf_low"
            elif direction == "short":
                prev_high = float(htf_prev_bar.get("high", 0))
                cur_high = float(htf_bar.get("high", 0))
                cur_close = float(htf_bar.get("close", 0))
                reaction_confirmed = cur_close > prev_high
                reaction_warning = cur_high > prev_high
                reaction_rule = "bearish_phase_e_close_above_previous_htf_high"

        # Reaction-failed signal (for D→E collapse detection by DAG).
        # Compared against the pre-update extreme (watermark from before this bar),
        # so a bar that makes a new extreme AND closes past the old watermark is flagged.
        reaction_failed = False
        reaction_failed_rule: str | None = None
        if htf_bar and pre_update_extreme is not None:
            close = float(htf_bar.get("close", 0))
            if direction == "long":
                reaction_failed = close > pre_update_extreme
                reaction_failed_rule = "bullish_phase_d_close_above_phase_e_extreme"
            elif direction == "short":
                reaction_failed = close < pre_update_extreme
                reaction_failed_rule = "bearish_phase_d_close_below_phase_e_extreme"

        eq_tolerance = float((_htf_liquidity(fused).get("eq_tolerance") or 0.0))
        new_extreme = self._new_htf_expansion_extreme(
            direction,
            htf_bar,
            pre_update_extreme,
            tolerance=eq_tolerance,
        )
        htf_pd_stopped_expanding = not new_extreme
        equal_extreme = self._htf_expansion_equal_extreme_facts(
            fused,
            direction,
            htf_bar,
            pre_update_extreme,
            tolerance=eq_tolerance,
        )

        return EvidenceCandidate(
            candidate_id=uuid4().hex,
            pattern="htf_expansion_context",
            status="ready",
            direction=direction,
            timeframe=_reference_tf(fused),
            evidence_refs=[],
            source_object_refs=[],
            location_context={
                "timestamp": timestamp,
                "current_price": _current_price(fused),
                "htf_bias": htf_bias,
                "htf_phase": htf_phase,
            },
            blocked_reasons=[],
            first_seen_at=timestamp,
            ready_at=timestamp,
            debug_facts={
                "htf_expansion_direction": self.htf_expansion_direction,
                "htf_expansion_extreme_price": self.htf_expansion_extreme_price,
                "htf_expansion_extreme_at": self.htf_expansion_extreme_at,
                "htf_expansion_epoch_id": self.htf_pd_epoch_id,
                # Compatibility aliases for the current Layer 4 consumer.
                "active_phase_e_direction": self.active_phase_e_direction,
                "active_phase_e_extreme_price": self.active_phase_e_extreme_price,
                "active_phase_e_extreme_time": self.active_phase_e_extreme_time,
                "new_htf_extreme": new_extreme,
                "htf_pd_stopped_expanding": htf_pd_stopped_expanding,
                **equal_extreme,
                "ltf_bias_counter_htf": ltf_bias_counter,
                "ltf_probe_outside_htf_pd_range": ltf_probe_outside_htf_pd_range,
                "ltf_probe_direction": ltf_probe_direction,
                "ltf_pd_counter_range_breached": ltf_pd_counter_range_breached,
                "ltf_counter_orderflow_direction": ltf_counter_orderflow_direction,
                "ltf_counter_orderflow_mss_watch": ltf_counter_orderflow_mss_watch,
                "ltf_swing_orderflow_mss_watch": ltf_swing_orderflow_mss_watch,
                "ltf_counter_orderflow_mss_regime": orderflow_mss_regime,
                "ltf_counter_orderflow_mss_monitor_status": orderflow_mss_monitor_status,
                "ltf_counter_orderflow_mss_trigger_source": orderflow_mss_trigger_source,
                "ltf_counter_orderflow_probe_breaks_protected_anchor": orderflow_probe_breaks_protected_anchor,
                "ltf_counter_orderflow_clean": ltf_counter_orderflow_clean,
                "ltf_counter_orderflow_broken": ltf_counter_orderflow_broken,
                "ltf_counter_orderflow_leg_id": ltf_counter_orderflow_leg_id,
                "ltf_counter_orderflow_started_at": ltf_counter_orderflow_started_at,
                "ltf_counter_orderflow_anchor_id": ltf_counter_orderflow_anchor_id,
                "ltf_counter_orderflow_disruption_id": ltf_counter_orderflow_disruption_id,
                "ltf_counter_orderflow_source_store": ltf_counter_orderflow_source_store,
                "ltf_counter_orderflow_quality": orderflow_quality,
                "ltf_counter_orderflow_regime": orderflow_regime,
                "ltf_probe_at_htf_opposing_zone": _opp_zone_entered,
                "ltf_probe_htf_opposing_zone_id": _opp_zone_id if _opp_zone_entered else None,
                "ltf_pullback_depth_pct": ltf_pullback_depth_pct,
                "reaction_confirmed": reaction_confirmed,
                "reaction_warning": reaction_warning,
                "reaction_rule": reaction_rule if (reaction_confirmed or reaction_warning) else None,
                "reaction_failed": reaction_failed,
                "reaction_failed_rule": reaction_failed_rule if reaction_failed else None,
                "previous_htf_low": float(htf_prev_bar.get("low", 0)) if htf_prev_bar else None,
                "current_htf_low": float(htf_bar.get("low", 0)) if htf_bar else None,
                "previous_htf_high": float(htf_prev_bar.get("high", 0)) if htf_prev_bar else None,
                "current_htf_high": float(htf_bar.get("high", 0)) if htf_bar else None,
                "current_htf_close": float(htf_bar.get("close", 0)) if htf_bar else None,
                "htf_phase": htf_phase,
                "htf_bias": htf_bias,
            },
        )
