from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pandas as pd

from ultrab.replayer.data_source import (
    ReplayDataConfig,
    load_app_config,
    load_full_ohlc,
    timeframe_label,
)
from ultrab.core.smc.candleEvent import FvgEventEngine
from ultrab.core.smc.hypothesis import HypothesisClassifier
from ultrab.core.smc.pivotEvent import PivotEventEngine
from ultrab.core.smc.sdZone import SDZoneBarResult, SDZoneEngine
from ultrab.core.smc.structureEngine import StructureEngine


@dataclass
class ReplayStepResult:
    cursor_index: int
    cursor_time: str | None
    revealed_bar: dict[str, Any] | None
    new_events: list[dict[str, Any]]
    done: bool


def _serialize_bar(bar_index: int, ts: pd.Timestamp, row: pd.Series) -> dict[str, Any]:
    return {
        "bar_index": int(bar_index),
        "time": ts.isoformat(),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
    }


def _serialize_event(
    event: Any,
    timeframe: str,
    display_event_log: bool = True,
    display_chart_markers: bool = True,
) -> dict[str, Any]:
    side = "high" if int(event.pivot_side) == 1 else "low"
    event_name = str(event.event_name)
    event_type = "bos" if event_name.endswith("Bos") else "confirmed"
    payload = {
        "tf": timeframe,
        "tier": event.tier,
        "event_code": event.event_code,
        "event_group": getattr(event, "event_group", "PE"),
        "side": side,
        "event_type": event_type,
        "bar_event": event_name,
        "event_name": event_name,
        "decision_ts": event.event_timestamp.isoformat(),
        "anchor_ts": event.pivot_timestamp.isoformat(),
        "price": float(event.pivot_price),
        "display_event_log": display_event_log,
        "display_chart_markers": display_chart_markers,
    }
    if getattr(event, "level_timestamp", None) is not None:
        payload["level_ts"] = event.level_timestamp.isoformat()
    if getattr(event, "level_price", None) is not None:
        payload["level_price"] = float(event.level_price)
    if getattr(event, "level_side", None) is not None:
        payload["level_side"] = "high" if int(event.level_side) == 1 else "low"
    if getattr(event, "mode", None) is not None:
        payload["mode"] = event.mode
    if getattr(event, "survival_bars", None) is not None:
        payload["survival_bars"] = int(event.survival_bars)
    if getattr(event, "source_tier", None) is not None:
        payload["source_tier"] = event.source_tier
    if getattr(event, "source_event_code", None) is not None:
        payload["source_event_code"] = event.source_event_code
    if getattr(event, "previous_same_side_timestamp", None) is not None:
        payload["previous_same_side_ts"] = event.previous_same_side_timestamp.isoformat()
    if getattr(event, "previous_same_side_price", None) is not None:
        payload["previous_same_side_price"] = float(event.previous_same_side_price)
    if getattr(event, "confirmation_timestamp", None) is not None:
        payload["confirmation_ts"] = event.confirmation_timestamp.isoformat()
    if getattr(event, "confirmation_event_timestamp", None) is not None:
        payload["confirmation_event_ts"] = event.confirmation_event_timestamp.isoformat()
    if getattr(event, "confirmation_price", None) is not None:
        payload["confirmation_price"] = float(event.confirmation_price)
    if getattr(event, "relation", None) is not None:
        payload["relation"] = event.relation
    return payload


def _serialize_fvg_event(
    event: Any,
    timeframe: str,
    display_event_log: bool,
    display_chart_markers: bool,
) -> dict[str, Any]:
    side = "high" if event.fvg_type == "rally" else "low"
    payload: dict[str, Any] = {
        "tf": timeframe,
        "tier": "ce",
        "event_code": event.event_code,
        "event_group": event.event_group,
        "event_type": "fvg",
        "bar_event": event.event_name,
        "event_name": event.event_name,
        "decision_ts": event.event_timestamp.isoformat(),
        "anchor_ts": event.bar2_timestamp.isoformat(),
        "fvg_type": event.fvg_type,
        "side": side,
        "bar1_high": float(event.bar1_high),
        "bar1_low": float(event.bar1_low),
        "display_event_log": display_event_log,
        "display_chart_markers": display_chart_markers,
    }
    if event.event_code == "CE01":
        payload["price"] = float(event.bar2_close)
        payload["bar2_close"] = float(event.bar2_close)
        payload["bar2_open"] = float(event.bar2_open)
        payload["sub_type"] = event.sub_type
    else:
        # CE02 — price is the near edge of the gap (where price would fill first)
        payload["price"] = float(event.gap_bottom) if event.fvg_type == "rally" else float(event.gap_top)
        payload["gap_top"] = float(event.gap_top)
        payload["gap_bottom"] = float(event.gap_bottom)
        payload["gap_size"] = float(event.gap_size)
    return payload


def _fvg_display_enabled(replay_config: dict[str, Any], target: str) -> bool:
    fvg_cfg = replay_config.get("marker_config", {}).get("candlestick_events", {})
    display_cfg = fvg_cfg.get("display", {})
    return bool(fvg_cfg.get("enabled", False) and display_cfg.get(target, False))


def _fvg_config(replay_config: dict[str, Any]) -> dict[str, Any]:
    return replay_config.get("marker_config", {}).get("candlestick_events", {})


def _pivot_display_enabled(replay_config: dict[str, Any], target: str) -> bool:
    pivot_cfg = replay_config.get("marker_config", {}).get("pivot_events", {})
    display_cfg = pivot_cfg.get("display", {})
    target_cfg = display_cfg.get(target, {})
    if isinstance(target_cfg, dict):
        return bool(pivot_cfg.get("enabled", False) and any(target_cfg.values()))
    return bool(pivot_cfg.get("enabled", False) and target_cfg)


def _pivot_tier_display_enabled(replay_config: dict[str, Any], tier: str, target: str) -> bool:
    pivot_cfg = replay_config.get("marker_config", {}).get("pivot_events", {})
    display_cfg = pivot_cfg.get("display", {})
    target_cfg = display_cfg.get(target, {})
    if isinstance(target_cfg, dict):
        return bool(pivot_cfg.get("enabled", False) and target_cfg.get(tier, False))
    return bool(pivot_cfg.get("enabled", False) and target_cfg)


def _pivot_config(replay_config: dict[str, Any]) -> dict[str, Any]:
    return replay_config.get("marker_config", {}).get("pivot_events", {})


def _sd_zone_config(replay_config: dict[str, Any]) -> dict[str, Any]:
    return replay_config.get("marker_config", {}).get("sd_zones", {})


def _structure_config(replay_config: dict[str, Any]) -> dict[str, Any]:
    return replay_config.get("structure", {})


def _hypothesis_config(replay_config: dict[str, Any]) -> dict[str, Any]:
    return replay_config.get("hypothesis", {})


def _structure_dual_display(struct_cfg: dict[str, Any]) -> str:
    display = str(struct_cfg.get("dual_display", "")).strip().lower()
    if display in {"higher", "lower", "both", "projected", "dual"}:
        return display
    return "both" if struct_cfg.get("ltf_enabled", False) else "higher"


class ReplaySession:
    def __init__(
        self,
        config_path: str,
        data_config: ReplayDataConfig,
        start_time: str | None = None,
    ) -> None:
        self.session_id = uuid4().hex
        self.config_path = config_path
        self.app_config = load_app_config(config_path)
        self.data_config = data_config
        self.full_bars = load_full_ohlc(data_config)

        self.replay_config = self.app_config.get("replay", {})
        self.window_bars = int(self.data_config.window_bars)
        self.event_log_enabled = bool(self.replay_config.get("event_log_enabled", True))
        self.warmup_bars = int(self.replay_config.get("warmup_bars", 200))

        self.window_start_index = self._default_window_start_index()
        self.end_index = len(self.full_bars) - 1
        self.start_index = self._resolve_start_index(start_time)

        self._candle = None
        self._pivot = None
        self._sd_zone = None
        self._structure = None
        self._hypothesis_classifier = None
        self._show_fvg_events = _fvg_display_enabled(self.replay_config, "event_log")
        self._show_fvg_markers = _fvg_display_enabled(self.replay_config, "chart_markers")
        self._show_pivot_events = _pivot_display_enabled(self.replay_config, "event_log")
        self._show_pivot_markers = _pivot_display_enabled(self.replay_config, "chart_markers")
        self.current_index = self.start_index - 1
        self.visible_events: list[dict[str, Any]] = []
        self._init_engine()

    def reset(self) -> None:
        self.current_index = self.start_index - 1
        self.visible_events = []
        self._sd_zone = None
        self._structure = None
        self._init_engine()

    def rewind_one(self) -> None:
        if self.current_index < self.start_index:
            return
        self._rebuild_to_index(self.current_index - 1)

    def rewind_to_time(self, target_time: str, step_before: bool = True) -> None:
        target_index = self._resolve_start_index(target_time)
        if step_before:
            target_index -= 1
        self._rebuild_to_index(target_index)

    def step(self) -> ReplayStepResult:
        if self.current_index >= self.end_index:
            return ReplayStepResult(
                cursor_index=self.current_index,
                cursor_time=self.current_time_iso(),
                revealed_bar=None,
                new_events=[],
                done=True,
            )

        self.current_index += 1
        row = self.full_bars.iloc[self.current_index]
        new_events = self._process_row(row)
        revealed_bar = _serialize_bar(self.current_index, row.name, row)

        return ReplayStepResult(
            cursor_index=self.current_index,
            cursor_time=row.name.isoformat(),
            revealed_bar=revealed_bar,
            new_events=new_events,
            done=self.current_index >= self.end_index,
        )

    def snapshot(self) -> dict[str, Any]:
        visible = self.visible_bars_payload()
        current_price = self._current_price()
        zones = self._sd_zone.get_zone_snapshot(current_price) if self._sd_zone else []
        last_resolved_zone = self._sd_zone.get_last_resolved_zone_snapshot() if self._sd_zone else None
        structure = self._structure.get_snapshot(current_price) if self._structure else None
        payload = {
            "session_id": self.session_id,
            "symbol": self.data_config.symbol,
            "timeframe": self.data_config.timeframe.upper(),
            "start_time": self.full_bars.index[self.start_index].isoformat(),
            "cursor_time": self.current_time_iso(),
            "next_time": self.next_time_iso(),
            "bar_count": len(visible),
            "bars": visible,
            "events": self.visible_events,
            "zones": zones,
            "last_resolved_zone": last_resolved_zone,
            "structure": structure,
            "done": self.current_index >= self.end_index,
        }
        if self._hypothesis_classifier is not None:
            payload["hypothesis"] = self._hypothesis_classifier.classify(payload).to_dict()
        return payload

    def metadata(self) -> dict[str, Any]:
        window = self.full_bars.iloc[self.window_start_index : self.end_index + 1]
        return {
            "session_id": self.session_id,
            "symbol": self.data_config.symbol,
            "timeframe": self.data_config.timeframe.upper(),
            "data_start_time": self.full_bars.index[0].isoformat(),
            "data_end_time": self.full_bars.index[-1].isoformat(),
            "window_start_time": window.index[0].isoformat(),
            "window_end_time": window.index[-1].isoformat(),
            "default_start_time": self.full_bars.index[self.start_index].isoformat(),
            "window_bars": self.window_bars,
            "warmup_bars": self.warmup_bars,
        }

    def visible_bars_payload(self) -> list[dict[str, Any]]:
        visible_end = self._visible_end_index()
        if visible_end < 0:
            return []

        visible_start = max(0, visible_end - self.window_bars + 1)
        visible = self.full_bars.iloc[visible_start : visible_end + 1]
        return [
            _serialize_bar(idx, ts, row)
            for idx, (ts, row) in zip(range(visible_start, visible_end + 1), visible.iterrows())
        ]

    def current_time_iso(self) -> str | None:
        if self.current_index < self.start_index:
            return None
        return self.full_bars.index[self.current_index].isoformat()

    def next_time_iso(self) -> str | None:
        next_index = self.current_index + 1
        if next_index > self.end_index:
            return None
        return self.full_bars.index[next_index].isoformat()

    def _current_price(self) -> float:
        idx = self._visible_end_index()
        if idx < 0 or idx >= len(self.full_bars):
            return 0.0
        return float(self.full_bars.iloc[idx]["close"])

    def _default_window_start_index(self) -> int:
        return max(0, len(self.full_bars) - self.window_bars)

    def _rebuild_to_index(self, target_index: int) -> None:
        bounded_index = min(target_index, self.end_index)
        self.reset()
        if bounded_index < self.start_index:
            self.current_index = self.start_index - 1
            return

        for idx in range(self.start_index, bounded_index + 1):
            row = self.full_bars.iloc[idx]
            self.current_index = idx
            self._process_row(row)

    def _resolve_start_index(self, start_time: str | None) -> int:
        if not start_time:
            return self.window_start_index

        start_ts = pd.Timestamp(start_time)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize("UTC")
        else:
            start_ts = start_ts.tz_convert("UTC")

        idx = int(self.full_bars.index.searchsorted(start_ts, side="left"))
        idx = max(0, idx)
        idx = min(idx, self.end_index)
        return idx

    def _visible_start_index(self) -> int:
        visible_end = self._visible_end_index()
        return max(0, visible_end - self.window_bars + 1)

    def _visible_end_index(self) -> int:
        """
        Render a historical window even before the replay cursor reaches the start bar.

        This keeps the chart populated when the user jumps to a historical cursor time,
        while the first visible replay step still reveals the chosen start bar.
        """
        if self.current_index >= self.start_index:
            return self.current_index
        return self.start_index - 1

    def _init_engine(self) -> None:
        self._candle = None
        self._pivot = None
        self._sd_zone = None
        self._structure = None
        self._hypothesis_classifier = HypothesisClassifier(_hypothesis_config(self.replay_config))
        if not self.event_log_enabled:
            return

        fvg_cfg = _fvg_config(self.replay_config)
        if fvg_cfg.get("enabled", False):
            self._candle = FvgEventEngine(fvg_cfg)

        pivot_cfg = _pivot_config(self.replay_config)
        if pivot_cfg.get("enabled", False):
            self._pivot = PivotEventEngine(pivot_cfg)

        sd_cfg = _sd_zone_config(self.replay_config)
        if sd_cfg.get("enabled", False):
            self._sd_zone = SDZoneEngine(sd_cfg, timeframe_label(self.data_config.timeframe))

        struct_cfg = _structure_config(self.replay_config)
        tf = timeframe_label(self.data_config.timeframe).lower()
        if struct_cfg.get("enabled", False):
            self._structure = StructureEngine(struct_cfg, tf)

        warmup_start = max(0, self.start_index - self.warmup_bars)
        warmup = self.full_bars.iloc[warmup_start : self.start_index]
        for _, row in warmup.iterrows():
            ce02: list = []
            pivot_events: list = []
            if self._candle is not None:
                events = self._candle.on_bar(row)
                ce02 = [e for e in events if e.event_code == "CE02"]
            if self._pivot is not None:
                pivot_events = self._pivot.on_bar(row)
            bar_result = SDZoneBarResult(created=[], mitigated=[])
            if self._sd_zone is not None:
                bar_result = self._sd_zone.on_bar(row, ce02)
            if self._structure is not None:
                self._structure.on_bar(row, pivot_events, ce02, bar_result)

    def _process_row(self, row: pd.Series) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        ce02: list = []
        pivot_events: list = []

        if self._candle is not None:
            candle_events = self._candle.on_bar(row)
            ce02 = [e for e in candle_events if e.event_code == "CE02"]
            if self._show_fvg_events or self._show_fvg_markers:
                normalized.extend(
                    _serialize_fvg_event(
                        event,
                        timeframe_label(self.data_config.timeframe),
                        self._show_fvg_events,
                        self._show_fvg_markers,
                    )
                    for event in candle_events
                )

        if self._pivot is not None:
            pivot_events = self._pivot.on_bar(row)
            if self._show_pivot_events or self._show_pivot_markers:
                normalized.extend(
                    _serialize_event(
                        event,
                        timeframe_label(self.data_config.timeframe),
                        _pivot_tier_display_enabled(self.replay_config, event.tier, "event_log"),
                        _pivot_tier_display_enabled(self.replay_config, event.tier, "chart_markers"),
                    )
                    for event in pivot_events
                )

        bar_result = SDZoneBarResult(created=[], mitigated=[])
        if self._sd_zone is not None:
            bar_result = self._sd_zone.on_bar(row, ce02)

        if self._structure is not None:
            self._structure.on_bar(row, pivot_events, ce02, bar_result)

        self.visible_events.extend(normalized)
        return normalized


class DualReplaySession:
    def __init__(
        self,
        config_path: str,
        symbol: str,
        lower_config: ReplayDataConfig,
        higher_config: ReplayDataConfig,
        combo_name: str,
        start_time: str | None = None,
    ) -> None:
        self.session_id = uuid4().hex
        self.config_path = config_path
        self.app_config = load_app_config(config_path)
        self.replay_config = self.app_config.get("replay", {})
        self.symbol = symbol.upper()
        self.combo_name = combo_name
        self.lower_config = lower_config
        self.higher_config = higher_config
        self.master_tf = timeframe_label(lower_config.timeframe)
        self.lower_label = timeframe_label(lower_config.timeframe)
        self.higher_label = timeframe_label(higher_config.timeframe)
        self.window_bars = int(lower_config.window_bars)
        self.event_log_enabled = bool(self.replay_config.get("event_log_enabled", True))
        self.warmup_bars = int(self.replay_config.get("warmup_bars", 200))

        self.lower_bars = load_full_ohlc(lower_config)
        self.higher_bars = load_full_ohlc(higher_config)
        self.lower_delta = pd.Timedelta(lower_config.bar_duration)
        self.higher_delta = pd.Timedelta(higher_config.bar_duration)

        self.lower_window_start_index = max(0, len(self.lower_bars) - self.window_bars)
        self.lower_end_index = len(self.lower_bars) - 1
        self.lower_start_index = self._resolve_index(self.lower_bars, start_time, self.lower_window_start_index)
        self.higher_start_index = self._resolve_index(self.higher_bars, self.lower_bars.index[self.lower_start_index].isoformat(), 0)

        self.lower_candle = None
        self.higher_candle = None
        self.lower_pivot = None
        self.higher_pivot = None
        self.lower_sd_zone = None
        self.higher_sd_zone = None
        self.hypothesis_classifier = None
        self._show_fvg_events = _fvg_display_enabled(self.replay_config, "event_log")
        self._show_fvg_markers = _fvg_display_enabled(self.replay_config, "chart_markers")
        self._show_pivot_events = _pivot_display_enabled(self.replay_config, "event_log")
        self._show_pivot_markers = _pivot_display_enabled(self.replay_config, "chart_markers")
        self.current_lower_index = self.lower_start_index - 1
        self.current_higher_index = self.higher_start_index - 1
        self.visible_events: list[dict[str, Any]] = []
        self._init_engines()

    def reset(self) -> None:
        self.current_lower_index = self.lower_start_index - 1
        self.current_higher_index = self.higher_start_index - 1
        self.visible_events = []
        self.lower_sd_zone = None
        self.higher_sd_zone = None
        self.lower_structure = None
        self.higher_structure = None
        self._init_engines()

    def rewind_one(self) -> None:
        if self.current_lower_index < self.lower_start_index:
            return
        self._rebuild_to_lower_index(self.current_lower_index - 1)

    def rewind_to_time(self, target_time: str, step_before: bool = True) -> None:
        target_index = self._resolve_index(self.lower_bars, target_time, self.lower_window_start_index)
        if step_before:
            target_index -= 1
        self._rebuild_to_lower_index(target_index)

    def step(self) -> ReplayStepResult:
        if self.current_lower_index >= self.lower_end_index:
            return ReplayStepResult(
                cursor_index=self.current_lower_index,
                cursor_time=self.current_time_iso(),
                revealed_bar=None,
                new_events=[],
                done=True,
            )

        self.current_lower_index += 1
        lower_row = self.lower_bars.iloc[self.current_lower_index]
        new_events = self._process_lower_step(lower_row)
        revealed_bar = _serialize_bar(self.current_lower_index, lower_row.name, lower_row)
        return ReplayStepResult(
            cursor_index=self.current_lower_index,
            cursor_time=lower_row.name.isoformat(),
            revealed_bar=revealed_bar,
            new_events=new_events,
            done=self.current_lower_index >= self.lower_end_index,
        )

    def snapshot(self) -> dict[str, Any]:
        lower_visible = self._lower_visible_bars_payload()
        higher_visible = self._higher_visible_bars_payload()
        lower_price = float(self.lower_bars.iloc[self._lower_visible_end_index()]["close"]) if self._lower_visible_end_index() >= 0 else 0.0
        higher_price = float(self.higher_bars.iloc[self.current_higher_index]["close"]) if self.current_higher_index >= 0 else 0.0
        lower_zones = self.lower_sd_zone.get_zone_snapshot(lower_price) if self.lower_sd_zone else []
        higher_zones = self.higher_sd_zone.get_zone_snapshot(higher_price) if self.higher_sd_zone else []
        lower_last_resolved_zone = self.lower_sd_zone.get_last_resolved_zone_snapshot() if self.lower_sd_zone else None
        higher_last_resolved_zone = self.higher_sd_zone.get_last_resolved_zone_snapshot() if self.higher_sd_zone else None
        lower_structure = self.lower_structure.get_snapshot(lower_price) if self.lower_structure else None
        higher_structure = self.higher_structure.get_snapshot(higher_price) if self.higher_structure else None
        structure_display = _structure_dual_display(_structure_config(self.replay_config))
        projected_structure = higher_structure if structure_display in {"projected", "dual"} else None
        primary_structure = higher_structure if higher_structure is not None else lower_structure
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
            "bar_count": len(lower_visible),
            "bars": lower_visible,
            "lower_bars": lower_visible,
            "higher_bars": higher_visible,
            "events": self.visible_events,
            "zones": lower_zones + higher_zones,
            "lower_last_resolved_zone": lower_last_resolved_zone,
            "higher_last_resolved_zone": higher_last_resolved_zone,
            "lower_structure": lower_structure,
            "higher_structure": higher_structure,
            "projected_structure": projected_structure,
            "structure": primary_structure,
            "done": self.current_lower_index >= self.lower_end_index,
        }
        if self.hypothesis_classifier is not None:
            payload["hypothesis"] = self.hypothesis_classifier.classify(payload).to_dict()
        return payload

    def metadata(self) -> dict[str, Any]:
        lower_window = self.lower_bars.iloc[self.lower_window_start_index : self.lower_end_index + 1]
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
            "window_start_time": lower_window.index[0].isoformat(),
            "window_end_time": lower_window.index[-1].isoformat(),
            "default_start_time": self.lower_bars.index[self.lower_start_index].isoformat(),
            "window_bars": self.window_bars,
            "warmup_bars": self.warmup_bars,
        }

    def current_time_iso(self) -> str | None:
        if self.current_lower_index < self.lower_start_index:
            return None
        return self.lower_bars.index[self.current_lower_index].isoformat()

    def next_time_iso(self) -> str | None:
        next_index = self.current_lower_index + 1
        if next_index > self.lower_end_index:
            return None
        return self.lower_bars.index[next_index].isoformat()

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
        self.hypothesis_classifier = HypothesisClassifier(_hypothesis_config(self.replay_config))
        if not self.event_log_enabled:
            return

        fvg_cfg = _fvg_config(self.replay_config)
        if fvg_cfg.get("enabled", False):
            self.lower_candle = FvgEventEngine(fvg_cfg)
            self.higher_candle = FvgEventEngine(fvg_cfg)

        pivot_cfg = _pivot_config(self.replay_config)
        if pivot_cfg.get("enabled", False):
            self.lower_pivot = PivotEventEngine(pivot_cfg)
            self.higher_pivot = PivotEventEngine(pivot_cfg)

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

        lower_warmup_start = max(0, self.lower_start_index - self.warmup_bars)
        for _, row in self.lower_bars.iloc[lower_warmup_start : self.lower_start_index].iterrows():
            ce02: list = []
            pivot_events: list = []
            if self.lower_candle is not None:
                events = self.lower_candle.on_bar(row)
                ce02 = [e for e in events if e.event_code == "CE02"]
            if self.lower_pivot is not None:
                pivot_events = self.lower_pivot.on_bar(row)
            bar_result = SDZoneBarResult(created=[], mitigated=[])
            if self.lower_sd_zone is not None:
                bar_result = self.lower_sd_zone.on_bar(row, ce02)
            if self.lower_structure is not None:
                self.lower_structure.on_bar(row, pivot_events, ce02, bar_result)

        higher_cutoff_index = self.higher_start_index
        higher_warmup_start = max(0, higher_cutoff_index - self.warmup_bars)
        for _, row in self.higher_bars.iloc[higher_warmup_start : higher_cutoff_index].iterrows():
            ce02 = []
            pivot_events = []
            if self.higher_candle is not None:
                events = self.higher_candle.on_bar(row)
                ce02 = [e for e in events if e.event_code == "CE02"]
            if self.higher_pivot is not None:
                pivot_events = self.higher_pivot.on_bar(row)
            bar_result = SDZoneBarResult(created=[], mitigated=[])
            if self.higher_sd_zone is not None:
                bar_result = self.higher_sd_zone.on_bar(row, ce02)
            if self.higher_structure is not None:
                self.higher_structure.on_bar(row, pivot_events, ce02, bar_result)
        self.current_higher_index = higher_cutoff_index - 1

    def _rebuild_to_lower_index(self, target_index: int) -> None:
        bounded_index = min(target_index, self.lower_end_index)
        self.reset()
        if bounded_index < self.lower_start_index:
            self.current_lower_index = self.lower_start_index - 1
            return

        for idx in range(self.lower_start_index, bounded_index + 1):
            self.current_lower_index = idx
            lower_row = self.lower_bars.iloc[idx]
            self._process_lower_step(lower_row)

    def _process_lower_step(self, lower_row: pd.Series) -> list[dict[str, Any]]:
        emitted: list[dict[str, Any]] = []
        lower_ce02: list = []
        lower_pivot_events: list = []

        if self.lower_candle is not None:
            lower_candle_events = self.lower_candle.on_bar(lower_row)
            lower_ce02 = [e for e in lower_candle_events if e.event_code == "CE02"]
            if self._show_fvg_events or self._show_fvg_markers:
                emitted.extend(
                    _serialize_fvg_event(
                        event,
                        self.lower_label,
                        self._show_fvg_events,
                        self._show_fvg_markers,
                    )
                    for event in lower_candle_events
                )

        if self.lower_pivot is not None:
            lower_pivot_events = self.lower_pivot.on_bar(lower_row)
            if self._show_pivot_events or self._show_pivot_markers:
                emitted.extend(
                    _serialize_event(
                        event,
                        self.lower_label,
                        _pivot_tier_display_enabled(self.replay_config, event.tier, "event_log"),
                        _pivot_tier_display_enabled(self.replay_config, event.tier, "chart_markers"),
                    )
                    for event in lower_pivot_events
                )

        lower_bar_result = SDZoneBarResult(created=[], mitigated=[])
        if self.lower_sd_zone is not None:
            lower_bar_result = self.lower_sd_zone.on_bar(lower_row, lower_ce02)

        if self.lower_structure is not None:
            self.lower_structure.on_bar(lower_row, lower_pivot_events, lower_ce02, lower_bar_result)

        lower_close_ts = lower_row.name
        while self.current_higher_index + 1 < len(self.higher_bars) and self.higher_bars.index[self.current_higher_index + 1] <= lower_close_ts:
            self.current_higher_index += 1
            higher_row = self.higher_bars.iloc[self.current_higher_index]
            higher_ce02: list = []
            higher_pivot_events: list = []
            if self.higher_candle is not None:
                higher_candle_events = self.higher_candle.on_bar(higher_row)
                higher_ce02 = [e for e in higher_candle_events if e.event_code == "CE02"]
                if self._show_fvg_events or self._show_fvg_markers:
                    emitted.extend(
                        _serialize_fvg_event(
                            event,
                            self.higher_label,
                            self._show_fvg_events,
                            self._show_fvg_markers,
                        )
                        for event in higher_candle_events
                    )
            if self.higher_pivot is not None:
                higher_pivot_events = self.higher_pivot.on_bar(higher_row)
                if self._show_pivot_events or self._show_pivot_markers:
                    emitted.extend(
                        _serialize_event(
                            event,
                            self.higher_label,
                            _pivot_tier_display_enabled(self.replay_config, event.tier, "event_log"),
                            _pivot_tier_display_enabled(self.replay_config, event.tier, "chart_markers"),
                        )
                        for event in higher_pivot_events
                    )
            higher_bar_result = SDZoneBarResult(created=[], mitigated=[])
            if self.higher_sd_zone is not None:
                higher_bar_result = self.higher_sd_zone.on_bar(higher_row, higher_ce02)
            if self.higher_structure is not None:
                self.higher_structure.on_bar(higher_row, higher_pivot_events, higher_ce02, higher_bar_result)

        emitted.sort(key=lambda event: (event["decision_ts"], 0 if event["tf"] == self.higher_label else 1, event["event_code"]))
        self.visible_events.extend(emitted)
        return emitted

    def _lower_visible_bars_payload(self) -> list[dict[str, Any]]:
        visible_end = self._lower_visible_end_index()
        if visible_end < 0:
            return []
        visible_start = max(0, visible_end - self.window_bars + 1)
        visible = self.lower_bars.iloc[visible_start : visible_end + 1]
        return [
            _serialize_bar(idx, ts, row)
            for idx, (ts, row) in zip(range(visible_start, visible_end + 1), visible.iterrows())
        ]

    def _higher_visible_bars_payload(self) -> list[dict[str, Any]]:
        closed_end = self.current_higher_index
        if closed_end < 0 and self.current_lower_index < self.lower_start_index:
            return []

        closed_start = max(0, closed_end - self.window_bars + 1) if closed_end >= 0 else 0
        payload: list[dict[str, Any]] = []
        if closed_end >= 0:
            visible = self.higher_bars.iloc[closed_start : closed_end + 1]
            payload.extend(
                _serialize_bar(idx, ts, row)
                for idx, (ts, row) in zip(range(closed_start, closed_end + 1), visible.iterrows())
            )

        partial = self._current_higher_partial_bar()
        if partial is not None:
            payload.append(partial)

        return payload[-self.window_bars :]

    def _current_higher_partial_bar(self) -> dict[str, Any] | None:
        if self.current_lower_index < self.lower_start_index:
            return None
        next_higher_index = self.current_higher_index + 1
        if next_higher_index >= len(self.higher_bars):
            return None

        last_closed_ts = self.higher_bars.index[self.current_higher_index] if self.current_higher_index >= 0 else None
        current_lower_ts = self.lower_bars.index[self.current_lower_index]
        if current_lower_ts >= self.higher_bars.index[next_higher_index]:
            return None

        if last_closed_ts is None:
            segment = self.lower_bars.iloc[: self.current_lower_index + 1]
        else:
            segment = self.lower_bars[(self.lower_bars.index > last_closed_ts) & (self.lower_bars.index <= current_lower_ts)]
        if segment.empty:
            return None

        first = segment.iloc[0]
        last = segment.iloc[-1]
        partial_row = pd.Series(
            {
                "open": float(first["open"]),
                "high": float(segment["high"].max()),
                "low": float(segment["low"].min()),
                "close": float(last["close"]),
            }
        )
        return _serialize_bar(next_higher_index, self.higher_bars.index[next_higher_index], partial_row)

    def _lower_visible_end_index(self) -> int:
        if self.current_lower_index >= self.lower_start_index:
            return self.current_lower_index
        return self.lower_start_index - 1
