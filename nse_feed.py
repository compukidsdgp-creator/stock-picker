"""
Official NSE corporate-announcements feed.

Uses the maintained `nse` library (NseIndiaApi). Two things it solves for us:
  1. NSE's cookie handshake + browser headers (raw requests get 401'd).
  2. server=True mode (httpx + HTTP/2) that works from cloud IPs like GitHub
     Actions / Streamlit Cloud, which NSE otherwise firewalls.

Still best-effort: if NSE blocks the runner anyway, this returns {} and the
pipeline falls back to Google News RSS (news.py). Install: pip install nse[server]
"""
from __future__ import annotations
from datetime import datetime, timedelta

from news import _tag   # reuse the keyword tagger


def fetch_announcements(days_back: int = 2) -> dict[str, dict]:
    """Return {SYMBOL: {'tag':..., 'headline':...}} from the official feed.

    One call for the whole market's recent announcements, then indexed by
    symbol — far cheaper than querying per name.
    """
    try:
        from nse import NSE
    except Exception:
        print("  nse library not installed; skipping official feed")
        return {}

    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=days_back)

    data = None
    try:
        with NSE(download_folder="/tmp", server=True) as nse:
            try:
                data = nse.announcements(index="equities",
                                         from_date=from_dt, to_date=to_dt)
            except TypeError:
                # older/newer signature — fall back to recent, no date args
                data = nse.announcements()
    except Exception as e:
        print(f"  NSE announcements unavailable ({e}); will use RSS fallback")
        return {}

    # Response is usually a list of dicts; occasionally wrapped in {'data': [...]}
    if isinstance(data, dict):
        items = data.get("data", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []

    out: dict[str, dict] = {}
    for a in items:
        if not isinstance(a, dict):
            continue
        sym = str(a.get("symbol") or a.get("Symbol") or "").strip().upper()
        subj = str(a.get("desc") or a.get("attchmntText")
                   or a.get("subject") or a.get("sm_name") or "").strip()
        if not sym or not subj:
            continue
        # any official announcement is a real catalyst; keyword-tag, default NEWS
        tag = _tag(subj) or "NEWS"
        out.setdefault(sym, {"tag": tag, "headline": subj[:180]})
    print(f"  official NSE feed: {len(out)} symbols with announcements")
    return out
