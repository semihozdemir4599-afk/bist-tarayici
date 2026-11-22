"""Ortak tarama mantığı: hem Streamlit paneli hem e-posta raporu bunu kullanır."""
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

LIMIT_PCT = 10.0
TZ = ZoneInfo("Europe/Istanbul")

TREND_COLS = ["Hisse", "Son", "Değişim %", "Skor (0-7)", "RSI", "MACD hist",
              "Hacim x", "EMA20", "EMA50", "Giriş", "Stop", "Hedef 1",
              "Hedef 2", "Tavan fiyatı", "Sinyaller"]
TAVAN_COLS = ["Hisse", "Son", "Değişim %", "Tavan skor (0-6)", "Hacim x",
              "Kapanış konumu", "Ort. hacim (mn TL)", "Seri tavan", "RSI",
              "Ref. giriş", "Stop (gün düşüğü)", "Hedef +%5", "Tavan fiyatı",
              "Tavan sinyalleri"]


def read_list(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [x.strip().upper() for x in f
                    if x.strip() and not x.strip().startswith("#")]
    except FileNotFoundError:
        return []


def fetch(tickers):
    syms = [t + ".IS" for t in tickers]
    return yf.download(syms, period="1y", interval="1d", group_by="ticker",
                       auto_adjust=False, progress=False, threads=True)


def session_fraction(last_bar_date):
    """Seans açıksa ve son mum bugünün mumuysa, seansın geçen oranı (0-1)."""
    now = datetime.now(TZ)
    if now.weekday() >= 5 or last_bar_date != now.date():
        return None
    start = now.replace(hour=10, minute=0, second=0, microsecond=0)
    end = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now <= start or now >= end:
        return None
    return max((now - start) / (end - start), 0.15)


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def macd(close, fast=12, slow=26, sig=9):
    line = ema(close, fast) - ema(close, slow)
    signal = ema(line, sig)
    return line, signal, line - signal


def atr(df, n=14):
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(),
                    (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def analyze(df, frac=None):
    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).copy()
    if len(df) < 60:
        return None
    c = df["Close"]
    df["EMA20"], df["EMA50"] = ema(c, 20), ema(c, 50)
    df["RSI"] = rsi(c)
    df["MACD"], df["SIG"], df["HIST"] = macd(c)
    df["ATR"] = atr(df)
    df["VOLAVG"] = df["Volume"].shift(1).rolling(20).mean()
    df["HIGH20"] = df["High"].rolling(20).max().shift(1)
    df["TURN"] = (df["Close"] * df["Volume"]).shift(1).rolling(20).mean()
    df["CHG"] = c.pct_change() * 100

    last, prev = df.iloc[-1], df.iloc[-2]
    rel_vol = last["Volume"] / last["VOLAVG"] if last["VOLAVG"] > 0 else np.nan
    if frac and not np.isnan(rel_vol):
        rel_vol = rel_vol / frac  # seans içi: hacmi günün geçen oranına göre ölçekle
    chg = last["CHG"]
    rng = last["High"] - last["Low"]
    close_pos = (last["Close"] - last["Low"]) / rng if rng > 0 else 1.0

    # ---- Trend skoru (0-7) ----
    score, notes = 0, []
    if last["Close"] > last["EMA20"]:
        score += 1; notes.append("Fiyat>EMA20")
    if last["EMA20"] > last["EMA50"]:
        score += 1; notes.append("EMA20>EMA50")
    if 50 <= last["RSI"] <= 70:
        score += 1; notes.append("RSI 50-70")
    elif last["RSI"] > 75:
        score -= 1; notes.append("RSI aşırı alım")
    if last["MACD"] > last["SIG"]:
        score += 1; notes.append("MACD>Sinyal")
    if last["HIST"] > prev["HIST"]:
        score += 1; notes.append("MACD hist. artıyor")
    if rel_vol >= 1.5:
        score += 1; notes.append("Hacim>=1.5x")
    if last["Close"] >= last["HIGH20"] * 0.98:
        score += 1; notes.append("20g zirveye yakın")

    entry = last["High"] * 1.002
    stop = entry - 1.5 * last["ATR"]

    # ---- Tavan skoru (0-6) ----
    seri = 0
    for v in df["CHG"].values[::-1]:
        if v >= 9.5:
            seri += 1
        else:
            break
    tscore, tnotes = 0, []
    if rel_vol >= 2:
        tscore += 1; tnotes.append("Hacim>=2x")
    if chg >= 4:
        tscore += 1; tnotes.append("Gün +%4 üstü")
    if close_pos >= 0.9:
        tscore += 1; tnotes.append("Güçlü kapanış")
    if last["Close"] >= last["HIGH20"]:
        tscore += 1; tnotes.append("20g zirve kırılımı")
    if last["Close"] > last["EMA20"]:
        tscore += 1; tnotes.append("Fiyat>EMA20")
    if chg >= 9.5:
        tscore += 1; tnotes.append("Bugün tavan/tavana yakın")

    return {
        "Son": round(last["Close"], 2),
        "Değişim %": round(chg, 2),
        "Skor (0-7)": score,
        "RSI": round(last["RSI"], 1),
        "MACD hist": round(last["HIST"], 3),
        "Hacim x": round(rel_vol, 2) if not np.isnan(rel_vol) else np.nan,
        "EMA20": round(last["EMA20"], 2),
        "EMA50": round(last["EMA50"], 2),
        "Giriş": round(entry, 2),
        "Stop": round(stop, 2),
        "Hedef 1": round(entry + 1.5 * last["ATR"], 2),
        "Hedef 2": round(entry + 3.0 * last["ATR"], 2),
        "Tavan fiyatı": round(last["Close"] * (1 + LIMIT_PCT / 100), 2),
        "Sinyaller": ", ".join(notes),
        "Tavan skor (0-6)": tscore,
        "Kapanış konumu": round(close_pos, 2),
        "Ort. hacim (mn TL)": round(last["TURN"] / 1e6, 1) if last["TURN"] > 0 else 0.0,
        "Seri tavan": seri,
        "Ref. giriş": round(last["Close"], 2),
        "Stop (gün düşüğü)": round(last["Low"], 2),
        "Hedef +%5": round(last["Close"] * 1.05, 2),
        "Tavan sinyalleri": ", ".join(tnotes),
        "Son mum": str(df.index[-1].date()),
        "_df": df,
    }


def scan(tickers, raw):
    rows, frames, failed = [], {}, []
    for t in tickers:
        try:
            df = raw[t + ".IS"].dropna(subset=["Close"])
            if df.empty:
                failed.append(t)
                continue
            frac = session_fraction(df.index[-1].date())
            res = analyze(df, frac)
        except Exception:
            res = None
        if res is None:
            failed.append(t)
            continue
        frames[t] = res.pop("_df")
        rows.append({"Hisse": t, **res})
    return rows, frames, failed
