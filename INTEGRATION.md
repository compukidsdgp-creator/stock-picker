# SwingScope — unified pipeline (scan → score → vet → TRUST)

These files fold the Level-2 vetting into your first app so the whole thing
runs in one scheduled job. Drop them into your existing SwingScope repo.

## What to copy in

| File | Action |
|---|---|
| `pipeline.py` | **replaces** your existing pipeline.py |
| `app.py` | **replaces** your existing app.py (now leads with the TRUST list) |
| `vetting.py` | **new** — the 5-stage hard-gate engine |
| `reference/index_proxy.csv` | **new** — prebuilt from your 20yr data |
| `reference/risk_baseline.csv` | **new** — prebuilt from your 20yr data |

Keep everything else unchanged: `swingscope.py`, `universe.py`,
`nse_feed.py`, `news.py`, `requirements.txt`, `.github/workflows/daily.yml`.
No new dependencies — vetting uses pandas/numpy/yfinance you already have.

## What the merged run does

1. Fetch universe OHLCV, run scans, tag catalysts, score 0–5 (unchanged).
2. Write `data/latest.csv` — the full scanned bucket (unchanged).
3. **New:** take every name with `score >= 5` and run the 5-stage hard gate:
   - Stage 1 (trend/RS) and Stage 3 (risk) reuse the price history already
     in memory — no re-fetch.
   - Stage 4 (news) reuses the catalyst tag already fetched for that name.
   - Stage 2 (fundamentals) is the only extra call — one yfinance `.info`
     per top pick (a handful of names, so it's cheap).
   - Relative-strength benchmark is computed **live** from today's universe
     (median 126-day return), so it's current, not stale.
4. Write `data/trusted.csv` — every score≥5 name with its verdict and which
   gates it passed. `verdict == TRUST` only if all four gates pass.

The dashboard now shows the **TRUST list first**, an expander of the vetted-
but-dropped names (with the reason each failed), then the full bucket below.

## Honest reminder

TRUST means "no gate tripped on best-effort data" — not a prediction. The
20yr backtest showed the price gates add only a modest edge; the funnel's job
is to drop names with clear problems and show you why. Paper-trade first and
size by risk. Free fundamentals are patchy, so some names fail Stage 2 as
"unverifiable" by design — a paid data key is the biggest upgrade from here.
