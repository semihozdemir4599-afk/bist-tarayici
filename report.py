"""BIST raporu (TradingView verisi): tavana yürüyenler, tavandakiler, trend adayları.
Telegram (önerilen) ve/veya e-posta ile gönderir. GitHub Actions tarafından çalıştırılır.
Telegram: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
E-posta : GMAIL_USER, GMAIL_APP_PASSWORD, MAIL_TO (isteğe bağlı)
"""
import json
import os
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import tvscan as tv

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

DISCLAIMER = ("Veri TradingView kaynaklıdır ve yaklaşık 15 dakika gecikmelidir. Tavan skoru "
              "henüz doğrulanmamış bir sıralama aracıdır, tavan garantisi vermez. Geçmiş testlerde "
              "günlük veriyle açılış alımı kâr getirmedi. Giriş/çıkış öncesi anlık fiyatı ve "
              "tahtayı Meksa'dan kontrol et. Yatırım tavsiyesi değildir.")


def to_html(df):
    if df.empty:
        return "<p>Kriterleri sağlayan hisse yok.</p>"
    return df.to_html(index=False, border=0, na_rep="-")


def line_run(r):
    return (f"{r['Hisse']} | skor {r['Tavan skoru (0-6)']}/6 | {r['Değişim %']:+.1f}% | "
            f"hacim {r['Hacim (mn TL)']:.0f} mn TL | RSI {r['RSI']:.0f}\n"
            f"   giriş {r['Giriş']} | hedef {r['Hedef']} | stop {r['Stop']}\n"
            f"   {r['Tavan sinyalleri']}")


def line_lock(r):
    return (f"{r['Hisse']} {r['Değişim %']:+.1f}% | skor {r['Tavan skoru (0-6)']}/6 | "
            f"hacim {r['Hacim (mn TL)']:.0f} mn TL | RSI {r['RSI']:.0f}")


def line_trend(r):
    return (f"{r['Hisse']} {r['Son']} ({r['Değişim %']:+.1f}%) skor {r['Trend skoru (0-6)']}/6 | "
            f"RSI {r['RSI']:.0f} | hacim {r['Hacim x']}x\n"
            f"   giriş {r['Giriş']} | stop {r['Stop']} | hedef {r['Hedef']}")


def build_text(stamp, mline, run_t, lock_t, trend_t, progress, summary):
    p = [f"BIST Raporu - {stamp}", mline, "",
         "TAVANA YÜRÜYENLER (gün içi %4 üstü, tavan olmamış)"]
    p += [line_run(r) for _, r in run_t.iterrows()] or ["Şu an yok."]
    p += ["", f"ŞU AN TAVANDA ({len(lock_t)} hisse)"]
    p += [line_lock(r) for _, r in lock_t.iterrows()] or ["Yok."]
    p += ["", "TREND ADAYLARI (BIST 100, skor >= 5)"]
    p += [line_trend(r) for _, r in trend_t.iterrows()] or ["Yok."]
    if progress:
        p += ["", progress]
    if summary:
        p += ["", summary]
    p += ["", DISCLAIMER]
    return "\n".join(p)


def chunk_text(text, limit=3900):
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit and cur:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur)
    return chunks


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for part in chunk_text(text):
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": part,
                                       "disable_web_page_preview": "true"}).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as resp:
            body = json.loads(resp.read().decode())
            if not body.get("ok"):
                raise RuntimeError("Telegram hatası: " + str(body))


def send_email(user, pwd, to, subject, html):
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(user, pwd.replace(" ", ""))
        s.sendmail(user, [x.strip() for x in to.split(",")], msg.as_string())


def main():
    now = datetime.now(tv.TZ)
    stamp = now.strftime("%d.%m.%Y %H:%M")
    d = tv.enrich(tv.fetch_all())
    if d.empty:
        raise SystemExit("Veri alınamadı.")

    run_raw = tv.tavan_candidates(d)
    run_t = tv.tavan_table(run_raw)
    lock_t = tv.lock_table(tv.tavan_locked(d))
    trend_t = tv.trend_table(tv.trend_candidates(d))
    mline = tv.market_line(d)

    fresh = tv.in_session(now)
    progress = tv.todays_progress(d, now) if fresh else ""
    tv.log_run(run_raw, now)
    summary = tv.settle_and_summarize(d, now) if tv.in_settle_window(now) else ""
    if not fresh and not summary:
        mline += "\n(Seans dışı: veri son kapanışa aittir, kayıt tutulmadı.)"

    text = build_text(stamp, mline, run_t, lock_t, trend_t, progress, summary)
    html = f"""<html><head>{STYLE}</head><body>
<h2>BIST Raporu - {stamp}</h2><p>{mline}</p>
<h3>Tavana yürüyenler (gün içi %4 üstü, tavan olmamış)</h3>{to_html(run_t)}
<h3>Şu an tavanda ({len(lock_t)} hisse)</h3>{to_html(lock_t)}
<h3>Trend adayları (BIST 100, skor >= 5)</h3>{to_html(trend_t)}
<p>{progress}</p><pre>{summary}</pre>
<p class="warn">{DISCLAIMER}</p></body></html>"""

    sent, errors = [], []
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if tg_token and tg_chat:
        try:
            send_telegram(tg_token, tg_chat, text)
            sent.append("Telegram")
        except Exception as e:
            errors.append("Telegram: " + type(e).__name__)  # token loga yazılmasın

    user = os.environ.get("GMAIL_USER", "").strip()
    pwd = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    to = os.environ.get("MAIL_TO", "").strip() or user
    if user and pwd:
        try:
            send_email(user, pwd, to, f"BIST Raporu {stamp}", html)
            sent.append("E-posta")
        except Exception as e:
            errors.append("E-posta: " + type(e).__name__ + " " + str(e)[:120])

    if not (tg_token and tg_chat) and not (user and pwd):
        print("Gönderim ayarı yok. Rapor metni:\n" + text)
        return
    print("Gönderilen:", ", ".join(sent) if sent else "yok", "| Hatalar:", errors or "yok")
    if not sent:
        raise SystemExit("Rapor hiçbir kanaldan gönderilemedi.")


if __name__ == "__main__":
    main()
