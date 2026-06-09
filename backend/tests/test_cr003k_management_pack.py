"""CR-003-K: monthly management pack report."""
from app.constants import ROLE_DIRECTOR, ROLE_SITE_MANAGER


def test_management_pack_html_has_7_sections(db, seed):
    from app.services.reports import build_management_pack_html

    company = seed["a"]["company"]
    html = build_management_pack_html(db, company, "Haziran 2026")
    assert "Yönetici Özeti" in html
    assert "Proje Finansal KPI" in html
    assert "Marj Hareketi" in html
    assert "Nakit Akışı ve Tahsilat" in html
    assert "Bütçe Kategori Detayı" in html
    assert "Alt Yüklenici ve Tedarikçi Riski" in html
    assert "Eylem Listesi" in html
    assert company.name in html


def test_management_pack_endpoint(client, seed, monkeypatch):
    # Stub WeasyPrint so no system libs are needed.
    import app.services.reports as reports

    monkeypatch.setattr(reports, "_html_to_pdf", lambda html: b"%PDF-1.4 stub")
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.get("/api/v1/reports/management-pack", params={"period": "2026-06"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_management_pack_site_manager_forbidden(client, seed):
    # Site managers cannot export reports (InvoiceCreatorUser gate).
    client.login(seed["a"]["users"][ROLE_SITE_MANAGER])
    assert client.get("/api/v1/reports/management-pack").status_code == 403
