from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ultrab.backtester.runtime import BacktestRuntime
from ultrab.replayer.data_source import ReplayDataConfig, load_full_ohlc, replay_data_config
from ultrab.replayer.replay_session import DualReplaySession
from ultrab.runtime.dual_smc import DualSmcRuntime


CONFIG_PATH = Path(__file__).resolve().parents[1] / "src" / "ultrab" / "replayer" / "config.yaml"


def _configs() -> tuple[ReplayDataConfig, ReplayDataConfig, str]:
    base = replay_data_config(CONFIG_PATH)
    lower = ReplayDataConfig(base.root, "EURUSD", "15m", base.window_bars)
    higher = ReplayDataConfig(base.root, "EURUSD", "4h", base.window_bars)
    if not lower.parquet_path.exists() or not higher.parquet_path.exists():
        pytest.skip("ULTRA-B dual timeframe historical data is not available")
    lower_bars = load_full_ohlc(lower)
    start_time = lower_bars.index[max(0, len(lower_bars) - 80)].isoformat()
    return lower, higher, start_time


def _context_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "cursor_time": snapshot["cursor_time"],
        "next_time": snapshot["next_time"],
        "lower_structure": snapshot["lower_structure"],
        "higher_structure": snapshot["higher_structure"],
        "projected_structure": snapshot["projected_structure"],
        "liquidity": snapshot.get("liquidity"),
        "structure": snapshot["structure"],
        "zones": snapshot["zones"],
        "lower_last_resolved_zone": snapshot["lower_last_resolved_zone"],
        "higher_last_resolved_zone": snapshot["higher_last_resolved_zone"],
    }


def _hypothesis_projection(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    hypothesis = snapshot.get("hypothesis")
    if not hypothesis:
        return None
    debug = hypothesis.get("debug_facts") or {}
    return {
        "cursor_time": snapshot["cursor_time"],
        "phase": hypothesis.get("phase"),
        "direction": hypothesis.get("direction"),
        "status": hypothesis.get("status"),
        "poi_id": hypothesis.get("poi_id"),
        "entry_policy": hypothesis.get("entry_policy"),
        "target_policy": hypothesis.get("target_policy"),
        "previous_phase": debug.get("previous_phase"),
        "htf_pd_epoch_id": debug.get("htf_pd_epoch_id"),
    }


def test_backtester_runtime_is_the_headless_runtime_alias():
    assert BacktestRuntime is DualSmcRuntime


def test_runtime_environment_uses_shared_replay_config_values():
    lower, higher, start_time = _configs()
    runtime = DualSmcRuntime(
        str(CONFIG_PATH),
        symbol="EURUSD",
        lower_config=lower,
        higher_config=higher,
        combo_name="15m_4h",
        start_time=start_time,
    )

    metadata = runtime.metadata()["runtime_environment"]

    assert metadata["state_mode"] == "live_bootstrap"
    assert metadata["warmup_bars"] == 200
    assert metadata["window_bars"] == lower.window_bars == 500
    assert metadata["hypothesis_state_start_time"] == start_time


def test_dual_replayer_composes_headless_runtime():
    lower, higher, start_time = _configs()
    session = DualReplaySession(
        str(CONFIG_PATH),
        symbol="EURUSD",
        lower_config=lower,
        higher_config=higher,
        combo_name="15m_4h",
        start_time=start_time,
    )

    assert isinstance(session._runtime, DualSmcRuntime)


def test_dual_replayer_and_headless_runtime_context_stay_identical():
    lower, higher, start_time = _configs()
    runtime = DualSmcRuntime(
        str(CONFIG_PATH),
        symbol="EURUSD",
        lower_config=lower,
        higher_config=higher,
        combo_name="15m_4h",
        start_time=start_time,
    )
    session = DualReplaySession(
        str(CONFIG_PATH),
        symbol="EURUSD",
        lower_config=lower,
        higher_config=higher,
        combo_name="15m_4h",
        start_time=start_time,
    )

    for _ in range(40):
        runtime_step = runtime.step()
        replay_step = session.step()

        assert replay_step.cursor_index == runtime_step.cursor_index
        assert replay_step.cursor_time == runtime_step.cursor_time
        assert session.current_higher_index == runtime.current_higher_index

        runtime_snapshot = runtime.snapshot(classify=False)
        replay_snapshot = session.snapshot()
        assert _context_projection(replay_snapshot) == _context_projection(runtime_snapshot)


def test_dual_runtime_snapshot_exposes_liquidity_context_for_backtester_and_replayer():
    lower, higher, start_time = _configs()
    runtime = BacktestRuntime(
        str(CONFIG_PATH),
        symbol="EURUSD",
        lower_config=lower,
        higher_config=higher,
        combo_name="15m_4h",
        start_time=start_time,
    )
    session = DualReplaySession(
        str(CONFIG_PATH),
        symbol="EURUSD",
        lower_config=lower,
        higher_config=higher,
        combo_name="15m_4h",
        start_time=start_time,
    )

    runtime.step()
    session.step()

    runtime_liquidity = runtime.snapshot(classify=False)["liquidity"]
    replay_liquidity = session.snapshot()["liquidity"]

    assert replay_liquidity == runtime_liquidity
    assert "htf_pd_grab_reclaim_ready" in runtime_liquidity
    assert "htf_eq_grab_reclaim_ready" in runtime_liquidity
    assert "active_htf_pd_pools" in runtime_liquidity
    assert "active_htf_eq_pools" in runtime_liquidity


def test_dual_runtime_hypothesis_snapshot_is_idempotent_per_cursor():
    lower, higher, start_time = _configs()
    runtime = DualSmcRuntime(
        str(CONFIG_PATH),
        symbol="EURUSD",
        lower_config=lower,
        higher_config=higher,
        combo_name="15m_4h",
        start_time=start_time,
    )

    runtime.step()
    first = runtime.classify_snapshot()
    second = runtime.classify_snapshot()

    assert _hypothesis_projection(second) == _hypothesis_projection(first)


def test_dual_rewind_rebuilds_stateful_hypothesis_memory():
    lower, higher, start_time = _configs()
    session = DualReplaySession(
        str(CONFIG_PATH),
        symbol="EURUSD",
        lower_config=lower,
        higher_config=higher,
        combo_name="15m_4h",
        start_time=start_time,
    )

    expected_at_target = None
    target_time = None
    for step_index in range(35):
        session.step()
        snapshot = session.snapshot()
        if step_index == 24:
            expected_at_target = _hypothesis_projection(snapshot)
            target_time = snapshot["cursor_time"]

    assert target_time is not None
    assert expected_at_target is not None

    session.rewind_to_time(target_time, step_before=False)
    rewound_snapshot = session.snapshot()

    assert _hypothesis_projection(rewound_snapshot) == expected_at_target
