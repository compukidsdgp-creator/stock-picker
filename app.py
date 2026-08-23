"""
SwingScope dashboard (Streamlit).

Thin viewer: reads data/latest.csv produced by the scheduled pipeline and
draws the bucket + a stop-loss chart for any selected name. Deploy on
Streamlit Community Cloud, pointing at this file.
"""
from __future__ import annotations
import os
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import yfinance as yf

st.set_page_config(page_title="SwingScope", layout="wide")

LATEST = "data/latest.csv"


@st.cache_data(ttl=1800)
def load_bucket() -> pd.DataFrame:
    if not os.path.exists(LATEST):
        return pd.DataFrame()
    return pd.read_csv(LATEST)


@st.cache_data(ttl=1800)
def load_history(symbol: str) -> pd.DataFrame:
    df = yf.download(f"{symbol}.NS", period="6mo", interval="1d",
                     auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.rename(columns=str.lower)


st.title("SwingScope — daily bucket")
st.caption("Scan + catalyst shortlist for swing trades. Research only, not advice.")

bucket = load_bucket()
if bucket.empty:
    st.info("No picks file yet. Run the pipeline (or the GitHub Action) to generate today's bucket.")
    st.stop()

date = bucket["date"].iloc[0]

# ---- KPIs
c1, c2, c3, c4 = st.columns(4)
c1.metric("Date", date)
c2.metric("Names", len(bucket))
c3.metric("Score 4-5", int((bucket["score"] >= 4).sum()))
c4.metric("With catalyst", int(bucket["catalyst"].notna().sum()))

# ---- filter
min_score = st.slider("Minimum score", 0, 5, 3)
view = bucket[bucket["score"] >= min_score].reset_index(drop=True)

st.subheader(f"Bucket · {len(view)} names at score ≥ {min_score}")
st.dataframe(
    view[["ticker", "setups", "catalyst", "score", "entry", "stop",
          "target_1r", "target_2r", "rr", "rsi14", "vol_x_avg"]],
    use_container_width=True, hide_index=True,
)

# ---- per-stock chart
st.subheader("Stop-loss chart")
sym = st.selectbox("Pick a name", view["ticker"].tolist())
row = view[view["ticker"] == sym].iloc[0]
hist = load_history(sym)

if not hist.empty:
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(hist.index, hist["close"], color="#2f4bd8", lw=1.6, label="Close")
    ax.axhline(row["stop"], color="#d64545", ls="--", lw=1.2, label="Stop-loss")
    ax.axhline(row["target_1r"], color="#1f9d63", ls="--", lw=1.0, label="Target 1R")
    ax.axhline(row["target_2r"], color="#1f9d63", ls=":", lw=1.0, label="Target 2R")
    ax.axhspan(hist["close"].min(), row["stop"], color="#d64545", alpha=0.06)
    ax.set_title(f"{sym} — setups {row['setups']} · score {int(row['score'])}/5")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.15)
    st.pyplot(fig)

if isinstance(row.get("headline"), str) and row["headline"]:
    st.caption(f"Catalyst headline: {row['headline']}")
