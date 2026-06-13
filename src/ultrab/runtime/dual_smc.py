from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from ultrab.core.smc.candleEvent import FvgEventEngine
from ultrab.core.smc.evidence_compiler import EvidenceCompiler
from ultrab.core.smc.hypothesis import HypothesisClassifier
from ultrab.core.smc.liquidity import LiquidityContextEngine
from ultrab.core.smc.orderflow import OrderflowContext
from ultrab.core.smc.pivotEvent import PivotEventEngine
from ultrab.core.smc.sdZone import SDZoneBarResult, SDZoneEngine
from ultrab.core.smc.fusion import Fusion
from ultrab.core.smc.snapshot_normalizer import SnapshotNormalizer
from ultrab.core.smc.structureEngine import StructureEngine
from ultrab.replayer.data_source import (
    ReplayDataConfig,
    load_app_config,
    load_full_ohlc,
    timeframe_label,
)
from ultrab.runtime.environment import RuntimeEnvironment


@dataclass(frozen=True)
class RuntimeEmittedEvent:
    timeframe: str
    event: Any


@dataclass(frozen=True)
class RuntimeStepResult:
    cursor_index: int
    cursor_time: str | None
    done: bool
    new_events: tuple[RuntimeEmittedEvent, ...] = ()


def _serialize_bar(bar_index: int, ts: pd.Timestamp, row: pd.Series) -> dict[str, Any]:
    return {
        "bar_index": int(bar_index),
        "time": ts.isoformat(),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
    }


def _fvg_config(replay_config: dict[str, Any]) -> dict[str, Any]:
    return replay_config.get("marker_config", {}).get("candlestick_events", {})


def _pivot_config(replay_config: dict[str, Any]) -> dict[str, Any]:
    return replay_config.get("marker_config", {}).get("pivot_events", {})


def _sd_zone_config(replay_config: dict[str, Any]) -> dict[str, Any]:
    return replay_config.get("marker_config", {}).get("sd_zones", {})


def _structure_config(replay_config: dict[str, Any]) -> dict[str, Any]:
    return replay_config.get("structure", {})


def _orderflow_config(replay_config: dict[str, Any]) -> dict[str, Any]:
    return replay_config.get("orderflow", {})


def _liquidity_config(app_config: dict[str, Any], replay_config: dict[str, Any]) -> dict[str, Any]:
    return app_config.get("liquidity", replay_config.get("liquidity", {}))


def _structure_dual_display(struct_cfg: dict[str, Any]) -> str:
    display = str(struct_cfg.get("dual_display", "")).strip().lower()
    if display in {"higher", "lower", "both", "projected", "dual"}:
        return display
    return "both" if struct_cfg.get("ltf_enabled", False) else "higher"


class _PartialBar:
    def __init__(self, bar_index: int, timestamp: pd.Timestamp) -> None:
        self.bar_index = bar_index
        self.timestamp = timestamp
        self.open: float | None = None
        self.high: float | None = None
        self.low: float | None = None
        self.close: float | None = None

    def update(self, row: pd.Series) -> None:
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        if self.open is None:
            self.open = float(row["open"])
            self.high = high
            self.low = low
        else:
            self.high = max(float(self.high), high)
            self.low = min(float(self.low), low)
        self.close = close

    def to_dict(self) -> dict[str, Any] | None:
        if self.open is None or self.high is None or self.low is None or self.close is None:
            return None
        return {
            "bar_index": int(self.bar_index),
            "time": self.timestamp.isoformat(),
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
        }


class DualSmcRuntime:
    """
    Headless dual-timeframe SMC runtime.

    This is the reusable backend counterpart to ``DualReplaySession``. It keeps
    the live-style lower-timeframe clock and updates the same FVG, pivot, SD,
    structure, and hypothesis engines, but it does not build browser chart
    payloads or store visible event logs.
    """

    def __init__(
        self,
        config_path: str | Path,
        symbol: str,
        lower_config: ReplayDataConfig,
        higher_config: ReplayDataConfig,
        combo_name: str,
        start_time: str | None = None,
    ) -> None:
        self.session_id = uuid4().hex
        self.config_path = str(config_path)
        self.app_config = load_app_config(config_path)
        self.replay_config = self.app_config.get("replay", {})
        self.symbol = symbol.upper()
        self.combo_name = combo_name
        self.requested_start_time = start_time
        self.lower_config = lower_config
        self.higher_config = higher_config
        self.master_tf = timeframe_label(lower_config.timeframe)
        self.lower_label = timeframe_label(lower_config.timeframe)
        self.higher_label = timeframe_label(higher_config.timeframe)
        self.event_log_enabled = bool(self.replay_config.get("event_log_enabled", True))
        self.warmup_bars = int(self.replay_config.get("warmup_bars", 200))
        self.runtime_environment = RuntimeEnvironment.from_app_config(
            self.app_config,
            warmup_bars=self.warmup_bars,
            window_bars=self.lower_config.window_bars,
        )

        self.lower_bars = load_full_ohlc(lower_config)
        self.higher_bars = load_full_ohlc(higher_config)

        self.lower_end_index = len(self.lower_bars) - 1
        lower_window_start_index = max(0, len(self.lower_bars) - self.lower_config.window_bars)
        self.lower_start_index = self._resolve_index(self.lower_bars, start_time, lower_window_start_index)
        self.higher_start_index = self._resolve_index(
            self.higher_bars,
            self.lower_bars.index[self.lower_start_index].isoformat(),
            0,
        )

        self.lower_candle = None
        self.higher_candle = None
        self.lower_pivot = None
        self.higher_pivot = None
        self.lower_sd_zone = None
        self.higher_sd_zone = None
        self.lower_structure = None
        self.higher_structure = None
        self.lower_orderflow = None
        self.liquidity = None
        self.evidence_compiler: EvidenceCompiler | None = None
        self.hypothesis_classifier: HypothesisClassifier | None = None
        self.current_lower_index = self.lower_start_index - 1
        self.current_higher_index = self.higher_start_index - 1
        self._partial_higher: _PartialBar | None = None
        self._last_lower_ce02_events: list = []
        self._last_hypothesis_lower_index: int | None = None
        self._last_hypothesis_payload: dict[str, Any] | None = None
        self._init_engines()

    def reset(self) -> None:
        self.current_lower_index = self.lower_start_index - 1
        self.current_higher_index = self.higher_start_index - 1
        self.lower_sd_zone = None
        self.higher_sd_zone = None
        self.lower_structure = None
        self.higher_structure = None
        self.lower_orderflow = None
        self.liquidity = None
        self.evidence_compiler = None
        self._partial_higher = None
        self._last_lower_ce02_events = []
        self._last_hypothesis_lower_index = None
        self._last_hypothesis_payload = None
        self._init_engines()

    def step(self) -> RuntimeStepResult:
        if self.current_lower_index >= self.lower_end_index:
            return RuntimeStepResult(
                cursor_index=self.current_lower_index,
                cursor_time=self.current_time_iso(),
                done=True,
            )

        self.current_lower_index += 1
        lower_row = self.lower_bars.iloc[self.current_lower_index]
        new_events = self._process_lower_step(lower_row)
        return RuntimeStepResult(
            cursor_index=self.current_lower_index,
            cursor_time=lower_row.name.isoformat(),
            done=self.current_lower_index >= self.lower_end_index,
            new_events=tuple(new_events),
        )

    def classify_snapshot(self) -> dict[str, Any]:
        payload = self.snapshot(classify=False)
        hypothesis = self._hypothesis_for_payload(payload)
        if hypothesis is not None:
            payload["hypothesis"] = hypothesis
        return payload

    def snapshot(self, classify: bool = True) -> dict[str, Any]:
        lower_price = self._current_lower_price()
        higher_price = self._current_higher_price()
        lower_zones = self.lower_sd_zone.get_zone_snapshot(lower_price) if self.lower_sd_zone else []
        higher_zones = self.higher_sd_zone.get_zone_snapshot(higher_price) if self.higher_sd_zone else []
        lower_last_resolved_zone = self.lower_sd_zone.get_last_resolved_zone_snapshot() if self.lower_sd_zone else None
        higher_last_resolved_zone = self.higher_sd_zone.get_last_resolved_zone_snapshot() if self.higher_sd_zone else None
        lower_structure = self.lower_structure.get_snapshot(lower_price) if self.lower_structure else None
        higher_structure = self.higher_structure.get_snapshot(higher_price) if self.higher_structure else None
        lower_orderflow = (
            self.lower_orderflow.snapshot(lower_structure, evaluated_at=self.current_time_iso())
            if self.lower_orderflow
            else {}
        )
        orderflow = lower_orderflow
        liquidity = self.liquidity.snapshot() if self.liquidity else {}
        structure_display = _structure_dual_display(_structure_config(self.replay_config))
        projected_structure = higher_structure if structure_display in {"projected", "dual"} else None
        primary_structure = higher_structure if higher_structure is not None else lower_structure
        lower_bars = self._lower_bars_for_classifier()
        payload = {
            "session_id": self.session_id,
            "mode": "dual",
            "symbol": self.symbol,
            "combo": self.combo_name,
            "master_tf": self.master_tf,
            "lower_tf": self.lower_label,
            "higher_tf": self.higher_label,
            "timeframe": self.lower_label,
            "cursor_time": self.current_time_iso(),
            "next_time": self.next_time_iso(),
            "bar_count": len(lower_bars),
            "bars": lower_bars,
            "lower_bars": lower_bars,
            "higher_bars": self._higher_bars_for_classifier(),
            "events": [],
            "runtime_environment": self.runtime_environment_metadata(),
            "zones": lower_zones + higher_zones,
            "lower_last_resolved_zone": lower_last_resolved_zone,
            "higher_last_resolved_zone": higher_last_resolved_zone,
            "lower_structure": lower_structure,
            "higher_structure": higher_structure,
            "projected_structure": projected_structure,
            "liquidity": liquidity,
            "orderflow": orderflow,
            "lower_orderflow": lower_orderflow,
            "structure": primary_structure,
            "done": self.current_lower_index >= self.lower_end_index,
        }
        current_bar_index = self.current_lower_index if self.current_lower_index >= self.lower_start_index else None
        lower_context_snapshot = SnapshotNormalizer.project(
            cursor={
                "currentTimestamp": self.current_time_iso(),
                "currentPrice": lower_price,
                "currentBarIndex": current_bar_index,
                "timeframe": self.lower_label,
                "mode": "single",
                "symbol": self.symbol,
            },
            structure=lower_structure,
            zones=[z for z in payload["zones"] if z.get("timeframe") == self.lower_label],
            liquidity=liquidity,
            orderflow=lower_orderflow,
            last_resolved_zone=lower_last_resolved_zone,
        )
        higher_context_snapshot = SnapshotNormalizer.project(
            cursor={
                "currentTimestamp": self.current_time_iso(),
                "currentPrice": higher_price,
                "currentBarIndex": self.current_higher_index if self.current_higher_index >= self.higher_start_index else None,
                "timeframe": self.higher_label,
                "mode": "single",
                "symbol": self.symbol,
            },
            structure=higher_structure,
            zones=[z for z in payload["zones"] if z.get("timeframe") == self.higher_label],
            liquidity=liquidity,
            orderflow={},
            last_resolved_zone=higher_last_resolved_zone,
        )
        payload["context_snapshot"] = Fusion.fuse_dual(
            lower_context_snapshot,
            higher_context_snapshot,
            execution_tf=self.lower_label,
            reference_tf=self.higher_label,
            symbol=self.symbol,
        )
        if self.evidence_compiler is not None:
            candidates = self.evidence_compiler.update(
                payload["context_snapshot"],
                higher_bars=payload.get("higher_bars"),
            )
            payload["evidence_candidates"] = [c.to_dict() for c in candidates]
            payload["evidence_compiler_epoch_id"] = self.evidence_compiler.htf_pd_epoch_id
        if classify and self.hypothesis_classifier is not None:
            hypothesis = self._hypothesis_for_payload(payload)
            if hypothesis is not None:
                payload["hypothesis"] = hypothesis
        return payload

    def _hypothesis_for_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self.hypothesis_classifier is None:
            return None
        if self.current_lower_index < self.lower_start_index:
            return None
        if (
            self._last_hypothesis_lower_index != self.current_lower_index
            or self._last_hypothesis_payload is None
        ):
            self._last_hypothesis_payload = self.hypothesis_classifier.classify(payload).to_dict()
            self._last_hypothesis_lower_index = self.current_lower_index
        return self._last_hypothesis_payload

    def metadata(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "mode": "dual",
            "symbol": self.symbol,
            "combo": self.combo_name,
            "master_tf": self.master_tf,
            "lower_tf": self.lower_label,
            "higher_tf": self.higher_label,
            "data_start_time": self.lower_bars.index[0].isoformat(),
            "data_end_time": self.lower_bars.index[-1].isoformat(),
            "default_start_time": self.lower_bars.index[self.lower_start_index].isoformat(),
            "warmup_bars": self.warmup_bars,
            "runtime_environment": self.runtime_environment_metadata(),
        }

    def runtime_environment_metadata(self) -> dict[str, Any]:
        lower_warmup_start = max(0, self.lower_start_index - self.warmup_bars)
        higher_warmup_start = max(0, self.higher_start_index - self.warmup_bars)
        metadata = self.runtime_environment.to_dict()
        metadata.update(
            {
                "requested_start_time": self.requested_start_time,
                "hypothesis_state_start_time": self.lower_bars.index[self.lower_start_index].isoformat(),
                "lower_engine_warmup_start_time": self.lower_bars.index[lower_warmup_start].isoformat(),
                "higher_engine_warmup_start_time": self.higher_bars.index[higher_warmup_start].isoformat(),
            }
        )
        return metadata

    def current_time_iso(self) -> str | None:
        if self.current_lower_index < self.lower_start_index:
            return None
        return self.lower_bars.index[self.current_lower_index].isoformat()

    def next_time_iso(self) -> str | None:
        next_index = self.current_lower_index + 1
        if next_index > self.lower_end_index:
            return None
        return self.lower_bars.index[next_index].isoformat()

    def rebuild_to_lower_index(self, target_index: int) -> None:
        bounded_index = min(target_index, self.lower_end_index)
        self.reset()
        if bounded_index < self.lower_start_index:
            self.current_lower_index = self.lower_start_index - 1
            return

        while self.current_lower_index < bounded_index:
            self.step()

    def rewind_to_time(self, target_time: str, step_before: bool = True) -> None:
        target_index = self._resolve_index(self.lower_bars, target_time, self.lower_start_index)
        if step_before:
            target_index -= 1
        self.rebuild_to_lower_index(target_index)

    def _resolve_index(
        self,
        bars: pd.DataFrame,
        target_time: str | None,
        default_index: int,
    ) -> int:
        if not target_time:
            return default_index
        target_ts = pd.Timestamp(target_time)
        if target_ts.tzinfo is None:
            target_ts = target_ts.tz_localize("UTC")
        else:
            target_ts = target_ts.tz_convert("UTC")
        idx = int(bars.index.searchsorted(target_ts, side="left"))
        idx = max(0, idx)
        idx = min(idx, len(bars) - 1)
        return idx

    def _init_engines(self) -> None:
        self.lower_candle = None
        self.higher_candle = None
        self.lower_pivot = None
        self.higher_pivot = None
        self.lower_sd_zone = None
        self.higher_sd_zone = None
        self.lower_structure = None
        self.higher_structure = None
        self.lower_orderflow = OrderflowContext(_orderflow_config(self.replay_config), timeframe=self.lower_label)
        self.liquidity = None
        self.evidence_compiler = EvidenceCompiler()
        self.hypothesis_classifier = HypothesisClassifier(self.replay_config.get("hypothesis", {}))
        if not self.event_log_enabled:
            return

        fvg_cfg = _fvg_config(self.replay_config)
        if fvg_cfg.get("enabled", False):
            self.lower_candle = FvgEventEngine({**fvg_cfg, "timeframe": self.lower_label})
            self.higher_candle = FvgEventEngine({**fvg_cfg, "timeframe": self.higher_label})

        pivot_cfg = _pivot_config(self.replay_config)
        if pivot_cfg.get("enabled", False):
            self.lower_pivot = PivotEventEngine({**pivot_cfg, "timeframe": self.lower_label})
            self.higher_pivot = PivotEventEngine({**pivot_cfg, "timeframe": self.higher_label})

        sd_cfg = _sd_zone_config(self.replay_config)
        if sd_cfg.get("enabled", False):
            self.lower_sd_zone = SDZoneEngine(sd_cfg, self.lower_label)
            self.higher_sd_zone = SDZoneEngine(sd_cfg, self.higher_label)

        struct_cfg = _structure_config(self.replay_config)
        if struct_cfg.get("enabled", False):
            display = _structure_dual_display(struct_cfg)
            if display in {"higher", "both", "projected", "dual"}:
                self.higher_structure = StructureEngine(struct_cfg, self.higher_label)
            if display in {"lower", "both", "dual"}:
                self.lower_structure = StructureEngine(struct_cfg, self.lower_label)

        liquidity_cfg = _liquidity_config(self.app_config, self.replay_config)
        if liquidity_cfg.get("enabled", True):
            self.liquidity = LiquidityContextEngine(liquidity_cfg, self.lower_label, self.higher_label)

        self._warm_lower_engines()
        self._warm_higher_engines()
        self._warm_liquidity_lower_interactions()
        self._seed_partial_higher()

    def _warm_lower_engines(self) -> None:
        lower_warmup_start = max(0, self.lower_start_index - self.warmup_bars)
        for _, row in self.lower_bars.iloc[lower_warmup_start : self.lower_start_index].iterrows():
            self._process_lower_engines(row)

    def _warm_higher_engines(self) -> None:
        higher_warmup_start = max(0, self.higher_start_index - self.warmup_bars)
        for _, row in self.higher_bars.iloc[higher_warmup_start : self.higher_start_index].iterrows():
            self._process_higher_engines(row)
        self.current_higher_index = self.higher_start_index - 1

    def _warm_liquidity_lower_interactions(self) -> None:
        if self.liquidity is None:
            return
        lower_warmup_start = max(0, self.lower_start_index - self.warmup_bars)
        for idx in range(lower_warmup_start, self.lower_start_index):
            row = self.lower_bars.iloc[idx]
            self.liquidity.on_lower_bar(row, ce02_events=[], lower_index=idx)

    def _seed_partial_higher(self) -> None:
        if self.lower_start_index <= 0:
            return
        next_higher_index = self.current_higher_index + 1
        if next_higher_index >= len(self.higher_bars):
            return
        last_closed_ts = self.higher_bars.index[self.current_higher_index] if self.current_higher_index >= 0 else None
        next_higher_ts = self.higher_bars.index[next_higher_index]
        partial = _PartialBar(next_higher_index, next_higher_ts)
        seed_start = 0
        if last_closed_ts is not None:
            seed_start = int(self.lower_bars.index.searchsorted(last_closed_ts, side="right"))
        seed_end = min(
            self.lower_start_index,
            int(self.lower_bars.index.searchsorted(next_higher_ts, side="left")),
        )
        for _, row in self.lower_bars.iloc[seed_start:seed_end].iterrows():
            partial.update(row)
        self._partial_higher = partial if partial.to_dict() is not None else None

    def _process_lower_step(self, lower_row: pd.Series) -> list[RuntimeEmittedEvent]:
        emitted = self._process_lower_engines(lower_row)
        emitted.extend(self._advance_higher_to(lower_row.name))
        self._update_partial_higher(lower_row)
        if self.liquidity is not None:
            self.liquidity.on_lower_bar(
                lower_row,
                ce02_events=self._last_lower_ce02_events,
                lower_index=self.current_lower_index,
            )
        emitted.sort(
            key=lambda item: (
                getattr(item.event, "event_timestamp").isoformat(),
                0 if item.timeframe == self.higher_label else 1,
                getattr(item.event, "event_code", ""),
            )
        )
        return emitted

    def _process_lower_engines(self, row: pd.Series) -> list[RuntimeEmittedEvent]:
        emitted: list[RuntimeEmittedEvent] = []
        ce02: list = []
        pivot_events: list = []
        if self.lower_candle is not None:
            events = self.lower_candle.on_bar(row)
            ce02 = [event for event in events if event.event_code == "CE02"]
            emitted.extend(RuntimeEmittedEvent(self.lower_label, event) for event in events)
        self._last_lower_ce02_events = ce02
        if self.lower_pivot is not None:
            pivot_events = self.lower_pivot.on_bar(row)
            emitted.extend(RuntimeEmittedEvent(self.lower_label, event) for event in pivot_events)
        bar_result = SDZoneBarResult(created=[], mitigated=[])
        if self.lower_sd_zone is not None:
            bar_result = self.lower_sd_zone.on_bar(row, ce02)
        if self.lower_structure is not None:
            self.lower_structure.on_bar(row, pivot_events, ce02, bar_result)
        return emitted

    def _process_higher_engines(self, row: pd.Series) -> list[RuntimeEmittedEvent]:
        emitted: list[RuntimeEmittedEvent] = []
        ce02: list = []
        pivot_events: list = []
        if self.higher_candle is not None:
            events = self.higher_candle.on_bar(row)
            ce02 = [event for event in events if event.event_code == "CE02"]
            emitted.extend(RuntimeEmittedEvent(self.higher_label, event) for event in events)
        if self.higher_pivot is not None:
            pivot_events = self.higher_pivot.on_bar(row)
            emitted.extend(RuntimeEmittedEvent(self.higher_label, event) for event in pivot_events)
        bar_result = SDZoneBarResult(created=[], mitigated=[])
        if self.higher_sd_zone is not None:
            bar_result = self.higher_sd_zone.on_bar(row, ce02)
        if self.higher_structure is not None:
            self.higher_structure.on_bar(row, pivot_events, ce02, bar_result)
        if self.liquidity is not None:
            higher_price = float(row["close"])
            higher_structure = (
                self.higher_structure.get_snapshot(higher_price)
                if self.higher_structure is not None
                else None
            )
            self.liquidity.on_higher_bar(row, pivot_events, higher_structure)
        return emitted

    def _advance_higher_to(self, lower_close_ts: pd.Timestamp) -> list[RuntimeEmittedEvent]:
        emitted: list[RuntimeEmittedEvent] = []
        advanced = False
        while (
            self.current_higher_index + 1 < len(self.higher_bars)
            and self.higher_bars.index[self.current_higher_index + 1] <= lower_close_ts
        ):
            self.current_higher_index += 1
            higher_row = self.higher_bars.iloc[self.current_higher_index]
            emitted.extend(self._process_higher_engines(higher_row))
            advanced = True
        if advanced:
            self._partial_higher = None
        return emitted

    def _update_partial_higher(self, lower_row: pd.Series) -> None:
        next_higher_index = self.current_higher_index + 1
        if next_higher_index >= len(self.higher_bars):
            self._partial_higher = None
            return
        next_higher_ts = self.higher_bars.index[next_higher_index]
        lower_ts = lower_row.name
        if lower_ts >= next_higher_ts:
            self._partial_higher = None
            return
        if self.current_higher_index >= 0 and lower_ts <= self.higher_bars.index[self.current_higher_index]:
            return
        if self._partial_higher is None or self._partial_higher.bar_index != next_higher_index:
            self._partial_higher = _PartialBar(next_higher_index, next_higher_ts)
        self._partial_higher.update(lower_row)

    def _current_lower_price(self) -> float:
        if self.current_lower_index < 0:
            return 0.0
        return float(self.lower_bars.iloc[self.current_lower_index]["close"])

    def _current_higher_price(self) -> float:
        if self.current_higher_index < 0:
            return 0.0
        return float(self.higher_bars.iloc[self.current_higher_index]["close"])

    def _lower_bars_for_classifier(self) -> list[dict[str, Any]]:
        if self.current_lower_index < self.lower_start_index:
            return []
        row = self.lower_bars.iloc[self.current_lower_index]
        return [_serialize_bar(self.current_lower_index, row.name, row)]

    def _higher_bars_for_classifier(self) -> list[dict[str, Any]]:
        bars: list[dict[str, Any]] = []
        partial = self._partial_higher.to_dict() if self._partial_higher else None
        if partial:
            if self.current_higher_index >= 0:
                row = self.higher_bars.iloc[self.current_higher_index]
                bars.append(_serialize_bar(self.current_higher_index, row.name, row))
            bars.append(partial)
            return bars

        start = max(0, self.current_higher_index - 1)
        for idx in range(start, self.current_higher_index + 1):
            if idx < 0:
                continue
            row = self.higher_bars.iloc[idx]
            bars.append(_serialize_bar(idx, row.name, row))
        return bars
