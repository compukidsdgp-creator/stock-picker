"""
Portfolio caps — the piece that stops your final list from being five
correlated names from one sector.

Given a ranked list of picks and a panel of recent daily returns, it greedily
keeps the highest-ranked names subject to two limits:
  • at most N per sector
  • no name too correlated with one already kept

This is the single biggest practical robustness win: one sector shock can't
take out half the book. Fully computable from the 20yr history — no network.
"""
from __future__ import annotations
import glob
import os
import pandas as pd


def build_returns(symbols: list[str], refdir: str, lookback: int = 252) -> pd.DataFrame:
    """Recent daily-return panel (date × symbol) from the 20yr CSVs."""
    cols = {}
    for sym in symbols:
        f = os.path.join(refdir, f"{sym}_NS_1d.csv")
        if not os.path.exists(f):
            continue
        d = (pd.read_csv(f, parse_dates=["Date"]).rename(columns=str.lower)
             .dropna(subset=["adj close"]).set_index("date").sort_index())
        cols[sym] = d["adj close"].pct_change().tail(lookback)
    return pd.DataFrame(cols)


def apply_caps(picks: pd.DataFrame, returns: pd.DataFrame,
               max_per_sector: int = 2, max_corr: float = 0.75,
               rank_col: str = "score"):
    """Greedy diversify. picks needs columns: symbol, sector, <rank_col>.
    Returns (kept_df, dropped_log)."""
    corr = returns.corr() if not returns.empty else pd.DataFrame()
    kept, dropped, sec_count = [], [], {}

    for _, r in picks.sort_values(rank_col, ascending=False).iterrows():
        sym, sec = r["symbol"], r.get("sector", "—")
        if sec_count.get(sec, 0) >= max_per_sector:
            dropped.append({"symbol": sym, "reason": f"sector cap ({sec})"})
            continue
        clash = None
        for k in kept:
            if sym in corr.index and k in corr.columns:
                c = corr.loc[sym, k]
                if pd.notna(c) and c > max_corr:
                    clash = (k, round(float(c), 2)); break
        if clash:
            dropped.append({"symbol": sym,
                            "reason": f"corr {clash[1]} with {clash[0]}"})
            continue
        kept.append(sym)
        sec_count[sec] = sec_count.get(sec, 0) + 1

    kept_df = picks[picks["symbol"].isin(kept)].copy()
    return kept_df, pd.DataFrame(dropped)
