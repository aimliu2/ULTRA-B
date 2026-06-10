from ultrab.core.smc.orderflow import OrderflowContext


def _anchor(point_id: str, price: float, side: str | None = None) -> dict:
    if side is not None:
        inferred_side = side
    elif point_id.startswith("H"):
        inferred_side = "high"
    elif point_id.startswith("L"):
        inferred_side = "low"
    else:
        inferred_side = None
    return {
        "point_id": point_id,
        "price": price,
        "confirmed_at": point_id,
        "side": inferred_side,
    }


def test_orderflow_mss_fires_on_latest_hl_break():
    ctx = OrderflowContext({"window_size": 6}, "15m")
    structure = {
        "timeframe": "15m",
        "structure_sequence": [
            _anchor("H1", 10.0),
            _anchor("L1", 5.0),
            _anchor("H2", 11.0),
            _anchor("L2", 6.0),
            _anchor("H3", 12.0),
            _anchor("L3", 7.0),   # latest HL — protected anchor
        ],
        "structure_probe": _anchor("probe", 6.5),  # below latest HL (7.0)
    }

    snapshot = ctx.snapshot(structure, evaluated_at="2025-01-01T00:00:00")

    assert snapshot["regime"] == "mss_watch"
    assert snapshot["mss_regime"] == "mss_watch"
    assert snapshot["mss_monitor_status"] == "watching_resolution"
    assert snapshot["mss_trigger_source"] == "probe_vs_protected_anchor"
    assert snapshot["probe_breaks_protected_anchor"] is True


def test_orderflow_defaults_to_orderflow_anchor_store():
    ctx = OrderflowContext({"window_size": 6}, "15m")
    structure = {
        "timeframe": "15m",
        "orderflow_anchor_sequence": [
            _anchor("OFANCH:H1", 10.0),
            _anchor("OFANCH:L1", 5.0),
            _anchor("OFANCH:H2", 11.0),
            _anchor("OFANCH:L2", 6.0),
            _anchor("OFANCH:H3", 12.0),
            _anchor("OFANCH:L3", 7.0),
        ],
        "orderflow_probe": _anchor("OFPROBE:probe", 6.5),
    }

    snapshot = ctx.snapshot(structure, evaluated_at="2025-01-01T00:00:00")

    assert snapshot["source_store"] == "orderflow_anchor_sequence"
    assert snapshot["protected_anchor_ref"] == "OFANCH:L3"
    assert snapshot["disruption_point_ref"] == "OFPROBE:probe"
    assert snapshot["regime"] == "mss_watch"


def test_orderflow_mss_does_not_fire_on_ll_break():
    """Probe below a LL (not an HL) must not trigger MSS — LL is not the protected anchor."""
    ctx = OrderflowContext({"window_size": 6}, "15m")
    structure = {
        "timeframe": "15m",
        "structure_sequence": [
            _anchor("H1", 10.0),
            _anchor("L1", 8.0),
            _anchor("H2", 11.0),
            _anchor("L2", 7.0),   # HL (7 < 8 → LL actually, let me recalc)
            _anchor("H3", 12.0),
            _anchor("L3", 6.0),   # LL (6 < 7)
        ],
        # probe below L3=6.0 but L3 is LL not HL — no latest HL to break
        "structure_probe": _anchor("probe", 5.5),
    }

    snapshot = ctx.snapshot(structure, evaluated_at="2025-01-01T00:00:00")

    # latest HL: L1=8.0 (seed), L2=7.0 (LL), L3=6.0 (LL) — no HL in sequence after L1
    # score: H1→H2=HH, H2→H3=HH; L1→L2=LL, L2→L3=LL → bear=2, bull=2 → mixed/compression
    assert snapshot["probe_breaks_protected_anchor"] is False


def test_orderflow_uses_explicit_side_when_retained_sequence_starts_low():
    ctx = OrderflowContext({"window_size": 8}, "15m")
    structure = {
        "timeframe": "15m",
        "structure_sequence": [
            _anchor("L0", 1.17767, "low"),
            _anchor("H0", 1.18973, "high"),
            _anchor("L1", 1.18345, "low"),
            _anchor("H1", 1.19720, "high"),
            _anchor("L2", 1.19492, "low"),
            _anchor("H2", 1.19898, "high"),
            _anchor("L3", 1.19583, "low"),
            _anchor("H3", 1.20818, "high"),
        ],
        "structure_probe": _anchor("probe", 1.20348, "low"),
    }

    snapshot = ctx.snapshot(structure, evaluated_at="2026-01-28T00:15:00+00:00")

    assert snapshot["confirmed_sequence"] == ["L0", "H0", "HL", "HH", "HL", "HH", "HL", "HH"]
    assert snapshot["confirmed_direction"] == "bullish"
    assert snapshot["side_alternation_clean"] is True
    assert snapshot["protected_anchor_ref"] == "L3"
    assert snapshot["probe_breaks_protected_anchor"] is False
    assert snapshot["regime"] == "directional"
    assert snapshot["mss_regime"] == "directional"
    assert snapshot["mss_trigger_source"] == "none"


def test_orderflow_empty_snapshot():
    ctx = OrderflowContext({"window_size": 6}, "15m")

    snapshot = ctx.snapshot(None, evaluated_at="2025-01-01T00:00:00")

    assert snapshot["mss_regime"] == "unknown"
    assert snapshot["mss_monitor_status"] == "none"
    assert snapshot["mss_trigger_source"] == "none"
    assert "choch_monitor_status" not in snapshot
    assert "choch_trigger_source" not in snapshot
