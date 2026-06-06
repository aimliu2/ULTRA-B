from __future__ import annotations

from typing import Any


EPS = 1e-5


def _price(point: dict[str, Any]) -> float | None:
    value = point.get("price")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _point_ref(point: dict[str, Any]) -> str:
    return str(point.get("point_id") or point.get("ref") or point.get("timestamp") or "unknown")


def _side_at(index: int, starts_with: str) -> str:
    high_on_even = starts_with.upper() == "H"
    return "high" if (index % 2 == 0) == high_on_even else "low"


def _point_side(point: dict[str, Any], index: int, starts_with: str) -> str:
    side = str(point.get("side") or "").strip().lower()
    if side in {"high", "low"}:
        return side
    return _side_at(index, starts_with)


def _cmp(a: float, b: float) -> str:
    if abs(a - b) <= EPS:
        return "EQ"
    return "UP" if a > b else "DOWN"


class OrderflowContext:
    """Stateless Layer 3 orderflow projector over structure sequence + live probe."""

    def __init__(self, cfg: dict[str, Any] | None = None, timeframe: str | None = None) -> None:
        cfg = cfg or {}
        self.source = str(cfg.get("source", "structure_sequence"))
        self.window_size = int(cfg.get("probe_points", cfg.get("window_size", 8)))
        self.starts_with = str(cfg.get("starts_with", "H"))
        self.timeframe = timeframe

    def snapshot(
        self,
        structure: dict[str, Any] | None,
        *,
        evaluated_at: str | None = None,
    ) -> dict[str, Any]:
        if not structure:
            return self._empty(evaluated_at, "insufficient_points")

        probe_key = self.source.replace("_sequence", "_probe")
        anchors = [
            point
            for point in structure.get(self.source) or []
            if _price(point) is not None
        ]
        if not anchors and self.source == "structure_sequence":
            anchors = [
                point
                for point in structure.get("structure_anchor_sequence") or []
                if _price(point) is not None
            ]
            probe_key = "structure_anchor_probe"
        probe = structure.get(probe_key)
        if _price(probe or {}) is None:
            probe = None

        confirmed = anchors[-self.window_size :]
        labels = self._label_confirmed(confirmed)
        side_alternation_clean = self._side_alternation_clean(labels)
        score = self._score_direction(labels, side_alternation_clean)
        latest_high = self._latest_by_side(labels, "high")
        latest_low = self._latest_by_side(labels, "low")
        prev_high = self._previous_by_side(labels, "high")
        prev_low = self._previous_by_side(labels, "low")

        mss_watch_confirmed = False
        if len(labels) >= 2:
            if score["direction"] == "bullish":
                if (latest_low and latest_low.get("label") == "LL") or (
                    latest_high and latest_high.get("label") == "LH"
                ):
                    mss_watch_confirmed = True
            elif score["direction"] == "bearish":
                if (latest_high and latest_high.get("label") == "HH") or (
                    latest_low and latest_low.get("label") == "HL"
                ):
                    mss_watch_confirmed = True

        regime = "directional"
        monitor = "none"
        live_pressure = "none"
        blocked_reason = None
        protected_anchor = None
        probe_breaks_protected_anchor = False

        if len(confirmed) < self.window_size:
            regime = "unknown"
            blocked_reason = "insufficient_points"
        elif score["direction"] == "mixed":
            regime = "compression"
            blocked_reason = "compression"
        elif score["direction"] == "unknown":
            regime = "unknown"
            blocked_reason = "insufficient_points"
        elif score["equal"] > 0:
            regime = "compression"
            blocked_reason = "compression"

        probe_relation = self._locate_probe(probe, latest_high, latest_low)
        if probe and score["direction"] == "bullish":
            protected_anchor = self._latest_by_label(labels, "HL")
            if protected_anchor and _price(probe) < _price(protected_anchor) - EPS:
                probe_breaks_protected_anchor = True
                regime = "mss_watch"
                monitor = "watching_resolution"
                live_pressure = "anchor_threat"
                blocked_reason = None
        if probe and score["direction"] == "bearish":
            protected_anchor = self._latest_by_label(labels, "LH")
            if protected_anchor and _price(probe) > _price(protected_anchor) + EPS:
                probe_breaks_protected_anchor = True
                regime = "mss_watch"
                monitor = "watching_resolution"
                live_pressure = "anchor_threat"
                blocked_reason = None

        if live_pressure == "none":
            if probe_relation in {"above_active_high", "below_active_low"}:
                live_pressure = "breakaway_watch"
            elif probe_relation in {"upper_half", "lower_half"}:
                live_pressure = "pullback_extending"

        sequence = [point["label"] for point in labels]
        mss_trigger_source = "probe_vs_protected_anchor" if probe_breaks_protected_anchor else "none"
        return {
            "confirmed_direction": score["direction"],
            "regime": regime,
            "mss_regime": regime,
            "mss_watch_confirmed": mss_watch_confirmed,
            "quality": score["quality"],
            "live_pressure": live_pressure,
            "mss_monitor_status": monitor,
            "source": self.source,
            "window_size": self.window_size,
            "confirmed_sequence": sequence,
            "sequence_with_probe": [*sequence, "probe"] if probe else sequence,
            "probe_label": "probe" if probe else None,
            "last_shift_at": labels[-1].get("confirmed_at") if labels else None,
            "supporting_itr_refs": [],
            "supporting_anchor_refs": [_point_ref(point) for point in labels],
            "protected_anchor_ref": _point_ref(protected_anchor) if protected_anchor else None,
            "disruption_point_ref": _point_ref(probe) if probe_breaks_protected_anchor and probe else None,
            "decision_point_ref": None,
            "range_ref": self._range_ref(latest_high, latest_low),
            "previous_range_ref": self._range_ref(prev_high, prev_low),
            "probe_ref": _point_ref(probe) if probe else None,
            "probe_price": _price(probe) if probe else None,
            "probe_breaks_protected_anchor": probe_breaks_protected_anchor,
            "probe_relation": probe_relation,
            "side_alternation_clean": side_alternation_clean,
            "mss_trigger_source": mss_trigger_source,
            "liquidity_annotations": [
                {"ref": _point_ref(point), "label": point["label"]}
                for point in labels
                if point["label"] in {"EH", "EL"}
            ],
            "pullback_status": "unknown",
            "timeframe": self.timeframe or structure.get("timeframe"),
            "evaluated_at": evaluated_at,
            "blocked_reason": blocked_reason,
        }

    def _empty(self, evaluated_at: str | None, blocked_reason: str) -> dict[str, Any]:
        return {
            "confirmed_direction": "unknown",
            "regime": "unknown",
            "mss_regime": "unknown",
            "mss_watch_confirmed": False,
            "quality": "weak",
            "live_pressure": "none",
            "mss_monitor_status": "none",
            "source": self.source,
            "window_size": self.window_size,
            "confirmed_sequence": [],
            "sequence_with_probe": [],
            "probe_label": None,
            "last_shift_at": None,
            "supporting_itr_refs": [],
            "supporting_anchor_refs": [],
            "protected_anchor_ref": None,
            "disruption_point_ref": None,
            "decision_point_ref": None,
            "range_ref": None,
            "probe_ref": None,
            "probe_breaks_protected_anchor": False,
            "probe_relation": "unknown",
            "side_alternation_clean": False,
            "mss_trigger_source": "none",
            "liquidity_annotations": [],
            "pullback_status": "unknown",
            "timeframe": self.timeframe,
            "evaluated_at": evaluated_at,
            "blocked_reason": blocked_reason,
        }

    def _label_confirmed(self, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        last_high: dict[str, Any] | None = None
        last_low: dict[str, Any] | None = None
        labels: list[dict[str, Any]] = []
        for index, point in enumerate(points):
            side = _point_side(point, index, self.starts_with)
            price = _price(point)
            previous = last_high if side == "high" else last_low
            label = "H0" if side == "high" else "L0"
            relation = "seed"
            previous_ref = None
            if previous is not None and price is not None:
                previous_price = _price(previous)
                if previous_price is not None:
                    relation = _cmp(price, previous_price)
                    if side == "high":
                        label = "HH" if relation == "UP" else "LH" if relation == "DOWN" else "EH"
                    else:
                        label = "HL" if relation == "UP" else "LL" if relation == "DOWN" else "EL"
                    previous_ref = _point_ref(previous)
            enriched = {**point, "side": side, "label": label, "relation": relation, "previous_ref": previous_ref}
            labels.append(enriched)
            if side == "high":
                last_high = enriched
            else:
                last_low = enriched
        return labels

    @staticmethod
    def _side_alternation_clean(labels: list[dict[str, Any]]) -> bool:
        if len(labels) < 2:
            return False
        sides = [point.get("side") for point in labels]
        return all(current != previous for previous, current in zip(sides, sides[1:]))

    def _score_direction(
        self,
        labels: list[dict[str, Any]],
        side_alternation_clean: bool,
    ) -> dict[str, Any]:
        scored = [point for point in labels if point["label"] not in {"H0", "L0"}]
        bull = sum(1 for point in scored if point["label"] in {"HH", "HL"})
        bear = sum(1 for point in scored if point["label"] in {"LH", "LL"})
        equal = sum(1 for point in scored if point["label"] in {"EH", "EL"})
        clean_quality = "clean" if side_alternation_clean and not equal else "weak"
        if len(scored) < 4:
            return {"direction": "unknown", "quality": "weak", "bull": bull, "bear": bear, "equal": equal}
        if bull >= 4 and bear == 0:
            return {"direction": "bullish", "quality": clean_quality, "bull": bull, "bear": bear, "equal": equal}
        if bear >= 4 and bull == 0:
            return {"direction": "bearish", "quality": clean_quality, "bull": bull, "bear": bear, "equal": equal}
        if bull > bear:
            return {"direction": "bullish", "quality": "weak", "bull": bull, "bear": bear, "equal": equal}
        if bear > bull:
            return {"direction": "bearish", "quality": "weak", "bull": bull, "bear": bear, "equal": equal}
        return {"direction": "mixed", "quality": "weak" if equal else "broken", "bull": bull, "bear": bear, "equal": equal}

    @staticmethod
    def _latest_by_side(labels: list[dict[str, Any]], side: str) -> dict[str, Any] | None:
        return next((point for point in reversed(labels) if point.get("side") == side), None)

    @staticmethod
    def _latest_by_label(labels: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
        return next((point for point in reversed(labels) if point.get("label") == label), None)

    @staticmethod
    def _previous_by_side(labels: list[dict[str, Any]], side: str) -> dict[str, Any] | None:
        matches = [point for point in reversed(labels) if point.get("side") == side]
        return matches[1] if len(matches) > 1 else None

    @staticmethod
    def _range_ref(high: dict[str, Any] | None, low: dict[str, Any] | None) -> str | None:
        if not high or not low:
            return None
        return f"{_point_ref(high)}/{_point_ref(low)}"

    @staticmethod
    def _locate_probe(
        probe: dict[str, Any] | None,
        latest_high: dict[str, Any] | None,
        latest_low: dict[str, Any] | None,
    ) -> str:
        if not probe or not latest_high or not latest_low:
            return "unknown"
        probe_price = _price(probe)
        high_price = _price(latest_high)
        low_price = _price(latest_low)
        if probe_price is None or high_price is None or low_price is None:
            return "unknown"
        active_high = max(high_price, low_price)
        active_low = min(high_price, low_price)
        mid = (active_high + active_low) / 2
        if probe_price > active_high + EPS:
            return "above_active_high"
        if probe_price < active_low - EPS:
            return "below_active_low"
        return "upper_half" if probe_price >= mid else "lower_half"
