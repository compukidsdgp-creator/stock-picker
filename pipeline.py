"""
Daily pipeline. Run by GitHub Actions after market close.

  python pipeline.py

Universe: full NSE mainboard (EQUITY_L.csv). Cap it for testing with
  SWINGSCOPE_MAX=200 python pipeline.py

Catalysts: official NSE announcements feed first, Google News RSS fallback.

Writes:
  data/latest.csv            -> today's bucket (the app reads this)
  data/picks_YYYY-MM-DD.csv  -> dated archive
"""
from __future__ import annotations
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

import swingscope as ss
import universe
import nse_feed
import news

OUT_DIR = "data"


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")

    symbols = universe.fetch_universe()
    cap = os.getenv("SWINGSCOPE_MAX")
    if cap:
        symbols = symbols[: int(cap)]
        print(f"  capped universe to {len(symbols)} for this run")

    print(f"[{today}] fetching OHLCV for {len(symbols)} symbols ...")
    data = ss.fetch_ohlcv(symbols)
    print(f"  usable history for {len(data)} symbols")

    hits = ss.run_scans(data)
    print(f"  {len(hits)} names passed a scan")

    if hits.empty:
        pd.DataFrame().to_csv(f"{OUT_DIR}/latest.csv", index=False)
        print("  no hits today — wrote empty latest.csv")
        return

    # --- catalyst overlay: official NSE feed first, RSS fallback per name
    ann = nse_feed.fetch_announcements(days_back=2)
    tags, heads = [], []
    for sym in hits["ticker"]:
        if sym in ann:
            tags.append(ann[sym]["tag"])
            heads.append(ann[sym]["headline"])
        else:
            c = news.fetch_catalyst(sym)          # Google News RSS fallback
            tags.append(c["tag"])
            heads.append(c["headline"])
    hits["catalyst"] = tags
    hits["headline"] = heads

    hits["score"] = hits.apply(
        lambda r: ss.score_row(r, has_catalyst=bool(r["catalyst"])), axis=1
    )
    hits["date"] = today
    hits = hits.sort_values(["score", "rr"], ascending=False).reset_index(drop=True)

    cols = ["date", "ticker", "setups", "catalyst", "score", "entry", "stop",
            "target_1r", "target_2r", "rr", "rsi14", "vol_x_avg", "headline"]
    hits = hits[cols]

    hits.to_csv(f"{OUT_DIR}/latest.csv", index=False)
    hits.to_csv(f"{OUT_DIR}/picks_{today}.csv", index=False)
    print(f"  wrote {len(hits)} rows -> {OUT_DIR}/latest.csv")


if __name__ == "__main__":
    main()
