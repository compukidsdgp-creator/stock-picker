"""
India-specific signals — delivery % and promoter pledge/holding.

These catch things price and generic fundamentals miss:
  • Delivery %  — share of traded volume actually delivered (not intraday
    churn). High delivery on an up-move = real accumulation. NSE publishes it.
  • Promoter pledge / holding — rising pledge or falling promoter stake is a
    classic blow-up warning that nothing else here sees.

DATA HONESTY:
  • Delivery % is fetchable from NSE via the `nse` library (best-effort;
    NSE may block cloud IPs, so it degrades to None).
  • Promoter pledge has NO reliable free API. The clean sources are paid
    (Trendlyne / indianapi) or the quarterly shareholding-pattern filings.
    So pledge here reads from an OPTIONAL CSV you supply; without it the gate
    is skipped (returns None), never silently passed.

Gates return (passed | None, detail). None = "couldn't verify" — the caller
decides whether to treat unverifiable as skip or as fail.
"""
from __future__ import annotations
import pandas as pd


# ---------------------------------------------------------------- delivery %
def fetch_delivery_pct(symbol: str, sessions: int = 5) -> float | None:
    """Average delivery % over the last N sessions via the `nse` library.
    Returns None if unavailable (not installed / blocked / no data)."""
    try:
        from datetime import datetime, timedelta
        from nse import NSE
        vals = []
        with NSE(download_folder="/tmp", server=True) as nse:
            day = datetime.now()
            got = 0
            for _ in range(sessions * 2):          # walk back over weekends/holidays
                if got >= sessions:
                    break
                try:
                    df = nse.deliveryBhavcopy(day)
                    col = next((c for c in df.columns if "DELIV_PER" in c.upper()
                                or "DELIVERY" in c.upper()), None)
                    scol = next((c for c in df.columns if c.upper().strip() == "SYMBOL"), None)
                    if col and scol:
                        row = df[df[scol].astype(str).str.strip() == symbol]
                        if not row.empty:
                            vals.append(float(str(row.iloc[0][col]).replace("-", "nan")))
                            got += 1
                except Exception:
                    pass
                day -= timedelta(days=1)
        vals = [v for v in vals if v == v]         # drop NaN
        return round(sum(vals) / len(vals), 1) if vals else None
    except Exception:
        return None


def fetch_delivery_map(symbols: list[str], sessions: int = 5) -> dict:
    """Average delivery % for MANY symbols in one pass — downloads each recent
    session's delivery bhavcopy once (not per symbol). Returns {SYMBOL: pct|None}."""
    want = {s.upper() for s in symbols}
    acc: dict[str, list] = {s: [] for s in want}
    try:
        from datetime import datetime, timedelta
        from nse import NSE
        with NSE(download_folder="/tmp", server=True) as nse:
            day, got = datetime.now(), 0
            for _ in range(sessions * 2):
                if got >= sessions:
                    break
                try:
                    df = nse.deliveryBhavcopy(day)
                    col = next((c for c in df.columns if "DELIV_PER" in c.upper()
                                or "DELIVERY" in c.upper()), None)
                    scol = next((c for c in df.columns if c.upper().strip() == "SYMBOL"), None)
                    if col and scol:
                        df = df.copy()
                        df[scol] = df[scol].astype(str).str.strip().str.upper()
                        hit = df[df[scol].isin(want)]
                        for _, r in hit.iterrows():
                            try:
                                acc[r[scol]].append(float(str(r[col]).replace("-", "nan")))
                            except Exception:
                                pass
                        got += 1
                except Exception:
                    pass
                day -= timedelta(days=1)
    except Exception:
        return {s: None for s in want}
    out = {}
    for s, vals in acc.items():
        vals = [v for v in vals if v == v]
        out[s] = round(sum(vals) / len(vals), 1) if vals else None
    return out


def delivery_gate(deliv_pct: float | None, minimum: float = 45.0):
    """Real accumulation if delivery % is high. None -> unverifiable."""
    if deliv_pct is None:
        return None, {"reason": "delivery % unavailable", "delivery_pct": None}
    return deliv_pct >= minimum, {"reason": f"delivery {deliv_pct}%",
                                  "delivery_pct": deliv_pct}


# ---------------------------------------------------------------- pledge / holding
def load_pledge_csv(path: str) -> dict:
    """Optional CSV you supply: columns symbol, pledge_pct, promoter_holding,
    promoter_holding_prev. Returns {SYMBOL: {...}}."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    out = {}
    for _, r in df.iterrows():
        out[str(r["symbol"]).strip().upper()] = {
            "pledge_pct": float(r.get("pledge_pct", 0) or 0),
            "holding": float(r.get("promoter_holding", "nan")),
            "holding_prev": float(r.get("promoter_holding_prev", "nan")),
        }
    return out


def pledge_gate(pledge_row: dict | None, max_pledge: float = 20.0,
                max_holding_drop: float = 2.0):
    """Fail on high pledge or a meaningful promoter-stake reduction.
    None (no data) -> unverifiable."""
    if not pledge_row:
        return None, {"reason": "pledge/holding data not supplied"}
    pledge = pledge_row.get("pledge_pct", 0.0)
    h, hp = pledge_row.get("holding"), pledge_row.get("holding_prev")
    drop = (hp - h) if (h == h and hp == hp) else 0.0     # NaN-safe
    reasons = []
    if pledge > max_pledge: reasons.append(f"pledge {pledge}% > {max_pledge}%")
    if drop > max_holding_drop: reasons.append(f"promoter stake down {drop:.1f}pp")
    passed = not reasons
    return passed, {"reason": "; ".join(reasons) or f"pledge {pledge}%, stake stable",
                    "pledge_pct": pledge, "holding_drop": round(drop, 2)}
