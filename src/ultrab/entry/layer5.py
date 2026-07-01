from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
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
    trigger_age_bars: int = 0


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
    trigger_age_bars: int = 0


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


def _parse_bar_minutes(tf: Any) -> int:
    label = str(tf or "").strip().upper()
    try:
        if label.endswith("M"):
            return max(1, int(label[:-1]))
        if label.endswith("H"):
            return max(1, int(label[:-1])) * 60
        if label.endswith("D"):
            return max(1, int(label[:-1])) * 1440
    except ValueError:
        return 15
    return 15


def _trigger_age_bars(
    cursor_time: str | None,
    trigger_at: str | None,
    *,
    bar_minutes: int = 15,
) -> int:
    if not cursor_time or not trigger_at:
        return 0
    try:
        cursor = datetime.fromisoformat(str(cursor_time).replace("Z", "+00:00"))
        trigger = datetime.fromisoformat(str(trigger_at).replace("Z", "+00:00"))
    except ValueError:
        return 0
    minutes = max(1, bar_minutes)
    return max(0, int((cursor - trigger).total_seconds() / 60 / minutes))


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

    D Path A: D.watch hold — internal counter iChoCh -> internal counter iSB sequence.
              SL = watch_range_extreme + buffer.
    B Path A: B.watch hold — internal counter iChoCh -> internal pro iChoCh.
    B Path B: B.watch -> A.watch transition after B OTE steps 1+2 were armed.
    D TP:     pd_midpoint (50% HTF PD range). B TP: progress cap toward 90% objective.
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
        phase_a_objective_threshold: float = 0.90,
        max_trigger_age_bars: int = 20,
    ) -> None:
        self.policy_name = policy_name
        self.symbol_geometry: dict[str, dict] = symbol_geometry or {}
        self.min_rr = min_rr
        self.phase_a_objective_threshold = phase_a_objective_threshold
        self.max_trigger_age_bars = max_trigger_age_bars
        self.budget = EntryBudgetLedger(epoch_budget=epoch_budget)
        self._stale_opportunities: set[tuple[str, str, str | None]] = set()
        self._processed_opportunities: set[tuple[str, str, str | None]] = set()
        # cache_key = "{epoch_id}:{prior_direction}" — stable across D→C phase transition
        self._d_watch_budget_spent: dict[str, bool] = {}  # True once any path fires and is accepted
        self._b_watch_episode_spent: set[str] = set()
        self._b_watch_pending_trigger: dict[str, str] = {}
        self._a_watch_total_count: dict[str, int] = {}
        self._a_watch_ote_last_pro_extreme: dict[str, float] = {}
        self._a_watch_ex_fired: set[str] = set()

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

        # ── Phase B — OTE.entry ──────────────────────────────────────────────
        # trade_direction == direction (pro-HTF) — opposite of Phase D counter trades.
        if phase == "B" and phase_sub_status == "watch":
            direction = hypothesis.get("direction")
            epoch_id = debug.get("htf_pd_epoch_id") or snapshot.get("evidence_compiler_epoch_id")
            phase_episode_id = str(debug.get("phase_episode_id") or hypothesis.get("hypothesis_id") or "")
            if not direction or not epoch_id:
                return None
            if phase_episode_id in self._b_watch_episode_spent:
                return None
            choch_cand = _candidate(snapshot, "ltf_counter_choch", direction) or {}
            choch_facts = choch_cand.get("debug_facts") or {}
            return self._try_b_watch_path_a(
                snapshot, debug, choch_facts, direction, epoch_id, phase_episode_id,
                pip_size, sl_buffer_pips, min_sl_pips, max_sl_pips,
            )

        # ── Phase B-owned transition entry: B.watch → A.watch ────────────────
        if (
            phase == "A"
            and phase_sub_status == "watch"
            and debug.get("phase_a_entry_transition_origin_node") == "B.watch"
        ):
            direction = hypothesis.get("direction")
            epoch_id = debug.get("htf_pd_epoch_id") or snapshot.get("evidence_compiler_epoch_id")
            phase_episode_id = str(debug.get("phase_a_entry_transition_prior_phase_episode_id") or "")
            if not direction or not epoch_id or not phase_episode_id:
                return None
            if phase_episode_id in self._b_watch_episode_spent:
                return None
            choch_cand = _candidate(snapshot, "ltf_counter_choch", direction) or {}
            choch_facts = choch_cand.get("debug_facts") or {}
            return self._try_b_watch_path_b(
                snapshot, debug, choch_facts, direction, epoch_id, phase_episode_id,
                pip_size, sl_buffer_pips, min_sl_pips, max_sl_pips,
            )

        # ── Phase A — pro-HTF continuation entries ─────────────────────────
        if (
            phase == "A"
            and phase_sub_status == "watch"
            and debug.get("phase_a_entry_transition_origin_node") != "B.watch"
        ):
            direction = hypothesis.get("direction")
            epoch_id = debug.get("htf_pd_epoch_id") or snapshot.get("evidence_compiler_epoch_id")
            phase_episode_id = str(debug.get("phase_episode_id") or hypothesis.get("hypothesis_id") or "")
            if not direction or not epoch_id or not phase_episode_id:
                return None
            choch_cand = _candidate(snapshot, "ltf_counter_choch", direction) or {}
            choch_facts = choch_cand.get("debug_facts") or {}
            return self._try_a_watch_path_a(
                snapshot, debug, choch_facts, direction, epoch_id, phase_episode_id,
                pip_size, sl_buffer_pips, min_sl_pips, max_sl_pips,
            )

        if phase == "A" and phase_sub_status == "watch_weaken":
            direction = hypothesis.get("direction")
            epoch_id = debug.get("htf_pd_epoch_id") or snapshot.get("evidence_compiler_epoch_id")
            phase_episode_id = str(debug.get("phase_episode_id") or hypothesis.get("hypothesis_id") or "")
            if not direction or not epoch_id or not phase_episode_id:
                return None
            choch_cand = _candidate(snapshot, "ltf_counter_choch", direction) or {}
            choch_facts = choch_cand.get("debug_facts") or {}
            return self._try_a_watch_weaken_ex(
                snapshot, debug, choch_cand, choch_facts, direction, epoch_id, phase_episode_id,
                pip_size, sl_buffer_pips, min_sl_pips, max_sl_pips,
            )

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

        result = self._try_path_a(
            snapshot, debug, choch_facts, trade_direction, epoch_id, phase_episode_id,
            watch_entered_at, pip_size, sl_buffer_pips, min_sl_pips, max_sl_pips,
        )

        if isinstance(result, EntryIntent):
            self._d_watch_budget_spent[cache_key] = True
        return result

    def _try_path_a(
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
        """D.watch_pathA: internal counter iChoCh -> counter iSB sequence from D.watch."""
        seq_seen = bool(choch_facts.get("ltf_counter_ichoch_isb_sequence_seen"))
        if choch_facts.get("ltf_counter_sequence_trade_direction") != trade_direction:
            return None
        isb_at = choch_facts.get("ltf_counter_sequence_isb_event_at")
        if not seq_seen or not isb_at or not _time_gt(isb_at, watch_entered_at):
            return None

        watch_extreme = _float(debug.get("phase_d_shadow_watch_range_extreme"))
        if watch_extreme is None:
            return None

        isb_event_id = choch_facts.get("ltf_counter_sequence_isb_event_id")
        isb_level = _float(choch_facts.get("ltf_counter_sequence_isb_level"))

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
            evidence_id=str(isb_event_id or uuid4().hex),
            timeframe=None,
            direction=trade_direction,
            presented_at=isb_at,
            source_store="phase_d_shadow",
            level=watch_extreme,
            sl_side="above" if trade_direction == "short" else "below",
            sl_price_raw=watch_extreme,
            sl_buffer_pips=sl_buffer_pips,
            sl_price=sl_price,
        )
        trigger = TriggerEvidence(
            trigger_kind="counter_ichoch_immediate",
            trigger_path="D.watch_pathA",
            event_at=isb_at,
            event_id=str(isb_event_id) if isb_event_id is not None else None,
            level=isb_level,
            source_level_id=choch_facts.get("ltf_counter_sequence_isb_source_level_id"),
            source_store=choch_facts.get("ltf_counter_sequence_source_store")
            or "internal_structure_sequence",
        )
        htf = snapshot.get("higher_structure") or {}
        tp_price = _float(htf.get("pd_midpoint"))
        if tp_price is None:
            return None
        return self._make_intent(
            snapshot, epoch_id, phase_episode_id, trade_direction, sl_price,
            evidence, trigger, pip_size, min_sl_pips, max_sl_pips,
            tp_price=tp_price,
            phase_override="D",
        )

    def _try_b_watch_path_a(
        self,
        snapshot: dict[str, Any],
        debug: dict[str, Any],
        choch_facts: dict[str, Any],
        direction: Direction,
        epoch_id: Any,
        phase_episode_id: str,
        pip_size: float,
        sl_buffer_pips: float,
        min_sl_pips: float,
        max_sl_pips: float,
    ) -> EntryIntent | SkipIntent | None:
        """B.watch_pathA: internal counter iChoCh -> internal pro iChoCh.
        trade_direction == direction (pro-HTF). SL = commitment_extreme ± buffer."""
        entered_at = debug.get("phase_b_shadow_entered_at")
        commitment_extreme = _float(debug.get("phase_b_shadow_commitment_extreme_level"))
        commitment_event_id = debug.get("phase_b_shadow_commitment_extreme_event_id")
        if not entered_at or commitment_extreme is None:
            return None

        counter_break = "down" if direction == "long" else "up"
        pro_break = "up" if direction == "long" else "down"

        counter_ichoch_at = choch_facts.get("ltf_counter_ichoch_event_at")
        if (
            not choch_facts.get("ltf_counter_ichoch_seen")
            or choch_facts.get("ltf_counter_ichoch_direction") != counter_break
            or not _time_gt(counter_ichoch_at, entered_at)
        ):
            return None

        pro_ichoch_at = choch_facts.get("ltf_pro_ichoch_event_at")
        if (
            not choch_facts.get("ltf_pro_ichoch_seen")
            or choch_facts.get("ltf_pro_ichoch_direction") != pro_break
            or not _time_gt(pro_ichoch_at, counter_ichoch_at)
        ):
            return None

        # SL geometry: commitment_extreme is the invalidation floor (set at C→B entry)
        buffer = sl_buffer_pips * pip_size
        sl_raw = (commitment_extreme - buffer if direction == "long"
                  else commitment_extreme + buffer)
        entry_price_est = self._entry_price(snapshot) or 0.0
        computed_pips = abs(entry_price_est - sl_raw) / pip_size if pip_size else 0.0
        if computed_pips < min_sl_pips:
            sl_price = (entry_price_est - min_sl_pips * pip_size if direction == "long"
                        else entry_price_est + min_sl_pips * pip_size)
        else:
            sl_price = sl_raw
        tp_price = self._htf_objective_tp(snapshot, direction, entry_price_est, sl_price, pip_size)
        if tp_price is None:
            return None

        pro_ichoch_event_id = choch_facts.get("ltf_pro_ichoch_event_id")
        pro_ichoch_level = _float(choch_facts.get("ltf_pro_ichoch_level"))
        timeframe = str(snapshot.get("lower_tf") or snapshot.get("timeframe") or "")

        evidence = CounterEntryEvidence(
            evidence_kind="b_watch_commitment",
            evidence_id=str(commitment_event_id or uuid4().hex),
            timeframe=timeframe,
            direction=direction,
            presented_at=entered_at,
            source_store="phase_b_shadow",
            level=commitment_extreme,
            sl_side="below" if direction == "long" else "above",
            sl_price_raw=commitment_extreme,
            sl_buffer_pips=sl_buffer_pips,
            sl_price=sl_price,
        )
        trigger = TriggerEvidence(
            trigger_kind="pro_ichoch",
            trigger_path="B.watch_pathA",
            event_at=pro_ichoch_at,
            event_id=str(pro_ichoch_event_id) if pro_ichoch_event_id is not None else None,
            level=pro_ichoch_level,
            source_level_id=choch_facts.get("ltf_pro_ichoch_source_level_id"),
            source_store=choch_facts.get("ltf_pro_ichoch_source_store")
            or "internal_structure_sequence",
        )
        if self._b_watch_trigger_locked(phase_episode_id, trigger.event_id):
            return None
        result = self._make_intent(
            snapshot, epoch_id, phase_episode_id, direction, sl_price,
            evidence, trigger, pip_size, min_sl_pips, max_sl_pips,
            tp_price=tp_price,
            phase_override="B",
        )
        self._record_b_watch_result(phase_episode_id, trigger.event_id, result)
        return result

    def _try_b_watch_path_b(
        self,
        snapshot: dict[str, Any],
        debug: dict[str, Any],
        choch_facts: dict[str, Any],
        direction: Direction,
        epoch_id: Any,
        phase_episode_id: str,
        pip_size: float,
        sl_buffer_pips: float,
        min_sl_pips: float,
        max_sl_pips: float,
    ) -> EntryIntent | SkipIntent | None:
        """B.watch_pathB: B-owned transition entry completed by B.watch -> A.watch."""
        entered_at = (
            debug.get("phase_a_entry_transition_prior_entered_at")
            or debug.get("phase_b_shadow_entered_at")
        )
        commitment_extreme = _float(debug.get("phase_a_entry_transition_commitment_extreme_level"))
        if not entered_at or commitment_extreme is None:
            return None

        counter_break = "down" if direction == "long" else "up"
        counter_ichoch_at = choch_facts.get("ltf_counter_ichoch_event_at")
        if (
            not choch_facts.get("ltf_counter_ichoch_seen")
            or choch_facts.get("ltf_counter_ichoch_direction") != counter_break
            or not _time_gt(counter_ichoch_at, entered_at)
        ):
            return None

        transition_at = debug.get("phase_a_entry_transition_at")
        transition_id = debug.get("phase_a_entry_transition_event_id")
        if not transition_at or not transition_id:
            return None
        if not _time_gt(transition_at, counter_ichoch_at):
            return None

        buffer = sl_buffer_pips * pip_size
        entry_price_est = self._entry_price(snapshot) or 0.0
        sl_raw = commitment_extreme - buffer if direction == "long" else commitment_extreme + buffer
        computed_pips = abs(entry_price_est - sl_raw) / pip_size if pip_size else 0.0
        if computed_pips < min_sl_pips:
            sl_price = (entry_price_est - min_sl_pips * pip_size if direction == "long"
                        else entry_price_est + min_sl_pips * pip_size)
        else:
            sl_price = sl_raw
        tp_price = self._htf_objective_tp(snapshot, direction, entry_price_est, sl_price, pip_size)
        if tp_price is None:
            return None

        commitment_event_id = debug.get("phase_b_shadow_commitment_extreme_event_id")
        evidence = CounterEntryEvidence(
            evidence_kind="b_watch_commitment",
            evidence_id=str(commitment_event_id or transition_id),
            timeframe=str(snapshot.get("lower_tf") or snapshot.get("timeframe") or ""),
            direction=direction,
            presented_at=entered_at,
            source_store="phase_b_shadow",
            level=commitment_extreme,
            sl_side="below" if direction == "long" else "above",
            sl_price_raw=commitment_extreme,
            sl_buffer_pips=sl_buffer_pips,
            sl_price=sl_price,
        )
        trigger = TriggerEvidence(
            trigger_kind="pro_major_structure_transition",
            trigger_path="B.watch_pathB",
            event_at=transition_at,
            event_id=str(transition_id),
            level=_float(debug.get("phase_a_entry_transition_level")),
            source_level_id=None,
            source_store="major_structure",
        )
        if self._b_watch_trigger_locked(phase_episode_id, trigger.event_id):
            return None
        result = self._make_intent(
            snapshot, epoch_id, phase_episode_id, direction, sl_price,
            evidence, trigger, pip_size, min_sl_pips, max_sl_pips,
            tp_price=tp_price,
            phase_override="B",
        )
        self._record_b_watch_result(phase_episode_id, trigger.event_id, result)
        return result

    def _try_a_watch_path_a(
        self,
        snapshot: dict[str, Any],
        debug: dict[str, Any],
        choch_facts: dict[str, Any],
        direction: Direction,
        epoch_id: Any,
        phase_episode_id: str,
        pip_size: float,
        sl_buffer_pips: float,
        min_sl_pips: float,
        max_sl_pips: float,
    ) -> EntryIntent | SkipIntent | None:
        """A.watch_pathA: counter iChoCh -> pro iChoCh OTE continuation."""
        entered_at = debug.get("phase_a_shadow_entered_at")
        commitment_extreme = _float(debug.get("phase_a_shadow_commitment_extreme_level"))
        if not entered_at or commitment_extreme is None:
            return None

        budget_key = f"{epoch_id}:{direction}"
        if self._a_watch_total_count.get(budget_key, 0) >= 3:
            return None

        counter_break = "down" if direction == "long" else "up"
        pro_break = "up" if direction == "long" else "down"

        counter_ichoch_at = choch_facts.get("ltf_counter_ichoch_event_at")
        if (
            not choch_facts.get("ltf_counter_ichoch_seen")
            or choch_facts.get("ltf_counter_ichoch_direction") != counter_break
            or not _time_gt(counter_ichoch_at, entered_at)
        ):
            return None

        pro_ichoch_at = choch_facts.get("ltf_pro_ichoch_event_at")
        if (
            not choch_facts.get("ltf_pro_ichoch_seen")
            or choch_facts.get("ltf_pro_ichoch_direction") != pro_break
            or not _time_gt(pro_ichoch_at, counter_ichoch_at)
        ):
            return None

        pro_extreme_at_weaken = _float(debug.get("phase_a_shadow_pro_extreme_at_weaken"))
        if debug.get("phase_a_shadow_pro_attempt_weaken") and pro_extreme_at_weaken is not None:
            last_pro_extreme = self._a_watch_ote_last_pro_extreme.get(budget_key)
            if last_pro_extreme is not None:
                advanced = (
                    pro_extreme_at_weaken > last_pro_extreme
                    if direction == "long"
                    else pro_extreme_at_weaken < last_pro_extreme
                )
                if not advanced:
                    return None

        buffer = sl_buffer_pips * pip_size
        sl_raw = commitment_extreme - buffer if direction == "long" else commitment_extreme + buffer
        entry_price_est = self._entry_price(snapshot) or 0.0
        computed_pips = abs(entry_price_est - sl_raw) / pip_size if pip_size else 0.0
        if computed_pips < min_sl_pips:
            sl_price = (entry_price_est - min_sl_pips * pip_size if direction == "long"
                        else entry_price_est + min_sl_pips * pip_size)
        else:
            sl_price = sl_raw

        tp_price = self._htf_objective_tp(snapshot, direction, entry_price_est, sl_price, pip_size)
        if tp_price is None:
            return None

        pro_ichoch_event_id = choch_facts.get("ltf_pro_ichoch_event_id")
        pro_ichoch_level = _float(choch_facts.get("ltf_pro_ichoch_level"))
        trigger = TriggerEvidence(
            trigger_kind="pro_ichoch",
            trigger_path="A.watch_pathA",
            event_at=pro_ichoch_at,
            event_id=str(pro_ichoch_event_id) if pro_ichoch_event_id is not None else None,
            level=pro_ichoch_level,
            source_level_id=choch_facts.get("ltf_pro_ichoch_source_level_id"),
            source_store=choch_facts.get("ltf_pro_ichoch_source_store")
            or "internal_structure_sequence",
        )
        evidence = CounterEntryEvidence(
            evidence_kind="a_watch_commitment",
            evidence_id=str(debug.get("phase_a_shadow_commitment_extreme_event_id") or pro_ichoch_event_id or uuid4().hex),
            timeframe=str(snapshot.get("lower_tf") or snapshot.get("timeframe") or ""),
            direction=direction,
            presented_at=entered_at,
            source_store="phase_a_shadow",
            level=commitment_extreme,
            sl_side="below" if direction == "long" else "above",
            sl_price_raw=commitment_extreme,
            sl_buffer_pips=sl_buffer_pips,
            sl_price=sl_price,
        )
        result = self._make_intent(
            snapshot, epoch_id, phase_episode_id, direction, sl_price,
            evidence, trigger, pip_size, min_sl_pips, max_sl_pips,
            tp_price=tp_price,
            phase_override="A",
        )
        if isinstance(result, EntryIntent):
            self._a_watch_total_count[budget_key] = self._a_watch_total_count.get(budget_key, 0) + 1
            if debug.get("phase_a_shadow_pro_attempt_weaken") and pro_extreme_at_weaken is not None:
                self._a_watch_ote_last_pro_extreme[budget_key] = pro_extreme_at_weaken
        return result

    def _try_a_watch_weaken_ex(
        self,
        snapshot: dict[str, Any],
        debug: dict[str, Any],
        choch_cand: dict[str, Any],
        choch_facts: dict[str, Any],
        direction: Direction,
        epoch_id: Any,
        phase_episode_id: str,
        pip_size: float,
        sl_buffer_pips: float,
        min_sl_pips: float,
        max_sl_pips: float,
    ) -> EntryIntent | SkipIntent | None:
        """A.watch_weaken_ex: pro iChoCh -> pro iSB final continuation slot."""
        weaken_at = debug.get("phase_a_shadow_pro_attempt_weaken_at")
        watch_extreme = _float(debug.get("phase_a_shadow_watch_range_extreme"))
        if not weaken_at or watch_extreme is None:
            return None

        budget_key = f"{epoch_id}:{direction}"
        if budget_key in self._a_watch_ex_fired or self._a_watch_total_count.get(budget_key, 0) >= 3:
            return None
        if choch_cand.get("status") != "ready":
            return None
        if (
            not choch_facts.get("ltf_pro_ichoch_isb_sequence_seen")
            or choch_facts.get("ltf_pro_sequence_trade_direction") != direction
        ):
            return None

        ichoch_at = choch_facts.get("ltf_pro_sequence_ichoch_event_at")
        isb_at = choch_facts.get("ltf_pro_sequence_isb_event_at")
        isb_event_id = choch_facts.get("ltf_pro_sequence_isb_event_id")
        if not ichoch_at or not isb_at or not isb_event_id or not _time_gt(ichoch_at, weaken_at):
            return None

        buffer = sl_buffer_pips * pip_size
        sl_raw = watch_extreme - buffer if direction == "long" else watch_extreme + buffer
        entry_price_est = self._entry_price(snapshot) or 0.0
        computed_pips = abs(entry_price_est - sl_raw) / pip_size if pip_size else 0.0
        if computed_pips < min_sl_pips:
            sl_price = (entry_price_est - min_sl_pips * pip_size if direction == "long"
                        else entry_price_est + min_sl_pips * pip_size)
        else:
            sl_price = sl_raw

        tp_price = self._htf_objective_tp(snapshot, direction, entry_price_est, sl_price, pip_size)
        if tp_price is None:
            return None

        trigger = TriggerEvidence(
            trigger_kind="pro_ichoch_isb_sequence",
            trigger_path="A.watch_weaken_ex",
            event_at=isb_at,
            event_id=str(isb_event_id),
            level=_float(choch_facts.get("ltf_pro_sequence_isb_level")),
            source_level_id=choch_facts.get("ltf_pro_sequence_isb_source_level_id"),
            source_store=choch_facts.get("ltf_pro_sequence_source_store")
            or "internal_structure_sequence",
        )
        evidence = CounterEntryEvidence(
            evidence_kind="a_watch_weaken_ex",
            evidence_id=str(isb_event_id),
            timeframe=str(snapshot.get("lower_tf") or snapshot.get("timeframe") or ""),
            direction=direction,
            presented_at=weaken_at,
            source_store="phase_a_shadow",
            level=watch_extreme,
            sl_side="below" if direction == "long" else "above",
            sl_price_raw=watch_extreme,
            sl_buffer_pips=sl_buffer_pips,
            sl_price=sl_price,
        )
        result = self._make_intent(
            snapshot, epoch_id, phase_episode_id, direction, sl_price,
            evidence, trigger, pip_size, min_sl_pips, max_sl_pips,
            tp_price=tp_price,
            phase_override="A",
        )
        if isinstance(result, EntryIntent) or (
            isinstance(result, SkipIntent) and result.stale_marked
        ):
            self._a_watch_total_count[budget_key] = 3
            self._a_watch_ex_fired.add(budget_key)
        return result

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
        *,
        tp_price: float,
        phase_override: str | None = None,
    ) -> EntryIntent | SkipIntent | None:
        hypothesis = snapshot.get("hypothesis") or {}

        opportunity_key = (str(epoch_id), phase_episode_id, trigger.event_id)
        if opportunity_key in self._stale_opportunities or opportunity_key in self._processed_opportunities:
            return None

        cursor_time = snapshot.get("cursor_time") or ""
        tf_label = snapshot.get("lower_tf") or snapshot.get("timeframe") or "15M"
        age_bars = _trigger_age_bars(
            str(cursor_time) if cursor_time else None,
            trigger.event_at,
            bar_minutes=_parse_bar_minutes(tf_label),
        )
        if self.max_trigger_age_bars > 0 and age_bars > self.max_trigger_age_bars:
            return None

        entry_price = self._entry_price(snapshot)
        if entry_price is None or sl_price is None:
            return None

        sl_pips = abs(entry_price - sl_price) / pip_size
        tp_pips = abs(entry_price - tp_price) / pip_size

        effective_phase = phase_override or hypothesis.get("phase") or "D"

        if sl_pips > max_sl_pips:
            return self._skip(
                snapshot,
                epoch_id=str(epoch_id),
                phase_episode_id=phase_episode_id,
                direction=trade_direction,
                reason="SL_too_wide",
                evidence=evidence,
                trigger=trigger,
                stale=False,
                risk_pips=sl_pips,
                trigger_age_bars=age_bars,
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
                trigger_age_bars=age_bars,
                phase_override=effective_phase,
            )

        self.budget.spend(effective_phase, phase_episode_id)
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
            trigger_age_bars=age_bars,
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
        trigger_age_bars: int = 0,
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
            trigger_age_bars=trigger_age_bars,
        )

    def _htf_objective_tp(
        self,
        snapshot: dict[str, Any],
        direction: Direction,
        entry_price: float,
        sl_price: float,
        pip_size: float,
    ) -> float | None:
        htf = snapshot.get("higher_structure") or {}
        pd_low = _float(htf.get("range_low"))
        pd_high = _float(htf.get("range_high"))
        if pd_low is None or pd_high is None or pip_size <= 0:
            return None
        span = pd_high - pd_low
        if span <= 0:
            return None
        sl_pips = abs(entry_price - sl_price) / pip_size
        threshold = self.phase_a_objective_threshold
        if direction == "long":
            progress_level = pd_low + threshold * span
            progress_pips = max(0.0, (progress_level - entry_price) / pip_size)
            tp_pips = min(progress_pips, 2.5 * sl_pips)
            return entry_price + tp_pips * pip_size
        progress_level = pd_high - threshold * span
        progress_pips = max(0.0, (entry_price - progress_level) / pip_size)
        tp_pips = min(progress_pips, 2.5 * sl_pips)
        return entry_price - tp_pips * pip_size

    def _b_watch_trigger_locked(self, phase_episode_id: str, trigger_id: str | None) -> bool:
        locked_id = self._b_watch_pending_trigger.get(phase_episode_id)
        return locked_id is not None and trigger_id != locked_id

    def _record_b_watch_result(
        self,
        phase_episode_id: str,
        trigger_id: str | None,
        result: EntryIntent | SkipIntent | None,
    ) -> None:
        if result is None:
            return
        if isinstance(result, SkipIntent) and not result.stale_marked:
            if result.skip_reason == "runway_too_short" and trigger_id is not None:
                self._b_watch_pending_trigger[phase_episode_id] = trigger_id
            return
        self._b_watch_episode_spent.add(phase_episode_id)
        self._b_watch_pending_trigger.pop(phase_episode_id, None)

    def _entry_price(self, snapshot: dict[str, Any]) -> float | None:
        bars = snapshot.get("lower_bars") or snapshot.get("bars") or []
        if bars:
            return _float(bars[-1].get("close"))
        context = snapshot.get("context_snapshot") or {}
        return _float(context.get("currentPrice"))
