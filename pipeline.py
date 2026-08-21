"""
SwingScope — unified daily pipeline: scan -> score -> VET -> final TRUST list.

Run by GitHub Actions after close:
    python pipeline.py           # full market
    SWINGSCOPE_MAX=200 python pipeline.py   # capped, for testing

Writes:
  data/latest.csv    all scanned+scored names (the bucket)
  data/trusted.csv   score>=5 names run through the 5-stage hard gate;
                     verdict TRUST only if all gates pass
"""
from __future__ import annotations
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import yfinance as yf

import swingscope as ss
import universe
import nse_feed
import news
import vetting

OUT_DIR = "data"
TRUST_MIN_SCORE = 5


def _baseline() -> pd.DataFrame:
    try:
        return pd.read_csv("reference/risk_baseline.csv")
    except Exception:
        print("  (no reference/risk_baseline.csv — stage 3 vol percentile weakened)")
        return pd.DataFrame(columns=["symbol", "vol1y", "turnover_med", "max_dd"])


def _benchmark_ret126(data: dict) -> float:
    """Equal-weight universe 126-day return = the relative-strength benchmark
    (computed live from today's fetch, so it's current, not stale)."""
    rets = [df["close"].iloc[-1] / df["close"].iloc[-127] - 1
            for df in data.values() if len(df) > 127]
    return float(np.median(rets)) if rets else 0.0


def _info(sym: str) -> dict:
    try:
        return yf.Ticker(f"{sym}.NS").info or {}
    except Exception:
        return {}


def _vet(sym, df, row, base, index_ret126):
    r = {
        1: vetting.stage1_trend(df, index_ret126),
        2: vetting.stage2_fundamentals(_info(sym)),
        3: vetting.stage3_risk(df, base, sym),
        4: vetting.stage4_news(
            {"tag": row.get("catalyst"), "headline": row.get("headline")}
            if row.get("headline") else None),
    }
    return r, vetting.verdict(r)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")

    symbols = universe.fetch_universe()
    cap = os.getenv("SWINGSCOPE_MAX")
    if cap:
        symbols = symbols[: int(cap)]

    print(f"[{today}] fetching {len(symbols)} symbols ...")
    data = ss.fetch_ohlcv(symbols)
    print(f"  usable history for {len(data)} symbols")

    hits = ss.run_scans(data)
    print(f"  {len(hits)} names passed a scan")
    if hits.empty:
        pd.DataFrame().to_csv(f"{OUT_DIR}/latest.csv", index=False)
        pd.DataFrame().to_csv(f"{OUT_DIR}/trusted.csv", index=False)
        print("  no hits — wrote empty files")
        return

    # --- catalyst overlay (official NSE feed -> RSS fallback)
    ann = nse_feed.fetch_announcements(days_back=2)
    tags, heads = [], []
    for sym in hits["ticker"]:
        if sym in ann:
            tags.append(ann[sym]["tag"]); heads.append(ann[sym]["headline"])
        else:
            c = news.fetch_catalyst(sym); tags.append(c["tag"]); heads.append(c["headline"])
    hits["catalyst"], hits["headline"] = tags, heads

    hits["score"] = hits.apply(
        lambda r: ss.score_row(r, has_catalyst=bool(r["catalyst"])), axis=1)
    hits["date"] = today
    hits = hits.sort_values(["score", "rr"], ascending=False).reset_index(drop=True)
    hits[["date", "ticker", "setups", "catalyst", "score", "entry", "stop",
          "target_1r", "target_2r", "rr", "rsi14", "vol_x_avg", "headline"]
         ].to_csv(f"{OUT_DIR}/latest.csv", index=False)
    print(f"  wrote {len(hits)} -> data/latest.csv")

    # --- VET the score>=5 names through the 5-stage hard gate
    top = hits[hits["score"] >= TRUST_MIN_SCORE]
    print(f"  vetting {len(top)} names with score>={TRUST_MIN_SCORE} ...")
    base = _baseline()
    index_ret126 = _benchmark_ret126(data)

    vrows = []
    for _, row in top.iterrows():
        sym = row["ticker"]
        df = data.get(sym)
        if df is None or len(df) < 210:
            continue
        r, v = _vet(sym, df, row, base, index_ret126)
        vrows.append({
            "date": today, "ticker": sym, "score": int(row["score"]),
            "verdict": v["verdict"],
            "s1_trend": r[1][0], "s2_fund": r[2][0],
            "s3_risk": r[3][0], "s4_news": r[4][0],
            "entry": row["entry"], "stop": row["stop"],
            "target_1r": row["target_1r"], "target_2r": row["target_2r"],
            "why": v["why"], "headline": row["headline"],
        })

    vdf = pd.DataFrame(vrows).sort_values(
        ["verdict", "score"], ascending=[True, False])   # TRUST sorts before DROP
    vdf.to_csv(f"{OUT_DIR}/trusted.csv", index=False)
    n_trust = int((vdf["verdict"] == "TRUST").sum()) if not vdf.empty else 0
    print(f"  wrote {len(vdf)} vetted -> data/trusted.csv  ({n_trust} TRUST)")


if __name__ == "__main__":
    main()
