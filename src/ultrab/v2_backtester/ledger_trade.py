# ledger_trade.py — trade event ledger
#
# Records every signal, decision, and trade outcome chronologically.
# Writes two CSV files per run into studies-trade-logs/:
#
#   {symbol}_{run_id}_signals.csv   — candidate + decision events (one row per signal)
#   {symbol}_{run_id}_trades.csv    — trade lifecycle events (one row per closed trade)
#
# Decision clock: entry-TF bar close (15m)
# Execution clock: 1m bars (TP/SL resolution), handled by cursor.py
#
from __future__ import annotations

import csv
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ultrab.v2_backtester.engine import InstrumentEngine, Trade

# Output directory
_LOG_DIR = Path(__file__).parent.parent / 'studies-trade-logs'


# ---------------------------------------------------------------------------
# Column schemas
# ---------------------------------------------------------------------------

_SIGNAL_COLS = [
    # When
    'bar_time',
    # What fired
    'symbol',
    'branch',
    'phase',
    'entry_timeframe',
    'context_timeframe',
    'hypothesis',
    'direction',
    'trigger_type',
    # Context at signal time
    'context_dir',
    'of_direction',
    'a1_ctx_valid',
    'a2_of_gate',
    'regime',
    'session',
    # Trade parameters (known at signal bar)
    'signal_ema20',
    'signal_st_line',
    # Decision
    'decision',           # 'accepted' | 'skipped'
    'skip_reason',        # populated on skip
    'policy',             # 'P1' | 'P2' | 'P3' | ''
    'allow_stack',
    # Engine state snapshot at decision time
    'open_trade_count',
    'in_cooldown',
    'choch_confirmed',
    'choch_direction',
    'choch_level',
    'pivot_count',
    'last_high',
    'last_low',
    'new_extreme_flag',
    'sb_used',
]

_TRADE_COLS = [
    # Identity
    'trade_id',
    'symbol',
    'branch',
    'phase',
    'entry_timeframe',
    'context_timeframe',
    'hypothesis',
    'direction',
    'trigger_type',
    # Entry
    'entry_time',
    'entry_price',
    'sl',
    'tp',
    'sl_pips',
    # Exit
    'exit_time',
    'exit_price',
    'exit_reason',       # 'tp' | 'sl'
    'r_result',
    # Flags
    'is_stacked',
    'is_reentry',
    'conflict_winner',
    # Context
    'context_dir',
    'of_direction',
    'regime_at_entry',
    'session_at_entry',
    'policy',
    'allow_stack',
]


# ---------------------------------------------------------------------------
# TradeLedger
# ---------------------------------------------------------------------------

class TradeLedger:
    """
    Append-only event recorder for one backtest run.

    Create one instance per run. Call log_signal(), log_entry(), log_trade()
    during the cursor walk. Call save() at the end.
    """

    def __init__(
        self,
        symbol:     str,
        run_id:     Optional[str] = None,
        log_dir:    Optional[Path] = None,
        pip_size:   float = 0.0001,   # EURUSD / GBPUSD etc.
    ) -> None:
        self.symbol   = symbol
        self.run_id   = run_id or _make_run_id()
        self.log_dir  = Path(log_dir) if log_dir else _LOG_DIR
        self.pip_size = pip_size

        self._signals: list[dict] = []
        self._trades:  list[dict] = []

        # Carry forward signal context to the trade record when the entry fills
        # keyed by trade_id (set at fill time)
        self._pending_context: dict = {}

    # ------------------------------------------------------------------
    # Logging methods called by cursor
    # ------------------------------------------------------------------

    def log_signal(
        self,
        bar_time:  object,
        candidate: dict,
        decision:  str,
        engine:    InstrumentEngine,
        skip_reason: str = '',
    ) -> None:
        """
        Record a candidate signal and the policy decision made on it.
        Called once per fired hypothesis per bar.
        """
        snap = engine.snapshot()
        row  = {
            'bar_time':        _fmt_ts(bar_time),
            'symbol':          self.symbol,
            'branch':          candidate.get('branch', ''),
            'phase':           candidate.get('phase', ''),
            'entry_timeframe':  candidate.get('entry_timeframe', ''),
            'context_timeframe': candidate.get('context_timeframe', ''),
            'hypothesis':      candidate.get('hypothesis', ''),
            'direction':       candidate.get('direction', ''),
            'trigger_type':    candidate.get('trigger_type', ''),
            'context_dir':     candidate.get('context_dir', ''),
            'of_direction':    candidate.get('of_direction', ''),
            'a1_ctx_valid':    candidate.get('a1_ctx_valid', ''),
            'a2_of_gate':      candidate.get('a2_of_gate', ''),
            'regime':          candidate.get('regime', ''),
            'session':         candidate.get('session', ''),
            'signal_ema20':    candidate.get('_ema20', ''),
            'signal_st_line':  candidate.get('_st_line', ''),
            'decision':        decision,
            'skip_reason':     skip_reason,
            'policy':          candidate.get('policy', ''),
            'allow_stack':     candidate.get('allow_stack', ''),
            # Engine state
            'open_trade_count': snap['open_trade_count'],
            'in_cooldown':      snap['in_cooldown'],
            'choch_confirmed':  snap['choch_confirmed'],
            'choch_direction':  snap['choch_direction'],
            'choch_level':      snap['choch_level'],
            'pivot_count':      snap['pivot_count'],
            'last_high':        snap['last_high'],
            'last_low':         snap['last_low'],
            'new_extreme_flag': snap['new_extreme_flag'],
            'sb_used':          snap['sb_used'],
        }
        self._signals.append(row)

        # Cache context for the trade record when this accepted candidate fills
        if decision == 'accepted':
            self._pending_context = {
                'regime_at_entry':  candidate.get('regime', ''),
                'session_at_entry': candidate.get('session', ''),
                'policy':           candidate.get('policy', ''),
                'allow_stack':      candidate.get('allow_stack', ''),
                'trigger_type':     candidate.get('trigger_type', ''),
                'context_dir':      candidate.get('context_dir', ''),
                'of_direction':     candidate.get('of_direction', ''),
                'branch':           candidate.get('branch', ''),
                'phase':            candidate.get('phase', ''),
                'entry_timeframe':  candidate.get('entry_timeframe', ''),
                'context_timeframe': candidate.get('context_timeframe', ''),
            }

    def log_entry(self, trade: Trade, candidate: Optional[dict] = None) -> None:
        """
        Called by cursor when a pending entry fills (next bar open).
        Stores partial trade row; completed in log_trade() on exit.
        """
        ctx = (
            {
                'regime_at_entry':  candidate.get('regime', ''),
                'session_at_entry': candidate.get('session', ''),
                'policy':           candidate.get('policy', ''),
                'allow_stack':      candidate.get('allow_stack', ''),
                'trigger_type':     candidate.get('trigger_type', ''),
                'context_dir':      candidate.get('context_dir', ''),
                'of_direction':     candidate.get('of_direction', ''),
                'branch':           candidate.get('branch', ''),
                'phase':            candidate.get('phase', ''),
                'entry_timeframe':  candidate.get('entry_timeframe', ''),
                'context_timeframe': candidate.get('context_timeframe', ''),
            }
            if candidate is not None
            else self._pending_context
        )
        self._trades.append({
            'trade_id':         trade.trade_id,
            'symbol':           trade.symbol,
            'branch':           ctx.get('branch', getattr(trade, 'branch', '')),
            'phase':            ctx.get('phase', getattr(trade, 'phase', '')),
            'entry_timeframe':   ctx.get('entry_timeframe', getattr(trade, 'entry_timeframe', '')),
            'context_timeframe': ctx.get('context_timeframe', getattr(trade, 'context_timeframe', '')),
            'hypothesis':       trade.hypothesis,
            'direction':        trade.direction,
            'trigger_type':     ctx.get('trigger_type', ''),
            'entry_time':       _fmt_ts(trade.entry_time),
            'entry_price':      trade.entry_price,
            'sl':               trade.sl,
            'tp':               trade.tp,
            'sl_pips':          round(trade.sl_distance / self.pip_size, 1),
            'exit_time':        '',
            'exit_price':       '',
            'exit_reason':      '',
            'r_result':         '',
            'is_stacked':       trade.is_stacked,
            'is_reentry':       trade.is_reentry,
            'conflict_winner':  trade.conflict_winner or '',
            'context_dir':      ctx.get('context_dir', ''),
            'of_direction':     ctx.get('of_direction', ''),
            'regime_at_entry':  ctx.get('regime_at_entry', ''),
            'session_at_entry': ctx.get('session_at_entry', ''),
            'policy':           ctx.get('policy', ''),
            'allow_stack':      ctx.get('allow_stack', ''),
        })

    def log_trade(self, trade: Trade) -> None:
        """
        Called by cursor when a trade closes (TP or SL hit).
        Finds the existing entry row and fills in exit fields.
        """
        for row in reversed(self._trades):
            if row['trade_id'] == trade.trade_id and row['exit_time'] == '':
                row['exit_time']   = _fmt_ts(trade.exit_time)
                row['exit_price']  = trade.exit_price
                row['exit_reason'] = trade.exit_reason
                row['r_result']    = round(trade.r_result, 4) if trade.r_result is not None else ''
                break

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> tuple[Path, Path]:
        """
        Write signals and trades CSVs to studies-trade-logs/.

        Returns
        -------
        (signals_path, trades_path)
        """
        self.log_dir.mkdir(parents=True, exist_ok=True)

        signals_path = self.log_dir / f'{self.symbol}_{self.run_id}_signals.csv'
        trades_path  = self.log_dir / f'{self.symbol}_{self.run_id}_trades.csv'

        _write_csv(signals_path, _SIGNAL_COLS, self._signals)
        _write_csv(trades_path,  _TRADE_COLS,  self._trades)

        return signals_path, trades_path

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """
        Quick performance summary from the closed trade log.
        Returns a dict of key metrics for console printing.
        """
        closed = [r for r in self._trades if r['exit_reason'] != '']

        if not closed:
            return {'trades': 0}

        r_vals = [float(r['r_result']) for r in closed if r['r_result'] != '']
        wins   = [r for r in r_vals if r > 0]
        losses = [r for r in r_vals if r < 0]

        total_win  = sum(wins)
        total_loss = abs(sum(losses))
        pf         = total_win / total_loss if total_loss > 0 else float('inf')
        win_rate   = len(wins) / len(r_vals) if r_vals else 0.0
        ev         = sum(r_vals) / len(r_vals) if r_vals else 0.0
        max_dd     = _max_drawdown(r_vals)

        by_hyp = {}
        for hyp in ('A1', 'A2', 'B'):
            h_trades = [r for r in closed if r['hypothesis'] == hyp]
            h_r      = [float(r['r_result']) for r in h_trades if r['r_result'] != '']
            h_wins   = [r for r in h_r if r > 0]
            h_loss   = abs(sum(r for r in h_r if r < 0))
            if not h_trades:
                h_pf = None
            elif h_loss > 0:
                h_pf = round(sum(h_wins) / h_loss, 4)
            else:
                h_pf = None
            by_hyp[hyp] = {'trades': len(h_trades), 'pf': h_pf}

        return {
            'trades':     len(closed),
            'pf':         round(pf, 4),
            'win_rate':   round(win_rate, 4),
            'ev_per_R':   round(ev, 4),
            'total_R':    round(sum(r_vals), 2),
            'max_drawdown_R': round(max_dd, 4),
            'by_hyp':     by_hyp,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run_id() -> str:
    """Short unique run ID: YYYYMMDD_HHMMSS_<4-char uuid>"""
    now = datetime.now(timezone.utc)
    return now.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:4]


def _fmt_ts(ts: object) -> str:
    if ts is None:
        return ''
    if isinstance(ts, str):
        return ts
    return str(ts)


def _write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def _max_drawdown(r_vals: list[float]) -> float:
    """Closed-trade max drawdown in R from a sequence of realised results."""
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in r_vals:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd
