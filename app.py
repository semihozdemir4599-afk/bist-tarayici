import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="BIST Günlük Tarayıcı", layout="wide")

# ---------------------------------------------------------------
# Ayarlar
# ---------------------------------------------------------------
LIMIT_PCT = 10.0  # BIST günlük fiyat limiti (%)


def load_tickers():
    try:
        with open("tickers.txt", encoding="utf-8") as f:
            return [x.strip().upper() for x in f if x.strip()]
    except FileNotFoundError:
        return ["THYAO", "ASELS", "GARAN"]


# ---------------------------------------------------------------
# Göstergeler
# ---------------------------------------------------------------
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(close, fast=12, slow=26, sig=9):
    line = ema(close, fast) - ema(close, slow)
    signal = ema(line, sig)
    return line, signal, line - signal


def atr(df, n=14):
    pc = df["Close"].shift(1)
    tr = pd.concat(
        [df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def analyze(df):
    """Tek hisse için göstergeleri ve skoru hesaplar."""
    df = df.dropna(subset=["Close", "High", "Low", "Volume"]).copy()
    if len(df) < 60:
        return None

    c = df["Close"]
    df["EMA20"] = ema(c, 20)
    df["EMA50"] = ema(c, 50)
    df["RSI"] = rsi(c)
    df["MACD"], df["SIG"], df["HIST"] = macd(c)
    df["ATR"] = atr(df)
    df["VOL20"] = df["Volume"].rolling(20).mean()
    df["HIGH20"] = df["High"].rolling(20).max().shift(1)

    last, prev = df.iloc[-1], df.iloc[-2]
    rel_vol = last["Volume"] / last["VOL20"] if last["VOL20"] else np.nan
    chg = (last["Close"] / prev["Close"] - 1) * 100

    score, notes = 0, []

    if last["Close"] > last["EMA20"]:
        score += 1
        notes.append("Fiyat>EMA20")
    if last["EMA20"] > last["EMA50"]:
        score += 1
        notes.append("EMA20>EMA50")
    if 50 <= last["RSI"] <= 70:
        score += 1
        notes.append("RSI 50-70")
    elif last["RSI"] > 75:
        score -= 1
        notes.append("RSI aşırı alım")
    if last["MACD"] > last["SIG"]:
        score += 1
        notes.append("MACD>Sinyal")
    if last["HIST"] > prev["HIST"]:
        score += 1
        notes.append("MACD hist. artıyor")
    if rel_vol >= 1.5:
        score += 1
        notes.append("Hacim>=1.5x")
    if last["Close"] >= last["HIGH20"] * 0.98:
        score += 1
        notes.append("20g zirveye yakın")

    # Seviyeler (yaklaşık, kırılım mantığı)
    entry = last["High"] * 1.002
    stop = entry - 1.5 * last["ATR"]
    t1 = entry + 1.5 * last["ATR"]
    t2 = entry + 3.0 * last["ATR"]
    limit_up = last["Close"] * (1 + LIMIT_PCT / 100)

    return {
        "Son": round(last["Close"], 2),
        "Değişim %": round(chg, 2),
        "Skor (0-7)": score,
        "RSI": round(last["RSI"], 1),
        "MACD hist": round(last["HIST"], 3),
        "Hacim x": round(rel_vol, 2),
        "EMA20": round(last["EMA20"], 2),
        "EMA50": round(last["EMA50"], 2),
        "Giriş": round(entry, 2),
        "Stop": round(stop, 2),
        "Hedef 1": round(t1, 2),
        "Hedef 2": round(t2, 2),
        "Tavan fiyatı": round(limit_up, 2),
        "Sinyaller": ", ".join(notes),
        "_df": df,
    }


@st.cache_data(ttl=900, show_spinner=False)
def fetch(tickers):
    syms = [t + ".IS" for t in tickers]
    return yf.download(
        syms,
        period="1y",
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=True,
    )


# ---------------------------------------------------------------
# Arayüz
# ---------------------------------------------------------------
st.title("BIST Günlük Tarayıcı")
st.caption(
    "EMA20 / EMA50 / RSI / MACD / Hacim bazlı skorlama. "
    "Veri: Yahoo Finance (gecikmeli, günlük mum). Yatırım tavsiyesi değildir."
)

tickers = load_tickers()
min_score = st.slider("Minimum skor", 0, 7, 4)

if st.button("Taramayı çalıştır / yenile", type="primary"):
    st.cache_data.clear()

with st.spinner("Veriler indiriliyor ve hesaplanıyor..."):
    raw = fetch(tuple(tickers))

rows, frames, failed = [], {}, []
for t in tickers:
    try:
        df = raw[t + ".IS"]
        res = analyze(df)
        if res is None:
            failed.append(t)
            continue
        frames[t] = res.pop("_df")
        rows.append({"Hisse": t, **res})
    except Exception:
        failed.append(t)

if not rows:
    st.error("Veri alınamadı. Biraz sonra tekrar dene.")
    st.stop()

table = (
    pd.DataFrame(rows)
    .sort_values(["Skor (0-7)", "Hacim x"], ascending=False)
    .reset_index(drop=True)
)
view = table[table["Skor (0-7)"] >= min_score]

st.subheader(f"Aday listesi ({len(view)} hisse)")
st.dataframe(view, use_container_width=True, hide_index=True)

if failed:
    st.caption("Verisi alınamayan hisseler: " + ", ".join(failed))

st.subheader("Hisse detayı")
pick = st.selectbox("Hisse seç", table["Hisse"].tolist())
d = frames[pick].tail(120)
st.line_chart(d[["Close", "EMA20", "EMA50"]])
c1, c2 = st.columns(2)
c1.caption("RSI")
c1.line_chart(d[["RSI"]])
c2.caption("MACD / Sinyal")
c2.line_chart(d[["MACD", "SIG"]])

with st.expander("Skor ve seviyeler nasıl hesaplanıyor?"):
    st.markdown(
        """
**Skor (her biri 1 puan):** Fiyat>EMA20, EMA20>EMA50, RSI 50-70 arası,
MACD>Sinyal, MACD histogramı artıyor, hacim 20 günlük ortalamanın 1,5 katı ve üstü,
fiyat 20 günlük zirvenin %2 yakınında. RSI>75 ise 1 puan düşer.

**Giriş:** son günün yükseğinin %0,2 üstü (kırılım).
**Stop:** giriş - 1,5 x ATR. **Hedef 1/2:** giriş + 1,5 / 3 x ATR.
**Tavan fiyatı:** son kapanış x 1,10 (yaklaşık).

Bu seviyeler günlük veriyle hesaplanan kaba rehberlerdir; gerçek giriş-çıkış
için gün içi fiyat ve tahta durumunu ayrıca kontrol et.
"""
    )
