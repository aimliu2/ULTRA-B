from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "src" / "ultrab").is_dir():
            return parent
    return Path.cwd()


ROOT = find_repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from ultrab.backtester.ledger_portfolio import (  # type: ignore  # noqa: E402
        load_candidate_ledgers,
        loss_cluster_profile,
        profit_factor,
        summarize_replay,
    )
except ModuleNotFoundError:
    from ledger_portfolio import (  # type: ignore  # noqa: E402
        load_candidate_ledgers,
        loss_cluster_profile,
        profit_factor,
        summarize_replay,
    )


DEFAULT_ANALYSIS_DIR = ROOT / "portfolio-analysis"
DEFAULT_REGISTRY_PATH = DEFAULT_ANALYSIS_DIR / "candidate_registry.csv"
DEFAULT_LEDGER_DIR = DEFAULT_ANALYSIS_DIR / "candidate_ledgers"
DEFAULT_RESULTS_DIR = DEFAULT_ANALYSIS_DIR / "results"
DEFAULT_FUNNEL_CONFIG_PATH = ROOT / "funnel.yaml"


@dataclass(frozen=True)
class CBRatchetConfig:
    name: str
    enabled: bool
    base_equity_R: float = 100.0
    trigger_pct: float = 0.08
    recovery_buffer: float = 0.97
    next_trigger_pct: float = 0.92
    first_trigger_from_peak: bool = True



@dataclass
class CBState:
    peak: float
    anchor: float
    triggered_session: bool = False
    trigger_count: int = 0
    last_trigger_time: pd.Timestamp | None = None
    active_session_key: str | None = None


@dataclass(frozen=True)
class FunnelVariant:
    name: str
    cb_config: CBRatchetConfig
    highwind_enabled: bool


def read_registry(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_funnel_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    for key in ["portfolios", "cb_variants", "highwind"]:
        if key not in config:
            raise ValueError(f"Missing '{key}' in funnel config: {path}")
    return config


def cb_variants_from_config(config: dict) -> list[CBRatchetConfig]:
    variants = []
    for row in config["cb_variants"]:
        variants.append(CBRatchetConfig(
            name=str(row["name"]),
            enabled=bool(row.get("enabled", True)),
            base_equity_R=float(row.get("base_equity_R", 100.0)),
            trigger_pct=float(row.get("trigger_pct", 0.08)),
            recovery_buffer=float(row.get("recovery_buffer", 0.97)),
            next_trigger_pct=float(row.get("next_trigger_pct", 0.92)),
            first_trigger_from_peak=bool(row.get("first_trigger_from_peak", True)),
        ))
    return variants


def highwind_symbol_thresholds(highwind_config: dict) -> dict:
    return {
        symbol: cfg
        for symbol, cfg in highwind_config.items()
        if isinstance(cfg, dict) and "window" in cfg
    }


def funnel_variants_from_config(config: dict) -> list[FunnelVariant]:
    variants = []
    for cb_config in cb_variants_from_config(config):
        variants.append(FunnelVariant(
            name=f"{cb_config.name}__hw_off",
            cb_config=cb_config,
            highwind_enabled=False,
        ))
        if config["highwind"].get("enabled", True):
            variants.append(FunnelVariant(
                name=f"{cb_config.name}__hw_on",
                cb_config=cb_config,
                highwind_enabled=True,
            ))
    return variants


def candidate_ledger_path(ledger_dir: Path, candidate_id: str) -> Path:
    return ledger_dir / f"{candidate_id}.csv"


def load_portfolio_trades(registry_path: Path, ledger_dir: Path, symbols: list[str]) -> pd.DataFrame:
    registry = read_registry(registry_path)
    symbol_to_candidate = {row["symbol"]: row["candidate_id"] for row in registry}
    missing = sorted(set(symbols) - set(symbol_to_candidate))
    if missing:
        raise ValueError(f"Missing symbols in registry: {missing}")
    paths = [candidate_ledger_path(ledger_dir, symbol_to_candidate[symbol]) for symbol in symbols]
    return load_candidate_ledgers(paths)


def session_key(entry_time: pd.Timestamp, session: object) -> str:
    label = str(session) if pd.notna(session) else "unknown"
    return f"{entry_time.date()}::{label}"


def update_cb_peak(state: CBState, equity: float, cfg: CBRatchetConfig) -> None:
    if equity > state.peak:
        state.peak = equity
        state.anchor = equity * cfg.recovery_buffer


def cb_trigger_level(state: CBState, cfg: CBRatchetConfig) -> float:
    if cfg.first_trigger_from_peak and state.trigger_count == 0:
        return state.peak * (1.0 - cfg.trigger_pct)
    return state.anchor * cfg.next_trigger_pct


def maybe_trigger_cb(
    state: CBState,
    *,
    equity: float,
    now: pd.Timestamp,
    cfg: CBRatchetConfig,
) -> bool:
    if not cfg.enabled:
        return False
    if state.triggered_session:
        return True

    trigger_level = cb_trigger_level(state, cfg)
    if equity > trigger_level:
        return False

    state.triggered_session = True
    state.trigger_count += 1
    state.last_trigger_time = now

    accepted_damage_level = trigger_level if cfg.first_trigger_from_peak and state.trigger_count == 1 else state.anchor
    state.peak = accepted_damage_level
    state.anchor = accepted_damage_level * cfg.recovery_buffer
    return True


def reset_cb_session_if_needed(state: CBState, key: str) -> None:
    if state.active_session_key != key:
        state.active_session_key = key
        state.triggered_session = False


def empty_highwind_stats() -> dict:
    return {
        "highwind_live_trade_count": 0,
        "highwind_resized_trade_count": 0,
        "highwind_shadow_trade_count": 0,
        "highwind_tax_R": 0.0,
        "highwind_saved_R": 0.0,
        "highwind_opportunity_cost_R": 0.0,
        "all_symbols_halted_entry_count": 0,
        "max_concurrent_halted_symbols": 0,
        "final_halted_symbols": "",
        "halt_count_by_symbol": {},
        "recovery_count_by_symbol": {},
        "shadow_trade_count_by_symbol": {},
    }


def init_highwind_state(symbols: list[str], thresholds: dict) -> dict:
    state = {}
    for symbol in symbols:
        if symbol not in thresholds:
            raise ValueError(f"Missing Highwind thresholds for {symbol}")
        cfg = thresholds[symbol]
        window = int(cfg["window"])
        seed_wins = int(cfg["seed_wins"])
        seed_losses = int(cfg["seed_losses"])
        state[symbol] = {
            "window": ([1] * seed_wins + [0] * seed_losses)[-window:],
            "window_size": window,
            "level": "NORMAL",
            "halt_count": 0,
            "recovery_count": 0,
            "shadow_trade_count": 0,
        }
    return state


def highwind_level_from_wr(wr: float, cfg: dict) -> str:
    if wr < float(cfg["halt_threshold"]):
        return "HALT"
    if wr < float(cfg["l2_threshold"]):
        return "L2"
    if wr < float(cfg["l1_threshold"]):
        return "L1"
    return "NORMAL"


def highwind_update_on_exit(
    state: dict,
    *,
    symbol: str,
    raw_r_result: float,
    exit_time: pd.Timestamp,
    thresholds: dict,
    events: list[dict],
    auto_recovery: bool,
) -> None:
    if raw_r_result == 0 or symbol not in state:
        return

    symbol_state = state[symbol]
    cfg = thresholds[symbol]
    window = int(symbol_state["window_size"])
    old_level = symbol_state["level"]
    outcome = 1 if raw_r_result > 0 else 0

    symbol_state["window"].append(outcome)
    symbol_state["window"] = symbol_state["window"][-window:]
    wr = sum(symbol_state["window"]) / window

    if old_level == "HALT":
        if auto_recovery and wr >= float(cfg["l1_threshold"]):
            new_level = "L2"
            symbol_state["recovery_count"] += 1
        else:
            new_level = "HALT"
    else:
        new_level = highwind_level_from_wr(wr, cfg)
        if new_level == "HALT" and old_level != "HALT":
            symbol_state["halt_count"] += 1
        elif wr >= float(cfg["l1_threshold"]):
            step_up = {"L2": "L1", "L1": "NORMAL", "NORMAL": "NORMAL"}
            new_level = step_up.get(old_level, new_level)

    symbol_state["level"] = new_level
    if new_level != old_level:
        events.append({
            "symbol": symbol,
            "time": exit_time,
            "old_level": old_level,
            "new_level": new_level,
            "rolling_wr": round(wr, 4),
            "raw_r_result": raw_r_result,
            "event_type": "highwind_level_change",
        })


def cb_rearm_target(session: object, rearm_map: dict) -> str | None:
    label = str(session) if pd.notna(session) else "unknown"
    return rearm_map.get(label)


def cb_reset_session_if_rearmed(state: CBState, session: object, rearm_map: dict) -> None:
    if not state.triggered_session:
        return
    label = str(session) if pd.notna(session) else "unknown"
    if state.active_session_key == label:
        return
    if state.active_session_key is not None and label == state.active_session_key:
        return
    # active_session_key stores the re-arm target while CB is triggered.
    if label == state.active_session_key:
        state.triggered_session = False


def replay_trade_funnel(
    trades: pd.DataFrame,
    *,
    portfolio_id: str,
    portfolio_cap: int,
    symbols: list[str],
    variant: FunnelVariant,
    highwind_thresholds: dict,
    highwind_size_mult: dict,
    highwind_auto_recovery: bool,
    cb_rearm_map: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict, pd.Series]:
    ordered = trades.sort_values(["entry_time", "symbol", "candidate_id", "source_trade_id"]).reset_index(drop=True)

    accepted_rows: list[dict] = []
    skipped_rows: list[dict] = []
    cb_events: list[dict] = []
    highwind_events: list[dict] = []
    open_positions: list[dict] = []
    pending_closes: list[dict] = []
    highwind_state = init_highwind_state(symbols, highwind_thresholds)

    cb_config = variant.cb_config
    equity = cb_config.base_equity_R
    cb_state = CBState(
        peak=cb_config.base_equity_R,
        anchor=cb_config.base_equity_R * cb_config.recovery_buffer,
    )
    highwind_stats = empty_highwind_stats()

    def process_closes(until: pd.Timestamp) -> None:
        nonlocal equity, pending_closes
        still_open = []
        for pos in pending_closes:
            if pd.notna(pos["exit_time"]) and pos["exit_time"] <= until:
                raw_r = float(pos["raw_r_result"])
                sized_r = float(pos["r_result"])
                if pos.get("execution_mode") == "live":
                    equity += sized_r
                    update_cb_peak(cb_state, equity, cb_config)
                if variant.highwind_enabled:
                    highwind_update_on_exit(
                        highwind_state,
                        symbol=pos["symbol"],
                        raw_r_result=raw_r,
                        exit_time=pos["exit_time"],
                        thresholds=highwind_thresholds,
                        events=highwind_events,
                        auto_recovery=highwind_auto_recovery,
                    )
            else:
                still_open.append(pos)
        pending_closes = still_open

    for row in ordered.to_dict("records"):
        entry_time = row["entry_time"]
        process_closes(entry_time)

        open_positions = [
            pos for pos in open_positions
            if pd.notna(pos["exit_time"]) and pos["exit_time"] > entry_time
        ]
        current_session = str(row.get("session")) if pd.notna(row.get("session")) else "unknown"
        if cb_state.triggered_session and current_session == cb_state.active_session_key:
            cb_state.triggered_session = False

        open_count_before = len(open_positions)
        open_risk_before = round(sum(float(pos.get("open_risk", 1.0)) for pos in open_positions), 4)

        triggered_before = cb_state.triggered_session
        cb_active = maybe_trigger_cb(cb_state, equity=equity, now=entry_time, cfg=cb_config)
        if cb_active:
            skipped = row.copy()
            skipped.update({
                "portfolio_id": portfolio_id,
                "portfolio_cap": portfolio_cap,
                "cb_variant": cb_config.name,
                "funnel_variant": variant.name,
                "highwind_enabled": variant.highwind_enabled,
                "skip_reason": "cb_triggered" if not triggered_before else "cb_session_active",
                "equity_R_before": round(equity, 4),
                "cb_peak_R": round(cb_state.peak, 4),
                "cb_anchor_R": round(cb_state.anchor, 4),
                "cb_trigger_count": cb_state.trigger_count,
                "open_positions_before": open_count_before,
                "open_R_before": open_risk_before,
            })
            skipped_rows.append(skipped)
            if not triggered_before:
                rearm_target = cb_rearm_target(row.get("session"), cb_rearm_map)
                cb_state.active_session_key = rearm_target
                cb_events.append({
                    "portfolio_id": portfolio_id,
                    "cb_variant": cb_config.name,
                    "funnel_variant": variant.name,
                    "trigger_time": entry_time,
                    "session": current_session,
                    "rearm_session": rearm_target,
                    "equity_R": round(equity, 4),
                    "peak_R": round(cb_state.peak, 4),
                    "anchor_R": round(cb_state.anchor, 4),
                    "next_trigger_R": round(cb_trigger_level(cb_state, cb_config), 4),
                    "open_positions_before": open_count_before,
                })
            continue

        symbol = row["symbol"]
        hw_level = highwind_state[symbol]["level"] if variant.highwind_enabled else "NORMAL"
        size_mult = float(highwind_size_mult.get(hw_level, 1.0)) if variant.highwind_enabled else 1.0
        halted_symbols = [
            s for s in symbols
            if variant.highwind_enabled and highwind_state[s]["level"] == "HALT"
        ]
        highwind_stats["max_concurrent_halted_symbols"] = max(
            int(highwind_stats["max_concurrent_halted_symbols"]),
            len(halted_symbols),
        )
        if variant.highwind_enabled and len(halted_symbols) == len(symbols):
            highwind_stats["all_symbols_halted_entry_count"] += 1

        if variant.highwind_enabled and hw_level == "HALT":
            shadow = row.copy()
            raw_r = float(row["r_result"])
            shadow.update({
                "portfolio_id": portfolio_id,
                "portfolio_cap": portfolio_cap,
                "cb_variant": cb_config.name,
                "funnel_variant": variant.name,
                "highwind_enabled": True,
                "highwind_level_at_entry": hw_level,
                "highwind_size_mult": 0.0,
                "execution_mode": "shadow",
                "skip_reason": "highwind_halt_shadow",
                "raw_r_result": raw_r,
                "r_result": 0.0,
                "highwind_delta_R": -raw_r,
                "equity_R_before": round(equity, 4),
                "open_positions_before": open_count_before,
                "open_R_before": open_risk_before,
            })
            skipped_rows.append(shadow)
            pending_closes.append(shadow)
            highwind_state[symbol]["shadow_trade_count"] += 1
            highwind_stats["highwind_shadow_trade_count"] += 1
            highwind_stats["highwind_tax_R"] += -raw_r
            if raw_r < 0:
                highwind_stats["highwind_saved_R"] += abs(raw_r)
            elif raw_r > 0:
                highwind_stats["highwind_opportunity_cost_R"] += raw_r
            continue

        if open_count_before >= portfolio_cap:
            skipped = row.copy()
            skipped.update({
                "portfolio_id": portfolio_id,
                "portfolio_cap": portfolio_cap,
                "cb_variant": cb_config.name,
                "funnel_variant": variant.name,
                "highwind_enabled": variant.highwind_enabled,
                "highwind_level_at_entry": hw_level,
                "highwind_size_mult": size_mult,
                "skip_reason": "portfolio_cap_full",
                "equity_R_before": round(equity, 4),
                "open_positions_before": open_count_before,
                "open_R_before": open_risk_before,
            })
            skipped_rows.append(skipped)
            continue

        accepted = row.copy()
        raw_r = float(row["r_result"])
        sized_r = raw_r * size_mult
        accepted.update({
            "portfolio_id": portfolio_id,
            "portfolio_cap": portfolio_cap,
            "cb_variant": cb_config.name,
            "funnel_variant": variant.name,
            "highwind_enabled": variant.highwind_enabled,
            "highwind_level_at_entry": hw_level,
            "highwind_size_mult": size_mult,
            "execution_mode": "live",
            "raw_r_result": raw_r,
            "r_result": sized_r,
            "highwind_delta_R": sized_r - raw_r,
            "equity_R_before": round(equity, 4),
            "open_positions_before": open_count_before,
            "open_R_before": open_risk_before,
            "open_positions_after": open_count_before + 1,
            "open_R_after": round(open_risk_before + float(row.get("open_risk", 1.0)) * size_mult, 4),
        })
        accepted_rows.append(accepted)
        open_positions.append(accepted)
        pending_closes.append(accepted)
        highwind_stats["highwind_live_trade_count"] += 1
        if variant.highwind_enabled and size_mult != 1.0:
            highwind_stats["highwind_resized_trade_count"] += 1
            highwind_stats["highwind_tax_R"] += sized_r - raw_r
            if raw_r < 0:
                highwind_stats["highwind_saved_R"] += abs(sized_r - raw_r)
            elif raw_r > 0:
                highwind_stats["highwind_opportunity_cost_R"] += abs(sized_r - raw_r)

    if pending_closes:
        for pos in sorted(pending_closes, key=lambda item: item["exit_time"]):
            if pd.notna(pos["exit_time"]):
                raw_r = float(pos["raw_r_result"])
                sized_r = float(pos["r_result"])
                if pos.get("execution_mode") == "live":
                    equity += sized_r
                    update_cb_peak(cb_state, equity, cb_config)
                if variant.highwind_enabled:
                    highwind_update_on_exit(
                        highwind_state,
                        symbol=pos["symbol"],
                        raw_r_result=raw_r,
                        exit_time=pos["exit_time"],
                        thresholds=highwind_thresholds,
                        events=highwind_events,
                        auto_recovery=highwind_auto_recovery,
                    )

    accepted = pd.DataFrame(accepted_rows)
    skipped = pd.DataFrame(skipped_rows)
    cb_events_df = pd.DataFrame(cb_events)
    highwind_events_df = pd.DataFrame(highwind_events)
    metrics, monthly = summarize_replay(
        accepted,
        portfolio_id=portfolio_id,
        portfolio_cap=portfolio_cap,
        symbols=symbols,
        skipped_count=int((skipped.get("skip_reason") == "portfolio_cap_full").sum()) if not skipped.empty else 0,
    )

    cb_skips = skipped[skipped["skip_reason"].isin(["cb_triggered", "cb_session_active"])] if not skipped.empty else skipped
    counterfactual_r = float(cb_skips["r_result"].sum()) if not cb_skips.empty else 0.0
    counterfactual_vals = cb_skips["r_result"].astype(float).tolist() if not cb_skips.empty else []

    metrics.update({
        "cb_variant": cb_config.name,
        "funnel_variant": variant.name,
        "highwind_enabled": variant.highwind_enabled,
        "cb_enabled": cb_config.enabled,
        "cb_trigger_count": int(len(cb_events_df)),
        "cb_skipped_trade_count": int(len(cb_skips)),
        "cb_skipped_trade_counterfactual_R": round(counterfactual_r, 4),
        "cb_skipped_trade_counterfactual_PF": profit_factor(counterfactual_vals),
        "cb_skipped_loss_cluster_profile": loss_cluster_profile(counterfactual_vals),
        "final_equity_R": round(equity, 4),
        "cb_final_peak_R": round(cb_state.peak, 4),
        "cb_final_anchor_R": round(cb_state.anchor, 4),
    })

    if variant.highwind_enabled:
        highwind_stats["final_halted_symbols"] = "+".join(
            s for s in symbols if highwind_state[s]["level"] == "HALT"
        )
        highwind_stats["halt_count_by_symbol"] = {
            s: int(highwind_state[s]["halt_count"]) for s in symbols
        }
        highwind_stats["recovery_count_by_symbol"] = {
            s: int(highwind_state[s]["recovery_count"]) for s in symbols
        }
        highwind_stats["shadow_trade_count_by_symbol"] = {
            s: int(highwind_state[s]["shadow_trade_count"]) for s in symbols
        }
    else:
        highwind_stats["final_halted_symbols"] = ""
        highwind_stats["halt_count_by_symbol"] = {}
        highwind_stats["recovery_count_by_symbol"] = {}
        highwind_stats["shadow_trade_count_by_symbol"] = {}
    for key, value in highwind_stats.items():
        metrics[key] = round(value, 4) if isinstance(value, float) else value

    return accepted, skipped, cb_events_df, highwind_events_df, metrics, monthly


def highwind_calibration(trades: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    rows = []
    for symbol, group in trades.groupby("symbol"):
        if symbol not in thresholds:
            raise ValueError(f"Missing assigned Highwind thresholds for {symbol}")

        assigned = thresholds[symbol]
        closed = group[group["r_result"].ne(0)].copy()
        wins = closed[closed["r_result"] > 0]
        losses = closed[closed["r_result"] < 0]
        win_count = len(wins)
        loss_count = len(losses)
        trade_count = win_count + loss_count
        wr = win_count / trade_count if trade_count else 0.0
        avg_win = float(wins["r_result"].mean()) if win_count else 0.0
        avg_loss = abs(float(losses["r_result"].mean())) if loss_count else 1.0
        be_wr = avg_loss / (avg_win + avg_loss) if avg_win + avg_loss else 0.0

        rows.append({
            "symbol": symbol,
            "trade_count": int(trade_count),
            "win_rate": round(wr, 4),
            "avg_win_R": round(avg_win, 4),
            "avg_loss_R": round(avg_loss, 4),
            "breakeven_wr": round(be_wr, 4),
            "assigned_window": int(assigned["window"]),
            "assigned_halt_threshold": float(assigned["halt_threshold"]),
            "assigned_l2_threshold": float(assigned["l2_threshold"]),
            "assigned_l1_threshold": float(assigned["l1_threshold"]),
            "assigned_seed_wins": int(assigned["seed_wins"]),
            "assigned_seed_losses": int(assigned["seed_losses"]),
        })
    return pd.DataFrame(rows).sort_values("symbol")


def simulate_highwind(
    trades: pd.DataFrame,
    calibration: pd.DataFrame,
) -> pd.DataFrame:
    cfg = {row["symbol"]: row for _, row in calibration.iterrows()}
    state = {}
    events = []
    ordered = trades.sort_values(["exit_time", "entry_time", "symbol"]).reset_index(drop=True)

    for row in ordered.to_dict("records"):
        symbol = row["symbol"]
        r_result = float(row["r_result"])
        if r_result == 0 or symbol not in cfg:
            continue
        if symbol not in state:
            seed_wins = int(cfg[symbol]["assigned_seed_wins"])
            seed_losses = int(cfg[symbol]["assigned_seed_losses"])
            window = int(cfg[symbol]["assigned_window"])
            state[symbol] = {
                "window": ([1] * seed_wins + [0] * seed_losses)[-window:],
                "level": "NORMAL",
                "halt_count": 0,
                "window_size": window,
            }

        outcome = 1 if r_result > 0 else 0
        symbol_state = state[symbol]
        window = int(symbol_state["window_size"])
        symbol_state["window"].append(outcome)
        symbol_state["window"] = symbol_state["window"][-window:]
        wr = sum(symbol_state["window"]) / window
        old_level = symbol_state["level"]
        c = cfg[symbol]

        if wr < float(c["assigned_halt_threshold"]):
            new_level = "HALT"
        elif wr < float(c["assigned_l2_threshold"]):
            new_level = "L2"
        elif wr < float(c["assigned_l1_threshold"]):
            new_level = "L1"
        else:
            new_level = "NORMAL"

        if new_level == "HALT" and old_level != "HALT":
            symbol_state["halt_count"] += 1

        symbol_state["level"] = new_level
        if new_level != old_level:
            events.append({
                "symbol": symbol,
                "time": row["exit_time"],
                "old_level": old_level,
                "new_level": new_level,
                "rolling_wr": round(wr, 4),
                "r_result": r_result,
            })

    return pd.DataFrame(events)


def clean_metrics(metrics: dict) -> dict:
    cleaned = {}
    for key, value in metrics.items():
        if isinstance(value, (dict, list)):
            cleaned[key] = json.dumps(value, sort_keys=True)
        else:
            cleaned[key] = value
    return cleaned


def write_report(
    metrics: pd.DataFrame,
    calibration: pd.DataFrame,
    highwind_events: pd.DataFrame,
    report_path: Path,
) -> None:
    cb_delta = metrics.copy()
    off = cb_delta[cb_delta["funnel_variant"].eq("cb_off__hw_off")][
        ["portfolio_name", "total_R", "max_drawdown_R", "monthly_R_std", "worst_month_R", "trade_count"]
    ].rename(columns={
        "total_R": "raw_total_R",
        "max_drawdown_R": "raw_max_drawdown_R",
        "monthly_R_std": "raw_monthly_R_std",
        "worst_month_R": "raw_worst_month_R",
        "trade_count": "raw_trade_count",
    })
    cb_delta = cb_delta.merge(off, on="portfolio_name", how="left")
    cb_delta["delta_total_R"] = cb_delta["total_R"] - cb_delta["raw_total_R"]
    cb_delta["delta_max_drawdown_R"] = cb_delta["max_drawdown_R"] - cb_delta["raw_max_drawdown_R"]
    cb_delta["delta_monthly_R_std"] = cb_delta["monthly_R_std"] - cb_delta["raw_monthly_R_std"]
    cb_delta["delta_worst_month_R"] = cb_delta["worst_month_R"] - cb_delta["raw_worst_month_R"]

    view_cols = [
        "portfolio_name",
        "funnel_variant",
        "total_R",
        "delta_total_R",
        "max_drawdown_R",
        "delta_max_drawdown_R",
        "monthly_R_std",
        "delta_monthly_R_std",
        "worst_month_R",
        "delta_worst_month_R",
        "cb_trigger_count",
        "cb_skipped_trade_count",
        "cb_skipped_trade_counterfactual_R",
        "highwind_tax_R",
        "highwind_saved_R",
        "highwind_opportunity_cost_R",
        "highwind_shadow_trade_count",
        "max_concurrent_halted_symbols",
        "final_halted_symbols",
    ]
    hw_counts = (
        highwind_events.groupby(["symbol", "new_level"]).size().unstack(fill_value=0).reset_index()
        if not highwind_events.empty else pd.DataFrame(columns=["symbol"])
    )

    lines = [
        "# Step 7 Intervention Test",
        "",
        "## Scope",
        "",
        "```text",
        "This is a backtester-side prototype only.",
        "No bot files are edited.",
        "CB is modeled as a damage-containment rule on closed-R portfolio equity.",
        "Highwind resizes live trades, shadows HALT trades, and auto-recovers through rolling WR.",
        "```",
        "",
        "## Funnel Variant Comparison",
        "",
        cb_delta[view_cols].to_markdown(index=False),
        "",
        "## Assigned Highwind Thresholds",
        "",
        calibration.to_markdown(index=False),
        "",
        "## Highwind Level Change Counts",
        "",
        hw_counts.to_markdown(index=False),
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step 7 CB and Highwind trade-funnel prototype.")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER_DIR)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--funnel-config", type=Path, default=DEFAULT_FUNNEL_CONFIG_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.results_dir.mkdir(parents=True, exist_ok=True)
    funnel_config = load_funnel_config(args.funnel_config)
    portfolios = funnel_config["portfolios"]
    funnel_variants = funnel_variants_from_config(funnel_config)
    highwind_config = funnel_config["highwind"]
    highwind_thresholds = highwind_symbol_thresholds(highwind_config)
    highwind_size_mult = highwind_config.get("size_mult", {"NORMAL": 1.0, "L1": 0.75, "L2": 0.5, "HALT": 0.0})
    highwind_auto_recovery = bool(highwind_config.get("auto_recovery", True))
    cb_rearm_map = funnel_config.get("cb_session_rearm", {})

    all_symbols = sorted({s for spec in portfolios.values() for s in spec["symbols"]})
    all_trades = load_portfolio_trades(args.registry, args.ledger_dir, all_symbols)
    calibration = highwind_calibration(all_trades, highwind_thresholds)
    highwind_events = simulate_highwind(all_trades, calibration)

    metrics_rows = []
    accepted_frames = []
    skipped_frames = []
    cb_event_frames = []
    highwind_event_frames = [highwind_events.assign(portfolio_id="calibration", funnel_variant="calibration")]

    for portfolio_name, spec in portfolios.items():
        trades = load_portfolio_trades(args.registry, args.ledger_dir, spec["symbols"])
        for variant in funnel_variants:
            portfolio_id = f"{portfolio_name}__N{spec['portfolio_cap']}__{variant.name}"
            accepted, skipped, cb_events, hw_events, metrics, _ = replay_trade_funnel(
                trades,
                portfolio_id=portfolio_id,
                portfolio_cap=int(spec["portfolio_cap"]),
                symbols=list(spec["symbols"]),
                variant=variant,
                highwind_thresholds=highwind_thresholds,
                highwind_size_mult=highwind_size_mult,
                highwind_auto_recovery=highwind_auto_recovery,
                cb_rearm_map=cb_rearm_map,
            )
            metrics["portfolio_name"] = portfolio_name
            metrics_rows.append(clean_metrics(metrics))
            if not accepted.empty:
                accepted_frames.append(accepted)
            if not skipped.empty:
                skipped_frames.append(skipped)
            if not cb_events.empty:
                cb_event_frames.append(cb_events)
            if not hw_events.empty:
                hw_events = hw_events.assign(portfolio_id=portfolio_id, funnel_variant=variant.name)
                highwind_event_frames.append(hw_events)

    metrics_df = pd.DataFrame(metrics_rows)
    accepted_df = pd.concat(accepted_frames, ignore_index=True) if accepted_frames else pd.DataFrame()
    skipped_df = pd.concat(skipped_frames, ignore_index=True) if skipped_frames else pd.DataFrame()
    cb_events_df = pd.concat(cb_event_frames, ignore_index=True) if cb_event_frames else pd.DataFrame()
    highwind_events_df = pd.concat(highwind_event_frames, ignore_index=True) if highwind_event_frames else pd.DataFrame()

    metrics_path = args.results_dir / "intervention_frontier.csv"
    accepted_path = args.results_dir / "intervention_accepted_trades.csv"
    skipped_path = args.results_dir / "intervention_skipped_trades.csv"
    cb_events_path = args.results_dir / "intervention_cb_events.csv"
    calibration_path = args.results_dir / "highwind_calibration.csv"
    highwind_events_path = args.results_dir / "highwind_level_events.csv"
    report_path = args.results_dir / "intervention_tax_report.md"

    metrics_df.to_csv(metrics_path, index=False)
    accepted_df.to_csv(accepted_path, index=False)
    skipped_df.to_csv(skipped_path, index=False)
    cb_events_df.to_csv(cb_events_path, index=False)
    calibration.to_csv(calibration_path, index=False)
    highwind_events_df.to_csv(highwind_events_path, index=False)
    write_report(metrics_df, calibration, highwind_events_df, report_path)

    print(json.dumps({
        "metrics": str(metrics_path.relative_to(ROOT)),
        "accepted_trades": str(accepted_path.relative_to(ROOT)),
        "skipped_trades": str(skipped_path.relative_to(ROOT)),
        "cb_events": str(cb_events_path.relative_to(ROOT)),
        "highwind_calibration": str(calibration_path.relative_to(ROOT)),
        "highwind_events": str(highwind_events_path.relative_to(ROOT)),
        "report": str(report_path.relative_to(ROOT)),
        "portfolio_points": int(len(metrics_df)),
    }, indent=2))


if __name__ == "__main__":
    main()
