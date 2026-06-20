from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal
from uuid import uuid4


Direction = Literal["long", "short"]


@dataclass(frozen=True)
class CounterEntryEvidence:
    evidence_kind: str
    evidence_id: str
    timeframe: str | None
    direction: Direction
    presented_at: str | None
    source_store: str
    zone_id: str | None = None
    high: float | None = None
    low: float | None = None
    in_zone: bool | None = None
    liquidity_event_id: str | None = None
    pool_id: str | None = None
    level: float | None = None
    taken_at: str | None = None
    reclaimed_at: str | None = None
    sl_side: str | None = None
    sl_price_raw: float | None = None
    sl_buffer_pips: float = 2.0
    sl_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TriggerEvidence:
    trigger_kind: str
    trigger_path: str
    event_at: str | None
    event_id: str | None
    level: float | None
    source_level_id: str | None
    source_store: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EntryIntent:
    intent_id: str
    symbol: str
    timeframe: str
    epoch_id: str
    phase: str
    phase_sub_status: str | None
    phase_episode_id: str
    policy_name: str
    direction: Direction
    execution_mode: str
    entry_price: float
    stop_loss: float
    target_price: float
    target_r: float
    risk_pips: float
    created_at: str | None
    evidence: CounterEntryEvidence
    trigger: TriggerEvidence
    budget_spent: bool = True
    skip_reason: str | None = None


@dataclass(frozen=True)
class SkipIntent:
    intent_id: str
    symbol: str
    timeframe: str
    epoch_id: str
    phase: str
    phase_sub_status: str | None
    phase_episode_id: str
    policy_name: str
    direction: Direction
    created_at: str | None
    skip_reason: str
    evidence: CounterEntryEvidence | None
    trigger: TriggerEvidence | None
    budget_spent: bool = False
    stale_marked: bool = False
    risk_pips: float | None = None


def pip_size_for_symbol(symbol: str) -> float:
    return 0.01 if symbol.upper().endswith("JPY") else 0.0001


def _opposite(direction: str | None) -> Direction | None:
    if direction == "long":
        return "short"
    if direction == "short":
        return "long"
    return None


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _time_gt(left: str | None, right: str | None) -> bool:
    return bool(left and right and str(left) > str(right))


def _candidate(snapshot: dict[str, Any], pattern: str, direction: str | None) -> dict[str, Any] | None:
    for item in snapshot.get("evidence_candidates") or []:
        if item.get("pattern") == pattern and item.get("direction") == direction:
            return item
    return None


class EntryBudgetLedger:
    def __init__(self, epoch_budget: int = 1) -> None:
        self.epoch_budget = epoch_budget
        self.epoch_id: str | None = None
        self.epoch_direction: str | None = None
        self.spent_by_epoch = 0
        self.spent_by_phase: dict[str, int] = {}
        self.spent_by_phase_episode: dict[str, int] = {}

    def sync_epoch(self, epoch_id: str | None, epoch_direction: str | None) -> None:
        if epoch_id != self.epoch_id or epoch_direction != self.epoch_direction:
            self.epoch_id = epoch_id
            self.epoch_direction = epoch_direction
            self.spent_by_epoch = 0
            self.spent_by_phase = {}
            self.spent_by_phase_episode = {}

    def available(self, phase: str, phase_episode_id: str) -> bool:
        if phase != "D":
            return False
        if self.spent_by_epoch >= self.epoch_budget:
            return False
        if self.spent_by_phase.get(phase, 0) >= 1:
            return False
        return self.spent_by_phase_episode.get(phase_episode_id, 0) < 1

    def spend(self, phase: str, phase_episode_id: str) -> None:
        self.spent_by_epoch += 1
        self.spent_by_phase[phase] = self.spent_by_phase.get(phase, 0) + 1
        self.spent_by_phase_episode[phase_episode_id] = (
            self.spent_by_phase_episode.get(phase_episode_id, 0) + 1
        )


class EntryPermissionEngine:
    """Layer 5 Phase D permission engine — D.lax policy.

    SA:         D.watch, no zone — iChoCh bar close → entry. SL = watch_range_extreme + buffer.
    B:          D.watch, zone tapped during hold — iChoCh → entry. SL = zone proximal.
    C2:         C.pullback (origin D.watch_mss), no prior iChoCh → entry at transition bar.
    B_express:  Express D.watch (zone tap at E.stalling/pullback) + iChoCh → entry.
                SL = express_zone_proximal from shadow (fallback: watch_range_extreme).
    C2_express: Express D.watch + MSS fires, no prior iChoCh → entry at C.pullback transition bar.
                SL = express_zone_proximal from shadow (fallback: watch_range_extreme).
    All:    TP = pd_midpoint (50% HTF PD range). RR >= 1.75 to take.
    Symbol geometry (sl_band_pips, sl_buffer_pips) is per-symbol from config.yaml asset_geometry.
    Unknown symbol returns None — no silent fallback to EURUSD defaults.
    """

    def __init__(
        self,
        *,
        policy_name: str = "D.lax",
        symbol_geometry: dict[str, dict] | None = None,
        min_rr: float = 1.75,
        epoch_budget: int = 1,
    ) -> None:
        self.policy_name = policy_name
        self.symbol_geometry: dict[str, dict] = symbol_geometry or {}
        self.min_rr = min_rr
        self.budget = EntryBudgetLedger(epoch_budget=epoch_budget)
        self._stale_opportunities: set[tuple[str, str, str | None]] = set()
        self._processed_opportunities: set[tuple[str, str, str | None]] = set()
        # cache_key = "{epoch_id}:{prior_direction}" — stable across D→C phase transition
        self._d_watch_budget_spent: dict[str, bool] = {} # True once any path fires and is accepted

    def evaluate(self, snapshot: dict[str, Any]) -> EntryIntent | SkipIntent | None:
        hypothesis = snapshot.get("hypothesis") or {}
        debug = hypothesis.get("debug_facts") or {}
        phase = hypothesis.get("phase")
        phase_sub_status = hypothesis.get("phase_sub_status")

        # Resolve symbol geometry — unknown symbol returns None (no silent EURUSD fallback)
        sym = str(snapshot.get("symbol") or "")
        geom = self.symbol_geometry.get(sym)
        if geom is None:
            return None
        min_sl_pips = float(geom["min_sl_pips"])
        max_sl_pips = float(geom["max_sl_pips"])
        sl_buffer_pips = float(geom.get("sl_buffer_pips", 2.0))
        pip_size = pip_size_for_symbol(sym)

        # ── Path C: C.pullback from D.watch_mss ───────────────────────────────
        # Path C is a transition-bar entry. Persistent phase_c_shadow_origin_node
        # is deliberately ignored so later C.pullback hold bars cannot retry.
        if (phase == "C" and phase_sub_status == "pullback"
                and debug.get("phase_c_entry_transition_origin_node") == "D.watch_mss"):
            prior_direction = debug.get("prior_phase_e_direction") or debug.get("active_phase_e_direction")
            trade_direction = _opposite(prior_direction)
            epoch_id = debug.get("htf_pd_epoch_id") or snapshot.get("evidence_compiler_epoch_id")
            phase_episode_id = str(debug.get("phase_episode_id") or hypothesis.get("hypothesis_id") or "")
            if not trade_direction or not epoch_id or not phase_episode_id:
                return None
            cache_key = f"{epoch_id}:{prior_direction}"
            self.budget.sync_epoch(str(epoch_id), prior_direction)
            if not self.budget.available("D", phase_episode_id):
                return None
            if self._d_watch_budget_spent.get(cache_key):
                return None
            result = self._try_path_c(
                snapshot, debug, trade_direction, epoch_id,
                phase_episode_id, cache_key, pip_size, sl_buffer_pips, min_sl_pips, max_sl_pips,
            )
            if isinstance(result, EntryIntent):
                self._d_watch_budget_spent[cache_key] = True
            return result

        # ── D.watch phase ──────────────────────────────────────────────────────
        if phase != "D" or phase_sub_status != "watch":
            return None
        if debug.get("phase_d_shadow_node") != "D.watch" and debug.get("phase_d_node") != "D.watch":
            return None

        prior_direction = debug.get("prior_phase_e_direction") or debug.get("active_phase_e_direction")
        trade_direction = _opposite(prior_direction)
        epoch_id = debug.get("htf_pd_epoch_id") or snapshot.get("evidence_compiler_epoch_id")
        phase_episode_id = str(debug.get("phase_episode_id") or hypothesis.get("hypothesis_id") or "")
        watch_entered_at = debug.get("phase_d_shadow_watch_entered_at")

        self.budget.sync_epoch(str(epoch_id) if epoch_id else None, prior_direction)
        if not trade_direction or not epoch_id or not phase_episode_id or not watch_entered_at:
            return None
        if not self.budget.available("D", phase_episode_id):
            return None

        cache_key = f"{epoch_id}:{prior_direction}"
        if self._d_watch_budget_spent.get(cache_key):
            return None

        choch_cand = _candidate(snapshot, "ltf_counter_choch", prior_direction) or {}
        choch_facts = choch_cand.get("debug_facts") or {}

        is_express = bool(debug.get("phase_d_shadow_entry_express"))
        express_zone_proximal = _float(debug.get("phase_d_shadow_express_zone_proximal"))

        # HTF zone context: sticky E flag (immune to EC clearing on 4H close) OR zone seen during D.watch
        htf_zone_context = (
            bool(debug.get("phase_e_shadow_htf_reaction_seen"))
            or bool(debug.get("phase_d_shadow_htf_zone_seen"))
        )

        if is_express:
            result = self._try_path_b_express(
                snapshot, choch_facts, trade_direction, watch_entered_at,
                express_zone_proximal, debug, epoch_id, phase_episode_id,
                pip_size, sl_buffer_pips, min_sl_pips, max_sl_pips,
            )
        elif htf_zone_context:
            result = self._try_path_b(
                snapshot, choch_facts, prior_direction, trade_direction, watch_entered_at,
                pip_size, sl_buffer_pips, min_sl_pips, max_sl_pips,
            )
        else:
            result = self._try_d_watch_path_sa(
                snapshot, debug, choch_facts, trade_direction, epoch_id, phase_episode_id,
                watch_entered_at, pip_size, sl_buffer_pips, min_sl_pips, max_sl_pips,
            )

        if isinstance(result, EntryIntent):
            self._d_watch_budget_spent[cache_key] = True
        return result

    def _try_d_watch_path_sa(
        self,
        snapshot: dict[str, Any],
        debug: dict[str, Any],
        choch_facts: dict[str, Any],
        trade_direction: Direction,
        epoch_id: Any,
        phase_episode_id: str,
        watch_entered_at: str,
        pip_size: float,
        sl_buffer_pips: float,
        min_sl_pips: float,
        max_sl_pips: float,
    ) -> EntryIntent | SkipIntent | None:
        """D.watch_pathSA: iChoCh bar close from D.watch, no HTF zone context.
        Gate: choch_seen + choch_at > watch_entered_at + watch_range_extreme present.
        SL = phase_d_shadow.watch_range_extreme + buffer; max_sl_pips rejects fast flush."""
        choch_seen = bool(choch_facts.get("ltf_counter_choch_seen"))
        choch_at = choch_facts.get("ltf_counter_choch_event_at")
        if not choch_seen or not choch_at or not _time_gt(choch_at, watch_entered_at):
            return None

        watch_extreme = _float(debug.get("phase_d_shadow_watch_range_extreme"))
        if watch_extreme is None:
            return None

        choch_event_id = choch_facts.get("ltf_counter_choch_event_id")
        choch_level = _float(choch_facts.get("ltf_counter_choch_level"))

        buffer = sl_buffer_pips * pip_size
        sl_raw = watch_extreme - buffer if trade_direction == "long" else watch_extreme + buffer
        entry_price_est = self._entry_price(snapshot) or 0.0
        computed_pips = abs(entry_price_est - sl_raw) / pip_size if pip_size else 0.0
        if computed_pips < min_sl_pips:
            sl_price = (entry_price_est - min_sl_pips * pip_size if trade_direction == "long"
                        else entry_price_est + min_sl_pips * pip_size)
        else:
            sl_price = sl_raw

        evidence = CounterEntryEvidence(
            evidence_kind="watch_extreme",
            evidence_id=str(choch_event_id or uuid4().hex),
            timeframe=None,
            direction=trade_direction,
            presented_at=choch_at,
            source_store="phase_d_shadow",
            level=watch_extreme,
            sl_side="above" if trade_direction == "short" else "below",
            sl_price_raw=watch_extreme,
            sl_buffer_pips=sl_buffer_pips,
            sl_price=sl_price,
        )
        trigger = TriggerEvidence(
            trigger_kind="counter_ichoch_immediate",
            trigger_path="D.watch_pathSA",
            event_at=choch_at,
            event_id=str(choch_event_id) if choch_event_id is not None else None,
            level=choch_level,
            source_level_id=choch_facts.get("ltf_counter_choch_source_level_id"),
            source_store=choch_facts.get("ltf_counter_choch_source_store") or "structure_isc",
        )
        return self._make_intent(
            snapshot, epoch_id, phase_episode_id, trade_direction, sl_price,
            evidence, trigger, pip_size, min_sl_pips, max_sl_pips, phase_override="D",
        )

    def _try_path_c(
        self,
        snapshot: dict[str, Any],
        debug: dict[str, Any],
        trade_direction: Direction,
        epoch_id: Any,
        phase_episode_id: str,
        cache_key: str,
        pip_size: float,
        sl_buffer_pips: float,
        min_sl_pips: float,
        max_sl_pips: float,
    ) -> EntryIntent | SkipIntent | None:
        """Path C2 / C2_express: C.pullback from D.watch_mss.
        C2: MSS transition alone → entry. SL = watch_range_extreme + buffer.
        C2_express: same gate, but SL = express_zone_proximal (fallback: watch_range_extreme)."""
        is_express = bool(debug.get("phase_d_shadow_entry_express"))
        express_zone_proximal = _float(debug.get("phase_d_shadow_express_zone_proximal"))
        watch_extreme = _float(debug.get("phase_d_shadow_watch_range_extreme"))

        sl_extreme = (express_zone_proximal if express_zone_proximal is not None else watch_extreme) if is_express else watch_extreme
        if sl_extreme is None:
            return None

        buffer = sl_buffer_pips * pip_size
        transition_at = debug.get("phase_c_entry_transition_at")
        transition_id = debug.get("phase_c_entry_transition_event_id")
        if not transition_at or not transition_id:
            return None

        if bool(debug.get("phase_c_entry_transition_internal_pressure_invalidated")):
            return None

        trigger_path = "D.watch_pathC2_express" if is_express else "D.watch_pathC2"

        entry_price_est = self._entry_price(snapshot) or 0.0
        sl_raw = sl_extreme - buffer if trade_direction == "long" else sl_extreme + buffer
        computed_pips = abs(entry_price_est - sl_raw) / pip_size if pip_size else 0.0
        if computed_pips < min_sl_pips:
            sl_price = (entry_price_est - min_sl_pips * pip_size if trade_direction == "long"
                        else entry_price_est + min_sl_pips * pip_size)
        else:
            sl_price = sl_raw

        evidence = CounterEntryEvidence(
            evidence_kind="watch_extreme",
            evidence_id=str(transition_id),
            timeframe=None,
            direction=trade_direction,
            presented_at=transition_at,
            source_store="phase_d_shadow",
            level=sl_extreme,
            sl_side="above" if trade_direction == "short" else "below",
            sl_price_raw=sl_extreme,
            sl_buffer_pips=sl_buffer_pips,
            sl_price=sl_price,
        )
        trigger = TriggerEvidence(
            trigger_kind="d_watch_mss_plain",
            trigger_path=trigger_path,
            event_at=transition_at,
            event_id=str(transition_id),
            level=sl_extreme,
            source_level_id=None,
            source_store="phase_c_transition",
        )
        return self._make_intent(
            snapshot, epoch_id, phase_episode_id, trade_direction, sl_price,
            evidence, trigger, pip_size, min_sl_pips, max_sl_pips, phase_override="D",
        )

    def _make_intent(
        self,
        snapshot: dict[str, Any],
        epoch_id: Any,
        phase_episode_id: str,
        trade_direction: Direction,
        sl_price: float,
        evidence: CounterEntryEvidence,
        trigger: TriggerEvidence,
        pip_size: float,
        min_sl_pips: float,
        max_sl_pips: float,
        phase_override: str | None = None,
    ) -> EntryIntent | SkipIntent | None:
        hypothesis = snapshot.get("hypothesis") or {}

        opportunity_key = (str(epoch_id), phase_episode_id, trigger.event_id)
        if opportunity_key in self._stale_opportunities or opportunity_key in self._processed_opportunities:
            return None

        entry_price = self._entry_price(snapshot)
        if entry_price is None or sl_price is None:
            return None

        htf = snapshot.get("higher_structure") or {}
        tp_price = _float(htf.get("pd_midpoint"))
        if tp_price is None:
            return None

        sl_pips = abs(entry_price - sl_price) / pip_size
        tp_pips = abs(entry_price - tp_price) / pip_size

        effective_phase = phase_override or hypothesis.get("phase") or "D"

        if sl_pips > max_sl_pips:
            self._stale_opportunities.add(opportunity_key)
            return self._skip(
                snapshot,
                epoch_id=str(epoch_id),
                phase_episode_id=phase_episode_id,
                direction=trade_direction,
                reason="late_entry_risk_too_wide",
                evidence=evidence,
                trigger=trigger,
                stale=True,
                risk_pips=sl_pips,
                phase_override=effective_phase,
            )

        rr = tp_pips / sl_pips if sl_pips > 0 else 0.0
        if rr < self.min_rr:
            return self._skip(
                snapshot,
                epoch_id=str(epoch_id),
                phase_episode_id=phase_episode_id,
                direction=trade_direction,
                reason="runway_too_short",
                evidence=evidence,
                trigger=trigger,
                stale=False,
                risk_pips=sl_pips,
                phase_override=effective_phase,
            )

        self.budget.spend("D", phase_episode_id)
        self._processed_opportunities.add(opportunity_key)
        return EntryIntent(
            intent_id=uuid4().hex,
            symbol=str(snapshot.get("symbol") or ""),
            timeframe=str(snapshot.get("timeframe") or snapshot.get("lower_tf") or ""),
            epoch_id=str(epoch_id),
            phase=effective_phase,
            phase_sub_status=hypothesis.get("phase_sub_status"),
            phase_episode_id=phase_episode_id,
            policy_name=self.policy_name,
            direction=trade_direction,
            execution_mode="MP",
            entry_price=entry_price,
            stop_loss=sl_price,
            target_price=tp_price,
            target_r=round(rr, 3),
            risk_pips=sl_pips,
            created_at=snapshot.get("cursor_time"),
            evidence=evidence,
            trigger=trigger,
        )

    def _try_path_b(
        self,
        snapshot: dict[str, Any],
        choch_facts: dict[str, Any],
        prior_direction: str,
        trade_direction: Direction,
        watch_entered_at: str,
        pip_size: float,
        sl_buffer_pips: float,
        min_sl_pips: float,
        max_sl_pips: float,
    ) -> EntryIntent | SkipIntent | None:
        """Path B: HTF SD zone context + fresh iChoCh confirms initiation fade → entry.
        SL = zone proximal (near edge) + buffer, floor at min_sl_pips."""
        hypothesis = snapshot.get("hypothesis") or {}
        epoch_id = (hypothesis.get("debug_facts") or {}).get("htf_pd_epoch_id") or snapshot.get("evidence_compiler_epoch_id")
        phase_episode_id = str((hypothesis.get("debug_facts") or {}).get("phase_episode_id") or hypothesis.get("hypothesis_id") or "")

        reaction = _candidate(snapshot, "htf_counter_reaction", prior_direction) or {}
        rfacts = reaction.get("debug_facts") or {}
        if not rfacts.get("htf_opposing_sd_tapped") and not rfacts.get("htf_opposing_sd_reaction"):
            return None

        zone_ids = rfacts.get("htf_opposing_sd_zone_ids") or []
        zone = self._htf_proximal_zone(snapshot, zone_ids, trade_direction)
        if zone is None:
            return None

        choch_at = choch_facts.get("ltf_counter_choch_event_at")
        if not choch_facts.get("ltf_counter_choch_seen") or not _time_gt(choch_at, watch_entered_at):
            return None

        # SL = zone proximal line (the near edge — low for short supply zone, high for long demand zone)
        proximal = _float(zone.get("low") if trade_direction == "short" else zone.get("high"))
        if proximal is None:
            return None

        buffer = sl_buffer_pips * pip_size
        sl_raw = proximal + buffer if trade_direction == "short" else proximal - buffer
        entry_price_est = self._entry_price(snapshot) or 0.0
        computed_pips = abs(entry_price_est - sl_raw) / pip_size if pip_size else 0.0
        if computed_pips < min_sl_pips:
            sl_price = (entry_price_est - min_sl_pips * pip_size if trade_direction == "long"
                        else entry_price_est + min_sl_pips * pip_size)
        else:
            sl_price = sl_raw

        evidence = CounterEntryEvidence(
            evidence_kind="htf_sd_zone",
            evidence_id=str(zone.get("zone_id") or uuid4().hex),
            timeframe=zone.get("timeframe") or snapshot.get("higher_tf"),
            direction=trade_direction,
            presented_at=rfacts.get("htf_opposing_sd_tapped_at") or choch_at,
            source_store="sd_zone",
            zone_id=zone.get("zone_id"),
            high=_float(zone.get("high")),
            low=_float(zone.get("low")),
            sl_side="above" if trade_direction == "short" else "below",
            sl_price_raw=proximal,
            sl_buffer_pips=sl_buffer_pips,
            sl_price=sl_price,
        )
        trigger = TriggerEvidence(
            trigger_kind="counter_ichoch",
            trigger_path="D.watch_pathB",
            event_at=choch_at,
            event_id=choch_facts.get("ltf_counter_choch_event_id"),
            level=_float(choch_facts.get("ltf_counter_choch_level")),
            source_level_id=choch_facts.get("ltf_counter_choch_source_level_id"),
            source_store=choch_facts.get("ltf_counter_choch_source_store"),
        )
        return self._make_intent(
            snapshot, epoch_id, phase_episode_id, trade_direction, sl_price,
            evidence, trigger, pip_size, min_sl_pips, max_sl_pips, phase_override="D",
        )

    def _try_path_b_express(
        self,
        snapshot: dict[str, Any],
        choch_facts: dict[str, Any],
        trade_direction: Direction,
        watch_entered_at: str,
        express_zone_proximal: float | None,
        debug: dict[str, Any],
        epoch_id: Any,
        phase_episode_id: str,
        pip_size: float,
        sl_buffer_pips: float,
        min_sl_pips: float,
        max_sl_pips: float,
    ) -> EntryIntent | SkipIntent | None:
        """B_express: express D.watch (zone tap at E.stalling/pullback) + fresh iChoCh → entry.
        SL = express_zone_proximal from shadow; fallback to watch_range_extreme when None."""
        choch_seen = bool(choch_facts.get("ltf_counter_choch_seen"))
        choch_at = choch_facts.get("ltf_counter_choch_event_at")
        if not choch_seen or not choch_at or not _time_gt(choch_at, watch_entered_at):
            return None

        proximal = (
            express_zone_proximal
            if express_zone_proximal is not None
            else _float(debug.get("phase_d_shadow_watch_range_extreme"))
        )
        if proximal is None:
            return None

        choch_event_id = choch_facts.get("ltf_counter_choch_event_id")
        choch_level = _float(choch_facts.get("ltf_counter_choch_level"))

        buffer = sl_buffer_pips * pip_size
        sl_raw = proximal + buffer if trade_direction == "short" else proximal - buffer
        entry_price_est = self._entry_price(snapshot) or 0.0
        computed_pips = abs(entry_price_est - sl_raw) / pip_size if pip_size else 0.0
        if computed_pips < min_sl_pips:
            sl_price = (entry_price_est - min_sl_pips * pip_size if trade_direction == "long"
                        else entry_price_est + min_sl_pips * pip_size)
        else:
            sl_price = sl_raw

        evidence = CounterEntryEvidence(
            evidence_kind="htf_sd_zone_express",
            evidence_id=str(choch_event_id or uuid4().hex),
            timeframe=None,
            direction=trade_direction,
            presented_at=choch_at,
            source_store="phase_d_shadow",
            level=proximal,
            sl_side="above" if trade_direction == "short" else "below",
            sl_price_raw=proximal,
            sl_buffer_pips=sl_buffer_pips,
            sl_price=sl_price,
        )
        trigger = TriggerEvidence(
            trigger_kind="counter_ichoch",
            trigger_path="D.watch_pathB_express",
            event_at=choch_at,
            event_id=str(choch_event_id) if choch_event_id is not None else None,
            level=choch_level,
            source_level_id=choch_facts.get("ltf_counter_choch_source_level_id"),
            source_store=choch_facts.get("ltf_counter_choch_source_store"),
        )
        return self._make_intent(
            snapshot, epoch_id, phase_episode_id, trade_direction, sl_price,
            evidence, trigger, pip_size, min_sl_pips, max_sl_pips, phase_override="D",
        )

    def _skip(
        self,
        snapshot: dict[str, Any],
        *,
        epoch_id: str,
        phase_episode_id: str,
        direction: Direction,
        reason: str,
        evidence: CounterEntryEvidence | None,
        trigger: TriggerEvidence | None,
        stale: bool,
        risk_pips: float | None,
        phase_override: str | None = None,
    ) -> SkipIntent:
        hypothesis = snapshot.get("hypothesis") or {}
        return SkipIntent(
            intent_id=uuid4().hex,
            symbol=str(snapshot.get("symbol") or ""),
            timeframe=str(snapshot.get("timeframe") or snapshot.get("lower_tf") or ""),
            epoch_id=epoch_id,
            phase=phase_override or "D",
            phase_sub_status=hypothesis.get("phase_sub_status"),
            phase_episode_id=phase_episode_id,
            policy_name=self.policy_name,
            direction=direction,
            created_at=snapshot.get("cursor_time"),
            skip_reason=reason,
            evidence=evidence,
            trigger=trigger,
            stale_marked=stale,
            risk_pips=risk_pips,
        )

    def _entry_price(self, snapshot: dict[str, Any]) -> float | None:
        bars = snapshot.get("lower_bars") or snapshot.get("bars") or []
        if bars:
            return _float(bars[-1].get("close"))
        context = snapshot.get("context_snapshot") or {}
        return _float(context.get("currentPrice"))

    def _htf_proximal_zone(
        self, snapshot: dict[str, Any], zone_ids: list[str], trade_direction: Direction
    ) -> dict[str, Any] | None:
        """Return the first matching HTF zone for SL proximal reference.
        Supply zone for short trades (SL above zone.low = near edge).
        Demand zone for long trades (SL below zone.high = near edge)."""
        zone_direction = "demand" if trade_direction == "long" else "supply"
        for zone_id in zone_ids:
            for zone in snapshot.get("zones") or []:
                if zone.get("zone_id") == zone_id and zone.get("direction") == zone_direction:
                    return zone
        return None
