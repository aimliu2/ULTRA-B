from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, render_template, request

from ultrab.replayer.data_source import (
    available_symbols,
    available_timeframes,
    bars_payload,
    load_app_config,
    replay_data_config,
    timeframe_label,
)
from ultrab.replayer.replay_session import DualReplaySession, ReplaySession
from ultrab.replayer.session_store import get_session, save_session


CONFIG_PATH = Path(__file__).with_name("config.yaml")
STATIC_ICON_PATH = Path(__file__).with_name("static") / "icons"

app = Flask(
    __name__,
    template_folder=str(Path(__file__).with_name("templates")),
    static_folder=str(STATIC_ICON_PATH),
    static_url_path="/icons",
)


@app.get("/")
def index():
    config = load_app_config(CONFIG_PATH)
    data_cfg = replay_data_config(CONFIG_PATH)
    payload = bars_payload(data_cfg)
    replay_cfg = config.get("replay", {})
    data_cfg_raw = config.get("data", {})
    dual_mode_cfg = config.get("dual_mode", {})
    return render_template(
        "index.html",
        app_config=config.get("app", {}),
        chart_meta={
            "symbol": payload["symbol"],
            "timeframe": payload["timeframe"],
            "window_bars": payload["window_bars"],
            "bar_count": payload["bar_count"],
            "initial_visible_bars": int(replay_cfg.get("initial_visible_bars", payload["window_bars"])),
            "chart_padding_bars": int(replay_cfg.get("chart_padding_bars", 8)),
            "tooltip_opacity": float(replay_cfg.get("tooltip_opacity", 0.5)),
            "chart_markers": replay_cfg.get("chart_markers", {}),
            "bar_colors": replay_cfg.get("bar_colors", {}),
            "sd_zones_display": (replay_cfg.get("marker_config", {}).get("sd_zones", {}).get("display", {})),
            "structure_pd_lines": replay_cfg.get("structure", {}).get("pd_lines", {}),
            "default_mode": str(data_cfg_raw.get("mode", "single")),
            "default_dual_combo": str(data_cfg_raw.get("dual_combo", "15m_4h")),
            "dual_combos": dual_mode_cfg.get("combos", {}),
        },
    )


@app.get("/api/bars")
def api_bars():
    data_cfg = replay_data_config(CONFIG_PATH)
    symbol = request.args.get("symbol", data_cfg.symbol).upper()
    timeframe = request.args.get("timeframe", data_cfg.timeframe).lower()
    requested_cfg = type(data_cfg)(
        root=data_cfg.root,
        symbol=symbol,
        timeframe=timeframe,
        window_bars=data_cfg.window_bars,
    )
    return jsonify(bars_payload(requested_cfg))


@app.get("/api/symbols")
def api_symbols():
    config = load_app_config(CONFIG_PATH)
    data_cfg = replay_data_config(CONFIG_PATH)
    symbols = available_symbols(data_cfg)
    timeframe_options = [
        {"value": tf, "label": timeframe_label(tf)}
        for tf in available_timeframes(data_cfg, data_cfg.symbol)
    ]
    return jsonify(
        {
            "default_symbol": data_cfg.symbol,
            "default_timeframe": data_cfg.timeframe,
            "default_mode": str(config.get("data", {}).get("mode", "single")),
            "default_dual_combo": str(config.get("data", {}).get("dual_combo", "15m_4h")),
            "symbols": symbols,
            "timeframes": timeframe_options,
            "dual_combos": config.get("dual_mode", {}).get("combos", {}),
        }
    )


@app.get("/api/timeframes")
def api_timeframes():
    data_cfg = replay_data_config(CONFIG_PATH)
    symbol = request.args.get("symbol", data_cfg.symbol).upper()
    return jsonify(
        {
            "symbol": symbol,
            "default_timeframe": data_cfg.timeframe,
            "timeframes": [
                {"value": tf, "label": timeframe_label(tf)}
                for tf in available_timeframes(data_cfg, symbol)
            ],
        }
    )


@app.post("/api/replay/session")
def api_replay_session():
    payload = request.get_json(silent=True) or {}
    config = load_app_config(CONFIG_PATH)
    data_cfg = replay_data_config(CONFIG_PATH)

    mode = str(payload.get("mode", config.get("data", {}).get("mode", "single"))).lower()
    symbol = str(payload.get("symbol", data_cfg.symbol)).upper()
    timeframe = str(payload.get("timeframe", data_cfg.timeframe)).lower()
    start_time = payload.get("start_time")

    if mode == "dual":
        combo_name = str(payload.get("dual_combo", config.get("data", {}).get("dual_combo", "15m_4h")))
        combo_cfg = (config.get("dual_mode", {}).get("combos", {}) or {}).get(combo_name)
        if not combo_cfg:
            return jsonify({"error": f"unknown dual combo: {combo_name}"}), 400

        lower_cfg = type(data_cfg)(
            root=data_cfg.root,
            symbol=symbol,
            timeframe=str(combo_cfg["lower_tf"]).lower(),
            window_bars=data_cfg.window_bars,
        )
        higher_cfg = type(data_cfg)(
            root=data_cfg.root,
            symbol=symbol,
            timeframe=str(combo_cfg["higher_tf"]).lower(),
            window_bars=data_cfg.window_bars,
        )
        session = save_session(
            DualReplaySession(
                str(CONFIG_PATH),
                symbol=symbol,
                lower_config=lower_cfg,
                higher_config=higher_cfg,
                combo_name=combo_name,
                start_time=start_time,
            )
        )
        return jsonify(
            {
                "metadata": session.metadata(),
                "snapshot": session.snapshot(),
            }
        )

    session_cfg = type(data_cfg)(
        root=data_cfg.root,
        symbol=symbol,
        timeframe=timeframe,
        window_bars=data_cfg.window_bars,
    )
    session = save_session(ReplaySession(str(CONFIG_PATH), session_cfg, start_time=start_time))
    return jsonify(
        {
            "metadata": session.metadata(),
            "snapshot": session.snapshot(),
        }
    )


@app.post("/api/replay/<session_id>/step")
def api_replay_step(session_id: str):
    session = get_session(session_id)
    result = session.step()
    return jsonify(
        {
            "step": {
                "cursor_index": result.cursor_index,
                "cursor_time": result.cursor_time,
                "revealed_bar": result.revealed_bar,
                "new_events": result.new_events,
                "done": result.done,
            },
            "snapshot": session.snapshot(),
        }
    )


@app.post("/api/replay/<session_id>/reset")
def api_replay_reset(session_id: str):
    session = get_session(session_id)
    session.reset()
    return jsonify({"snapshot": session.snapshot()})


@app.post("/api/replay/<session_id>/back")
def api_replay_back(session_id: str):
    session = get_session(session_id)
    session.rewind_one()
    return jsonify({"snapshot": session.snapshot()})


@app.post("/api/replay/<session_id>/rewind")
def api_replay_rewind(session_id: str):
    session = get_session(session_id)
    payload = request.get_json(silent=True) or {}
    target_time = payload.get("target_time")
    if not target_time:
        return jsonify({"error": "target_time is required"}), 400
    session.rewind_to_time(str(target_time), step_before=bool(payload.get("step_before", True)))
    return jsonify({"snapshot": session.snapshot()})


@app.get("/api/replay/<session_id>/snapshot")
def api_replay_snapshot(session_id: str):
    session = get_session(session_id)
    return jsonify(session.snapshot())


def main() -> None:
    config = load_app_config(CONFIG_PATH)
    app_cfg = config.get("app", {})
    host = app_cfg.get("host", "127.0.0.1")
    port = int(app_cfg.get("port", 5055))
    debug = bool(app_cfg.get("debug", True))
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
