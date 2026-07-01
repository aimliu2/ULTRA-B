from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from ultrab.entry.layer5 import EntryIntent, EntryPermissionEngine, SkipIntent
from ultrab.entry.layer6 import ActiveTrade, TradeAnalyzer, TradeResult
from ultrab.entry.regime_tags import REGIME_TAG_COLUMNS, regime_tags
from ultrab.replayer.data_source import ReplayDataConfig, load_app_config, replay_data_config
from ultrab.runtime.dual_smc import DualSmcRuntime


RESULT_COLUMNS = [
    "result_id",
    "intent_id",
    "symbol",
    "timeframe",
    "startup_mode",
    "epoch_id",
    "phase",
    "phase_sub_status",
    "phase_episode_id",
    "policy_name",
    "direction",
    "entry_time",
    "entry_price",
    "stop_loss",
    "target_price",
    "target_r",
    "risk_pips",
    "exit_time",
    "exit_price",
    "outcome",
    "r_result",
    "bars_held",
    "evidence_id",
    "evidence_kind",
    "evidence_presented_at",
    "trigger_event_id",
    "trigger_kind",
    "trigger_path",
    "trigger_event_at",
    "trigger_age_bars",
    "budget_spent",
    "stale_marked",
    "skip_reason",
    *REGIME_TAG_COLUMNS,
]


SUMMARY_COLUMNS = [
    "epoch_id",
    "d_watch_bars",
    "d_watch_bars_with_evidence",
    "d_watch_bars_with_trigger",
    "d_watch_bars_with_evidence_and_trigger",
    "entry_chances",
    "accepted_entries",
    "skipped_entries",
    "wins",
    "losses",
    "timeouts",
    "win_rate_pct",
    "avg_r",
    "evidence_liquidity_grab",
    "evidence_ltf_sd_zone",
    "evidence_htf_sd_zone",
    "evidence_watch_extreme",
    "trigger_D_watch_pathA",
    "SL_too_wide",
]

OBSERVATION_COLUMNS = [
    "cursor_time",
    "symbol",
    "timeframe",
    "epoch_id",
    "phase_episode_id",
    "prior_phase_e_direction",
    "phase",
    "phase_sub_status",
    "phase_d_watch_entered_at",
    "has_liquidity_grab_evidence",
    "liquidity_event_ids",
    "has_ltf_sd_zone_evidence",
    "ltf_sd_zone_id",
    "has_path_a_trigger",
    "path_a_event_id",
    "path_a_event_at",
    "entry_decision",
    "skip_reason",
    *REGIME_TAG_COLUMNS,
]


def _bar_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    bars = snapshot.get("lower_bars") or snapshot.get("bars") or []
    return bars[-1] if bars else None


def _candidate(snapshot: dict[str, Any], pattern: str, direction: str | None) -> dict[str, Any] | None:
    for item in snapshot.get("evidence_candidates") or []:
        if item.get("pattern") == pattern and item.get("direction") == direction:
            return item
    return None


def _phase_d_observation(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    hypothesis = snapshot.get("hypothesis") or {}
    debug = hypothesis.get("debug_facts") or {}
    if hypothesis.get("phase") != "D" or hypothesis.get("phase_sub_status") != "watch":
        return None
    prior = debug.get("prior_phase_e_direction") or debug.get("active_phase_e_direction")
    reaction = _candidate(snapshot, "htf_counter_reaction", prior) or {}
    story = _candidate(snapshot, "ltf_counter_story", prior) or {}
    trigger = _candidate(snapshot, "ltf_counter_choch", prior) or {}
    reaction_facts = reaction.get("debug_facts") or {}
    story_facts = story.get("debug_facts") or {}
    trigger_facts = trigger.get("debug_facts") or {}
    path_a_ready = bool(trigger_facts.get("ltf_counter_ichoch_isb_sequence_seen"))
    liquidity_ids = [
        str(value)
        for value in reaction_facts.get("liquidity_reclaim_ready_event_ids") or []
        if value
    ]
    ltf_zone_id = story_facts.get("selected_poi_id")
    row = {
        "cursor_time": snapshot.get("cursor_time"),
        "symbol": snapshot.get("symbol"),
        "timeframe": snapshot.get("timeframe") or snapshot.get("lower_tf"),
        "epoch_id": debug.get("htf_pd_epoch_id") or snapshot.get("evidence_compiler_epoch_id"),
        "phase_episode_id": debug.get("phase_episode_id") or hypothesis.get("hypothesis_id"),
        "prior_phase_e_direction": prior,
        "phase": hypothesis.get("phase"),
        "phase_sub_status": hypothesis.get("phase_sub_status"),
        "phase_d_watch_entered_at": debug.get("phase_d_shadow_watch_entered_at"),
        "has_liquidity_grab_evidence": bool(liquidity_ids),
        "liquidity_event_ids": "|".join(liquidity_ids),
        "has_ltf_sd_zone_evidence": bool(ltf_zone_id),
        "ltf_sd_zone_id": ltf_zone_id,
        "has_path_a_trigger": path_a_ready,
        "path_a_event_id": trigger_facts.get("ltf_counter_sequence_isb_event_id") if path_a_ready else None,
        "path_a_event_at": trigger_facts.get("ltf_counter_sequence_isb_event_at") if path_a_ready else None,
        "entry_decision": "",
        "skip_reason": "",
    }
    row.update(regime_tags(snapshot))
    return row


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})


def summarize_results(
    rows: list[dict[str, Any]],
    observations: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("epoch_id") or "")].append(row)
    obs_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observations or []:
        obs_grouped[str(row.get("epoch_id") or "")].append(row)

    summary: list[dict[str, Any]] = []
    for epoch_id in sorted(set(grouped) | set(obs_grouped)):
        epoch_rows = grouped.get(epoch_id, [])
        epoch_obs = obs_grouped.get(epoch_id, [])
        outcomes = Counter(str(row.get("outcome") or "") for row in epoch_rows)
        evidences = Counter(str(row.get("evidence_kind") or "") for row in epoch_rows)
        paths = Counter(str(row.get("trigger_path") or "") for row in epoch_rows)
        skip_reasons = Counter(str(row.get("skip_reason") or "") for row in epoch_rows)
        obs_evidence = sum(
            1
            for row in epoch_obs
            if row.get("has_liquidity_grab_evidence") or row.get("has_ltf_sd_zone_evidence")
        )
        obs_trigger = sum(
            1
            for row in epoch_obs
            if row.get("has_path_a_trigger")
        )
        obs_evidence_and_trigger = sum(
            1
            for row in epoch_obs
            if (
                row.get("has_liquidity_grab_evidence") or row.get("has_ltf_sd_zone_evidence")
            )
            and row.get("has_path_a_trigger")
        )
        wins = outcomes["win"]
        losses = outcomes["loss"]
        denomin = wins + losses
        r_values = [
            float(row["r_result"])
            for row in epoch_rows
            if row.get("r_result") not in (None, "")
        ]
        summary.append(
            {
                "epoch_id": epoch_id,
                "d_watch_bars": len(epoch_obs),
                "d_watch_bars_with_evidence": obs_evidence,
                "d_watch_bars_with_trigger": obs_trigger,
                "d_watch_bars_with_evidence_and_trigger": obs_evidence_and_trigger,
                "entry_chances": len(epoch_rows),
                "accepted_entries": outcomes["win"] + outcomes["loss"] + outcomes["timeout"],
                "skipped_entries": outcomes["skipped"],
                "wins": wins,
                "losses": losses,
                "timeouts": outcomes["timeout"],
                "win_rate_pct": round((wins / denomin) * 100.0, 2) if denomin else "",
                "avg_r": round(sum(r_values) / len(r_values), 4) if r_values else "",
                "evidence_liquidity_grab": evidences["liquidity_grab"],
                "evidence_ltf_sd_zone": evidences["ltf_sd_zone"],
                "evidence_htf_sd_zone": evidences["htf_sd_zone"],
                "evidence_watch_extreme": evidences["watch_extreme"],
                "trigger_D_watch_pathA": paths["D.watch_pathA"],
                "SL_too_wide": skip_reasons["SL_too_wide"],
            }
        )
    return summary


def run_backtest(args: argparse.Namespace) -> tuple[Path, Path, Path, list[dict[str, Any]], list[dict[str, Any]]]:
    config_path = Path(args.config)
    base = replay_data_config(config_path)
    lower_tf, higher_tf = args.combo.split("_", 1)
    lower = ReplayDataConfig(base.root, args.symbol.upper(), lower_tf, args.window_bars or base.window_bars)
    higher = ReplayDataConfig(base.root, args.symbol.upper(), higher_tf, args.window_bars or base.window_bars)
    runtime = DualSmcRuntime(
        str(config_path),
        symbol=args.symbol,
        lower_config=lower,
        higher_config=higher,
        combo_name=args.combo,
        start_time=args.start_time,
        startup_mode=args.startup_mode,
    )
    raw_cfg = load_app_config(config_path)
    hypothesis_cfg = raw_cfg.get("replay", {}).get("hypothesis", {})
    layer5_cfg = hypothesis_cfg.get("layer5_entry", {})
    phase_a_cfg = hypothesis_cfg.get("phase_a", {})
    objective_threshold = float(phase_a_cfg.get("objective_progress_threshold", 0.90))
    asset_geo_raw = layer5_cfg.get("asset_geometry", {})
    symbol_geometry = {
        sym: {
            "sl_buffer_pips": float(v.get("sl_buffer_pips", 2.0)),
            "min_sl_pips": float(v["sl_band_pips"]["min"]),
            "max_sl_pips": float(v["sl_band_pips"]["max"]),
        }
        for sym, v in asset_geo_raw.items()
    }
    layer5 = EntryPermissionEngine(
        symbol_geometry=symbol_geometry,
        phase_a_objective_threshold=objective_threshold,
    )
    analyzer = TradeAnalyzer(max_hold_bars=args.max_hold_bars)
    active: list[ActiveTrade] = []
    results: list[TradeResult] = []
    tags_by_intent_id: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    last_bar: dict[str, Any] | None = None
    steps = 0

    def process_snapshot(snapshot: dict[str, Any]) -> None:
        nonlocal active, last_bar
        bar = _bar_from_snapshot(snapshot)
        if bar is not None:
            last_bar = bar

        remaining: list[ActiveTrade] = []
        for trade in active:
            if bar is None:
                remaining.append(trade)
                continue
            result = analyzer.advance(trade, bar)
            if result is None:
                remaining.append(trade)
            else:
                results.append(result)
        active = remaining

        observation = _phase_d_observation(snapshot)
        decision = layer5.evaluate(snapshot)
        if isinstance(decision, EntryIntent):
            tags_by_intent_id[decision.intent_id] = regime_tags(snapshot, decision)
            active.append(analyzer.open_trade(decision))
            if observation is not None:
                observation["entry_decision"] = "accepted"
        elif isinstance(decision, SkipIntent):
            tags_by_intent_id[decision.intent_id] = regime_tags(snapshot, decision)
            results.append(analyzer.result_from_skip(decision))
            if observation is not None:
                observation["entry_decision"] = "skipped"
                observation["skip_reason"] = decision.skip_reason
        elif observation is not None:
            observation["entry_decision"] = "none"
        if observation is not None:
            observations.append(observation)

    if args.startup_mode == "right_edge_rebuild":
        process_snapshot(runtime.classify_snapshot())

    while True:
        step = runtime.step()
        snapshot = runtime.classify_snapshot()
        process_snapshot(snapshot)

        steps += 1
        if step.done or (args.max_steps and steps >= args.max_steps):
            break

    for trade in active:
        results.append(analyzer.close_open_end(trade, last_bar))

    rows = []
    for result in results:
        row = result.to_row()
        row["startup_mode"] = args.startup_mode
        row.update(tags_by_intent_id.get(result.intent_id, {}))
        rows.append(row)
    summary = summarize_results(rows, observations)
    output_dir = Path(args.output_dir)
    results_path = output_dir / args.results_file
    observations_path = output_dir / args.observations_file
    summary_path = output_dir / args.summary_file
    _write_csv(results_path, rows, RESULT_COLUMNS)
    _write_csv(observations_path, observations, OBSERVATION_COLUMNS)
    _write_csv(summary_path, summary, SUMMARY_COLUMNS)
    return results_path, observations_path, summary_path, rows, observations, summary


def _pct(num: int, denom: int) -> str:
    return f"{num / denom * 100:.1f}%" if denom else "n/a"


def write_markdown_report(
    path: Path,
    rows: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    summary: list[dict[str, Any]],
    args: argparse.Namespace,
) -> None:
    # --- epoch counts ---
    epochs_total = len(summary)
    epochs_with_d = sum(1 for s in summary if (s.get("d_watch_bars") or 0) > 0)

    # --- observation aggregates ---
    obs_total = len(observations)
    obs_path_a = sum(1 for o in observations if o.get("has_path_a_trigger"))

    # --- result aggregates (non-skipped and skipped split) ---
    accepted = [r for r in rows if r.get("outcome") in ("win", "loss", "timeout")]
    skipped = [r for r in rows if r.get("outcome") == "skipped"]
    total_decisions = len(accepted) + len(skipped)

    path_a_accepted = sum(1 for r in accepted if r.get("trigger_path") == "D.watch_pathA")
    path_a_skipped = sum(1 for r in skipped if r.get("trigger_path") == "D.watch_pathA")
    path_a_total = path_a_accepted + path_a_skipped
    htf_zone_decisions = sum(1 for r in rows if r.get("at_htf_sd_zone") is True)
    htf_zone_context_decisions = sum(1 for r in rows if r.get("htf_zone_context") is True)

    def _path_win_rate(path_tag: str) -> str:
        w = sum(1 for r in accepted if r.get("trigger_path") == path_tag and r.get("outcome") == "win")
        l = sum(1 for r in accepted if r.get("trigger_path") == path_tag and r.get("outcome") == "loss")
        return f"{w / (w + l) * 100:.1f}%" if (w + l) else "n/a"

    def _path_zone_count(path_tag: str) -> int:
        return sum(
            1
            for r in rows
            if r.get("trigger_path") == path_tag and r.get("at_htf_sd_zone") is True
        )

    skip_reasons = Counter(str(r.get("skip_reason") or "") for r in skipped)

    wins = sum(1 for r in accepted if r.get("outcome") == "win")
    losses = sum(1 for r in accepted if r.get("outcome") == "loss")
    timeouts = sum(1 for r in accepted if r.get("outcome") == "timeout")
    denomin = wins + losses
    win_rate = f"{wins / denomin * 100:.1f}%" if denomin else "n/a"
    r_vals = [float(r["r_result"]) for r in accepted if r.get("r_result") not in (None, "")]
    avg_r = f"{sum(r_vals) / len(r_vals):.3f}" if r_vals else "n/a"
    hold_vals = [int(r["bars_held"]) for r in accepted if r.get("bars_held") not in (None, "")]
    avg_hold = f"{sum(hold_vals) / len(hold_vals):.1f}" if hold_vals else "n/a"

    # date range from observations
    obs_times = sorted(o["cursor_time"] for o in observations if o.get("cursor_time"))
    period = f"{obs_times[0][:10]} → {obs_times[-1][:10]}" if obs_times else "unknown"

    lines = [
        f"# Layer 5 Phase D Backtest — {args.symbol} {args.combo}",
        f"",
        f"**Period**: {period}  ",
        f"**Policy**: D.lax (SL band from config, RR ≥ 1.75, TP = pd_midpoint)  ",
        f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"",
        f"---",
        f"",
        f"## HTF PD Epochs",
        f"",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total HTF PD epochs | {epochs_total} |",
        f"| Epochs with D.watch activity | {epochs_with_d} |",
        f"| Epochs without D.watch | {epochs_total - epochs_with_d} |",
        f"",
        f"---",
        f"",
        f"## Phase D Observations (D.watch bars)",
        f"",
        f"| Metric | Count | % of D.watch bars |",
        f"|--------|-------|-------------------|",
        f"| Total D.watch bars | {obs_total} | — |",
        f"| Bars with D.watch_pathA trigger (internal counter iChoCh -> internal pro iSB) | {obs_path_a} | {_pct(obs_path_a, obs_total)} |",
        f"",
        f"---",
        f"",
        f"## Layer 5 Entry Decisions",
        f"",
        f"| Metric | Count | % of decisions |",
        f"|--------|-------|----------------|",
        f"| Total decisions evaluated | {total_decisions} | — |",
        f"| Accepted (entry taken) | {len(accepted)} | {_pct(len(accepted), total_decisions)} |",
        f"| Skipped (all reasons) | {len(skipped)} | {_pct(len(skipped), total_decisions)} |",
    ]
    for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
        if reason:
            lines.append(f"| &nbsp;&nbsp;↳ {reason} | {count} | {_pct(count, total_decisions)} |")
    lines += [
        f"",
        f"### By Path",
        f"",
        f"| Path | Accepted | Skipped | Total seen | Accept% | Win rate |",
        f"|------|----------|---------|------------|---------|----------|",
        f"| D.watch_pathA | {path_a_accepted} | {path_a_skipped} | {path_a_total} | {_pct(path_a_accepted, path_a_total)} | {_path_win_rate('D.watch_pathA')} |",
        f"",
        f"### Regime Tags",
        f"",
        f"| Tag | Count | % of decisions |",
        f"|-----|-------|----------------|",
        f"| HTF zone context observed before/during entry | {htf_zone_context_decisions} | {_pct(htf_zone_context_decisions, total_decisions)} |",
        f"| Entry bar inside HTF S/D zone | {htf_zone_decisions} | {_pct(htf_zone_decisions, total_decisions)} |",
        f"",
        f"| Path | Decisions at HTF S/D | % of path decisions |",
        f"|------|----------------------|---------------------|",
        f"| D.watch_pathA | {_path_zone_count('D.watch_pathA')} | {_pct(_path_zone_count('D.watch_pathA'), path_a_total)} |",
        f"",
        f"---",
        f"",
        f"## Trade Outcomes (no spread / no slippage)",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total accepted trades | {len(accepted)} |",
        f"| Wins | {wins} |",
        f"| Losses | {losses} |",
        f"| Timeouts | {timeouts} |",
        f"| Win rate (W / W+L) | {win_rate} |",
        f"| Avg R (accepted only) | {avg_r} |",
        f"| Avg hold (bars) | {avg_hold} |",
        f"",
        f"---",
        f"",
        f"## Files",
        f"",
        f"| File | Description |",
        f"|------|-------------|",
        f"| `layer5_trade_results.csv` | Per-trade result rows (accepted + skipped) |",
        f"| `layer5_phase_d_observations.csv` | Per-bar D.watch observations |",
        f"| `layer5_epoch_summary.csv` | Per-epoch aggregates |",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Layer 5 Phase D backtest and write CSV analysis files.")
    parser.add_argument("--config", default="src/ultrab/replayer/config.yaml")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--combo", default="15m_4h")
    parser.add_argument("--start-time", default=None)
    parser.add_argument(
        "--startup-mode",
        choices=["right_edge_rebuild", "legacy_window_remainder"],
        default="right_edge_rebuild",
    )
    parser.add_argument("--window-bars", type=int, default=None)
    parser.add_argument("--max-steps", type=int, default=None)
    # SL band is now per-symbol from config.yaml layer5_entry.asset_geometry
    parser.add_argument("--max-hold-bars", type=int, default=32)
    parser.add_argument("--output-dir", default="analysis/layer5")
    parser.add_argument("--results-file", default="layer5_trade_results.csv")
    parser.add_argument("--observations-file", default="layer5_phase_d_observations.csv")
    parser.add_argument("--summary-file", default="layer5_epoch_summary.csv")
    parser.add_argument("--report-file", default="layer5_report.md")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    results_path, observations_path, summary_path, rows, observations, summary = run_backtest(args)
    output_dir = Path(args.output_dir)
    report_path = output_dir / args.report_file
    write_markdown_report(report_path, rows, observations, summary, args)
    print(f"wrote {len(rows)} result rows to {results_path}")
    print(f"wrote {len(observations)} phase D observations to {observations_path}")
    print(f"wrote {len(summary)} epoch summary rows to {summary_path}")
    print(f"wrote report to {report_path}")


if __name__ == "__main__":
    main()
