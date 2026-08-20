"""
Universe — the list of symbols to scan.

Pulls NSE's official equity master (EQUITY_L.csv), filters by series, and
caches it so we don't re-download every run. Falls back to the small
built-in list in swingscope.py if NSE is unreachable.

Series meaning: EQ = normal mainboard rolling settlement (what you want for
swing trading). BE = trade-to-trade. SM/ST = SME. Default keeps EQ only.
"""
from __future__ import annotations
import io
import os
import pandas as pd
import requests

from swingscope import UNIVERSE as FALLBACK

EQUITY_L = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
CACHE = "data/universe.csv"


def fetch_universe(series=("EQ",), use_cache: bool = True) -> list[str]:
    os.makedirs("data", exist_ok=True)

    if use_cache and os.path.exists(CACHE):
        try:
            syms = pd.read_csv(CACHE)["symbol"].dropna().tolist()
            if syms:
                print(f"  universe: {len(syms)} symbols (cached)")
                return syms
        except Exception:
            pass

    try:
        r = requests.get(EQUITY_L, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.BytesIO(r.content))
        df.columns = [c.strip() for c in df.columns]        # headers have spaces
        df["SERIES"] = df["SERIES"].astype(str).str.strip()
        syms = (df[df["SERIES"].isin(series)]["SYMBOL"]
                .astype(str).str.strip().tolist())
        pd.DataFrame({"symbol": syms}).to_csv(CACHE, index=False)
        print(f"  universe: {len(syms)} symbols (fresh from NSE)")
        return syms
    except Exception as e:
        print(f"  universe fetch failed ({e}); using built-in fallback list")
        return list(FALLBACK)
