from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from ultrab.replayer.data_source import ReplayDataConfig, load_full_ohlc, replay_data_config
from ultrab.runtime.dual_smc import DualSmcRuntime


CONFIG_PATH = Path(__file__).resolve().parents[1] / "src" / "ultrab" / "replayer" / "config.yaml"


def _configs() -> tuple[ReplayDataConfig, ReplayDataConfig, pd.DataFrame]:
    base = replay_data_config(CONFIG_PATH)
    lower = ReplayDataConfig(base.root, "EURUSD", "15m", base.window_bars)
    higher = ReplayDataConfig(base.root, "EURUSD", "4h", base.window_bars)
    if not lower.parquet_path.exists() or not higher.parquet_path.exists():
        pytest.skip("ULTRA-B dual timeframe historical data is not available")
    return lower, higher, load_full_ohlc(lower)


def _runtime(lower: ReplayDataConfig, higher: ReplayDataConfig, start_time: str, saved: dict[str, Any] | None = None):
    return DualSmcRuntime(
        str(CONFIG_PATH),
        symbol="EURUSD",
        lower_config=lower,
        higher_config=higher,
        combo_name="15m_4h",
        start_time=start_time,
        saved_shadow_state=saved,
    )


def _classify_until(runtime: DualSmcRuntime, target_index: int) -> dict[str, Any]:
    snapshot: dict[str, Any] | None = None
    while runtime.current_lower_index < target_index:
        runtime.step()
        snapshot = runtime.classify_snapshot()
    assert snapshot is not None
    return snapshot


def _first_weekend_gap(lower_bars: pd.DataFrame) -> tuple[int, int]:
    deltas = lower_bars.index.to_series().diff()
    gaps = deltas[deltas > pd.Timedelta(hours=24)]
    if gaps.empty:
        pytest.skip("No weekend-sized market halt gap found in local 15m data")
    target = gaps[gaps.index >= pd.Timestamp("2026-02-02T00:00:00+00:00")]
    resume_time = target.index[0] if not target.empty else gaps.index[0]
    resume_index = int(lower_bars.index.get_loc(resume_time))
    return resume_index - 1, resume_index


def _journal_projection(state: dict[str, Any]) -> dict[str, Any]:
    classifier_state = state["classifier_state"]
    shadow = classifier_state["shadow_thesis"]
    return {
        "previous_phase": classifier_state["previous_phase"],
        "htf_pd_epoch_id": classifier_state["htf_pd_epoch_id"],
        "active_phase_e_direction": classifier_state["active_phase_e_direction"],
        "phase_e_source_orderflow_leg_id": shadow["phase_e"]["source_orderflow_leg_id"],
        "phase_c_origin_node": shadow["phase_c"]["origin_node"],
        "phase_c_entered_at": shadow["phase_c"]["entered_at"],
        "phase_b_commitment_extreme_level": shadow["phase_b"]["commitment_extreme_level"],
        "phase_b_commitment_extreme_event_id": shadow["phase_b"]["commitment_extreme_event_id"],
        "phase_a_entered_at": shadow["phase_a"]["entered_at"],
        "phase_a_pro_extreme_at_weaken": shadow["phase_a"]["pro_extreme_at_weaken"],
    }


def test_weekend_gap_resume_uses_saved_journal_when_epoch_is_unchanged():
    lower, higher, lower_bars = _configs()
    save_index, resume_index = _first_weekend_gap(lower_bars)
    start_index = max(0, save_index - 160)
    save_time = lower_bars.index[save_index].isoformat()
    resume_time = lower_bars.index[resume_index].isoformat()

    before_halt = _runtime(lower, higher, lower_bars.index[start_index].isoformat())
    save_snapshot = _classify_until(before_halt, save_index)
    saved = before_halt.export_shadow_state(saved_at=save_time)
    hypothesis = save_snapshot.get("hypothesis") or {}
    if hypothesis.get("phase") == "X":
        pytest.skip(f"Weekend save point has no active thesis to preserve: {save_time}")

    after_halt = _runtime(lower, higher, resume_time, saved=saved)
    if after_halt.restart_diagnostics.get("restore_reject_reason") == "epoch_mismatch":
        pytest.skip(f"Weekend gap crossed an HTF epoch boundary: {save_time} -> {resume_time}")

    assert after_halt.restart_diagnostics["recovery_mode"] == "resume_saved_journal"
    assert after_halt.restart_diagnostics["restore_reject_reason"] is None
    assert _journal_projection(after_halt.export_shadow_state()) == _journal_projection(saved)

    after_halt.step()
    resumed = after_halt.classify_snapshot()
    assert resumed.get("hypothesis")
    assert resumed["hypothesis_restart"]["recovery_mode"] == "resume_saved_journal"


def test_random_wakeup_2026_02_02_bootstraps_layer4_before_visible_bar():
    lower, higher, lower_bars = _configs()
    target = pd.Timestamp("2026-02-02T00:00:00+00:00")
    if target < lower_bars.index[0] or target > lower_bars.index[-1]:
        pytest.skip("Local data does not include 2026-02-02T00:00:00+00:00")

    runtime = _runtime(lower, higher, target.isoformat())
    diagnostics = runtime.restart_diagnostics

    assert diagnostics["bootstrap_bars_used"] > 0
    assert diagnostics["bootstrap_start_time"] is not None
    assert diagnostics["bootstrap_end_time"] is not None
    assert diagnostics["recovery_mode"] in {"hidden_layer4_bootstrap", "terrain_relocation"}
    if diagnostics["recovery_mode"] == "hidden_layer4_bootstrap":
        assert diagnostics["bootstrap_success"] is True
        state = runtime.export_shadow_state()["classifier_state"]
        assert state["current_hypothesis"]["phase"] in {"A", "B", "C", "D", "E"}
    else:
        assert diagnostics["relocation_attempted"] is True
        assert diagnostics["relocation_selected_node"] is not None


def test_saved_journal_with_missing_b_commitment_anchor_is_rejected_before_bootstrap():
    lower, higher, lower_bars = _configs()
    save_index, resume_index = _first_weekend_gap(lower_bars)
    start_index = max(0, save_index - 160)

    before_halt = _runtime(lower, higher, lower_bars.index[start_index].isoformat())
    _classify_until(before_halt, save_index)
    saved = before_halt.export_shadow_state(saved_at=lower_bars.index[save_index].isoformat())
    saved_state = saved["classifier_state"]
    current = saved_state.get("current_hypothesis") or {}
    if current.get("phase") not in {"A", "B"}:
        pytest.skip("Anchor rejection requires an A/B saved hypothesis")

    saved_state["shadow_thesis"]["phase_b"]["commitment_extreme_level"] = None
    restarted = _runtime(lower, higher, lower_bars.index[resume_index].isoformat(), saved=saved)

    assert restarted.restart_diagnostics["restore_reject_reason"] == "missing_b_commitment_extreme_level"
    assert restarted.restart_diagnostics["recovery_mode"] != "resume_saved_journal"
