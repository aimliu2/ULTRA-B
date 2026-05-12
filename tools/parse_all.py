"""
Parse all MT5 CSVs in big-data/chartData → parquet in big-data/mlData/raw/{SYMBOL}/
"""

import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART_DATA = ROOT / "big-data" / "chartData"
ML_RAW = ROOT / "big-data" / "mlData" / "raw"

TF_MAP = {
    "Daily": "1d",
    "H4": "4h",
    "H1": "1h",
    "M15": "15m",
    "M5": "5m",
    "M1": "1m",
}

SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "GBPJPY", "USDJPY", "EURJPY", "XAUUSD"]


def parse_mt5_csv(filepath: Path, timezone_offset_hours: int = 0) -> pd.DataFrame:
    raw = pd.read_csv(filepath, sep='\t', nrows=2)
    has_time = '<TIME>' in list(raw.columns)

    df = pd.read_csv(filepath, sep='\t')
    df.columns = [c.strip('<>').lower() for c in df.columns]

    if has_time:
        df['timestamp'] = pd.to_datetime(
            df['date'].astype(str) + ' ' + df['time'].astype(str),
            format='%Y.%m.%d %H:%M:%S'
        )
    else:
        df['timestamp'] = pd.to_datetime(df['date'], format='%Y.%m.%d')

    if timezone_offset_hours != 0:
        df['timestamp'] = df['timestamp'] - pd.Timedelta(hours=timezone_offset_hours)

    df = df.rename(columns={'tickvol': 'tick_vol'})
    keep = ['timestamp', 'open', 'high', 'low', 'close', 'tick_vol', 'spread']
    df = df[keep].copy()
    df['bar_close_bull'] = df['close'] > df['open']

    for col in ['open', 'high', 'low', 'close']:
        df[col] = df[col].astype(float)
    df['tick_vol'] = df['tick_vol'].astype(int)

    return df.sort_values('timestamp').reset_index(drop=True)


def main():
    for symbol in SYMBOLS:
        out_dir = ML_RAW / symbol
        out_dir.mkdir(parents=True, exist_ok=True)

        for tf_raw, tf_label in TF_MAP.items():
            pattern = f"{symbol}_{tf_raw}_*.csv"
            matches = list(CHART_DATA.glob(pattern))
            if not matches:
                print(f"  SKIP  {symbol} {tf_raw} — no file found")
                continue

            csv_path = matches[0]
            out_path = out_dir / f"{symbol}-sorted-{tf_label}.parquet"

            df = parse_mt5_csv(csv_path)
            df.to_parquet(out_path, index=False)
            print(f"  OK    {symbol} {tf_raw:6s} → {out_path.name}  ({len(df):,} bars)")


if __name__ == "__main__":
    main()
