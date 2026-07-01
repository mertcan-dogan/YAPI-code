"""CR-036 PDF design toolkit — ReportLab theme & flowable factory.

Pure ReportLab (NO DB, NO matplotlib). Ported from the proven Heneka reference
build (``heneka_report_reference_build.py``). Provides the Heneka colour palette,
idempotent registration of the bundled Lato font weights, and a small set of
flowable factories (styles, pills, section headers, KPI cards, chart cards, the
AI early-warning panel and the data table) that a renderer composes into a
ReportLab story.

The matplotlib chart helpers live in ``report_charts`` so this module stays
import-light — it never imports matplotlib.
"""
import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.colors import HexColor, white
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, Image

# ---------------------------------------------------------------------------
# Palette — EXACT Heneka hex (reference lines 17-19).
# ---------------------------------------------------------------------------
NAVY = "#183047"
PETROL = "#0E625B"
GOLD = "#B9852A"
BG = "#F5F6F2"
INK = "#182422"
MUT = "#65726F"
RED = "#B94D45"
AMBER = "#C98E24"
GREEN = "#27815F"
HAIR = "#DCE0DA"
CARD = "#FFFFFF"
FNT = "#94A0A0"

RAG = {"r": RED, "a": AMBER, "g": GREEN}
TINT = {"r": "#F4E2E0", "a": "#F6ECD7", "g": "#E0EFE7"}

# ---------------------------------------------------------------------------
# Fonts — register the bundled Lato weights (app/fonts/lato/*.ttf).
# ---------------------------------------------------------------------------
# Mirror reports.FONTS_DIR so DejaVu and Lato share the same root.
FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")

# ReportLab font-name constants -> bundled ttf filename.
LATO_LIGHT = "Lato-Light"
LATO_REGULAR = "Lato"
LATO_MEDIUM = "Lato-Medium"
LATO_SEMIBOLD = "Lato-Semibold"
LATO_BOLD = "Lato-Bold"
LATO_BLACK = "Lato-Black"

_LATO_FILES = {
    LATO_LIGHT: "Lato-Light.ttf",
    LATO_REGULAR: "Lato-Regular.ttf",
    LATO_MEDIUM: "Lato-Medium.ttf",
    LATO_SEMIBOLD: "Lato-Semibold.ttf",
    LATO_BOLD: "Lato-Bold.ttf",
    LATO_BLACK: "Lato-Black.ttf",
}

_lato_registered = False

# Shared sample stylesheet — parent for every ParagraphStyle we build.
_BASE_STYLES = getSampleStyleSheet()


def register_lato_fonts():
    """Register the 6 bundled Lato weights with ReportLab (idempotent).

    Uses explicit bundled paths (app/fonts/lato/*.ttf) — NOT findSystemFonts.
    Also keeps DejaVu registered (via reports.register_turkish_fonts) so the
    Türkçe fallback family stays available.
    """
    global _lato_registered
    if _lato_registered:
        return
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.pdfmetrics import registerFontFamily

    lato_dir = os.path.join(FONTS_DIR, "lato")
    for name, fn in _LATO_FILES.items():
        pdfmetrics.registerFont(TTFont(name, os.path.join(lato_dir, fn)))

    # Map bold so <b> inline markup resolves when the base font is Lato.
    registerFontFamily(
        LATO_REGULAR,
        normal=LATO_REGULAR,
        bold=LATO_BOLD,
        italic=LATO_REGULAR,
        boldItalic=LATO_BOLD,
    )

    # Keep DejaVu registered as the Türkçe fallback family.
    from app.services import reports
    reports.register_turkish_fonts()

    _lato_registered = True


# ---------------------------------------------------------------------------
# Style helper (reference S()).
# ---------------------------------------------------------------------------
def s(name, font=LATO_REGULAR, size=9, color=INK, **kw):
    """Build a ParagraphStyle. ``color`` may be a hex string or a Color.

    ``leading`` defaults to ``size * 1.3`` and can be overridden via kwargs.
    """
    tc = color if isinstance(color, colors.Color) else HexColor(color)
    leading = kw.pop("leading", size * 1.3)
    return ParagraphStyle(
        name,
        parent=_BASE_STYLES["Normal"],
        fontName=font,
        fontSize=size,
        textColor=tc,
        leading=leading,
        **kw,
    )


def _esc(v):
    """Escape user-controlled text before it enters a ReportLab Paragraph.

    Paragraph interprets an XML-ish mini-markup (<b>, <font>, <a href>, entities),
    so a company / vendor / supplier / finding name containing '&' or '<' would
    crash doc.build() (DoS) or inject markup/links into the confidential PDF. Every
    data-bearing string in the factories below is escaped; numbers/None stringify
    harmlessly. (The AI summary keeps its own intentional markup — it is rendered
    outside this toolkit via _format_ai_md, which escapes its own input.)"""
    return escape(str(v))


# ---------------------------------------------------------------------------
# Flowable factories (reference pill/sect/kcard/kpirow/chartcard/aipanel/dtable).
# ---------------------------------------------------------------------------
def pill(text, rag, sz=7.5):
    """Rounded RAG status pill. ``rag`` is one of 'r' / 'a' / 'g'."""
    fg = RAG[rag]
    bg = TINT[rag]
    disp = str(text)
    wd = pdfmetrics.stringWidth(disp, LATO_BOLD, sz) + 13
    t = Table([[Paragraph(_esc(disp), s("p", LATO_BOLD, sz, fg, alignment=1))]], colWidths=[wd])
    t.hAlign = "LEFT"
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(bg)),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def sect(eyebrow, title):
    """Section header: gold eyebrow, navy title, gold rule. Returns flowables."""
    r = Table([[""]], colWidths=[1.0 * cm], rowHeights=[2.4])
    r.hAlign = "LEFT"
    r.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), HexColor(GOLD))]))
    return [
        Paragraph(eyebrow, s("eb", LATO_SEMIBOLD, 7.5, GOLD)),
        Spacer(1, 2),
        Paragraph(title, s("h", LATO_BOLD, 15, NAVY)),
        Spacer(1, 3),
        r,
        Spacer(1, 9),
    ]


def kcard(label, value, ctx=None, ctxcol=MUT, accent=PETROL):
    """A single KPI card: accent top rule, label, value, optional context."""
    rows = [
        [Paragraph(_esc(label), s("kl", LATO_SEMIBOLD, 7, MUT))],
        [Paragraph(_esc(value), s("kv", LATO_BOLD, 15, NAVY, leading=17))],
    ]
    if ctx:
        rows.append([Paragraph(_esc(ctx), s("kc", LATO_MEDIUM, 7.5, ctxcol))])
    inner = Table(rows, colWidths=[3.5 * cm])
    sty = [
        ("LINEABOVE", (0, 0), (-1, 0), 2.2, HexColor(accent)),
        ("BACKGROUND", (0, 0), (-1, -1), CARD),
        ("BOX", (0, 0), (-1, -1), 0.6, HexColor(HAIR)),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("TOPPADDING", (0, 1), (0, 1), 2),
        ("BOTTOMPADDING", (0, -1), (0, -1), 9),
    ]
    inner.setStyle(TableStyle(sty))
    return inner


def kpirow(items, colw=4.07):
    """Tile ``len(items)`` KPI cards across one row.

    ``items`` is a list of (label, value[, ctx, ctxcol, accent]) tuples;
    2-to-5-element tuples are tolerated (extra args use kcard defaults).
    """
    cells = [kcard(*it) for it in items]
    t = Table([cells], colWidths=[colw * cm] * len(cells))
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def chartcard(title, img, w, h):
    """White card wrapping a chart PNG (``img`` is a file path)."""
    inner = Table(
        [[Paragraph(title, s("ct", LATO_SEMIBOLD, 9, NAVY))],
         [Image(img, width=w, height=h)]],
        colWidths=[w + 0.7 * cm],
    )
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD),
        ("BOX", (0, 0), (-1, -1), 0.6, HexColor(HAIR)),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (0, 0), 9),
        ("BOTTOMPADDING", (0, 1), (0, 1), 10),
        ("ALIGN", (0, 1), (0, 1), "CENTER"),
    ]))
    return inner


def aipanel(text, foot):
    """AI early-warning panel: petrol left border, label, body, muted footer.

    The caller decides the footer content (confidence / coverage / etc.).
    """
    inner = Table(
        [[Paragraph("AI ERKEN UYARI", s("al", LATO_BOLD, 7.5, PETROL))],
         [Paragraph(_esc(text), s("at", LATO_REGULAR, 9, INK, leading=13))],
         [Paragraph(_esc(foot), s("af", LATO_MEDIUM, 7.5, MUT))]],
        colWidths=[16.0 * cm],
    )
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), "#EAF1EF"),
        ("LINEBEFORE", (0, 0), (0, -1), 3, HexColor(PETROL)),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (0, 0), 9),
        ("TOPPADDING", (0, 1), (0, 1), 3),
        ("TOPPADDING", (0, 2), (0, 2), 5),
        ("BOTTOMPADDING", (0, -1), (0, -1), 9),
    ]))
    return inner


def dtable(header, rows, colw, aligns=None, totals=None):
    """Data table with NAVY header, zebra rows and optional totals row.

    A cell value that is a ``(text, "r|a|g")`` tuple renders as a pill().
    ``aligns``: 0=left, 1=center, 2=right (default [0]+[2]*rest).
    ``totals`` (optional) renders a bold NAVY summary row with a top rule.
    """
    aligns = aligns or [0] + [2] * (len(header) - 1)
    body = [[Paragraph(_esc(h), s("hh", LATO_BOLD, 7, white, alignment=aligns[i]))
             for i, h in enumerate(header)]]
    for r in rows:
        cells = []
        for i, v in enumerate(r):
            if isinstance(v, tuple):
                cells.append(pill(v[0], v[1]))
            else:
                cells.append(Paragraph(_esc(v), s("c", LATO_REGULAR, 8, INK, alignment=aligns[i], leading=10.5)))
        body.append(cells)
    if totals:
        body.append([Paragraph(_esc(v), s("tt", LATO_BOLD, 8, NAVY, alignment=aligns[i]))
                     for i, v in enumerate(totals)])
    t = Table(body, colWidths=colw, repeatRows=1)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), HexColor(NAVY)),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.6, HexColor(HAIR)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2 if totals else -1), [CARD, "#FAFBF9"]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, HexColor(HAIR)),
    ]
    if totals:
        ts.append(("LINEABOVE", (0, -1), (-1, -1), 0.8, HexColor("#C9D0C8")))
        ts.append(("BACKGROUND", (0, -1), (-1, -1), "#EFF1EC"))
    t.setStyle(TableStyle(ts))
    return t
