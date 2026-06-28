"""CR-005-A: PDF Türkçe karakter desteği + grafikler.

The default Helvetica/Times fonts cannot render ş, ğ, ı, İ … so they appeared as
■ in the PDF. CR-005-A registered Unicode TTF fonts (DejaVu). CR-036 made **Lato**
the primary embedded face for the management pack (DejaVu stays registered as the
Türkçe fallback) and replaced the legacy reportlab.graphics charts with matplotlib
chart datasets (monthly_trend, commitment_chart, …). The intent is unchanged:
Türkçe + ₺ render without error and a real TrueType program is embedded.
"""
import pytest

from app.constants import ROLE_DIRECTOR


@pytest.fixture(autouse=True)
def _stub_ai(monkeypatch):
    """No network: stub the single AI call the data layer makes."""
    import app.services.ai as ai

    monkeypatch.setattr(ai, "management_summary", lambda ctx: "Yönetici özeti (test).")


def test_register_turkish_fonts_registers_unicode_family():
    from reportlab.pdfbase import pdfmetrics

    from app.services.reports import FONT_BOLD, FONT_NORMAL, FONT_OBLIQUE, register_turkish_fonts

    register_turkish_fonts()
    for name in (FONT_NORMAL, FONT_BOLD, FONT_OBLIQUE):
        font = pdfmetrics.getFont(name)
        # The registered face must cover the Turkish-specific code points.
        for ch in "şğıİŞĞ":
            assert ord(ch) in font.face.charToGlyph, f"{name} eksik glyph: {ch}"


def test_register_lato_fonts_covers_turkish_and_currency():
    """CR-036: the new primary face (Lato) covers Türkçe + the ₺ symbol."""
    from reportlab.pdfbase import pdfmetrics

    from app.services.report_theme import LATO_REGULAR, LATO_BOLD, register_lato_fonts

    register_lato_fonts()
    for name in (LATO_REGULAR, LATO_BOLD):
        font = pdfmetrics.getFont(name)
        for ch in "şğıİŞĞ₺":
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
    """CR-036 chart datasets (matplotlib-rendered): trend + commitment + FX split."""
    from app.services.reports import build_management_pack_data

    data = build_management_pack_data(db, seed["a"]["company"], "2026-06")
    for key in ("monthly_trend", "commitment_chart", "commitment_categories"):
        assert key in data
        assert isinstance(data[key], list)
    assert isinstance(data["fx_split"], dict)


def test_management_pack_pdf_embeds_unicode_font_and_renders(db, seed):
    """The real renderer (not stubbed) embeds the TTF and turns out a valid PDF."""
    from app.services.reports import build_management_pack_data, render_management_pack

    company = seed["a"]["company"]
    data = build_management_pack_data(db, company, "2026-06")
    assert data["company_name"] == company.name  # Türkçe şirket adı (Şirket A)

    pdf = render_management_pack(db, company, "2026-06")
    assert pdf.startswith(b"%PDF")
    # CR-036: Lato is the primary embedded face; DejaVu remains a valid fallback.
    assert b"Lato" in pdf or b"BitstreamVeraSans" in pdf or b"DejaVu" in pdf
    # An actual TrueType program is embedded (FontFile2), not a Latin-1 Type1 only.
    assert b"FontFile2" in pdf


def test_management_pack_endpoint_real_render_returns_pdf(client, seed):
    """End-to-end: the download endpoint returns a real (non-stub) PDF, no 500."""
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.get("/api/v1/reports/management-pack", params={"period": "2026-06"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
