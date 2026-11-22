import pandas as pd
import streamlit as st

import scanner as sc

st.set_page_config(page_title="BIST Günlük Tarayıcı", layout="wide")


@st.cache_data(ttl=900, show_spinner=False)
def fetch_cached(tickers):
    return sc.fetch(list(tickers))


st.title("BIST Günlük Tarayıcı")
st.caption(
    "EMA20 / EMA50 / RSI / MACD / Hacim bazlı skorlama ve tavan adayı taraması. "
    "Veri: Yahoo Finance (gecikmeli, günlük mum). Yatırım tavsiyesi değildir."
)

trend_list = sc.read_list("tickers.txt")
wide = sorted(set(trend_list) | set(sc.read_list("tavan_evren.txt")))

if st.button("Taramayı çalıştır / yenile", type="primary"):
    st.cache_data.clear()

with st.spinner("Veriler indiriliyor ve hesaplanıyor..."):
    raw = fetch_cached(tuple(wide))
    rows, frames, failed = sc.scan(wide, raw)

if not rows:
    st.error("Veri alınamadı. Biraz sonra tekrar dene.")
    st.stop()

all_df = pd.DataFrame(rows)
st.caption("Son mum tarihi: " + str(all_df["Son mum"].max()) +
           " (seans içinde bugünün mumu henüz tamamlanmamıştır)")

tab_trend, tab_tavan = st.tabs(["Trend adayları (BIST 100)", "Tavan adayları (geniş liste)"])

with tab_trend:
    min_score = st.slider("Minimum trend skoru", 0, 7, 5)
    t = all_df[all_df["Hisse"].isin(trend_list)]
    t = t[t["Skor (0-7)"] >= min_score].sort_values(
        ["Skor (0-7)", "Hacim x"], ascending=False)
    st.subheader(f"Trend adayları ({len(t)} hisse)")
    st.dataframe(t[sc.TREND_COLS], use_container_width=True, hide_index=True)

with tab_tavan:
    c1, c2 = st.columns(2)
    min_tv = c1.slider("Minimum tavan skoru", 0, 6, 4)
    min_turn = c2.slider("Minimum ort. işlem hacmi (milyon TL)", 0, 100, 5)
    v = all_df[(all_df["Tavan skor (0-6)"] >= min_tv)
               & (all_df["Ort. hacim (mn TL)"] >= min_turn)]
    v = v.sort_values(["Tavan skor (0-6)", "Hacim x"], ascending=False)
    st.subheader(f"Tavan adayları ({len(v)} hisse)")
    st.dataframe(v[sc.TAVAN_COLS], use_container_width=True, hide_index=True)
    st.warning(
        "Tavan adayı = 'sıçrama olasılığı görece yüksek' demektir, tavan garantisi değildir. "
        "Geçmiş testlerde (backtest_tavan.py) kuralların işe yarayıp yaramadığını kontrol et. "
        "Düşük hacimli hisselerde tavan kilitlenirse alım/satım yapamayabilirsin."
    )

if failed:
    st.caption("Verisi alınamayan hisseler: " + ", ".join(failed))

st.subheader("Hisse detayı")
pick = st.selectbox("Hisse seç", sorted(frames.keys()))
d = frames[pick].tail(120)
st.line_chart(d[["Close", "EMA20", "EMA50"]])
g1, g2 = st.columns(2)
g1.caption("RSI")
g1.line_chart(d[["RSI"]])
g2.caption("MACD / Sinyal")
g2.line_chart(d[["MACD", "SIG"]])

with st.expander("Skorlar ve seviyeler nasıl hesaplanıyor?"):
    st.markdown(
        """
**Trend skoru (0-7):** Fiyat>EMA20, EMA20>EMA50, RSI 50-70, MACD>Sinyal, MACD histogramı artıyor,
hacim 20g ortalamanın 1,5 katı ve üstü, fiyat 20g zirvenin %2 yakınında. RSI>75 ise 1 puan düşer.
Giriş: günün yükseğinin %0,2 üstü. Stop: giriş - 1,5 ATR. Hedefler: giriş + 1,5 / 3 ATR.

**Tavan skoru (0-6):** hacim >=2x, gün içi değişim >=+%4, kapanış günün üst %10'unda,
20g zirve kırılımı, fiyat>EMA20, bugün tavan/tavana yakın (>=%9,5).
Referans giriş: son kapanış (ertesi gün açılışı gap'e göre kontrol et). Stop: günün düşüğü.
Hedef: +%5 ve tavan fiyatı (kapanış x 1,10; yaklaşık).

Seans içinde bugünün mumu eksiktir: hacim, geçen seans oranına göre tahmini ölçeklenir.
"""
    )
