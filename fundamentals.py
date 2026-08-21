"""
Fundamental robustness — Piotroski F-score (0–9) and Altman Z-score.

Piotroski is a well-studied 9-point financial-health checklist; it's hard to
overfit because the signals are structural, not tuned. It turns the patchy
yfinance stage-2 into something principled: F-score >= 6 = healthy.

Pure scoring functions take structured inputs (so they're testable). A
yfinance adapter maps live statements onto them, returning None when data is
missing rather than guessing.
"""
from __future__ import annotations


def piotroski_fscore(cur: dict, prev: dict) -> tuple[int, dict]:
    """9-point score from current & prior-year line items. Keys expected:
    net_income, total_assets, ocf, revenue, gross_profit, long_term_debt,
    current_assets, current_liabilities, shares."""
    def roa(x): return x["net_income"] / x["total_assets"]
    def lev(x): return x["long_term_debt"] / x["total_assets"]
    def cr(x):  return x["current_assets"] / x["current_liabilities"]
    def gm(x):  return x["gross_profit"] / x["revenue"]
    def turn(x): return x["revenue"] / x["total_assets"]

    s = {
        "roa_positive":       roa(cur) > 0,
        "ocf_positive":       cur["ocf"] > 0,
        "roa_improving":      roa(cur) > roa(prev),
        "accruals_ok":        cur["ocf"] > cur["net_income"],      # OCF > NI
        "leverage_down":      lev(cur) < lev(prev),
        "current_ratio_up":   cr(cur) > cr(prev),
        "no_dilution":        cur["shares"] <= prev["shares"],
        "margin_up":          gm(cur) > gm(prev),
        "asset_turnover_up":  turn(cur) > turn(prev),
    }
    return sum(s.values()), s


def altman_z(x: dict) -> tuple[float, str]:
    """Altman Z (manufacturing). Keys: working_capital, retained_earnings,
    ebit, market_cap, total_liabilities, sales, total_assets."""
    ta = x["total_assets"]
    z = (1.2 * x["working_capital"] / ta + 1.4 * x["retained_earnings"] / ta
         + 3.3 * x["ebit"] / ta + 0.6 * x["market_cap"] / x["total_liabilities"]
         + 1.0 * x["sales"] / ta)
    zone = "safe" if z > 2.99 else "grey" if z >= 1.81 else "distress"
    return round(z, 2), zone


# ---------------------------------------------------------------- yfinance adapter
def fscore_from_yfinance(symbol: str) -> tuple[int | None, dict]:
    """Best-effort F-score from live statements. Returns (None, {...}) if the
    required line items aren't all available."""
    try:
        import yfinance as yf
        t = yf.Ticker(f"{symbol}.NS")
        inc, bs, cf = t.financials, t.balance_sheet, t.cashflow
        if inc is None or bs is None or cf is None or inc.shape[1] < 2:
            return None, {"reason": "insufficient statement history"}

        def row(df, *names):
            for n in names:
                if n in df.index:
                    return df.loc[n]
            return None

        def yr(series, i):
            return float(series.iloc[i]) if series is not None and len(series) > i else None

        ni = row(inc, "Net Income", "Net Income Common Stockholders")
        rev = row(inc, "Total Revenue", "Operating Revenue")
        gp = row(inc, "Gross Profit")
        ta = row(bs, "Total Assets")
        ltd = row(bs, "Long Term Debt", "Long Term Debt And Capital Lease Obligation")
        ca = row(bs, "Current Assets", "Total Current Assets")
        cl = row(bs, "Current Liabilities", "Total Current Liabilities")
        sh = row(bs, "Ordinary Shares Number", "Share Issued")
        ocf = row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")

        def pack(i):
            vals = dict(net_income=yr(ni, i), total_assets=yr(ta, i), ocf=yr(ocf, i),
                        revenue=yr(rev, i), gross_profit=yr(gp, i),
                        long_term_debt=yr(ltd, i) or 0.0,
                        current_assets=yr(ca, i), current_liabilities=yr(cl, i),
                        shares=yr(sh, i))
            return vals if all(v is not None for k, v in vals.items()
                               if k != "long_term_debt") else None

        cur, prev = pack(0), pack(1)
        if not cur or not prev:
            return None, {"reason": "missing line items"}
        score, detail = piotroski_fscore(cur, prev)
        return score, detail
    except Exception as e:
        return None, {"reason": f"fetch failed: {e}"}


def fscore_gate(score: int | None, minimum: int = 6) -> tuple[bool, dict]:
    """Hard gate helper. Missing data -> not passed (can't verify)."""
    if score is None:
        return False, {"reason": "F-score unverifiable", "score": None}
    return score >= minimum, {"reason": f"F-score {score}/9", "score": score}
