from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Event — shared by confirmed and BoS events
# ---------------------------------------------------------------------------

@dataclass
class MarkerEvent:
    tier:                str            # 'str' | 'itr' | 'ltr'
    event_code:          str            # e.g. 'PE01'
    event_name:          str            # e.g. 'strHighConfirmed'
    event_timestamp:     pd.Timestamp   # when the pattern completes (act on this)
    pivot_price:         float          # price of the relevant pivot
    pivot_timestamp:     pd.Timestamp   # where that pivot sits on the chart
    pivot_side:          int            # +1 high | -1 low
    level_price:         float | None = None      # broken level price for BoS
    level_timestamp:     pd.Timestamp | None = None  # broken level timestamp for BoS
    level_side:          int | None = None        # broken level side for BoS

    @property
    def confirmed_type(self) -> int:  # backward-compat alias
        return self.pivot_side

    @property
    def bar_event(self) -> str:  # backward-compat alias
        return self.event_name

    @property
    def bar_event_timestamp(self) -> pd.Timestamp:  # backward-compat alias
        return self.event_timestamp

    @property
    def bar_pivot_value(self) -> float:  # backward-compat alias
        return self.pivot_price

    @property
    def bar_pivot_timestamp(self) -> pd.Timestamp:  # backward-compat alias
        return self.pivot_timestamp

    def to_dict(self) -> dict:
        payload = {
            'eventCode':      self.event_code,
            'eventName':      self.event_name,
            'eventTimestamp': self.event_timestamp,
            'pivotTimestamp': self.pivot_timestamp,
            'pivotPrice':     self.pivot_price,
            'pivotSide':      self.pivot_side,
        }
        if self.level_timestamp is not None:
            payload['levelTimestamp'] = self.level_timestamp
        if self.level_price is not None:
            payload['levelPrice'] = self.level_price
        if self.level_side is not None:
            payload['levelSide'] = self.level_side
        return payload


_CONFIRMED_CODES: dict[tuple[str, int], str] = {
    ('str', +1): 'PE01',
    ('str', -1): 'PE02',
    ('itr', +1): 'PE03',
    ('itr', -1): 'PE04',
    ('ltr', +1): 'PE05',
    ('ltr', -1): 'PE06',
}

_STR_BOS_CODES: dict[int, str] = {
    +1: 'B01',
    -1: 'B02',
}


# ---------------------------------------------------------------------------
# Per-tier state: alternation gate + STR-level BoS detection
# ---------------------------------------------------------------------------

class _TierState:
    """
    Shared state for one tier (str / itr / ltr).

    Alternation gate
    ----------------
    A new pivot of side S is only allowed if the last confirmed was -S.
    Cold-start (no prior pivot) always passes.

    STR BoS detection
    -----------------
    The BoS path is currently defined for STR only.

    Close < last confirmed LOW  → bearish STR BoS → immediately confirms the
    highest high found between that LOW level and the decision bar.
    Close > last confirmed HIGH → bullish STR BoS → immediately confirms the
    lowest low found between that HIGH level and the decision bar.

    The broken level is consumed after firing (_last_high / _last_low set to None).
    A new N-bar pivot must re-establish the reference before the same side can
    fire BoS again. This prevents ping-pong between two frozen levels and mirrors
    groupN._fix_break_of_structure: the insertion happens once at the best
    counter-swing, not repeatedly at the same price.
    """

    def __init__(self, tier: str) -> None:
        self.tier = tier

        self._last_type:    Optional[int]          = None
        self._last_high:    Optional[float]         = None
        self._last_low:     Optional[float]         = None
        self._last_high_ts: Optional[pd.Timestamp]  = None
        self._last_low_ts:  Optional[pd.Timestamp]  = None
        self._high_since_low: Optional[float] = None
        self._high_since_low_ts: Optional[pd.Timestamp] = None
        self._low_since_high: Optional[float] = None
        self._low_since_high_ts: Optional[pd.Timestamp] = None

    # --- alternation ---

    def can_confirm(self, side: int) -> bool:
        return self._last_type is None or self._last_type != side

    def confirm(self, side: int, price: float, ts: pd.Timestamp) -> None:
        self._last_type = side
        if side == +1:
            self._last_high    = price
            self._last_high_ts = ts
            self._low_since_high = None
            self._low_since_high_ts = None
        else:
            self._last_low    = price
            self._last_low_ts = ts
            self._high_since_low = None
            self._high_since_low_ts = None

    def observe_bar(self, high: float, low: float, ts: pd.Timestamp) -> None:
        if self._last_low_ts is not None and ts > self._last_low_ts:
            if self._high_since_low is None or high >= self._high_since_low:
                self._high_since_low = high
                self._high_since_low_ts = ts

        if self._last_high_ts is not None and ts > self._last_high_ts:
            if self._low_since_high is None or low <= self._low_since_high:
                self._low_since_high = low
                self._low_since_high_ts = ts

    # --- BoS ---

    def check_str_bos(
        self,
        close:     float,
        signal_ts: pd.Timestamp,
    ) -> tuple[list[MarkerEvent], Optional[MarkerEvent]]:
        """
        Emit a STR BoS event when close crosses a confirmed STR pivot level.

        The broken level is consumed (set to None) after firing so the same
        level cannot re-trigger. A new N-bar pivot must re-establish the
        reference before the next BoS of the same side can fire.
        This keeps the event-driven behavior aligned with the current note:
        STR BoS is primary, higher-tier structural exceptions remain open.

        Returns (events_list, bos_event_or_None).
        """
        if self.tier != 'str':
            return [], None

        # Bearish BoS: broken low level confirms the best opposite HIGH in-segment
        if (self._last_low is not None
                and close < self._last_low
                and self._high_since_low is not None
                and self.can_confirm(+1)):
            level_price, level_ts = self._last_low, self._last_low_ts
            pivot_price, pivot_ts = self._high_since_low, self._high_since_low_ts
            self.confirm(+1, pivot_price, pivot_ts)
            self._last_low    = None   # consumed — BoS can't re-fire at this level
            self._last_low_ts = None
            self._high_since_low = None
            self._high_since_low_ts = None
            e = MarkerEvent(
                tier            = self.tier,
                event_code      = _STR_BOS_CODES[-1],
                event_name      = f'{self.tier}LowBos',
                event_timestamp = signal_ts,
                pivot_price     = pivot_price,
                pivot_timestamp = pivot_ts,
                pivot_side      = +1,
                level_price     = level_price,
                level_timestamp = level_ts,
                level_side      = -1,
            )
            return [e], e

        # Bullish BoS: broken high level confirms the best opposite LOW in-segment
        if (self._last_high is not None
                and close > self._last_high
                and self._low_since_high is not None
                and self.can_confirm(-1)):
            level_price, level_ts = self._last_high, self._last_high_ts
            pivot_price, pivot_ts = self._low_since_high, self._low_since_high_ts
            self.confirm(-1, pivot_price, pivot_ts)
            self._last_high    = None   # consumed
            self._last_high_ts = None
            self._low_since_high = None
            self._low_since_high_ts = None
            e = MarkerEvent(
                tier            = self.tier,
                event_code      = _STR_BOS_CODES[+1],
                event_name      = f'{self.tier}HighBos',
                event_timestamp = signal_ts,
                pivot_price     = pivot_price,
                pivot_timestamp = pivot_ts,
                pivot_side      = -1,
                level_price     = level_price,
                level_timestamp = level_ts,
                level_side      = +1,
            )
            return [e], e

        return [], None


# ---------------------------------------------------------------------------
# Rolling 3-pivot window (ITR and LTR)
# ---------------------------------------------------------------------------

class _SwingTracker:
    """
    Detects a confirmed pivot from a stream of prices pushed by the tier below.
    Uses the shared _TierState for alternation gating — will not fire two
    consecutive pivots of the same side.

    Fires when the middle of the last 3 prices is a local extreme:
      high (+1): prev < mid  and  mid >= last
      low  (-1): prev > mid  and  mid <= last
    """

    def __init__(self, side: int) -> None:
        self._side = side
        self._prices:    deque = deque(maxlen=3)
        self._pivot_tss: deque = deque(maxlen=3)

    def push(
        self,
        price:     float,
        pivot_ts:  pd.Timestamp,
        signal_ts: pd.Timestamp,
        state:     _TierState,
    ) -> Optional[MarkerEvent]:
        self._prices.append(price)
        self._pivot_tss.append(pivot_ts)

        if len(self._prices) < 3:
            return None

        prev, mid, last = self._prices[0], self._prices[1], self._prices[2]
        mid_ts   = self._pivot_tss[1]
        side_str = 'High' if self._side == +1 else 'Low'

        matched = (
            (self._side == +1 and prev < mid and mid >= last) or
            (self._side == -1 and prev > mid and mid <= last)
        )
        if not matched or not state.can_confirm(self._side):
            return None

        state.confirm(self._side, mid, mid_ts)
        return MarkerEvent(
            tier            = state.tier,
            event_code      = _CONFIRMED_CODES[(state.tier, self._side)],
            event_name      = f'{state.tier}{side_str}Confirmed',
            event_timestamp = signal_ts,
            pivot_price     = mid,
            pivot_timestamp = mid_ts,
            pivot_side      = self._side,
        )


# ---------------------------------------------------------------------------
# Public: three-tier pivot detector
# ---------------------------------------------------------------------------

class MarkerEngine:
    """
    Three-tier pivot detector: STR → ITR → LTR.

    Two confirmation paths
    ----------------------
    N-bar window (on_bar)
        Natural detection: N-bar symmetric window on raw OHLC.
        N = marking.str_bars in config (odd ∈ [3,5,7,9,11,13]).

    STR BoS (break of structure)
        Close breaks a confirmed STR pivot level → immediately confirms the
        best opposite-side STR pivot inside the active segment.
        Fires once per alternation cycle (alternation gate is the guard).
        This STR BoS event then flows into ITR/LTR through the normal cascade.

    Bias-shift injection (on_bias_shift)
        External signal (FVG, sweep, ChoCh) forces a STR pivot without
        requiring the N-bar window.

    All three paths
    ---------------
    - Enforce alternation: no two consecutive confirmed pivots of the same side.
    - Cascade STR confirmed → ITR _SwingTracker → LTR _SwingTracker.
    - Higher-tier structural exception events are not defined here.

    bar_event_timestamp = bar that completes the pattern (safe to act on).
    bar_pivot_timestamp = where the pivot sits on the chart (location only).
    """

    def __init__(self, config: dict) -> None:
        marking = config.get('marking', {})
        n = int(marking.get('str_bars', 3))
        if n % 2 != 1 or n < 3:
            raise ValueError(f'str_bars must be odd and >= 3, got {n}')

        self._n   = n
        self._mid = n // 2

        self._highs: deque = deque(maxlen=n)
        self._lows:  deque = deque(maxlen=n)
        self._tss:   deque = deque(maxlen=n)

        self._str = _TierState('str')
        self._itr = _TierState('itr')
        self._ltr = _TierState('ltr')

        self._itr_high = _SwingTracker(+1)
        self._itr_low  = _SwingTracker(-1)
        self._ltr_high = _SwingTracker(+1)
        self._ltr_low  = _SwingTracker(-1)
        events_cfg = marking.get('events', {})
        self._confirmed_enabled = bool(events_cfg.get('confirmed_enabled', True))
        self._bos_enabled = bool(events_cfg.get('bos_enabled', False))

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def on_bar(self, row: pd.Series) -> list[MarkerEvent]:
        """
        Process one closed bar.

        Order:
          1. Collect STR BoS first (using pre-bar STR state).
          2. Emit STR BoS + cascade to ITR/LTR.
          3. N-bar STR pivot detection + cascade to ITR/LTR.
        """
        signal_ts = row.name
        close     = float(row['close'])

        self._highs.append(float(row['high']))
        self._lows.append(float(row['low']))
        self._tss.append(signal_ts)
        self._str.observe_bar(float(row['high']), float(row['low']), signal_ts)

        events: list[MarkerEvent] = []

        if self._bos_enabled:
            # 1. STR BoS → cascade to ITR/LTR
            str_bos_evts, str_bos = self._str.check_str_bos(close, signal_ts)
            events.extend(str_bos_evts)
            if str_bos:
                events.extend(self._cascade(str_bos, signal_ts))

        # 3. N-bar STR pivot detection
        if not self._confirmed_enabled or len(self._highs) < self._n:
            return events

        highs    = list(self._highs)
        lows     = list(self._lows)
        tss      = list(self._tss)
        m        = self._mid
        pivot_ts = tss[m]

        if highs[m] > max(highs[:m]) and highs[m] >= max(highs[m + 1:]):
            events.extend(self._confirm_str(+1, highs[m], pivot_ts, signal_ts))

        if lows[m] < min(lows[:m]) and lows[m] <= min(lows[m + 1:]):
            events.extend(self._confirm_str(-1, lows[m], pivot_ts, signal_ts))

        return events

    def on_bias_shift(
        self,
        side:      int,
        price:     float,
        pivot_ts:  pd.Timestamp,
        signal_ts: pd.Timestamp,
    ) -> list[MarkerEvent]:
        """
        Inject a STR pivot driven by an external event (FVG, sweep, ChoCh).
        Respects the alternation gate — silently ignored if same side as last confirmed.
        Cascades to ITR and LTR exactly like a natural pivot.
        """
        return self._confirm_str(side, price, pivot_ts, signal_ts)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _confirm_str(
        self,
        side:      int,
        price:     float,
        pivot_ts:  pd.Timestamp,
        signal_ts: pd.Timestamp,
    ) -> list[MarkerEvent]:
        if not self._str.can_confirm(side):
            return []

        side_str = 'High' if side == +1 else 'Low'
        self._str.confirm(side, price, pivot_ts)

        e = MarkerEvent(
            tier            = 'str',
            event_code      = _CONFIRMED_CODES[('str', side)],
            event_name      = f'str{side_str}Confirmed',
            event_timestamp = signal_ts,
            pivot_price     = price,
            pivot_timestamp = pivot_ts,
            pivot_side      = side,
        )
        return [e, *self._cascade(e, signal_ts)]

    def _cascade(
        self,
        str_event: MarkerEvent,
        signal_ts: pd.Timestamp,
    ) -> list[MarkerEvent]:
        """Feed a confirmed STR event into ITR, then ITR into LTR."""
        events = []

        tracker = self._itr_high if str_event.confirmed_type == +1 else self._itr_low
        itr_e   = tracker.push(str_event.pivot_price, str_event.pivot_timestamp,
                               signal_ts, self._itr)
        if itr_e:
            events.append(itr_e)
            ltr_tracker = self._ltr_high if itr_e.confirmed_type == +1 else self._ltr_low
            ltr_e = ltr_tracker.push(itr_e.pivot_price, itr_e.pivot_timestamp,
                                     signal_ts, self._ltr)
            if ltr_e:
                events.append(ltr_e)

        return events
