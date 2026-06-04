from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LIVE_BOOTSTRAP = "live_bootstrap"
RESEARCH_FULL_CONTEXT = "research_full_context"
VALID_STATE_MODES = {LIVE_BOOTSTRAP, RESEARCH_FULL_CONTEXT}


@dataclass(frozen=True)
class RuntimeEnvironment:
    """Declares the observer contract used by replay/backtest runtime state."""

    profile: str
    state_mode: str
    state_start_policy: str
    heartbeat: str
    warmup_bars: int
    window_bars: int

    @classmethod
    def from_app_config(
        cls,
        app_config: dict[str, Any],
        *,
        warmup_bars: int,
        window_bars: int,
    ) -> "RuntimeEnvironment":
        raw = app_config.get("runtime_environment", {}) or {}
        state_mode = str(raw.get("state_mode", LIVE_BOOTSTRAP)).strip().lower()
        if state_mode not in VALID_STATE_MODES:
            raise ValueError(
                "runtime_environment.state_mode must be one of "
                f"{sorted(VALID_STATE_MODES)}, got {state_mode!r}"
            )

        if state_mode == LIVE_BOOTSTRAP:
            default_policy = "bounded_warmup"
        else:
            default_policy = "dataset_or_checkpoint"

        return cls(
            profile=str(raw.get("profile", state_mode)).strip() or state_mode,
            state_mode=state_mode,
            state_start_policy=str(raw.get("state_start_policy", default_policy)).strip() or default_policy,
            heartbeat=str(raw.get("heartbeat", "lower_timeframe")).strip() or "lower_timeframe",
            warmup_bars=int(warmup_bars),
            window_bars=int(window_bars),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "state_mode": self.state_mode,
            "state_start_policy": self.state_start_policy,
            "heartbeat": self.heartbeat,
            "warmup_bars": self.warmup_bars,
            "window_bars": self.window_bars,
        }

