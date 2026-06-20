from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from ultrab.entry.layer5 import EntryIntent, SkipIntent


@dataclass
class ActiveTrade:
    intent: EntryIntent
    bars_held: int = 0


@dataclass(frozen=True)
class TradeResult:
    result_id: str
    intent_id: str
    symbol: str
    timeframe: str
    epoch_id: str
    phase: str
    phase_sub_status: str | None
    phase_episode_id: str
    policy_name: str
    direction: str
    entry_time: str | None
    entry_price: float | None
    stop_loss: float | None
    target_price: float | None
    target_r: float | None
    risk_pips: float | None
    exit_time: str | None
    exit_price: float | None
    outcome: str
    r_result: float | None
    bars_held: int | None
    evidence_id: str | None
    evidence_kind: str | None
    evidence_presented_at: str | None
    trigger_event_id: str | None
    trigger_kind: str | None
    trigger_path: str | None
    trigger_event_at: str | None
    budget_spent: bool
    stale_marked: bool
    skip_reason: str | None

    def to_row(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "intent_id": self.intent_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "epoch_id": self.epoch_id,
            "phase": self.phase,
            "phase_sub_status": self.phase_sub_status,
            "phase_episode_id": self.phase_episode_id,
            "policy_name": self.policy_name,
            "direction": self.direction,
            "entry_time": self.entry_time,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target_price": self.target_price,
            "target_r": self.target_r,
            "risk_pips": self.risk_pips,
            "exit_time": self.exit_time,
            "exit_price": self.exit_price,
            "outcome": self.outcome,
            "r_result": self.r_result,
            "bars_held": self.bars_held,
            "evidence_id": self.evidence_id,
            "evidence_kind": self.evidence_kind,
            "evidence_presented_at": self.evidence_presented_at,
            "trigger_event_id": self.trigger_event_id,
            "trigger_kind": self.trigger_kind,
            "trigger_path": self.trigger_path,
            "trigger_event_at": self.trigger_event_at,
            "budget_spent": self.budget_spent,
            "stale_marked": self.stale_marked,
            "skip_reason": self.skip_reason,
        }


class TradeAnalyzer:
    def __init__(self, *, max_hold_bars: int = 32) -> None:
        self.max_hold_bars = max_hold_bars

    def open_trade(self, intent: EntryIntent) -> ActiveTrade:
        return ActiveTrade(intent=intent)

    def result_from_skip(self, intent: SkipIntent) -> TradeResult:
        evidence = intent.evidence
        trigger = intent.trigger
        return TradeResult(
            result_id=uuid4().hex,
            intent_id=intent.intent_id,
            symbol=intent.symbol,
            timeframe=intent.timeframe,
            epoch_id=intent.epoch_id,
            phase=intent.phase,
            phase_sub_status=intent.phase_sub_status,
            phase_episode_id=intent.phase_episode_id,
            policy_name=intent.policy_name,
            direction=intent.direction,
            entry_time=None,
            entry_price=None,
            stop_loss=None,
            target_price=None,
            target_r=None,
            risk_pips=intent.risk_pips,
            exit_time=intent.created_at,
            exit_price=None,
            outcome="skipped",
            r_result=None,
            bars_held=None,
            evidence_id=evidence.evidence_id if evidence else None,
            evidence_kind=evidence.evidence_kind if evidence else None,
            evidence_presented_at=evidence.presented_at if evidence else None,
            trigger_event_id=trigger.event_id if trigger else None,
            trigger_kind=trigger.trigger_kind if trigger else None,
            trigger_path=trigger.trigger_path if trigger else None,
            trigger_event_at=trigger.event_at if trigger else None,
            budget_spent=False,
            stale_marked=intent.stale_marked,
            skip_reason=intent.skip_reason,
        )

    def advance(self, trade: ActiveTrade, bar: dict[str, Any]) -> TradeResult | None:
        trade.bars_held += 1
        intent = trade.intent
        high = float(bar["high"])
        low = float(bar["low"])
        if intent.direction == "long":
            hit_sl = low <= intent.stop_loss
            hit_tp = high >= intent.target_price
        else:
            hit_sl = high >= intent.stop_loss
            hit_tp = low <= intent.target_price

        if hit_sl:
            return self._close(trade, bar, "loss", intent.stop_loss)
        if hit_tp:
            return self._close(trade, bar, "win", intent.target_price)
        if trade.bars_held >= self.max_hold_bars:
            return self._close(trade, bar, "timeout", float(bar["close"]))
        return None

    def close_open_end(self, trade: ActiveTrade, bar: dict[str, Any] | None) -> TradeResult:
        if bar is None:
            bar = {
                "time": trade.intent.created_at,
                "close": trade.intent.entry_price,
                "high": trade.intent.entry_price,
                "low": trade.intent.entry_price,
            }
        return self._close(trade, bar, "timeout", float(bar["close"]))

    def _close(
        self,
        trade: ActiveTrade,
        bar: dict[str, Any],
        outcome: str,
        exit_price: float,
    ) -> TradeResult:
        intent = trade.intent
        risk = abs(intent.entry_price - intent.stop_loss)
        if risk <= 0:
            r_result = None
        elif intent.direction == "long":
            r_result = (exit_price - intent.entry_price) / risk
        else:
            r_result = (intent.entry_price - exit_price) / risk
        return TradeResult(
            result_id=uuid4().hex,
            intent_id=intent.intent_id,
            symbol=intent.symbol,
            timeframe=intent.timeframe,
            epoch_id=intent.epoch_id,
            phase=intent.phase,
            phase_sub_status=intent.phase_sub_status,
            phase_episode_id=intent.phase_episode_id,
            policy_name=intent.policy_name,
            direction=intent.direction,
            entry_time=intent.created_at,
            entry_price=intent.entry_price,
            stop_loss=intent.stop_loss,
            target_price=intent.target_price,
            target_r=intent.target_r,
            risk_pips=intent.risk_pips,
            exit_time=bar.get("time"),
            exit_price=exit_price,
            outcome=outcome,
            r_result=r_result,
            bars_held=trade.bars_held,
            evidence_id=intent.evidence.evidence_id,
            evidence_kind=intent.evidence.evidence_kind,
            evidence_presented_at=intent.evidence.presented_at,
            trigger_event_id=intent.trigger.event_id,
            trigger_kind=intent.trigger.trigger_kind,
            trigger_path=intent.trigger.trigger_path,
            trigger_event_at=intent.trigger.event_at,
            budget_spent=intent.budget_spent,
            stale_marked=False,
            skip_reason=None,
        )
