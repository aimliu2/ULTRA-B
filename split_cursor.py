"""Cross-phase forward walker for one symbol.

SplitCursor coordinates multiple branch engines under one shared symbol
execution layer. Each branch keeps its own decision clock and signal state;
the optional 1m feed is used only for fill/exit timing between branch
decision events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd

from backtester.cursor import (
    _ContextRow,
    _REQUIRED_FEATURE_COLS,
    _has_nan_features,
)
from backtester.features import compute_regime
from backtester.strategy import resolve_sl_tp


@dataclass
class SplitBranch:
    """One hypothesis/phase branch in a split-engine run."""

    name: str
    hypothesis: str
    phase: str
    entry_timeframe: str
    context_timeframe: str
    engine: object
    config: dict
    aligned: pd.DataFrame


@dataclass
class PendingEntry:
    """Accepted candidate waiting for that branch's next entry bar open."""

    branch_name: str
    due_time: pd.Timestamp
    entry_price: float
    candidate: dict


class SplitCursor:
    """
    Multi-feed cursor for Step 4.5 cross-phase Policy 3 runs.

    Signal clocks are branch-native: a 15m branch evaluates only on 15m
    closes, a 5m branch evaluates only on 5m closes. The 1m dataframe, when
    present, is an execution clock only and never creates signal events.
    """

    def __init__(
        self,
        branches: dict[str, SplitBranch],
        policy_fn: Callable,
        ledger,
        config: dict,
        df_1m: Optional[pd.DataFrame] = None,
    ) -> None:
        if not branches:
            raise ValueError("SplitCursor requires at least one branch")

        self.branches = branches
        self.policy_fn = policy_fn
        self.ledger = ledger
        self.config = self._policy_config(config)
        self.df_1m = df_1m
        self._1m_index = df_1m.index if df_1m is not None else None
        self._1m_ns = df_1m.index.view("int64") if df_1m is not None else None
        self._1m_high = df_1m["high"].to_numpy(dtype=float) if df_1m is not None else None
        self._1m_low = df_1m["low"].to_numpy(dtype=float) if df_1m is not None else None

        self._pending: list[PendingEntry] = []
        self._pending_slots: int = 0          # queued-but-not-yet-filled count
        self._shared_open_trades: list = []
        self._trade_counter = 0

        for branch in self.branches.values():
            branch.engine.open_trades = self._shared_open_trades
            if "regime" not in branch.aligned.columns:
                branch.aligned = branch.aligned.copy()
                branch.aligned["regime"] = compute_regime(branch.aligned)

    def run(self) -> list:
        """Walk all branch feeds in chronological order."""
        events = self._events()
        prev_time: Optional[pd.Timestamp] = None

        for event_time, timestamp_events in events:
            self._fill_pending_due(event_time)

            if prev_time is not None:
                if self.df_1m is not None:
                    self._exit_via_1m(prev_time, event_time)
                else:
                    self._exit_via_event_rows(timestamp_events)

            candidates = []

            for branch_name, pos in timestamp_events:
                branch = self.branches[branch_name]
                row = branch.aligned.iloc[pos]
                if _has_nan_features(row, _REQUIRED_FEATURE_COLS):
                    continue

                feature_row = row
                context_row = _ContextRow(row)
                fired = branch.engine.on_bar(feature_row, context_row)
                if not fired:
                    continue

                for candidate in fired:
                    tagged = self._tag_candidate(candidate, branch)
                    candidates.append(tagged)

            if candidates:
                accepted_list = self._run_policy(candidates)
                accepted_keys = {
                    (candidate.get("branch"), candidate.get("hypothesis"))
                    for candidate in accepted_list
                }

                for accepted in accepted_list:
                    branch = self.branches[accepted["branch"]]
                    self.ledger.log_signal(
                        bar_time=event_time,
                        candidate=accepted,
                        decision="accepted",
                        engine=branch.engine,
                    )
                    branch.engine.accept_candidate(accepted)
                    self._queue_for_next_open(accepted, event_time)

                for candidate in candidates:
                    candidate_key = (candidate.get("branch"), candidate.get("hypothesis"))
                    if candidate_key in accepted_keys:
                        continue
                    branch = self.branches[candidate["branch"]]
                    skip_reason = candidate.get("_policy_skip_reason", "")
                    if not skip_reason and accepted_list:
                        skip_reason = "same_bar_priority_lost"
                    self.ledger.log_signal(
                        bar_time=event_time,
                        candidate=candidate,
                        decision="skipped",
                        engine=branch.engine,
                        skip_reason=skip_reason,
                    )

            prev_time = event_time

        if self.df_1m is None and events:
            self._fill_pending_due(events[-1][0])

        return self._closed_trades()

    def _policy_config(self, config: dict) -> dict:
        copied = dict(config)
        copied["execution"] = dict(config.get("execution", {}))
        cross = config.get("cross_phase", {})
        if "same_bar_priority" in cross:
            copied["execution"]["same_bar_priority"] = cross["same_bar_priority"]
        if "max_concurrent_positions_per_symbol" in cross:
            copied["execution"]["max_concurrent_positions_per_symbol"] = cross[
                "max_concurrent_positions_per_symbol"
            ]
        return copied

    def _events(self) -> list[tuple[pd.Timestamp, list[tuple[str, int]]]]:
        raw_events = []
        for branch_name, branch in self.branches.items():
            for pos, timestamp in enumerate(branch.aligned.index):
                raw_events.append((pd.Timestamp(timestamp), branch_name, pos))

        raw_events.sort(key=lambda item: item[0])
        grouped = []
        current_time = None
        current_items = []
        for timestamp, branch_name, pos in raw_events:
            if current_time is None or timestamp == current_time:
                current_time = timestamp
                current_items.append((branch_name, pos))
                continue
            grouped.append((current_time, current_items))
            current_time = timestamp
            current_items = [(branch_name, pos)]
        if current_time is not None:
            grouped.append((current_time, current_items))
        return grouped

    def _tag_candidate(self, candidate: dict, branch: SplitBranch) -> dict:
        return {
            **candidate,
            "branch": branch.name,
            "phase": branch.phase,
            "entry_timeframe": branch.entry_timeframe,
            "context_timeframe": branch.context_timeframe,
        }

    def _run_policy(self, candidates: list[dict]) -> list[dict]:
        policy_engine = next(iter(self.branches.values())).engine
        # Inject effective open count so policy_3 cap check includes pending (queued
        # but not yet filled) entries. Without this, cross-phase runs can violate cap=1
        # because a 15m-branch trade can be pending for up to 15m, during which a 5m
        # branch can fire and pass a cap check that only sees open_trades.
        effective_cfg = self._inject_effective_count(self.config)
        result = self.policy_fn(candidates, policy_engine, effective_cfg)
        if result is None:
            return []
        if isinstance(result, dict):
            return [result]
        return result

    def _inject_effective_count(self, config: dict) -> dict:
        """Return config with _effective_open_count patched in for the cap check."""
        exec_cfg = config.get("execution", {})
        if exec_cfg.get("max_concurrent_positions_per_symbol") is None:
            return config   # no cap configured, no need to patch
        effective = len(self._shared_open_trades) + self._pending_slots
        cfg = dict(config)
        cfg["execution"] = dict(exec_cfg)
        cfg["execution"]["_effective_open_count"] = effective
        return cfg

    def _queue_for_next_open(self, candidate: dict, event_time: pd.Timestamp) -> None:
        branch = self.branches[candidate["branch"]]
        positions = branch.aligned.index.get_indexer([event_time])
        if positions[0] < 0:
            candidate["_policy_skip_reason"] = "missing_branch_event_time"
            return

        next_pos = positions[0] + 1
        if next_pos >= len(branch.aligned):
            candidate["_policy_skip_reason"] = "no_next_branch_open"
            return

        next_row = branch.aligned.iloc[next_pos]
        self._pending.append(
            PendingEntry(
                branch_name=branch.name,
                due_time=pd.Timestamp(branch.aligned.index[next_pos]),
                entry_price=float(next_row["open"]),
                candidate=candidate,
            )
        )
        self._pending_slots += 1  # count queued entries in effective cap

    def _fill_pending_due(self, event_time: pd.Timestamp) -> None:
        due = [entry for entry in self._pending if entry.due_time <= event_time]
        self._pending = [entry for entry in self._pending if entry.due_time > event_time]
        self._pending_slots -= len(due)    # release slots before opening trades

        for pending in due:
            branch = self.branches[pending.branch_name]
            candidate = resolve_sl_tp(pending.candidate, pending.entry_price)
            trade = branch.engine.make_trade(
                hypothesis=candidate["hypothesis"],
                direction=candidate["direction"],
                entry_time=pending.due_time,
                entry_price=pending.entry_price,
                sl=candidate["sl"],
                tp=candidate["tp"],
                is_reentry=False,
                is_stacked=len(self._shared_open_trades) > 0,
                conflict_winner=candidate.get("conflict_winner"),
            )
            self._trade_counter += 1
            trade.trade_id = self._trade_counter
            trade.branch = branch.name
            trade.phase = branch.phase
            trade.entry_timeframe = branch.entry_timeframe
            trade.context_timeframe = branch.context_timeframe
            trade._origin_engine = branch.engine
            branch.engine.open_trade(trade)
            self.ledger.log_entry(trade, candidate)

    def _exit_via_1m(self, prev_time: pd.Timestamp, event_time: pd.Timestamp) -> None:
        if not self._shared_open_trades:
            return

        start = np.searchsorted(self._1m_ns, prev_time.value, side="right")
        stop = np.searchsorted(self._1m_ns, event_time.value, side="right")

        for i in range(start, stop):
            self._check_shared_exits(
                pd.Timestamp(self._1m_ns[i], tz="UTC"),
                high=self._1m_high[i],
                low=self._1m_low[i],
            )

    def _exit_via_event_rows(self, timestamp_events: list[tuple[str, int]]) -> None:
        for branch_name, pos in timestamp_events:
            row = self.branches[branch_name].aligned.iloc[pos]
            self._check_shared_exits(
                pd.Timestamp(row.name),
                high=float(row["high"]),
                low=float(row["low"]),
            )

    def _check_shared_exits(self, bar_time: pd.Timestamp, high: float, low: float) -> None:
        for trade in list(self._shared_open_trades):
            origin = getattr(trade, "_origin_engine")
            exit_reason, exit_price = origin._check_sl_tp(trade, high, low)
            if not exit_reason:
                continue

            trade.close(bar_time, exit_price, exit_reason)
            self._shared_open_trades.remove(trade)
            origin.trade_log.append(trade)
            hyp_state = origin.state_for(trade.hypothesis)
            if exit_reason == "sl":
                if origin._cooldown_enabled() and origin._cooldown_bars() > 0:
                    origin.cooldowns[trade.hypothesis].trigger()
                hyp_state.reset()
            else:
                hyp_state.reset()
            self.ledger.log_trade(trade)

    def _closed_trades(self) -> list:
        closed = []
        for branch in self.branches.values():
            closed.extend(branch.engine.trade_log)
        closed.sort(key=lambda trade: trade.exit_time)
        return closed
