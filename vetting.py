"""
Five-stage hard-gate vetting engine.

Each stage returns (passed: bool, detail: dict). A pick earns TRUST only if
all five pass. Stages 1 and 3 run on price + the 20yr reference; stage 2 on
best-effort yfinance fundamentals; stage 4 on recent news. Stage 5 combines.

Nothing here predicts the future. The gates remove names with clear problems
and rank confidence — they do not make a pick a sure thing.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

RED_FLAG_WORDS = ("fraud", "probe", "sebi", "penalty", "raid", "default",
                  "resign", "downgrade", "lawsuit", "scam", "insolvency",
                  "fire", "recall", "ban", "investigation")


# ---------------------------------------------------------------- stage 1
def stage1_trend(hist: pd.DataFrame, index_ret126: float) -> tuple[bool, dict]:
    """Healthy, confirmed uptrend that is beating the market."""
    c = hist["close"]
    px = float(c.iloc[-1])
    dma50 = float(c.rolling(50).mean().iloc[-1])
    dma200 = float(c.rolling(200).mean().iloc[-1])
    slope_up = c.rolling(200).mean().iloc[-1] > c.rolling(200).mean().iloc[-21]
    ret126 = float(c.iloc[-1] / c.iloc[-127] - 1) if len(c) > 127 else np.nan
    beats_mkt = ret126 > index_ret126

    passed = (px > dma50 and px > dma200 and bool(slope_up) and bool(beats_mkt))
    reasons = []
    if px <= dma50 or px <= dma200: reasons.append("below 50/200 DMA")
    if not slope_up: reasons.append("200 DMA not rising")
    if not beats_mkt: reasons.append("lagging the index")
    return passed, {"px": px, "dma50": dma50, "dma200": dma200,
                    "ret126": ret126, "index_ret126": index_ret126,
                    "reason": "; ".join(reasons) or "healthy uptrend, outperforming"}


# ---------------------------------------------------------------- stage 2
def stage2_fundamentals(info: dict) -> tuple[bool, dict]:
    """Best-effort financial health from yfinance .info. Missing core data
    fails under the hard gate — we won't pass what we can't verify."""
    pe = info.get("trailingPE")
    de = info.get("debtToEquity")
    roe = info.get("returnOnEquity")
    margin = info.get("profitMargins")
    growth = info.get("earningsGrowth") or info.get("revenueGrowth")

    if margin is None:
        return False, {"reason": "fundamentals unverifiable (no margin data)",
                       "pe": pe, "de": de, "roe": roe, "margin": margin}
    ok, reasons = True, []
    if not (margin > 0):
        ok = False; reasons.append("unprofitable")
    if pe is not None and not (0 < pe < 80):
        ok = False; reasons.append("PE extreme")
    if de is not None and not (de < 150):
        ok = False; reasons.append("high debt/equity")
    if roe is not None and not (roe > 0.10):
        ok = False; reasons.append("weak ROE")
    if growth is not None and not (growth > 0):
        ok = False; reasons.append("shrinking")

    return ok, {"pe": pe, "de": de, "roe": roe, "margin": margin,
                "growth": growth,
                "reason": "; ".join(reasons) or "financially healthy"}


# ---------------------------------------------------------------- stage 3
def stage3_risk(hist: pd.DataFrame, baseline: pd.DataFrame,
                symbol: str) -> tuple[bool, dict]:
    """Tradable and not pathologically risky or overextended."""
    c, h, l = hist["close"], hist["high"], hist["low"]
    px = float(c.iloc[-1])
    tr = (h - l).rolling(14).mean().iloc[-1]
    atr_pct = float(tr / px)
    vol1y = float(c.pct_change().tail(252).std() * np.sqrt(252))
    turnover = float((c * hist["volume"]).tail(21).median())
    ext = float(px / c.rolling(50).mean().iloc[-1] - 1)   # % above 50 DMA

    vdist = baseline["vol1y"].dropna()
    vol_pct = float((vdist < vol1y).mean())               # percentile vs history

    liquid = turnover > 5e7
    calm = vol_pct < 0.90
    not_extended = ext < 0.30

    reasons = []
    if not liquid: reasons.append("illiquid (<5cr/day)")
    if not calm: reasons.append("top-decile volatility")
    if not not_extended: reasons.append(">30% above 50 DMA")
    passed = liquid and calm and not_extended
    return passed, {"atr_pct": atr_pct, "vol1y": vol1y, "vol_pct": vol_pct,
                    "turnover": turnover, "ext_pct": ext,
                    "reason": "; ".join(reasons) or "liquid, controlled risk"}


# ---------------------------------------------------------------- stage 4
def stage4_news(catalyst: dict | None) -> tuple[bool, dict]:
    """Move must be justified by a real, recent, non-negative catalyst."""
    if not catalyst or not catalyst.get("headline"):
        return False, {"reason": "no recent catalyst to justify the move",
                       "headline": None, "tag": None}
    head = catalyst["headline"].lower()
    if any(w in head for w in RED_FLAG_WORDS):
        return False, {"reason": "negative/red-flag news",
                       "headline": catalyst["headline"], "tag": catalyst.get("tag")}
    return True, {"reason": f"supported ({catalyst.get('tag') or 'news'})",
                  "headline": catalyst["headline"], "tag": catalyst.get("tag")}


# ---------------------------------------------------------------- stage 5
STAGE_NAMES = {1: "Trend & RS", 2: "Fundamentals", 3: "Risk", 4: "News"}


def verdict(results: dict[int, tuple[bool, dict]]) -> dict:
    """Hard gate: TRUST only if all four stages pass."""
    passed_all = all(results[k][0] for k in (1, 2, 3, 4))
    failed = [STAGE_NAMES[k] for k in (1, 2, 3, 4) if not results[k][0]]
    return {
        "verdict": "TRUST" if passed_all else "DROP",
        "passed": sum(results[k][0] for k in (1, 2, 3, 4)),
        "failed_stages": failed,
        "why": "cleared all 5 gates" if passed_all
               else "failed: " + ", ".join(failed),
    }
