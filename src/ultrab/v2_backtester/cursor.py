# cursor.py — time-lapse forward walker
#
# Decision clock:  each closed entry-TF bar (15m)
# Execution clock: 1m bars for TP/SL exit resolution (optional; falls back
#                  to bar high/low range when 1m data is not provided)
#
# Per-bar sequence
# ----------------
# 1. Fill pending entry at this bar's open  (trade from prior bar's signal)
# 2. Walk 1m bars within this bar to resolve exits chronologically
#    (or use bar high/low range if 1m not available)
# 3. Evaluate signals via engine.on_bar()
# 4. Run policy to select accepted candidate
# 5. Queue as pending_entry for next bar fill
#
# The cursor never looks ahead. Each step only uses data available at
# that point in simulated time.
#
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional, Callable, TYPE_CHECKING

from ultrab.v2_backtester.strategy import resolve_sl_tp
from ultrab.v2_backtester.features import compute_regime

if TYPE_CHECKING:
    from ultrab.v2_backtester.engine import InstrumentEngine, Trade
    from ultrab.v2_backtester.ledger_trade import TradeLedger

# Context columns attached by align() with 'ctx_' prefix
_CTX_PREFIX = 'ctx_'

# Columns that must exist in feature_row (entry-TF features)
_REQUIRED_FEATURE_COLS = {
    'open', 'high', 'low', 'close',
    'st_dir', 'st_line', 'st_step_count',
    'ema3', 'ema3_prev', 'ema20', 'ema20_prev',
    'ema3_lag1', 'ema3_lag2', 'ema3_lag3',
    'close_prev', 'rsi30', 'session',
    'ctx_st_dir',
}

# Context columns forwarded to engine (stripped of prefix)
_CTX_COLS = {'st_dir', 'st_line', 'st_flip'}


class _ContextRow:
    """Lightweight view over ctx_ columns without per-bar Series allocation."""

    __slots__ = ('_row',)

    def __init__(self, row: pd.Series) -> None:
        self._row = row

    def __getitem__(self, key: str):
        return self._row[f'{_CTX_PREFIX}{key}']

    def get(self, key: str, default=None):
        col = f'{_CTX_PREFIX}{key}'
        try:
            return self._row[col]
        except KeyError:
            return default


class Cursor:
    """
    Forward walker for a single instrument.

    Usage
    -----
    cursor = Cursor(
        engine    = engine,
        policy_fn = policy.policy_2,
        ledger    = ledger,
        config    = config,
        df_1m     = df_1m,   # optional
    )
    cursor.run(df_aligned)
    """

    def __init__(
        self,
        engine:     InstrumentEngine,
        policy_fn:  Callable,
        ledger:     TradeLedger,
        config:     dict,
        df_1m:      Optional[pd.DataFrame] = None,
    ) -> None:
        self.engine    = engine
        self.policy_fn = policy_fn
        self.ledger    = ledger
        self.config    = config
        self.df_1m     = df_1m

        # Pending candidates waiting for next bar's open to fill entry price.
        # Policy 1 can queue multiple independent entries from the same bar.
        self._pending: list[dict] = []

        # Precompute 1m index for fast range lookups
        self._1m_index: Optional[pd.DatetimeIndex] = (
            df_1m.index if df_1m is not None else None
        )
        self._1m_ns: Optional[np.ndarray] = None
        self._1m_high: Optional[np.ndarray] = None
        self._1m_low: Optional[np.ndarray] = None
        if df_1m is not None:
            self._1m_ns = df_1m.index.view('int64')
            self._1m_high = df_1m['high'].to_numpy(dtype=float)
            self._1m_low = df_1m['low'].to_numpy(dtype=float)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self, df_aligned: pd.DataFrame) -> list[Trade]:
        """
        Walk forward through the aligned entry-TF DataFrame.

        Parameters
        ----------
        df_aligned : pd.DataFrame
            Output of align() — entry-TF features + ctx_ context features,
            with regime column added by compute_regime().
            Index: DatetimeIndex (UTC entry-TF bar close times).

        Returns
        -------
        list[Trade]
            All closed trades from engine.trade_log.
        """
        if 'regime' not in df_aligned.columns:
            df_aligned = df_aligned.copy()
            df_aligned['regime'] = compute_regime(df_aligned)

        prev_bar_time: Optional[pd.Timestamp] = None

        for bar_time, row in df_aligned.iterrows():
            # Skip warm-up rows (indicators not yet valid)
            if _has_nan_features(row, _REQUIRED_FEATURE_COLS):
                prev_bar_time = bar_time
                continue

            feature_row  = row
            context_row  = _ContextRow(row)
            bar_open     = float(row['open'])

            # 1. Fill pending entry from prior bar's signal at this bar's open
            if self._pending:
                self._fill_pending(bar_time, bar_open, feature_row, context_row)

            # 2. Resolve exits
            if self.df_1m is not None and prev_bar_time is not None:
                # Use 1m bars within this bar's time window
                self._exit_via_1m(bar_time, prev_bar_time)
            else:
                # Fallback: bar high/low range (SL wins on same-bar conflict)
                closed = self.engine.check_exits(
                    bar_time, float(row['high']), float(row['low'])
                )
                for trade in closed:
                    self.ledger.log_trade(trade)

            # 3. Signal evaluation — engine updates state and returns candidates
            candidates = self.engine.on_bar(feature_row, context_row)

            # 4. Policy — select one (or more for P1) accepted candidates
            if candidates:
                accepted_list = self._run_policy(candidates)

                for accepted in accepted_list:
                    hyp       = accepted['hypothesis']
                    direction = accepted['direction']

                    self.ledger.log_signal(
                        bar_time  = bar_time,
                        candidate = accepted,
                        decision  = 'accepted',
                        engine    = self.engine,
                    )

                    self.engine.accept_candidate(accepted)
                    self._pending.append(accepted)

                # Log skipped candidates (those not accepted)
                accepted_hyps = {a['hypothesis'] for a in accepted_list}
                for c in candidates:
                    if c['hypothesis'] not in accepted_hyps:
                        skip_reason = c.get('_policy_skip_reason', '')
                        if not skip_reason and accepted_list:
                            skip_reason = 'same_bar_priority_lost'
                        self.ledger.log_signal(
                            bar_time  = bar_time,
                            candidate = c,
                            decision  = 'skipped',
                            engine    = self.engine,
                            skip_reason = skip_reason,
                        )

            prev_bar_time = bar_time

        return self.engine.trade_log

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fill_pending(
        self,
        bar_time:    pd.Timestamp,
        entry_price: float,
        feature_row: pd.Series,
        context_row: pd.Series,
    ) -> None:
        """Fill the pending candidate at this bar's open price."""
        pending = self._pending
        self._pending = []

        for raw_candidate in pending:
            candidate = resolve_sl_tp(raw_candidate, entry_price)
            trade = self.engine.make_trade(
                hypothesis      = candidate['hypothesis'],
                direction       = candidate['direction'],
                entry_time      = bar_time,
                entry_price     = entry_price,
                sl              = candidate['sl'],
                tp              = candidate['tp'],
                is_reentry      = False,
                is_stacked      = len(self.engine.open_trades) > 0,
                conflict_winner = candidate.get('conflict_winner'),
            )
            self.engine.open_trade(trade)
            self.ledger.log_entry(trade, candidate)

    def _exit_via_1m(
        self,
        bar_close_time: pd.Timestamp,
        prev_bar_close: pd.Timestamp,
    ) -> None:
        """
        Walk 1m bars within the current entry-TF bar's time window.

        Window: (prev_bar_close, bar_close_time]
        Each 1m bar checks TP/SL in chronological order.
        This resolves same-bar TP+SL ambiguity correctly.
        """
        if not self.engine.open_trades:
            return

        start = np.searchsorted(self._1m_ns, prev_bar_close.value, side='right')
        stop = np.searchsorted(self._1m_ns, bar_close_time.value, side='right')

        for i in range(start, stop):
            closed = self.engine.check_exits(
                pd.Timestamp(self._1m_ns[i], tz='UTC'),
                self._1m_high[i],
                self._1m_low[i],
            )
            for trade in closed:
                self.ledger.log_trade(trade)

    def _run_policy(self, candidates: list[dict]) -> list[dict]:
        """
        Call the configured policy function and normalise the result to a list.
        Policy 1 returns list[dict]; Policy 2/3 return dict | None.
        """
        result = self.policy_fn(candidates, self.engine, self.config)

        if result is None:
            return []
        if isinstance(result, dict):
            return [result]
        return result   # already a list (Policy 1)


# ---------------------------------------------------------------------------
# Row extraction helpers
# ---------------------------------------------------------------------------

def _extract_feature_row(row: pd.Series) -> pd.Series:
    """Return entry-TF columns only (drop ctx_ prefixed columns)."""
    cols = [c for c in row.index if not c.startswith(_CTX_PREFIX)]
    return row[cols]


def _extract_context_row(row: pd.Series) -> pd.Series:
    """
    Return context columns with the ctx_ prefix stripped.
    e.g. 'ctx_st_dir' → 'st_dir'
    """
    ctx_cols = {c: c[len(_CTX_PREFIX):] for c in row.index if c.startswith(_CTX_PREFIX)}
    return row[list(ctx_cols.keys())].rename(ctx_cols)


def _has_nan_features(row: pd.Series, required: set) -> bool:
    """True if any required feature column is NaN on this row."""
    for col in required:
        if col in row.index and pd.isna(row[col]):
            return True
    return False
