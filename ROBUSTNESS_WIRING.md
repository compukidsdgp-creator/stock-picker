# Repo 1 — robustness wired in

The three add-ons are now integrated into the daily pipeline, plus the
reference is rebuilt on the broad 2,115-name universe.

## Copy into your Repo 1

| File | Action |
|---|---|
| `pipeline.py` | **replaces** existing |
| `india_signals.py` | **new** (batched delivery fetch) |
| `fundamentals.py` | **new** (Piotroski F-score) |
| `portfolio.py` | **new** (correlation + sector caps) |
| `reference/index_proxy.csv` | **replace** — broad 2,115-name index |
| `reference/risk_baseline.csv` | **replace** — broad 2,115-name baseline |

No new dependencies (`nse[server]`, `yfinance`, `pandas` already present).

## What the run now does

After the 4-stage vetting, each score≥5 name also gets:
- **Piotroski F-score** (live statements) — dropped only if CONFIRMED weak
  (score < `SWINGSCOPE_FSCORE_MIN`, default 4).
- **Delivery %** (NSE, one batched pass) — dropped only if CONFIRMED low
  (< `SWINGSCOPE_DELIV_MIN`, default 25).
- **Promoter pledge/holding** — dropped only on a real flag, and only if you
  supply data via `SWINGSCOPE_PLEDGE_CSV` (columns: symbol, pledge_pct,
  promoter_holding, promoter_holding_prev). No CSV = gate skipped.

**Key principle:** these are ADVISORY — a name is dropped only on a confirmed
red flag. Missing free data never drops a name (so a patchy fundamentals feed
won't nuke your list).

Then **portfolio caps** de-correlate and sector-cap the surviving TRUST names:
- at most `SWINGSCOPE_MAX_SECTOR` (default 2) per sector
- no name with correlation > `SWINGSCOPE_MAX_CORR` (default 0.75) to one
  already kept (correlations from the in-memory 2yr returns)

## Your final list

`data/trusted.csv` now has extra columns: `sector`, `fscore`, `delivery_pct`,
and **`diversified`**. Your true final picks are the rows where
`verdict == TRUST` **and** `diversified == True`. Rows sort those to the top.

Optional: in `app.py`, filter the headline table to `diversified == True` to
show only the de-correlated final list (one-line change; the raw TRUST list
stays available in the expander).

## Env knobs (all optional)

```
SWINGSCOPE_FSCORE_MIN=4     # F-score below this = drop
SWINGSCOPE_DELIV_MIN=25     # delivery % below this = drop
SWINGSCOPE_PLEDGE_CSV=path  # optional promoter pledge data
SWINGSCOPE_MAX_SECTOR=2     # max names per sector
SWINGSCOPE_MAX_CORR=0.75    # max pairwise correlation
```

## Honest notes

- F-score adds one financials fetch per top name; delivery does ~5 market
  downloads once. Adds a little runtime — fine in the scheduled job.
- Coverage is best-effort: many names won't have clean F-score/delivery data,
  so those gates simply won't fire (by design). The pledge gate does nothing
  until you feed it data.
- More gates ≠ more edge. These encode structural risk (distress, churn,
  promoter selling, over-concentration). The forward-test log is still the
  only thing that proves any of it works out-of-sample.
