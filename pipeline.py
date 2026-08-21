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
import fundamentals as Fu
import india_signals as I
import portfolio as P

OUT_DIR = "data"
TRUST_MIN_SCORE = 5

# Robustness knobs (env-overridable). Advisory gates fail only on a CONFIRMED
# red flag; missing free data never drops a name.
FS_FLOOR = int(os.getenv("SWINGSCOPE_FSCORE_MIN", "4"))    # confirmed-weak below this
DELIV_FLOOR = float(os.getenv("SWINGSCOPE_DELIV_MIN", "25"))
PLEDGE_CSV = os.getenv("SWINGSCOPE_PLEDGE_CSV")            # optional pledge data
MAX_PER_SECTOR = int(os.getenv("SWINGSCOPE_MAX_SECTOR", "2"))
MAX_CORR = float(os.getenv("SWINGSCOPE_MAX_CORR", "0.75"))


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


def _vet(sym, df, row, base, index_ret126, info):
    r = {
        1: vetting.stage1_trend(df, index_ret126),
        2: vetting.stage2_fundamentals(info),
        3: vetting.stage3_risk(df, base, sym),
        4: vetting.stage4_news(
            {"tag": row.get("catalyst"), "headline": row.get("headline")}
            if row.get("headline") else None),
    }
    return r, vetting.verdict(r)


def _returns_panel(symbols, data, lookback=252) -> pd.DataFrame:
    """Recent daily-return panel from the in-memory 2yr fetch (for corr caps)."""
    cols = {}
    for s in symbols:
        df = data.get(s)
        if df is not None and len(df) > lookback:
            cols[s] = df["close"].pct_change().tail(lookback)
    return pd.DataFrame(cols)


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

    # --- VET the score>=5 names through the 5-stage hard gate + robustness
    top = hits[hits["score"] >= TRUST_MIN_SCORE]
    print(f"  vetting {len(top)} names with score>={TRUST_MIN_SCORE} ...")
    base = _baseline()
    index_ret126 = _benchmark_ret126(data)

    # batched advisory data (one pass each, only for the top names)
    cand = list(top["ticker"])
    delivery = I.fetch_delivery_map(cand, sessions=5)
    pledge_map = {}
    if PLEDGE_CSV and os.path.exists(PLEDGE_CSV):
        try:
            pledge_map = I.load_pledge_csv(PLEDGE_CSV)
            print(f"  loaded pledge data for {len(pledge_map)} symbols")
        except Exception:
            pass

    vrows = []
    for _, row in top.iterrows():
        sym = row["ticker"]
        df = data.get(sym)
        if df is None or len(df) < 210:
            continue
        info = _info(sym)
        r, v = _vet(sym, df, row, base, index_ret126, info)

        # advisory robustness gates — fail ONLY on a confirmed red flag
        fscore = Fu.fscore_from_yfinance(sym)[0]
        deliv = delivery.get(sym)
        pledge_ok = I.pledge_gate(pledge_map.get(sym))[0]   # True/False/None
        fs_bad = fscore is not None and fscore < FS_FLOOR
        dv_bad = deliv is not None and deliv < DELIV_FLOOR
        pl_bad = pledge_ok is False
        red = []
        if fs_bad: red.append(f"F-score {fscore}<{FS_FLOOR}")
        if dv_bad: red.append(f"delivery {deliv}%<{DELIV_FLOOR}")
        if pl_bad: red.append("pledge/stake flag")

        final = "TRUST" if (v["verdict"] == "TRUST" and not red) else "DROP"
        why = v["why"] if final == v["verdict"] else "; ".join(red) or v["why"]

        vrows.append({
            "date": today, "ticker": sym, "score": int(row["score"]),
            "verdict": final, "sector": info.get("sector") or "—",
            "s1_trend": r[1][0], "s2_fund": r[2][0], "s3_risk": r[3][0],
            "s4_news": r[4][0], "fscore": fscore, "delivery_pct": deliv,
            "entry": row["entry"], "stop": row["stop"],
            "target_1r": row["target_1r"], "target_2r": row["target_2r"],
            "why": why, "headline": row["headline"],
        })

    vdf = pd.DataFrame(vrows)

    # --- portfolio caps: de-correlate + sector-cap the TRUST names
    vdf["diversified"] = False
    trust = vdf[vdf["verdict"] == "TRUST"]
    if len(trust) >= 1:
        rets = _returns_panel(list(trust["ticker"]), data)
        picks = trust[["ticker", "sector", "score"]].rename(columns={"ticker": "symbol"})
        kept, dropped = P.apply_caps(picks, rets, MAX_PER_SECTOR, MAX_CORR)
        keep_set = set(kept["symbol"])
        vdf.loc[vdf["ticker"].isin(keep_set) & (vdf["verdict"] == "TRUST"),
                "diversified"] = True
        if not dropped.empty:
            print(f"  portfolio caps dropped {len(dropped)}: "
                  + "; ".join(f"{d['symbol']} ({d['reason']})" for _, d in dropped.iterrows()))

    vdf = vdf.sort_values(["diversified", "verdict", "score"],
                          ascending=[False, True, False])
    vdf.to_csv(f"{OUT_DIR}/trusted.csv", index=False)
    n_trust = int((vdf["verdict"] == "TRUST").sum()) if not vdf.empty else 0
    n_div = int(vdf["diversified"].sum()) if not vdf.empty else 0
    print(f"  wrote {len(vdf)} vetted -> data/trusted.csv  "
          f"({n_trust} TRUST, {n_div} after portfolio caps)")


if __name__ == "__main__":
    main()
