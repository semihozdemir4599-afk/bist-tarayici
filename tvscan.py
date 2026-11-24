"""TradingView verisiyle tüm Borsa İstanbul taraması. Hem Streamlit paneli hem rapor kullanır."""
import os
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from tradingview_screener import Column, Query

TZ = ZoneInfo("Europe/Istanbul")
LIMIT_PCT = 10.0
LOG_PATH = "log/adaylar.csv"

FIELDS = ["name", "description", "close", "change", "volume", "relative_volume_10d_calc",
          "average_volume_10d_calc", "Value.Traded", "open", "high", "low", "EMA20", "EMA50",
          "RSI", "MACD.macd", "MACD.signal", "price_52_week_high", "market_cap_basic",
          "exchange", "type", "update_mode"]

TAVAN_COLS = ["Hisse", "Tavan skoru (0-6)", "Hacim (mn TL)", "Değişim %", "RSI",
              "Giriş", "Hedef", "Stop", "Tavan sinyalleri"]
LOCK_COLS = ["Hisse", "Tavan skoru (0-6)", "Hacim (mn TL)", "Değişim %", "RSI",
             "Tavan fiyatı", "Tavan sinyalleri"]
TREND_COLS = ["Hisse", "Trend skoru (0-6)", "Son", "Değişim %", "RSI", "Hacim x",
              "Giriş", "Stop", "Hedef", "Sinyaller"]


def read_list(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [x.strip().upper() for x in f
                    if x.strip() and not x.strip().startswith("#")]
    except FileNotFoundError:
        return []


def fetch_all():
    """Tüm BIST hisselerini tek istekte çeker (yaklaşık 15 dk gecikmeli)."""
    _, df = (Query().set_markets("turkey").select(*FIELDS)
             .where(Column("exchange") == "BIST").limit(2000).get_scanner_data())
    if "type" in df.columns:
        stocks = df[df["type"] == "stock"]
        if len(stocks) >= 100:
            df = stocks
    return df.dropna(subset=["close", "change"]).reset_index(drop=True)


def _signals(conds):
    names = [n for n, _ in conds]
    mat = np.column_stack([c.fillna(False).values.astype(bool) for _, c in conds])
    text = [", ".join(n for n, f in zip(names, row) if f) for row in mat]
    return mat.sum(axis=1), text


def enrich(df):
    d = df.copy()
    d["prev"] = d["close"] / (1 + d["change"] / 100)
    d["tavan_fiyat"] = (d["prev"] * (1 + LIMIT_PCT / 100)).round(2)
    rng = d["high"] - d["low"]
    d["konum"] = ((d["close"] - d["low"]) / rng.replace(0, np.nan)).fillna(1.0)
    d["hacim_mn"] = d["Value.Traded"] / 1e6
    d["relvol"] = d["relative_volume_10d_calc"]

    d["tavan_skor"], d["tavan_sinyal"] = _signals([
        ("Hacim>=2x", d["relvol"] >= 2),
        ("Gün +%4 üstü", d["change"] >= 4),
        ("Günün üst bölgesinde", d["konum"] >= 0.9),
        ("Fiyat>EMA20", d["close"] > d["EMA20"]),
        ("MACD>Sinyal", d["MACD.macd"] > d["MACD.signal"]),
        ("Tavan/tavana yakın", d["change"] >= 9.5),
    ])

    score, text = _signals([
        ("Fiyat>EMA20", d["close"] > d["EMA20"]),
        ("EMA20>EMA50", d["EMA20"] > d["EMA50"]),
        ("RSI 50-70", d["RSI"].between(50, 70)),
        ("MACD>Sinyal", d["MACD.macd"] > d["MACD.signal"]),
        ("Hacim>=1.5x", d["relvol"] >= 1.5),
        ("52h zirveye yakın", d["close"] >= 0.9 * d["price_52_week_high"]),
    ])
    d["trend_skor"] = score - (d["RSI"] > 75).astype(int)
    d["trend_sinyal"] = [t + (", RSI aşırı alım" if r > 75 else "")
                         for t, r in zip(text, d["RSI"].fillna(0))]
    return d


# ---------------------------------------------------------------- Listeler
def tavan_candidates(d, min_change=4.0, top=30):
    """Tavana yürüyenler: tavan olmamış, gün içinde min_change üstü yükselenler."""
    x = d[(d["change"] >= min_change) & (d["change"] < 9.5)]
    return x.sort_values(["tavan_skor", "change"], ascending=False).head(top)


def tavan_locked(d, top=40):
    x = d[d["change"] >= 9.5]
    return x.sort_values(["tavan_skor", "hacim_mn"], ascending=False).head(top)


def trend_candidates(d, universe=None, min_score=5, top=15):
    names = universe if universe else top100(d)["name"]
    x = d[d["name"].isin(names) & (d["trend_skor"] >= min_score)]
    return x.sort_values(["trend_skor", "relvol"], ascending=False).head(top)


# ---------------------------------------------------------------- Tablolar
def tavan_table(x):
    return pd.DataFrame({
        "Hisse": x["name"].values,
        "Tavan skoru (0-6)": x["tavan_skor"].values,
        "Hacim (mn TL)": x["hacim_mn"].round(1).values,
        "Değişim %": x["change"].round(2).values,
        "RSI": x["RSI"].round(1).values,
        "Giriş": x["close"].round(2).values,
        "Hedef": x["tavan_fiyat"].values,
        # Stop: günün düşüğü ya da giriş -%3'ten hangisi yakınsa (risk en fazla %3)
        "Stop": np.maximum(x["low"], x["close"] * 0.97).round(2).values,
        "Tavan sinyalleri": x["tavan_sinyal"].values,
    }, columns=TAVAN_COLS)


def lock_table(x):
    return pd.DataFrame({
        "Hisse": x["name"].values,
        "Tavan skoru (0-6)": x["tavan_skor"].values,
        "Hacim (mn TL)": x["hacim_mn"].round(1).values,
        "Değişim %": x["change"].round(2).values,
        "RSI": x["RSI"].round(1).values,
        "Tavan fiyatı": x["tavan_fiyat"].values,
        "Tavan sinyalleri": x["tavan_sinyal"].values,
    }, columns=LOCK_COLS)


def trend_table(x):
    entry = x["high"] * 1.002
    stop = x["EMA20"]
    return pd.DataFrame({
        "Hisse": x["name"].values,
        "Trend skoru (0-6)": x["trend_skor"].values,
        "Son": x["close"].round(2).values,
        "Değişim %": x["change"].round(2).values,
        "RSI": x["RSI"].round(1).values,
        "Hacim x": x["relvol"].round(2).values,
        "Giriş": entry.round(2).values,
        "Stop": stop.round(2).values,
        "Hedef": (entry + 1.5 * (entry - stop)).round(2).values,
        "Sinyaller": x["trend_sinyal"].values,
    }, columns=TREND_COLS)


def top100(d):
    """BIST 100 yaklaşığı: piyasa değeri en büyük 100 hisse."""
    return d.sort_values("market_cap_basic", ascending=False).head(100)


def market_line(d):
    try:
        x = top100(d)
        up, down = int((x["change"] > 0).sum()), int((x["change"] < 0).sum())
        above = 100 * (x["close"] > x["EMA20"]).mean()
        return (f"Piyasa (en büyük 100 hisse): {up} yükselen / {down} düşen | "
                f"medyan değişim {x['change'].median():+.2f}% | %{above:.0f}'i EMA20 üstünde")
    except Exception:
        return "Piyasa özeti hesaplanamadı."


# ---------------------------------------------------------------- Başarı takibi
# Not: resmi tatil günlerinde veri eski kalır; o günkü kayıtlar tekrar sayılabilir.
LOG_COLS = ["tarih", "saat", "hisse", "fiyat", "degisim", "skor", "relvol", "tavan_oldu"]


def _read_log():
    if not os.path.exists(LOG_PATH):
        return pd.DataFrame(columns=LOG_COLS)
    return pd.read_csv(LOG_PATH, dtype={"tavan_oldu": "object", "hisse": "object"})


def todays_progress(d, now):
    """Bugün daha önce listelenip şu an tavanda olanlar (kayıt eklenmeden önce çağır)."""
    log = _read_log()
    today = log[log["tarih"] == now.strftime("%Y-%m-%d")]
    if today.empty:
        return ""
    listed = sorted(set(today["hisse"]))
    hit = set(d.loc[d["change"] >= 9.5, "name"])
    got = [h for h in listed if h in hit]
    return (f"Bugün listelenen {len(listed)} adaydan şu an tavanda olan: "
            f"{len(got)}" + (" (" + ", ".join(got) + ")" if got else ""))


def _minutes(now):
    return now.hour * 60 + now.minute


def in_session(now):
    """Veri taze mi? Hafta içi 10:20-18:05 (veri 15 dk gecikmeli)."""
    return now.weekday() < 5 and 10 * 60 + 20 <= _minutes(now) <= 18 * 60 + 5


def in_settle_window(now):
    """Kapanış değerlendirmesi: hafta içi 18:10-20:00."""
    return now.weekday() < 5 and 18 * 60 + 10 <= _minutes(now) <= 20 * 60


def log_run(x, now):
    """Adayları kaydeder. Seans dışında ya da veri eskiyse (tatil) kaydetmez. True/False döner."""
    if x.empty or not in_session(now):
        return False
    rows = pd.DataFrame({
        "tarih": now.strftime("%Y-%m-%d"), "saat": now.strftime("%H:%M"),
        "hisse": x["name"].values, "fiyat": x["close"].round(2).values,
        "degisim": x["change"].round(2).values, "skor": x["tavan_skor"].values,
        "relvol": x["relvol"].round(2).values, "tavan_oldu": ""})
    log = _read_log()
    if not log.empty:
        last = log[(log["tarih"] == log["tarih"].iloc[-1]) & (log["saat"] == log["saat"].iloc[-1])]
        if last["tarih"].iloc[0] != now.strftime("%Y-%m-%d") and \
                set(zip(last["hisse"], last["fiyat"])) == set(zip(rows["hisse"], rows["fiyat"])):
            return False  # önceki günün aynısı: resmi tatil, veri eski
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    rows.to_csv(LOG_PATH, mode="a", header=not os.path.exists(LOG_PATH), index=False)
    return True


def settle_and_summarize(d, now):
    """Gün sonu: bugünkü adayların tavan olup olmadığını işler, başarı özetini döndürür."""
    log = _read_log()
    if log.empty:
        return ""
    today = now.strftime("%Y-%m-%d")
    hit = set(d.loc[d["change"] >= 9.5, "name"])
    m = log["tarih"] == today
    log.loc[m, "tavan_oldu"] = log.loc[m, "hisse"].map(lambda h: "1" if h in hit else "0")
    log.to_csv(LOG_PATH, index=False)

    done = log[log["tavan_oldu"].isin(["0", "1"])]
    first = done.sort_values(["tarih", "saat"]).drop_duplicates(["tarih", "hisse"])
    if first.empty:
        return ""

    def rate(x):
        k = int((x["tavan_oldu"] == "1").sum())
        return f"{k}/{len(x)} (%{100 * k / len(x):.0f})" if len(x) else "-"

    t = first[first["tarih"] == today]
    gun = first["tarih"].nunique()
    return "\n".join([
        f"BAŞARI TAKİBİ (adaylar ilk göründüğünde kaydedilir, kapanışta tavan olanlar sayılır)",
        f"Bugün: {rate(t)}",
        f"Tüm günler ({gun} gün): {rate(first)}",
        f"  Tavan skoru >=4: {rate(first[first['skor'] >= 4])}",
        f"  Tavan skoru <=3: {rate(first[first['skor'] <= 3])}",
        f"  Göreceli hacim >=2x: {rate(first[first['relvol'] >= 2])}",
    ])
