from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ultrab.entry.layer5 import EntryPermissionEngine
from ultrab.entry.layer6 import ChunkAnalyzer, SampleRecord
from ultrab.replayer.data_source import ReplayDataConfig, load_app_config, replay_data_config
from ultrab.runtime.dual_smc import DualSmcRuntime


@dataclass(frozen=True)
class SamplingResult:
    samples: list[SampleRecord]
    exclusions: Counter[str]
    reconstruction_failures: int

    @property
    def failure_rate(self) -> float:
        if not self.samples:
            return 0.0
        return self.reconstruction_failures / len(self.samples)


def _tf_minutes(tf: str) -> int:
    value = str(tf).strip().lower()
    if value.endswith("m"):
        return int(value[:-1])
    if value.endswith("h"):
        return int(value[:-1]) * 60
    if value.endswith("d"):
        return int(value[:-1]) * 1440
    raise ValueError(f"unsupported timeframe: {tf!r}")


def _parse_time(value: Any) -> pd.Timestamp | None:
    if value in (None, "") or pd.isna(value):
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _symbol_geometry(config: dict[str, Any]) -> dict[str, dict[str, float]]:
    layer5_cfg = (
        config.get("replay", {})
        .get("hypothesis", {})
        .get("layer5_entry", {})
    )
    raw = layer5_cfg.get("asset_geometry", {}) if isinstance(layer5_cfg, dict) else {}
    return {
        str(symbol).upper(): {
            "sl_buffer_pips": float(settings.get("sl_buffer_pips", 2.0)),
            "min_sl_pips": float(settings["sl_band_pips"]["min"]),
            "max_sl_pips": float(settings["sl_band_pips"]["max"]),
        }
        for symbol, settings in raw.items()
    }


def eligible_timeline(
    terrain: pd.DataFrame,
    *,
    window_bars: int,
    lower_tf: str,
    higher_tf: str,
) -> tuple[pd.DataFrame, Counter[str]]:
    exclusions: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    lower_minutes = _tf_minutes(lower_tf)
    higher_minutes = _tf_minutes(higher_tf)
    for _, row in terrain.iterrows():
        cursor = _parse_time(row.get("cursor_time"))
        htf_start = _parse_time(row.get("htf_epoch_start_time"))
        ltf_anchor = _parse_time(row.get("ltf_episode_anchor_time")) or htf_start
        if cursor is None or htf_start is None:
            exclusions["no_epoch"] += 1
            continue
        if ltf_anchor is None:
            exclusions["no_episode"] += 1
            continue
        htf_age = (cursor - htf_start).total_seconds() / 60 / higher_minutes
        ltf_age = (cursor - ltf_anchor).total_seconds() / 60 / lower_minutes
        if htf_age >= window_bars:
            exclusions["outside_window_htf"] += 1
            continue
        if ltf_age >= window_bars:
            exclusions["outside_window_ltf"] += 1
            continue
        candidate = dict(row)
        candidate["eligible_htf_age_bars"] = htf_age
        candidate["eligible_ltf_age_bars"] = ltf_age
        rows.append(candidate)
    return pd.DataFrame(rows), exclusions


def select_anchors(
    eligible: pd.DataFrame,
    *,
    per_bucket: int = 20,
    min_gap_bars: int = 250,
    lower_tf: str,
) -> pd.DataFrame:
    if eligible.empty:
        return eligible
    lower_delta = pd.Timedelta(minutes=_tf_minutes(lower_tf))
    min_gap = lower_delta * int(min_gap_bars)
    selected: list[pd.Series] = []
    grouped = eligible.sort_values("cursor_time").groupby(
        ["hypothesis_phase", "hypothesis_direction"],
        dropna=False,
    )
    for _, group in grouped:
        if group.empty:
            continue
        ranked = group.copy()
        ranked["_score"] = (
            (ranked["eligible_htf_age_bars"].astype(float) - ranked["eligible_htf_age_bars"].median()).abs()
            + (ranked["eligible_ltf_age_bars"].astype(float).clip(upper=10).rsub(10) / 10)
        )
        chosen_times: list[pd.Timestamp] = []
        for _, row in ranked.sort_values("_score").iterrows():
            cursor = _parse_time(row.get("cursor_time"))
            if cursor is None:
                continue
            if any(abs(cursor - prior) < min_gap for prior in chosen_times):
                continue
            chosen_times.append(cursor)
            selected.append(row.drop(labels=["_score"], errors="ignore"))
            if len(chosen_times) >= per_bucket:
                break
    return pd.DataFrame(selected)


def _chunk_configs(
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


def _reconstruction_matches(snapshot: dict[str, Any], terrain_row: pd.Series) -> bool:
    hypothesis = snapshot.get("hypothesis") or {}
    debug = hypothesis.get("debug_facts") or {}
    return (
        hypothesis.get("phase") == terrain_row.get("hypothesis_phase")
        and hypothesis.get("direction") == terrain_row.get("hypothesis_direction")
        and debug.get("htf_pd_epoch_id") == terrain_row.get("htf_epoch_id")
    )


def execute_anchor(
    *,
    config_path: Path,
    symbol: str,
    combo_name: str,
    terrain_row: pd.Series,
    max_forward_bars: int = 200,
) -> SampleRecord:
    config = load_app_config(config_path)
    lower, higher = _chunk_configs(config_path, symbol=symbol, combo_name=combo_name)
    anchor_time = str(terrain_row["cursor_time"])
    runtime = DualSmcRuntime(
        str(config_path),
        symbol=symbol,
        lower_config=lower,
        higher_config=higher,
        combo_name=combo_name,
        start_time=anchor_time,
        startup_mode="right_edge_rebuild",
    )
    snapshot = runtime.classify_snapshot()
    reconstruction_ok = _reconstruction_matches(snapshot, terrain_row)
    if not reconstruction_ok:
        return SampleRecord(
            anchor_time=anchor_time,
            symbol=symbol.upper(),
            combo=combo_name,
            phase=terrain_row.get("hypothesis_phase"),
            direction=terrain_row.get("hypothesis_direction"),
            eligible_htf_age_bars=terrain_row.get("eligible_htf_age_bars"),
            eligible_ltf_age_bars=terrain_row.get("eligible_ltf_age_bars"),
            reconstruction_ok=False,
            startup_mode="right_edge_rebuild",
            outcome="reconstruction_failure",
            exclusion_reason="reconstruction_failure",
        )
    layer5 = EntryPermissionEngine(symbol_geometry=_symbol_geometry(config))
    return ChunkAnalyzer(max_forward_bars=max_forward_bars).analyze(
        runtime,
        layer5,
        anchor_time=anchor_time,
        eligible_htf_age_bars=terrain_row.get("eligible_htf_age_bars"),
        eligible_ltf_age_bars=terrain_row.get("eligible_ltf_age_bars"),
        reconstruction_ok=True,
        startup_mode="right_edge_rebuild",
    )


def run_sampling(
    *,
    config_path: Path,
    terrain_path: Path,
    symbol: str,
    combo_name: str,
    per_bucket: int = 20,
    max_forward_bars: int = 200,
) -> SamplingResult:
    config = load_app_config(config_path)
    data_cfg = replay_data_config(config_path)
    combo = config.get("dual_mode", {}).get("combos", {}).get(combo_name)
    if not combo:
        raise ValueError(f"unknown combo: {combo_name}")
    terrain = pd.read_parquet(terrain_path)
    eligible, exclusions = eligible_timeline(
        terrain,
        window_bars=data_cfg.window_bars,
        lower_tf=str(combo["lower_tf"]),
        higher_tf=str(combo["higher_tf"]),
    )
    anchors = select_anchors(
        eligible,
        per_bucket=per_bucket,
        min_gap_bars=data_cfg.window_bars // 2,
        lower_tf=str(combo["lower_tf"]),
    )
    samples = [
        execute_anchor(
            config_path=config_path,
            symbol=symbol,
            combo_name=combo_name,
            terrain_row=row,
            max_forward_bars=max_forward_bars,
        )
        for _, row in anchors.iterrows()
    ]
    failures = sum(1 for sample in samples if not sample.reconstruction_ok)
    return SamplingResult(samples=samples, exclusions=exclusions, reconstruction_failures=failures)


def _main() -> None:
    parser = argparse.ArgumentParser(description="Run right-edge chunk sampling from a terrain timeline.")
    parser.add_argument("--config", default="src/ultrab/replayer/config.yaml")
    parser.add_argument("--terrain", required=True)
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--combo", default="15m_4h")
    parser.add_argument("--per-bucket", type=int, default=20)
    parser.add_argument("--max-forward-bars", type=int, default=200)
    parser.add_argument(
        "--output-dir",
        help=(
            "Run folder to write into. Defaults to "
            "analysis/resample-<phase>-<current-YYYYMM>."
        ),
    )
    parser.add_argument(
        "--phase",
        default="a",
        help="Phase label used in the default run folder name, e.g. a, b, c, d, e.",
    )
    parser.add_argument(
        "--run-label",
        help=(
            "Run folder label under analysis/ when --output-dir is omitted, "
            "for example resample-a-202301 or resample-d-202501."
        ),
    )
    args = parser.parse_args()

    result = run_sampling(
        config_path=Path(args.config),
        terrain_path=Path(args.terrain),
        symbol=args.symbol,
        combo_name=args.combo,
        per_bucket=args.per_bucket,
        max_forward_bars=args.max_forward_bars,
    )
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        phase = str(args.phase).strip().lower()
        label = args.run_label or f"resample-{phase}-{datetime.now(timezone.utc).strftime('%Y%m')}"
        output_dir = Path("analysis") / label
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "sample_records.parquet"
    pd.DataFrame([sample.to_row() for sample in result.samples]).to_parquet(output, index=False)
    print(f"wrote {output}")
    print(f"samples={len(result.samples)} reconstruction_failure_rate={result.failure_rate:.2%}")
    if result.exclusions:
        print(f"exclusions={dict(result.exclusions)}")


if __name__ == "__main__":
    _main()
