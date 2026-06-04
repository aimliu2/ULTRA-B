"""Backtester namespace.

V3 backtesting must reuse the headless runtime in :mod:`ultrab.runtime`.
The old A1/A2/B trade-trigger implementation remains available as legacy
submodules through :mod:`ultrab.v2_backtester`.
"""

from __future__ import annotations

from pathlib import Path


_PACKAGE_PATH = Path(__file__).resolve().parent
_V2_PACKAGE_PATH = Path(__file__).resolve().parents[1] / "v2_backtester"
__path__ = [str(_PACKAGE_PATH), str(_V2_PACKAGE_PATH)]

__all__ = []
