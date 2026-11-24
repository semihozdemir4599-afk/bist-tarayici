import streamlit as st

import tvscan as tv

st.set_page_config(page_title="BIST Tarayıcı", layout="wide")


@st.cache_data(ttl=120, show_spinner=False)
def load():
    return tv.enrich(tv.fetch_all())


st.title("BIST Tarayıcı (tüm hisseler)")
st.caption("Veri: TradingView, yaklaşık 15 dakika gecikmeli. Tavan skoru doğrulanmamış bir "
           "sıralama aracıdır, yatırım tavsiyesi değildir.")

if st.button("Yenile", type="primary"):
    st.cache_data.clear()

with st.spinner("Veriler alınıyor..."):
    try:
        d = load()
    except Exception as e:
        st.error("Veri alınamadı: " + type(e).__name__)
        st.stop()

st.write(tv.market_line(d))
st.caption(f"{len(d)} hisse tarandı.")

tab1, tab2, tab3 = st.tabs(["Tavana yürüyenler", "Şu an tavanda", "Trend adayları (BIST 100)"])

with tab1:
    min_chg = st.number_input("Minimum gün içi değişim %", 0.0, 9.0, 4.0, 0.5)
    x = tv.tavan_candidates(d, min_change=min_chg, top=60)
    st.subheader(f"Tavana yürüyenler ({len(x)} hisse)")
    st.dataframe(tv.tavan_table(x), use_container_width=True, hide_index=True)
    st.caption("Giriş: anlık fiyat (gecikmeli). Hedef: tavan fiyatı. "
               "Stop: günün düşüğü ya da giriş -%3'ten hangisi yakınsa.")

with tab2:
    x = tv.tavan_locked(d, top=100)
    st.subheader(f"Şu an tavanda ({len(x)} hisse)")
    st.dataframe(tv.lock_table(x), use_container_width=True, hide_index=True)

with tab3:
    ms = st.slider("Minimum trend skoru", 0, 6, 5)
    x = tv.trend_candidates(d, min_score=ms, top=60)
    st.subheader(f"Trend adayları ({len(x)} hisse)")
    st.dataframe(tv.trend_table(x), use_container_width=True, hide_index=True)

with st.expander("Skorlar nasıl hesaplanıyor?"):
    st.markdown("""
**Tavan skoru (0-6):** göreceli hacim >=2x, gün içi değişim >=+%4, fiyat günün üst %10'unda,
fiyat>EMA20, MACD>Sinyal, tavan/tavana yakın (>=%9,5).
**Trend skoru (0-6):** fiyat>EMA20, EMA20>EMA50, RSI 50-70, MACD>Sinyal, hacim >=1,5x,
fiyat 52 hafta zirvesinin %90'ı üstünde (RSI>75 ise 1 puan düşer).
Bu skorlar henüz geçmiş veriyle doğrulanmadı. Rapor her gün adayları kaydedip kapanışta
kaçının tavan olduğunu sayar (başarı takibi).
""")
