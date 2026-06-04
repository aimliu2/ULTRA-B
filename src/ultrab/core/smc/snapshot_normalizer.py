from __future__ import annotations

from typing import Any


def _pd_position(structure: dict[str, Any] | None) -> str:
    if not structure:
        return "unknown"
    pct = structure.get("range_position_pct")
    if pct is None:
        return "unknown"
    try:
        value = float(pct)
    except (TypeError, ValueError):
        return "unknown"
    if value > 50:
        return "premium"
    if value < 50:
        return "discount"
    return "midpoint"


def _level_ref(level: dict[str, Any] | None) -> dict[str, Any] | None:
    if not level:
        return None
    return {
        "tier": level.get("tier"),
        "side": level.get("side"),
        "price": level.get("price"),
        "timestamp": level.get("timestamp"),
    }


def _nearest_zones(zones: list[dict[str, Any]], direction: str) -> list[dict[str, Any]]:
    selected = [zone for zone in zones if zone.get("direction") == direction]
    return sorted(selected, key=lambda zone: abs(float(zone.get("distance") or 0.0)))


def _levels_by_side(structure: dict[str, Any] | None, current_price: float, above: bool) -> list[dict[str, Any]]:
    if not structure:
        return []
    levels = structure.get("recent_itr_levels") or []
    result = []
    for level in levels:
        price = level.get("price")
        if price is None:
            continue
        try:
            value = float(price)
        except (TypeError, ValueError):
            continue
        if above and value > current_price:
            result.append(level)
        if not above and value < current_price:
            result.append(level)
    return sorted(result, key=lambda level: abs(float(level.get("price")) - current_price))


class SnapshotNormalizer:
    """Read-only projector from single-TF channel snapshots to ContextSnapshot."""

    @staticmethod
    def project(
        *,
        cursor: dict[str, Any],
        structure: dict[str, Any] | None = None,
        zones: list[dict[str, Any]] | None = None,
        liquidity: dict[str, Any] | None = None,
        orderflow: dict[str, Any] | None = None,
        last_resolved_zone: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        zones = zones or []
        liquidity = liquidity or {}
        orderflow = orderflow or {}
        current_price = float(cursor.get("currentPrice") or 0.0)

        return {
            "currentTimestamp": cursor.get("currentTimestamp"),
            "currentPrice": current_price,
            "currentBarIndex": cursor.get("currentBarIndex"),
            "timeframe": cursor.get("timeframe"),
            "mode": cursor.get("mode", "single"),
            "symbol": cursor.get("symbol"),
            "bias": structure.get("bias") if structure else None,
            "biasTier": structure.get("tier") if structure else None,
            "rangeState": structure.get("phase") if structure else None,
            "currentLeg": _current_leg(structure, orderflow),
            "pdPosition": _pd_position(structure),
            "lastConfirmedHigh": _level_ref(structure.get("latest_itr_high") if structure else None),
            "lastConfirmedLow": _level_ref(structure.get("latest_itr_low") if structure else None),
            "nearestSupplyZones": _nearest_zones(zones, "supply"),
            "nearestDemandZones": _nearest_zones(zones, "demand"),
            "keyLevelsAbove": _levels_by_side(structure, current_price, True),
            "keyLevelsBelow": _levels_by_side(structure, current_price, False),
            "liquidity": liquidity,
            "orderflow": orderflow,
            "structure": structure,
            "zones": zones,
            "last_resolved_zone": last_resolved_zone,
            "structureAttempt": (
                structure.get("structure_attempt")
                if structure
                else None
            ),
            "invalidationRefs": _invalidation_refs(structure, orderflow),
        }


def _current_leg(structure: dict[str, Any] | None, orderflow: dict[str, Any] | None) -> str:
    if orderflow and orderflow.get("regime") in {"compression", "sweep_range"}:
        return "ranging"
    if orderflow and orderflow.get("live_pressure") in {"pullback_extending", "anchor_threat"}:
        return "pullback"
    if structure and structure.get("phase") == "pullback_confirmed":
        return "pullback"
    if structure and structure.get("phase") == "open":
        return "impulse"
    return "unknown"


def _invalidation_refs(
    structure: dict[str, Any] | None,
    orderflow: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if orderflow and orderflow.get("protected_anchor_ref"):
        refs.append({
            "kind": "orderflow_protected_anchor",
            "ref": orderflow.get("protected_anchor_ref"),
        })
    if structure and structure.get("range_high") is not None:
        refs.append({
            "kind": "structure_range_high",
            "price": structure.get("range_high"),
            "timestamp": structure.get("range_high_ts"),
        })
    if structure and structure.get("range_low") is not None:
        refs.append({
            "kind": "structure_range_low",
            "price": structure.get("range_low"),
            "timestamp": structure.get("range_low_ts"),
        })
    return refs
