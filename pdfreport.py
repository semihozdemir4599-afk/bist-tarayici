"""PDF rapor üretimi (reportlab): yatay A4, sıralı tablolar, Türkçe karakter destekli."""
import os
from xml.sax.saxutils import escape

import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TEXT_COLS = {"Tavan sinyalleri", "Sinyaller"}
FIXED = {"Hisse": 46, "Durum": 84, "Tavan skoru (0-6)": 56, "Trend skoru (0-6)": 56}
NUM_W = 54
_ASCII = str.maketrans("ığüşöçİĞÜŞÖÇ", "igusocIGUSOC")


def _font_files():
    bases = []
    try:
        import matplotlib
        bases.append(os.path.join(matplotlib.get_data_path(), "fonts", "ttf"))
    except Exception:
        pass
    bases += ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu"]
    for b in bases:
        r, bd = os.path.join(b, "DejaVuSans.ttf"), os.path.join(b, "DejaVuSans-Bold.ttf")
        if os.path.exists(r) and os.path.exists(bd):
            return r, bd
    return None, None


def _setup_fonts():
    r, b = _font_files()
    if r:
        pdfmetrics.registerFont(TTFont("DV", r))
        pdfmetrics.registerFont(TTFont("DV-B", b))
        return "DV", "DV-B", (lambda s: s)
    return "Helvetica", "Helvetica-Bold", (lambda s: s.translate(_ASCII))  # font yoksa ASCII


def _fmt(v):
    if isinstance(v, (bool, np.bool_)):
        return str(v)
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return "-" if np.isnan(v) else f"{v:.2f}"
    return str(v)


def _table(df, regular, bold, tr, avail):
    cols = list(df.columns)
    cell = ParagraphStyle("c", fontName=regular, fontSize=7.5, leading=9)
    head = ParagraphStyle("h", fontName=bold, fontSize=7.5, leading=9, textColor=colors.white)
    widths = [FIXED.get(c, NUM_W) for c in cols if c not in TEXT_COLS]
    n_text = sum(1 for c in cols if c in TEXT_COLS)
    rest = avail - sum(widths)
    scale = 1.0
    if n_text and rest < 120 * n_text:
        scale = (avail - 120 * n_text) / sum(widths)
    it = iter(widths)
    col_w = [(120 if rest < 120 * n_text else rest / n_text) if c in TEXT_COLS
             else next(it) * scale for c in cols]

    data = [[Paragraph(escape(tr(str(c))), head) for c in cols]]
    for _, row in df.iterrows():
        data.append([Paragraph(escape(tr(_fmt(row[c]))), cell) for c in cols])
    if "Değişim %" in cols:  # artı yeşil, eksi kırmızı (tablo oluşturulmadan önce uygulanmalı)
        j = cols.index("Değişim %")
        for i, v in enumerate(df["Değişim %"].values, start=1):
            col = "#0a7a3b" if v > 0 else "#b3261e" if v < 0 else "#222222"
            data[i][j] = Paragraph(escape(_fmt(v)), ParagraphStyle(
                "v", parent=cell, textColor=colors.HexColor(col), fontName=bold))
    t = Table(data, colWidths=col_w, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c9cfd8")),
             ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
             ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f1f4f8")))
    t.setStyle(TableStyle(style))
    return t


def build_pdf(path, title, stamp, mline, sections, texts=(), disclaimer=""):
    """sections: [(başlık, DataFrame, not|None)], texts: [(başlık, metin)]"""
    regular, bold, tr = _setup_fonts()
    page = landscape(A4)
    margin = 24
    avail = page[0] - 2 * margin
    h1 = ParagraphStyle("h1", fontName=bold, fontSize=16, leading=20)
    h2 = ParagraphStyle("h2", fontName=bold, fontSize=11, leading=14, spaceBefore=10, spaceAfter=4,
                        textColor=colors.HexColor("#1f3a5f"))
    body = ParagraphStyle("b", fontName=regular, fontSize=8.5, leading=11)
    small = ParagraphStyle("s", fontName=regular, fontSize=7.5, leading=10,
                           textColor=colors.HexColor("#555555"))

    def P(text, style):
        return Paragraph(escape(tr(text)).replace("\n", "<br/>"), style)

    story = [P(f"{title} - {stamp}", h1), Spacer(1, 3), P(mline, body),
             P("Veri: TradingView, yaklaşık 15 dakika gecikmeli.", small)]
    for heading, df, note in sections:
        story.append(P(heading, h2))
        if df is None or df.empty:
            story.append(P("Şu an yok.", body))
        else:
            story.append(_table(df, regular, bold, tr, avail))
        if note:
            story += [Spacer(1, 3), P(note, small)]
    for heading, text in texts:
        if text:
            story += [P(heading, h2), P(text, body)]
    if disclaimer:
        story += [Spacer(1, 8), P(disclaimer, small)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 7)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawRightString(page[0] - margin, 12, tr(f"Sayfa {doc.page}"))
        canvas.restoreState()

    SimpleDocTemplate(path, pagesize=page, leftMargin=margin, rightMargin=margin,
                      topMargin=margin, bottomMargin=24, title=tr(f"{title} {stamp}")
                      ).build(story, onFirstPage=footer, onLaterPages=footer)
    return path
