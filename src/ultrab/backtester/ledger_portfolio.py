from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class PortfolioBaselineResult:
    trades: pd.DataFrame
    metrics: dict
    monthly: pd.Series


@dataclass(frozen=True)
class PortfolioReplayResult:
    accepted: pd.DataFrame
    skipped: pd.DataFrame
    metrics: dict
    monthly: pd.Series


def load_candidate_ledgers(paths: Iterable[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        df = pd.read_csv(path)
        frames.append(df)
    if not frames:
        return pd.DataFrame()

    trades = pd.concat(frames, ignore_index=True)
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True, errors="coerce")
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], utc=True, errors="coerce")
    trades["r_result"] = pd.to_numeric(trades["r_result"], errors="coerce").fillna(0.0)
    trades["open_risk"] = pd.to_numeric(trades.get("open_risk", 1.0), errors="coerce").fillna(1.0)
    return trades.sort_values(["entry_time", "exit_time", "symbol", "candidate_id"]).reset_index(drop=True)


def max_drawdown(r_vals: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in r_vals:
        equity += float(r)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return round(max_dd, 4)


def profit_factor(r_vals: Iterable[float]) -> float | None:
    vals = [float(v) for v in r_vals]
    gross_win = sum(v for v in vals if v > 0)
    gross_loss = abs(sum(v for v in vals if v < 0))
    if gross_loss == 0:
        return None
    return round(gross_win / gross_loss, 4)


def loss_cluster_profile(r_vals: Iterable[float]) -> dict:
    clusters = []
    current_len = 0
    current_r = 0.0
    for r in r_vals:
        r = float(r)
        if r < 0:
            current_len += 1
            current_r += r
        elif current_len:
            clusters.append((current_len, current_r))
            current_len = 0
            current_r = 0.0
    if current_len:
        clusters.append((current_len, current_r))

    if not clusters:
        return {
            "cluster_count": 0,
            "max_cluster_len": 0,
            "worst_cluster_R": 0.0,
            "avg_cluster_len": 0.0,
            "avg_cluster_R": 0.0,
        }

    lengths = [c[0] for c in clusters]
    totals = [c[1] for c in clusters]
    return {
        "cluster_count": len(clusters),
        "max_cluster_len": max(lengths),
        "worst_cluster_R": round(min(totals), 4),
        "avg_cluster_len": round(sum(lengths) / len(lengths), 4),
        "avg_cluster_R": round(sum(totals) / len(totals), 4),
    }


def concurrent_profile(trades: pd.DataFrame) -> dict:
    events = []
    for row in trades.itertuples(index=False):
        if pd.isna(row.entry_time) or pd.isna(row.exit_time):
            continue
        risk = float(getattr(row, "open_risk", 1.0))
        events.append((row.entry_time, 1, risk))
        events.append((row.exit_time, -1, -risk))

    events.sort(key=lambda item: (item[0], item[1]))
    open_count = 0
    open_risk = 0.0
    max_count = 0
    max_risk = 0.0

    for _, delta_count, delta_risk in events:
        open_count += delta_count
        open_risk += delta_risk
        max_count = max(max_count, open_count)
        max_risk = max(max_risk, open_risk)

    return {
        "max_concurrent_positions": int(max_count),
        "max_open_R": round(float(max_risk), 4),
    }


def currency_exposure_counts(trades: pd.DataFrame) -> dict:
    pairs = {
        "USD": ["EURUSD", "GBPUSD", "AUDUSD", "USDJPY"],
        "EUR": ["EURUSD", "EURJPY"],
        "GBP": ["GBPUSD", "GBPJPY"],
        "JPY": ["USDJPY", "EURJPY", "GBPJPY"],
        "AUD": ["AUDUSD"],
    }
    counts = {}
    for currency, symbols in pairs.items():
        counts[currency] = int(trades["symbol"].isin(symbols).sum())
    return counts


def build_max_variance_baseline(trades: pd.DataFrame) -> PortfolioBaselineResult:
    if trades.empty:
        return PortfolioBaselineResult(trades=trades, metrics={}, monthly=pd.Series(dtype=float))

    exit_ordered = trades.sort_values(["exit_time", "entry_time", "symbol", "candidate_id"]).reset_index(drop=True)
    r_vals = exit_ordered["r_result"].astype(float).tolist()
    monthly = (
        exit_ordered.assign(exit_month=exit_ordered["exit_time"].dt.tz_convert(None).dt.to_period("M").astype(str))
        .groupby("exit_month")["r_result"]
        .sum()
        .sort_index()
    )
    days = max((exit_ordered["exit_time"].max() - exit_ordered["entry_time"].min()).days, 1)
    years = days / 365.25

    concurrent = concurrent_profile(exit_ordered)
    metrics = {
        "portfolio_id": "max_variance_all_candidates",
        "symbols": "+".join(sorted(exit_ordered["symbol"].unique())),
        "candidate_count": int(exit_ordered["candidate_id"].nunique()),
        "trade_count": int(len(exit_ordered)),
        "total_R": round(float(sum(r_vals)), 4),
        "annualized_R": round(float(sum(r_vals)) / years, 4) if years > 0 else None,
        "ev_per_trade_R": round(float(sum(r_vals)) / len(r_vals), 4),
        "pf": profit_factor(r_vals),
        "max_drawdown_R": max_drawdown(r_vals),
        "monthly_R_mean": round(float(monthly.mean()), 4),
        "monthly_R_std": round(float(monthly.std(ddof=0)), 4),
        "worst_month_R": round(float(monthly.min()), 4),
        "best_month_R": round(float(monthly.max()), 4),
        "loss_cluster_profile": loss_cluster_profile(r_vals),
        "max_concurrent_positions": concurrent["max_concurrent_positions"],
        "max_open_R": concurrent["max_open_R"],
        "trades_by_symbol": {
            k: int(v) for k, v in exit_ordered["symbol"].value_counts().sort_index().items()
        },
        "total_R_by_symbol": {
            k: round(float(v), 4)
            for k, v in exit_ordered.groupby("symbol")["r_result"].sum().sort_index().items()
        },
        "trades_by_session": {
            k: int(v) for k, v in exit_ordered["session"].value_counts().sort_index().items()
        },
        "total_R_by_session": {
            k: round(float(v), 4)
            for k, v in exit_ordered.groupby("session")["r_result"].sum().sort_index().items()
        },
        "currency_trade_exposure_counts": currency_exposure_counts(exit_ordered),
    }
    return PortfolioBaselineResult(trades=exit_ordered, metrics=metrics, monthly=monthly)


def _empty_monthly() -> pd.Series:
    return pd.Series(dtype=float)


def replay_with_portfolio_cap(
    trades: pd.DataFrame,
    *,
    portfolio_id: str,
    portfolio_cap: int,
    symbols: list[str],
) -> PortfolioReplayResult:
    """Replay already-normalized symbol ledgers under a shared portfolio cap.

    Symbol-level rules are assumed to be baked into the candidate ledgers. This
    function only applies a shared max concurrent open-position cap.
    """
    if trades.empty:
        return PortfolioReplayResult(
            accepted=trades.copy(),
            skipped=trades.copy(),
            metrics={
                "portfolio_id": portfolio_id,
                "portfolio_cap": portfolio_cap,
                "symbols": "+".join(symbols),
                "symbol_count": len(symbols),
                "trade_count": 0,
                "skipped_by_portfolio_cap": 0,
                "total_R": 0.0,
            },
            monthly=_empty_monthly(),
        )

    ordered = trades.sort_values(["entry_time", "symbol", "candidate_id", "source_trade_id"]).reset_index(drop=True)
    open_positions: list[dict] = []
    accepted_rows = []
    skipped_rows = []

    for row in ordered.to_dict("records"):
        entry_time = row["entry_time"]
        open_positions = [
            pos for pos in open_positions
            if pd.notna(pos["exit_time"]) and pos["exit_time"] > entry_time
        ]
        open_count_before = len(open_positions)
        open_risk_before = round(sum(float(pos.get("open_risk", 1.0)) for pos in open_positions), 4)

        if open_count_before >= portfolio_cap:
            skipped = row.copy()
            skipped.update({
                "portfolio_id": portfolio_id,
                "portfolio_cap": portfolio_cap,
                "skip_reason": "portfolio_cap_full",
                "open_positions_before": open_count_before,
                "open_R_before": open_risk_before,
            })
            skipped_rows.append(skipped)
            continue

        accepted = row.copy()
        accepted.update({
            "portfolio_id": portfolio_id,
            "portfolio_cap": portfolio_cap,
            "open_positions_before": open_count_before,
            "open_R_before": open_risk_before,
            "open_positions_after": open_count_before + 1,
            "open_R_after": round(open_risk_before + float(row.get("open_risk", 1.0)), 4),
        })
        accepted_rows.append(accepted)
        open_positions.append(row)

    accepted = pd.DataFrame(accepted_rows)
    skipped = pd.DataFrame(skipped_rows)
    metrics, monthly = summarize_replay(
        accepted,
        portfolio_id=portfolio_id,
        portfolio_cap=portfolio_cap,
        symbols=symbols,
        skipped_count=len(skipped),
    )
    return PortfolioReplayResult(accepted=accepted, skipped=skipped, metrics=metrics, monthly=monthly)


def summarize_replay(
    accepted: pd.DataFrame,
    *,
    portfolio_id: str,
    portfolio_cap: int,
    symbols: list[str],
    skipped_count: int,
) -> tuple[dict, pd.Series]:
    if accepted.empty:
        return {
            "portfolio_id": portfolio_id,
            "portfolio_cap": portfolio_cap,
            "symbols": "+".join(symbols),
            "symbol_count": len(symbols),
            "trade_count": 0,
            "skipped_by_portfolio_cap": skipped_count,
            "total_R": 0.0,
            "annualized_R": None,
            "ev_per_trade_R": None,
            "pf": None,
            "max_drawdown_R": 0.0,
            "monthly_R_mean": None,
            "monthly_R_std": None,
            "worst_month_R": None,
            "best_month_R": None,
            "loss_cluster_profile": loss_cluster_profile([]),
            "max_concurrent_positions": 0,
            "max_open_R": 0.0,
            "trades_by_symbol": {},
            "total_R_by_symbol": {},
        }, _empty_monthly()

    exit_ordered = accepted.sort_values(["exit_time", "entry_time", "symbol", "candidate_id"]).reset_index(drop=True)
    r_vals = exit_ordered["r_result"].astype(float).tolist()
    monthly = (
        exit_ordered.assign(exit_month=exit_ordered["exit_time"].dt.tz_convert(None).dt.to_period("M").astype(str))
        .groupby("exit_month")["r_result"]
        .sum()
        .sort_index()
    )
    days = max((exit_ordered["exit_time"].max() - exit_ordered["entry_time"].min()).days, 1)
    years = days / 365.25
    concurrent = concurrent_profile(exit_ordered)
    total_r = float(sum(r_vals))
    metrics = {
        "portfolio_id": portfolio_id,
        "portfolio_cap": portfolio_cap,
        "symbols": "+".join(symbols),
        "symbol_count": len(symbols),
        "trade_count": int(len(exit_ordered)),
        "skipped_by_portfolio_cap": int(skipped_count),
        "total_R": round(total_r, 4),
        "annualized_R": round(total_r / years, 4) if years > 0 else None,
        "ev_per_trade_R": round(total_r / len(r_vals), 4),
        "pf": profit_factor(r_vals),
        "max_drawdown_R": max_drawdown(r_vals),
        "monthly_R_mean": round(float(monthly.mean()), 4),
        "monthly_R_std": round(float(monthly.std(ddof=0)), 4),
        "worst_month_R": round(float(monthly.min()), 4),
        "best_month_R": round(float(monthly.max()), 4),
        "loss_cluster_profile": loss_cluster_profile(r_vals),
        "max_concurrent_positions": concurrent["max_concurrent_positions"],
        "max_open_R": concurrent["max_open_R"],
        "trades_by_symbol": {
            k: int(v) for k, v in exit_ordered["symbol"].value_counts().sort_index().items()
        },
        "total_R_by_symbol": {
            k: round(float(v), 4)
            for k, v in exit_ordered.groupby("symbol")["r_result"].sum().sort_index().items()
        },
        "trades_by_session": {
            k: int(v) for k, v in exit_ordered["session"].value_counts().sort_index().items()
        },
        "total_R_by_session": {
            k: round(float(v), 4)
            for k, v in exit_ordered.groupby("session")["r_result"].sum().sort_index().items()
        },
    }
    return metrics, monthly
