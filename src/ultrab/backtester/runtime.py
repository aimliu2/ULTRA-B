from __future__ import annotations

"""Backtester-facing imports for the V3 headless runtime.

This module intentionally does not implement a second cursor or engine loop.
Backtests should drive :class:`ultrab.runtime.dual_smc.DualSmcRuntime` directly
so they follow the same heartbeat, Event Layer, Context Layer, Fusion, and
Hypothesis dataflow as the headless replayer backend.
"""

from ultrab.runtime.dual_smc import DualSmcRuntime, RuntimeEmittedEvent, RuntimeStepResult


BacktestRuntime = DualSmcRuntime

__all__ = [
    "BacktestRuntime",
    "DualSmcRuntime",
    "RuntimeEmittedEvent",
    "RuntimeStepResult",
]
