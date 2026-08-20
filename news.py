"""
Catalyst overlay — best-effort, no API key.

Pulls recent headlines per ticker from Google News RSS and tags them by
keyword: ERN (earnings/results), EXP (capex/expansion/orders), NEWS (other).
Only call this for the handful of names that passed the scans.

This is a heuristic, not a fact-checker. A tag means "a headline mentioned
this" — you still read the item before trusting it.
"""
from __future__ import annotations
import urllib.parse
import feedparser

RSS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"

TAG_RULES = [
    ("ERN", ("results", "profit", "earnings", "q1", "q2", "q3", "q4",
             "quarter", "net profit", "revenue", "guidance", "beats", "misses")),
    ("EXP", ("capex", "expansion", "expand", "new plant", "capacity",
             "order", "contract", "wins", "acquire", "acquisition", "merger",
             "stake", "invest", "factory", "facility")),
    ("NEWS", ("upgrade", "downgrade", "target", "buy", "sell", "rating",
              "approval", "launch", "deal", "partnership", "block deal")),
]


def _tag(headline: str) -> str | None:
    h = headline.lower()
    for tag, kws in TAG_RULES:
        if any(k in h for k in kws):
            return tag
    return None


def fetch_catalyst(symbol: str, max_items: int = 6) -> dict:
    """Return {'tag': str|None, 'headline': str|None} for the strongest match."""
    q = urllib.parse.quote(f"{symbol} share NSE")
    try:
        feed = feedparser.parse(RSS.format(q=q))
    except Exception:
        return {"tag": None, "headline": None}

    for entry in feed.entries[:max_items]:
        title = getattr(entry, "title", "")
        tag = _tag(title)
        if tag:
            return {"tag": tag, "headline": title}
    # nothing matched a rule but headlines exist -> generic
    if feed.entries:
        return {"tag": None, "headline": feed.entries[0].title}
    return {"tag": None, "headline": None}
