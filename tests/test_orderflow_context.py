from ultrab.core.smc.orderflow import OrderflowContext


def _anchor(point_id: str, price: float) -> dict:
    return {
        "point_id": point_id,
        "price": price,
        "confirmed_at": point_id,
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


def test_orderflow_empty_snapshot():
    ctx = OrderflowContext({"window_size": 6}, "15m")

    snapshot = ctx.snapshot(None, evaluated_at="2025-01-01T00:00:00")

    assert snapshot["mss_regime"] == "unknown"
    assert snapshot["mss_monitor_status"] == "none"
    assert snapshot["mss_trigger_source"] == "none"
    assert "choch_monitor_status" not in snapshot
    assert "choch_trigger_source" not in snapshot
