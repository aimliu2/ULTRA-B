from __future__ import annotations

from typing import Any


class Fusion:
    """
    Layer 3 Fusion — combines per-TF ContextSnapshots into runtime current truth.

    Single TF: fused_snapshot = context_snapshot (identity).
    Dual TF:   builds DualContextSnapshot from lower + higher ContextSnapshots.

    Fusion does not re-read raw channels. It reads only what Snapshot Normalizer
    already projected. Evidence Compiler and Layer 4 consume the result.
    """

    @staticmethod
    def fuse_single(context_snapshot: dict[str, Any]) -> dict[str, Any]:
        return context_snapshot

    @staticmethod
    def fuse_dual(
        lower_snapshot: dict[str, Any],
        higher_snapshot: dict[str, Any],
        *,
        execution_tf: str,
        reference_tf: str,
        symbol: str,
    ) -> dict[str, Any]:
        htf_bias = higher_snapshot.get("bias")
        ltf_bias = lower_snapshot.get("bias")
        ltf_range_state = lower_snapshot.get("rangeState")

        alignment = _cross_tf_alignment(htf_bias, ltf_bias, ltf_range_state)
        narrative = _narrative(htf_bias, ltf_bias, ltf_range_state)

        projected_htf_levels = (
            higher_snapshot.get("keyLevelsAbove", []) + higher_snapshot.get("keyLevelsBelow", [])
        )
        projected_htf_zones = (
            higher_snapshot.get("nearestSupplyZones", []) + higher_snapshot.get("nearestDemandZones", [])
        )

        return {
            "mode": "dual",
            "symbol": symbol,
            "currentTimestamp": lower_snapshot.get("currentTimestamp"),
            "currentPrice": lower_snapshot.get("currentPrice"),
            "execution_tf": execution_tf,
            "reference_tf": reference_tf,
            "lower_context_snapshot": lower_snapshot,
            "higher_context_snapshot": higher_snapshot,
            "execution_context": lower_snapshot,
            "reference_context": higher_snapshot,
            "htf_bias": htf_bias,
            "cross_tf_alignment": alignment,
            "narrative": narrative,
            "execution_pd": lower_snapshot.get("pdPosition", "unknown"),
            "projected_htf_levels": projected_htf_levels,
            "projected_htf_zones": projected_htf_zones,
            "confluence_zones": _confluence_zones(lower_snapshot, higher_snapshot),
        }


def _cross_tf_alignment(
    htf_bias: str | None,
    ltf_bias: str | None,
    ltf_range_state: str | None,
) -> str:
    if not htf_bias or not ltf_bias:
        return "unknown"
    if htf_bias == ltf_bias:
        if ltf_range_state == "pullback_confirmed":
            return "pullback"
        return "continuation"
    return "counter_trend"


def _narrative(
    htf_bias: str | None,
    ltf_bias: str | None,
    ltf_range_state: str | None,
) -> str | None:
    if not htf_bias or not ltf_bias:
        return None
    if htf_bias == ltf_bias:
        phase = "pullback" if ltf_range_state == "pullback_confirmed" else "continuation"
        return f"LTF {ltf_bias} {phase} inside HTF {htf_bias}"
    return f"LTF {ltf_bias} counter-trend inside HTF {htf_bias}"


def _confluence_zones(
    lower_snap: dict[str, Any],
    higher_snap: dict[str, Any],
) -> list[dict[str, Any]]:
    # Thin stub: Evidence Compiler handles cross-TF zone matching.
    return []
