from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WarmupTrace:
    records: list[dict[str, Any]] = field(default_factory=list)

    def append(
        self,
        *,
        bar_time: str | None,
        hypothesis: dict[str, Any] | None,
        recovery_mode: str | None = None,
    ) -> None:
        if not bar_time or not hypothesis:
            return
        self.records.append(
            {
                "bar_time": bar_time,
                "phase": hypothesis.get("phase"),
                "phase_sub_status": hypothesis.get("phase_sub_status"),
                "direction": hypothesis.get("direction"),
                "recovery_mode": recovery_mode,
            }
        )

    def payload(self) -> list[dict[str, Any]]:
        return list(self.records)

    def probe_annotation(self, diagnostics: dict[str, Any]) -> dict[str, Any] | None:
        if not self.records:
            return None
        final = self.records[-1]
        mode = diagnostics.get("recovery_mode")
        phase = final.get("phase")
        sub_status = final.get("phase_sub_status")
        direction = final.get("direction")
        phase_label = ".".join(str(item) for item in (phase, sub_status) if item)
        detail = " ".join(str(item) for item in (phase_label, direction) if item)
        if not detail:
            detail = "unclassified"
        label = f"{mode or 'right_edge_rebuild'} -> {detail}"
        return {
            "bar_time": final.get("bar_time"),
            "label": label,
            "recovery_mode": mode,
            "phase": phase,
            "phase_sub_status": sub_status,
            "direction": direction,
        }
