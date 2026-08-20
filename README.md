# SwingScope

An automated daily swing-trade shortlist for NSE. A scheduled job scans the
**full market**, overlays **official NSE announcements** (news catalysts),
scores each name, and writes a CSV. A Streamlit app reads that CSV and shows
the bucket with stop-loss charts.

Research and process tooling only. Not investment advice. A scan finds
candidates and a catalyst explains a move — neither is a buy signal.

## How it works

```
GitHub Actions (cron)                         Streamlit Community Cloud
  load full universe (EQUITY_L.csv)             reads data/latest.csv
  fetch OHLCV in chunks (yfinance)    commit    renders table + charts
  run scans S1-S4                   -------->    (thin viewer, no scanning)
  tag: NSE feed -> RSS fallback
  score 0-5, write CSV
```

The scan runs in the scheduled job, **not** in the app.

## Files

| File | Role |
|---|---|
| `universe.py` | downloads NSE's full equity master, filters series, caches it |
| `swingscope.py` | chunked data fetch, indicators, scans S1-S4, scoring |
| `nse_feed.py` | official NSE corporate-announcements feed (server mode) |
| `news.py` | Google News RSS catalyst tagging (fallback when NSE blocks) |
| `pipeline.py` | runs it all, writes `data/latest.csv` + dated archive |
| `app.py` | Streamlit dashboard (reads the CSV) |
| `.github/workflows/daily.yml` | weekday cron that commits results |

## Run locally

```bash
pip install -r requirements.txt
SWINGSCOPE_MAX=150 python pipeline.py   # cap universe while testing
python pipeline.py                      # full market
streamlit run app.py
```

## Deploy (all free)

1. Push to GitHub.
2. **Actions** runs weekdays at 12:30 UTC (18:00 IST). Hit *Run workflow* once
   to generate the first `data/latest.csv`.
3. **App**: share.streamlit.io -> connect repo -> main file `app.py` -> deploy.

## The two big extensions

### Full-market universe
`universe.py` pulls `EQUITY_L.csv` from NSE, keeps `SERIES == "EQ"` (mainboard
rolling settlement — what you want for swing trades; excludes SME/trade-to-trade),
and caches it to `data/universe.csv`. Change the `series` argument to widen it.
The OHLCV fetch is **chunked** (100 names per Yahoo call, 1s pause) so a
~2000-name run doesn't trip rate limits — expect several minutes per run.

### Official NSE announcements
`nse_feed.py` uses the maintained `nse` library. Two problems it solves:
NSE requires a cookie handshake (raw `requests` gets 401'd), and NSE
**IP-blocks cloud servers** (GitHub Actions, Streamlit) — so we use the
library's `server=True` mode (httpx + HTTP/2), which is built to work from
those IPs. It fetches the whole market's recent announcements in one call and
indexes them by symbol.

If NSE blocks the runner anyway, `nse_feed` returns nothing and the pipeline
**falls back to Google News RSS** per name — so the catalyst column is always
populated, just from a less official source on bad days.

## Honest limitations

- **yfinance is unofficial** Yahoo data — usually fine for EOD, occasionally a
  name returns empty. Full-market runs take minutes.
- **NSE may still block** the runner despite `server=True`; that's why the RSS
  fallback exists. Run after-market (the workflow already does) and don't
  hammer it — the library throttles to ~3 req/sec.
- **Catalyst tags are heuristic** keyword matches. A tag means a headline
  mentioned it, not that it's verified. Read the item before acting.
- **GitHub cron isn't exact** — delayed at high load, and disabled after 60
  days of no commits. The daily commit keeps it alive.
- **Streamlit free tier** sleeps after ~12 idle hours; one private app.
- **Always spot-check** names against real charts before trading.
