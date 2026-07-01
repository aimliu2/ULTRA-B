from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ultrab.replayer.data_source import ReplayDataConfig, load_app_config, load_full_ohlc, replay_data_config
from ultrab.runtime.dual_smc import DualSmcRuntime


def _configs(
    config_path: Path,
    *,
    symbol: str,
    combo_name: str,
) -> tuple[ReplayDataConfig, ReplayDataConfig]:
    config = load_app_config(config_path)
    data_cfg = replay_data_config(config_path)
    combo = config.get("dual_mode", {}).get("combos", {}).get(combo_name)
    if not combo:
        raise ValueError(f"unknown combo: {combo_name}")
    lower = ReplayDataConfig(
        data_cfg.root,
        symbol.upper(),
        str(combo["lower_tf"]).lower(),
        data_cfg.window_bars,
        data_cfg.start_time,
    )
    higher = ReplayDataConfig(
        data_cfg.root,
        symbol.upper(),
        str(combo["higher_tf"]).lower(),
        data_cfg.window_bars,
        data_cfg.start_time,
    )
    return lower, higher


def _terrain_row(snapshot: dict[str, Any]) -> dict[str, Any]:
    hypothesis = snapshot.get("hypothesis") or {}
    debug = hypothesis.get("debug_facts") or {}
    return {
        "cursor_time": snapshot.get("cursor_time"),
        "htf_epoch_id": debug.get("htf_pd_epoch_id") or snapshot.get("evidence_compiler_epoch_id"),
        "htf_epoch_start_time": debug.get("htf_pd_epoch_start_time"),
        "ltf_episode_anchor_time": debug.get("ltf_episode_anchor_time"),
        "hypothesis_phase": hypothesis.get("phase"),
        "hypothesis_sub_status": hypothesis.get("phase_sub_status"),
        "hypothesis_direction": hypothesis.get("direction"),
        "hypothesis_status": hypothesis.get("status"),
    }


def run_survey(
    *,
    config_path: Path,
    symbol: str,
    combo_name: str,
    start_time: str | None = None,
    max_bars: int | None = None,
) -> list[dict[str, Any]]:
    lower, higher = _configs(config_path, symbol=symbol, combo_name=combo_name)
    if start_time is None:
        lower_bars = load_full_ohlc(lower)
        start_time = lower_bars.index[0].isoformat()
    runtime = DualSmcRuntime(
        str(config_path),
        symbol=symbol,
        lower_config=lower,
        higher_config=higher,
        combo_name=combo_name,
        start_time=start_time,
        startup_mode="right_edge_rebuild",
    )
    rows = [_terrain_row(runtime.classify_snapshot())]
    while max_bars is None or len(rows) < max_bars:
        step = runtime.step()
        if step.done and step.cursor_time is None:
            break
        rows.append(_terrain_row(runtime.classify_snapshot()))
        if step.done:
            break
    return rows


def _main() -> None:
    parser = argparse.ArgumentParser(description="Build a continuous Layer 3/4 terrain timeline.")
    parser.add_argument("--config", default="src/ultrab/replayer/config.yaml")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--combo", default="15m_4h")
    parser.add_argument("--start-time")
    parser.add_argument("--max-bars", type=int)
    parser.add_argument("--output-dir", default="analysis/terrain_timeline")
    args = parser.parse_args()

    rows = run_survey(
        config_path=Path(args.config),
        symbol=args.symbol,
        combo_name=args.combo,
        start_time=args.start_time,
        max_bars=args.max_bars,
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{args.symbol.upper()}_{args.combo}_terrain.parquet"
    pd.DataFrame(rows).to_parquet(output, index=False)
    print(f"wrote {output} rows={len(rows)}")


if __name__ == "__main__":
    _main()
