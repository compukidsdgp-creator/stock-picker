"""
SwingScope dashboard — leads with the vetted TRUST list, then the full bucket.

Thin viewer: reads data/trusted.csv and data/latest.csv committed by the
scheduled pipeline. Research only, not advice. TRUST = cleared all 5 gates on
best-effort data, not a prediction.
"""
from __future__ import annotations
import os
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import yfinance as yf

st.set_page_config(page_title="SwingScope", layout="wide")
TRUSTED, LATEST = "data/trusted.csv", "data/latest.csv"
TICK = {True: "✅", False: "❌"}


@st.cache_data(ttl=1800)
def load(path):
    return pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()


@st.cache_data(ttl=1800)
def history(sym):
    df = yf.download(f"{sym}.NS", period="1y", interval="1d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.rename(columns=str.lower)


st.title("SwingScope — daily TRUST list")
st.caption("Scan → score → 5-gate vetting, one pipeline. Research only, not advice.")

trusted, bucket = load(TRUSTED), load(LATEST)
if bucket.empty:
    st.info("No picks yet. Run the pipeline / GitHub Action to generate today's files.")
    st.stop()

date = bucket["date"].iloc[0]
n_trust = int((trusted["verdict"] == "TRUST").sum()) if not trusted.empty else 0
c1, c2, c3, c4 = st.columns(4)
c1.metric("Date", date)
c2.metric("Scanned bucket", len(bucket))
c3.metric("Vetted (score≥5)", len(trusted))
c4.metric("TRUST (all 5 gates)", n_trust)

# ---- headline: the TRUST list
st.subheader("✅ TRUST — cleared all five gates")
if n_trust == 0:
    st.warning("No names cleared all five gates today. That's normal — the hard gate is strict.")
else:
    t = trusted[trusted["verdict"] == "TRUST"].copy()
    for col in ["s1_trend", "s2_fund", "s3_risk", "s4_news"]:
        t[col] = t[col].map(lambda v: TICK[bool(v)])
    st.dataframe(
        t[["ticker", "score", "entry", "stop", "target_1r", "target_2r",
           "s1_trend", "s2_fund", "s3_risk", "s4_news", "headline"]],
        use_container_width=True, hide_index=True)

# ---- the dropped score>=5 names, so you can see WHY they failed
with st.expander("Vetted but dropped (why each failed the gate)"):
    if not trusted.empty:
        d = trusted[trusted["verdict"] != "TRUST"].copy()
        for col in ["s1_trend", "s2_fund", "s3_risk", "s4_news"]:
            d[col] = d[col].map(lambda v: TICK[bool(v)])
        st.dataframe(
            d[["ticker", "score", "s1_trend", "s2_fund", "s3_risk", "s4_news", "why"]],
            use_container_width=True, hide_index=True)

# ---- full scanned bucket below
st.subheader("Full scanned bucket")
min_score = st.slider("Minimum score", 0, 5, 4)
view = bucket[bucket["score"] >= min_score]
st.dataframe(
    view[["ticker", "setups", "catalyst", "score", "entry", "stop",
          "target_1r", "target_2r", "rr", "rsi14", "vol_x_avg"]],
    use_container_width=True, hide_index=True)

# ---- deep-dive chart
st.subheader("Chart")
names = (trusted["ticker"].tolist() if not trusted.empty else view["ticker"].tolist())
sym = st.selectbox("Name", names)
if sym:
    h = history(sym)
    if not h.empty:
        row = bucket[bucket["ticker"] == sym]
        fig, ax = plt.subplots(figsize=(10, 3.6))
        ax.plot(h.index, h["close"], color="#2f4bd8", lw=1.5, label="Close")
        ax.plot(h.index, h["close"].rolling(50).mean(), color="#c9860a", lw=1, label="50 DMA")
        ax.plot(h.index, h["close"].rolling(200).mean(), color="#d64545", lw=1, label="200 DMA")
        if not row.empty:
            ax.axhline(row["stop"].iloc[0], color="#d64545", ls="--", lw=1, label="Stop")
            ax.axhline(row["target_1r"].iloc[0], color="#1f9d63", ls="--", lw=1, label="1R")
        ax.legend(loc="upper left", fontsize=8); ax.grid(alpha=0.15)
        st.pyplot(fig)

st.caption("TRUST means no gate tripped on best-effort data — verify fundamentals and news before acting.")
