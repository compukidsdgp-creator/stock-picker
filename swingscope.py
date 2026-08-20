"""
SwingScope core — data, indicators, scans, scoring.

Everything here is deterministic: given the same OHLCV, it returns the same
list. The scans mirror the Chartink recipes S1-S4 from the playbook.
"""
from __future__ import annotations
import time
import pandas as pd
import numpy as np
import yfinance as yf

# ---------------------------------------------------------------- universe
# Start small; expand freely. To use the whole market, download NSE's
# EQUITY_L.csv and load its SYMBOL column instead of this list.
UNIVERSE = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "LT", "SBIN",
    "AXISBANK", "KOTAKBANK", "BHARTIARTL", "ITC", "HINDUNILVR", "BAJFINANCE",
    "MARUTI", "SUNPHARMA", "TITAN", "TATAMOTORS", "TATASTEEL", "ADANIENT",
    "ADANIPORTS", "POWERGRID", "NTPC", "ONGC", "COALINDIA", "WIPRO",
    "HCLTECH", "TECHM", "ULTRACEMCO", "GRASIM", "JSWSTEEL", "HINDALCO",
    "DIVISLAB", "DRREDDY", "CIPLA", "NESTLEIND", "BRITANNIA", "TATACONSUM",
    "HDFCLIFE", "SBILIFE", "BAJAJFINSV", "EICHERMOT", "HEROMOTOCO",
    "M&M", "PIDILITIND", "DMART", "TRENT", "SIEMENS", "ABB", "SYRMA",
    "LAURUSLABS", "HFCL", "NETWEB", "ADANIENSOL",
]

PRICE_FLOOR = 100.0          # ignore sub-100 names
TURNOVER_FLOOR = 5.0e7       # 5 crore daily traded value = "liquid enough"


# ---------------------------------------------------------------- data
def fetch_ohlcv(symbols: list[str], period: str = "2y",
                chunk: int = 100, pause: float = 1.0) -> dict[str, pd.DataFrame]:
    """Download daily OHLCV for each symbol, in chunks so a full-market run
    doesn't trip Yahoo's rate limits. Returns {symbol: DataFrame}.

    ~2000 names takes several minutes — fine inside a scheduled job.
    """
    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), chunk):
        batch = symbols[i:i + chunk]
        tickers = [f"{s}.NS" for s in batch]
        try:
            raw = yf.download(
                tickers=tickers, period=period, interval="1d",
                group_by="ticker", auto_adjust=False, threads=True, progress=False,
            )
        except Exception as e:
            print(f"  chunk {i // chunk} download failed: {e}")
            continue
        for s, t in zip(batch, tickers):
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = df.dropna(subset=["Close"]).rename(columns=str.lower)
                if len(df) >= 210:           # need enough for EMA200 / 250-max
                    out[s] = df
            except Exception:
                continue
        time.sleep(pause)                    # be polite between chunks
    return out


# ---------------------------------------------------------------- indicators
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    gain = d.clip(lower=0)
    loss = -d.clip(upper=0)
    ag = gain.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    al = loss.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)

def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["ema20"] = ema(d["close"], 20)
    d["ema50"] = ema(d["close"], 50)
    d["ema200"] = ema(d["close"], 200)
    d["vol_sma20"] = sma(d["volume"], 20)
    d["rsi14"] = rsi(d["close"], 14)
    d["hh40_prev"] = d["high"].shift(1).rolling(40).max()   # 40-day high, excl. today
    d["hh250"] = d["high"].rolling(250).max()
    d["ll10"] = d["low"].rolling(10).min()
    d["hh20"] = d["high"].rolling(20).max()
    return d


# ---------------------------------------------------------------- scans
# Each returns True if the LATEST bar passes. Names mirror playbook S1-S4.
def _s1_momentum_breakout(r) -> bool:
    return (r.close > r.ema20 and r.ema20 > r.ema50 and r.close > r.hh40_prev
            and r.rsi14 > 55 and r.volume > r.vol_sma20 and r.close > PRICE_FLOOR)

def _s2_tight_base(r) -> bool:
    return (r.close > 0.92 * r.hh250 and r.close > r.ema50
            and r.volume < r.vol_sma20 and r.close > PRICE_FLOOR)

def _s3_volume_shock(r) -> bool:
    return (r.volume > 2 * r.vol_sma20 and r.close > r.open
            and r.close > r.prev_close and r.close > PRICE_FLOOR)

def _s4_pullback(r) -> bool:
    return (r.ema20 > r.ema50 and r.ema50 > r.ema200
            and r.low <= r.ema20 * 1.02 and r.close > r.ema20
            and 40 < r.rsi14 < 62 and r.close > PRICE_FLOOR)

SCANS = {"S1": _s1_momentum_breakout, "S2": _s2_tight_base,
         "S3": _s3_volume_shock, "S4": _s4_pullback}


def run_scans(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Evaluate all scans on the latest bar of every symbol. One row per hit."""
    rows = []
    for sym, df in data.items():
        d = _enrich(df)
        if d[["ema200", "hh250"]].iloc[-1].isna().any():
            continue
        r = d.iloc[-1].copy()
        r["prev_close"] = d["close"].iloc[-2]
        hits = [name for name, fn in SCANS.items() if fn(r)]
        if not hits:
            continue

        entry = float(r.close)
        stop = float(min(r.ll10, r.ema20))          # swing low or 20 EMA
        risk = max(entry - stop, 1e-6)
        rr = (float(r.hh20) - entry) / risk         # reward:risk to 20-day high
        rows.append({
            "ticker": sym,
            "setups": "+".join(hits),
            "close": round(entry, 2),
            "entry": round(entry, 2),
            "stop": round(stop, 2),
            "target_1r": round(entry + risk, 2),
            "target_2r": round(entry + 2 * risk, 2),
            "rsi14": round(float(r.rsi14), 1),
            "vol_x_avg": round(float(r.volume / r.vol_sma20), 2),
            "turnover": float(r.close * r.volume),
            "rr": round(rr, 2),
            "above_20_50": bool(r.close > r.ema20 and r.close > r.ema50),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- score
def score_row(r: pd.Series, has_catalyst: bool) -> int:
    """0-5 go/no-go score from the playbook scorecard."""
    pts = 0
    pts += int(bool(r["above_20_50"]))          # 1 trend
    pts += int(r["vol_x_avg"] > 1.0)            # 2 volume
    pts += int(bool(has_catalyst))              # 3 catalyst
    pts += int(r["rr"] >= 2.0)                  # 4 reward:risk
    pts += int(r["turnover"] > TURNOVER_FLOOR)  # 5 liquidity
    return pts
