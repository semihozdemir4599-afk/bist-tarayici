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
import uuid
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pdfreport
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


NEXT_NOTE = ("Geçmiş testte (5 yıllık günlük veri) benzer skorlu hisselerin ertesi gün tavana "
             "dokunma oranı yaklaşık %23, tavanda kapatma oranı yaklaşık %14 idi; ama açılıştan "
             "alım kârlı değildi. Bu liste izleme listesidir, tavan garantisi değildir. Açılış "
             "boşluğunu ve tahtayı Meksa'dan kontrol et.")


def line_next(r):
    return (f"{r['Hisse']} | skor {r['Tavan skoru (0-6)']}/6 | {r['Değişim %']:+.1f}% | "
            f"hacim {r['Hacim (mn TL)']:.0f} mn TL | RSI {r['RSI']:.0f} | {r['Durum']}\n"
            f"   kapanış {r['Kapanış']} | yarın tavan fiyatı {r['Yarın tavan fiyatı']}\n"
            f"   {r['Tavan sinyalleri']}")


def build_text(stamp, mline, run_t, lock_t, trend_t, progress, summary,
               next_t=None, next_summary="", final=False):
    title = "BIST Gün Sonu Raporu" if final else "BIST Raporu"
    p = [f"{title} - {stamp}", mline, "",
         "TAVANA YÜRÜYENLER (gün içi %4 üstü, tavan olmamış)"]
    p += [line_run(r) for _, r in run_t.iterrows()] or ["Şu an yok."]
    p += ["", f"ŞU AN TAVANDA ({len(lock_t)} hisse)"]
    p += [line_lock(r) for _, r in lock_t.iterrows()] or ["Yok."]
    p += ["", "TREND ADAYLARI (BIST 100, skor >= 5)"]
    p += [line_trend(r) for _, r in trend_t.iterrows()] or ["Yok."]
    if final and next_t is not None:
        p += ["", f"YARININ OLASI TAVAN ADAYLARI (gün sonu verisine göre, {len(next_t)} hisse)"]
        p += [line_next(r) for _, r in next_t.iterrows()] or ["Şu an yok."]
        p += ["", NEXT_NOTE]
    if next_summary:
        p += ["", next_summary]
    if progress:
        p += ["", progress]
    if summary:
        p += ["", summary]
    p += ["", DISCLAIMER]
    return "\n".join(p)


def build_short(stamp, mline, run_t, lock_t, trend_t, progress, summary,
                next_t=None, next_summary="", final=False):
    """Telegram'a giden kısa özet. Tam tablolar PDF ekindedir."""
    title = "BIST Gün Sonu Raporu" if final else "BIST Raporu"
    p = [f"{title} - {stamp}", mline, ""]
    if final and next_t is not None:
        p += [f"YARININ OLASI TAVAN ADAYLARI (ilk 5 / {len(next_t)})"]
        p += [f"{r['Hisse']} {r['Değişim %']:+.1f}% | skor {r['Tavan skoru (0-6)']}/6 | "
              f"{r['Durum']} | yarın tavan {r['Yarın tavan fiyatı']}"
              for _, r in next_t.head(5).iterrows()] or ["Şu an yok."]
        p += [""]
    p += [f"TAVANA YÜRÜYENLER (ilk 5 / {len(run_t)})"]
    p += [f"{r['Hisse']} {r['Değişim %']:+.1f}% | skor {r['Tavan skoru (0-6)']}/6 | "
          f"{r['Hacim (mn TL)']:.0f} mn TL | giriş {r['Giriş']} → hedef {r['Hedef']} (stop {r['Stop']})"
          for _, r in run_t.head(5).iterrows()] or ["Şu an yok."]
    names = ", ".join(lock_t["Hisse"].head(10))
    more = ", ..." if len(lock_t) > 10 else ""
    p += ["", f"ŞU AN TAVANDA: {len(lock_t)} hisse" + (f" ({names}{more})" if len(lock_t) else "")]
    p += [f"TREND ADAYLARI: " + (", ".join(trend_t["Hisse"]) if len(trend_t) else "yok")]
    for extra in (next_summary, progress, summary):
        if extra:
            p += ["", extra]
    p += ["", "Tam tablolar ekteki PDF'te. Veri ~15 dk gecikmeli, yatırım tavsiyesi değildir."]
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


def send_telegram_document(token, chat_id, path, caption=""):
    """PDF'i Telegram'a belge olarak yollar (multipart, ek kütüphane gerektirmez)."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("chat_id", chat_id), ("caption", caption)):
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                      f"{value}\r\n").encode())
    with open(path, "rb") as f:
        content = f.read()
    fname = os.path.basename(path)
    parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; "
                  f"filename=\"{fname}\"\r\nContent-Type: application/pdf\r\n\r\n").encode()
                 + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendDocument", data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode())
        if not body.get("ok"):
            raise RuntimeError("Telegram belge hatası")


def send_email(user, pwd, to, subject, html, pdf_path=None):
    msg = MIMEMultipart("mixed")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(html, "html", "utf-8"))
    if pdf_path:
        with open(pdf_path, "rb") as f:
            att = MIMEApplication(f.read(), _subtype="pdf")
        att.add_header("Content-Disposition", "attachment", filename=os.path.basename(pdf_path))
        msg.attach(att)
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

    settle = tv.in_settle_window(now)
    fresh = tv.in_session(now)
    progress = tv.todays_progress(d, now) if fresh else ""
    tv.log_run(run_raw, now)
    summary = tv.settle_and_summarize(d, now) if settle else ""
    next_raw = tv.next_day_candidates(d) if settle else None
    next_t = tv.next_table(next_raw) if settle else None
    next_summary = tv.settle_next(d, now) if settle else ""  # önce dünkü liste değerlendirilir
    if settle:
        tv.log_next(next_raw, now)
    if not fresh and not settle:
        mline += "\n(Seans dışı: veri son kapanışa aittir, kayıt tutulmadı.)"

    text = build_text(stamp, mline, run_t, lock_t, trend_t, progress, summary,
                      next_t, next_summary, settle)
    title = "BIST Gün Sonu Raporu" if settle else "BIST Raporu"
    next_html = (f"<h3>Yarının olası tavan adayları (gün sonu verisine göre)</h3>"
                 f"{to_html(next_t)}<pre>{next_summary}</pre>"
                 f"<p class='warn'>{NEXT_NOTE}</p>") if settle else ""
    html = f"""<html><head>{STYLE}</head><body>
<h2>{title} - {stamp}</h2><p>{mline}</p>
<h3>Tavana yürüyenler (gün içi %4 üstü, tavan olmamış)</h3>{to_html(run_t)}
<h3>Şu an tavanda ({len(lock_t)} hisse)</h3>{to_html(lock_t)}
<h3>Trend adayları (BIST 100, skor >= 5)</h3>{to_html(trend_t)}
{next_html}
<p>{progress}</p><pre>{summary}</pre>
<p class="warn">{DISCLAIMER}</p></body></html>"""

    sent, errors = [], []

    # PDF: tam tablolar. Üretilemezse tam metin mesajına geri dönülür, rapor kaybolmaz.
    pdf_path = f"BIST_{now:%Y%m%d_%H%M}.pdf"
    sections = [("Tavana yürüyenler (gün içi %4 üstü, tavan olmamış)", run_t, None),
                (f"Şu an tavanda ({len(lock_t)} hisse)", lock_t, None),
                ("Trend adayları (BIST 100 yaklaşığı, skor >= 5)", trend_t, None)]
    if settle:
        sections.insert(0, (f"Yarının olası tavan adayları (gün sonu verisine göre, {len(next_t)} hisse)",
                            next_t, NEXT_NOTE))
    try:
        pdfreport.build_pdf(pdf_path, title, stamp, mline, sections,
                            texts=[("Yarın-adayı takibi", next_summary),
                                   ("Bugünkü adaylar", progress), ("Başarı takibi", summary)],
                            disclaimer=DISCLAIMER)
    except Exception as e:
        errors.append("PDF: " + type(e).__name__ + " " + str(e)[:100])
        pdf_path = None
    short = build_short(stamp, mline, run_t, lock_t, trend_t, progress, summary,
                        next_t, next_summary, settle)

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if tg_token and tg_chat:
        try:
            send_telegram(tg_token, tg_chat, short if pdf_path else text)
            if pdf_path:
                try:
                    send_telegram_document(tg_token, tg_chat, pdf_path, f"{title} - {stamp}")
                except Exception as e:
                    errors.append("Telegram PDF: " + type(e).__name__)
                    send_telegram(tg_token, tg_chat, text)  # PDF gitmediyse tam metin
            sent.append("Telegram")
        except Exception as e:
            errors.append("Telegram: " + type(e).__name__)  # token loga yazılmasın

    user = os.environ.get("GMAIL_USER", "").strip()
    pwd = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    to = os.environ.get("MAIL_TO", "").strip() or user
    if user and pwd:
        try:
            send_email(user, pwd, to, f"{title} {stamp}", html, pdf_path)
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
