"""CR-005-A: PDF Türkçe karakter düzeltmesi (DejaVu/Vera fontları) + 3 grafik.

The default Helvetica/Times fonts cannot render ş, ğ, ı, İ … so they appeared as
■ in the PDF. We register Unicode TTF fonts and embed three bar charts (margin,
budget usage, cash flow) into the management pack.
"""
import re

from app.constants import ROLE_DIRECTOR


def test_register_turkish_fonts_registers_unicode_family():
    from reportlab.pdfbase import pdfmetrics

    from app.services.reports import FONT_BOLD, FONT_NORMAL, FONT_OBLIQUE, register_turkish_fonts

    register_turkish_fonts()
    for name in (FONT_NORMAL, FONT_BOLD, FONT_OBLIQUE):
        font = pdfmetrics.getFont(name)
        # The registered face must cover the Turkish-specific code points.
        for ch in "şğıİŞĞ":
            assert ord(ch) in font.face.charToGlyph, f"{name} eksik glyph: {ch}"


def test_reports_source_has_no_legacy_font_names():
    """No Helvetica/Times/Courier font literals remain in the report code."""
    import app.services.reports as reports

    src = open(reports.__file__, encoding="utf-8").read()
    # Strip comments so the explanatory comment line doesn't trip the check.
    code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
    for legacy in ('"Helvetica', "'Helvetica", '"Times', "'Times", '"Courier', "'Courier"):
        assert legacy not in code, f"Eski font referansı kaldı: {legacy}"


def test_management_pack_data_has_chart_datasets(db, seed):
    from app.services.reports import build_management_pack_data

    data = build_management_pack_data(db, seed["a"]["company"], "2026-06")
    for key in ("margin_chart", "budget_chart", "cashflow_chart"):
        assert key in data
        assert isinstance(data[key], list)


def test_management_pack_pdf_embeds_unicode_font_and_renders(db, seed):
    """The real renderer (not stubbed) embeds the TTF and turns out a valid PDF."""
    from app.services.reports import build_management_pack_data, render_management_pack

    company = seed["a"]["company"]
    # Give the chart builders something to plot so charts are exercised.
    data = build_management_pack_data(db, company, "2026-06")
    assert data["company_name"] == company.name  # Türkçe şirket adı (Şirket A)

    pdf = render_management_pack(db, company, "2026-06")
    assert pdf.startswith(b"%PDF")
    # Embedded subset of the DejaVu-derived Bitstream Vera face → Türkçe glyphs.
    assert b"BitstreamVeraSans" in pdf or b"DejaVu" in pdf
    # An actual TrueType program is embedded (FontFile2), not a Latin-1 Type1 only.
    assert b"FontFile2" in pdf


def test_management_pack_endpoint_real_render_returns_pdf(client, seed):
    """End-to-end: the download endpoint returns a real (non-stub) PDF, no 500."""
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.get("/api/v1/reports/management-pack", params={"period": "2026-06"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
