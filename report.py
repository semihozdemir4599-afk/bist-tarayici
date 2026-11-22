"""E-posta raporu: trend adayları + tavan adayları. GitHub Actions tarafından çalıştırılır."""
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
import yfinance as yf

import scanner as sc

TREND_MIN_SCORE = 5
TAVAN_MIN_SCORE = 4
MIN_TURNOVER_MN = 5
TOP_N = 15

STYLE = """
<style>
body{font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#222}
table{border-collapse:collapse;margin:8px 0 18px 0}
th,td{border:1px solid #ccc;padding:4px 7px;text-align:right;white-space:nowrap}
th{background:#f0f2f6}
td:first-child,th:first-child{text-align:left;font-weight:bold}
td:last-child{text-align:left;white-space:normal}
.warn{color:#8a4b00;background:#fff4e0;padding:8px;border-radius:4px}
</style>
"""


def market_line():
    try:
        x = yf.download("XU100.IS", period="6mo", interval="1d", progress=False,
                        auto_adjust=False)
        c = x["Close"]
        if isinstance(c, pd.DataFrame):
            c = c.iloc[:, 0]
        c = c.dropna()
        e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
        last = float(c.iloc[-1])
        durum = ("EMA50 üstünde" if last > float(e50.iloc[-1]) else "EMA50 altında")
        trend = ("EMA20 üstünde" if last > float(e20.iloc[-1]) else "EMA20 altında")
        return (f"BIST 100: {last:,.0f} puan | {trend}, {durum} "
                f"(EMA20 {float(e20.iloc[-1]):,.0f}, EMA50 {float(e50.iloc[-1]):,.0f})")
    except Exception:
        return "BIST 100 durumu alınamadı."


def to_html(df, cols):
    if df.empty:
        return "<p>Kriterleri sağlayan hisse yok.</p>"
    return df[cols].to_html(index=False, border=0, na_rep="-")


def main():
    trend_list = sc.read_list("tickers.txt")
    wide = sorted(set(trend_list) | set(sc.read_list("tavan_evren.txt")))
    raw = sc.fetch(wide)
    rows, _, failed = sc.scan(wide, raw)
    if not rows:
        raise SystemExit("Veri alınamadı.")
    df = pd.DataFrame(rows)

    trend = df[df["Hisse"].isin(trend_list) & (df["Skor (0-7)"] >= TREND_MIN_SCORE)]
    trend = trend.sort_values(["Skor (0-7)", "Hacim x"], ascending=False).head(TOP_N)
    tavan = df[(df["Tavan skor (0-6)"] >= TAVAN_MIN_SCORE)
               & (df["Ort. hacim (mn TL)"] >= MIN_TURNOVER_MN)]
    tavan = tavan.sort_values(["Tavan skor (0-6)", "Hacim x"], ascending=False).head(TOP_N)

    now = datetime.now(sc.TZ)
    stamp = now.strftime("%d.%m.%Y %H:%M")
    html = f"""<html><head>{STYLE}</head><body>
<h2>BIST Raporu - {stamp}</h2>
<p>{market_line()}<br>Son mum tarihi: {df['Son mum'].max()}</p>
<h3>Trend adayları (BIST 100, skor >= {TREND_MIN_SCORE})</h3>
{to_html(trend, sc.TREND_COLS)}
<h3>Tavan adayları (geniş liste, tavan skoru >= {TAVAN_MIN_SCORE}, ort. hacim >= {MIN_TURNOVER_MN} mn TL)</h3>
{to_html(tavan, sc.TAVAN_COLS)}
<p class="warn">Veri Yahoo Finance kaynaklıdır, gecikmelidir ve günlük mum bazlıdır;
seans içi raporlarda bugünün mumu eksiktir (hacim tahmini ölçeklenir).
Bu liste izleme listesidir, yatırım tavsiyesi değildir. Tavan garantisi yoktur.
Giriş/çıkış öncesi gün içi fiyatı ve tahtayı kontrol et.</p>
<p>Verisi alınamayanlar: {', '.join(failed) if failed else '-'}</p>
</body></html>"""

    user = os.environ.get("GMAIL_USER")
    pwd = os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("MAIL_TO", user)
    if not user or not pwd:
        with open("report.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("GMAIL_USER / GMAIL_APP_PASSWORD tanımlı değil, rapor report.html olarak kaydedildi.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"BIST Raporu {stamp}"
    msg["From"] = user
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pwd.replace(" ", ""))
        s.sendmail(user, [x.strip() for x in to.split(",")], msg.as_string())
    print("Rapor gönderildi:", stamp)


if __name__ == "__main__":
    main()
