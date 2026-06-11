"""CR-003-K: monthly management pack report (CR-004-A: ReportLab renderer)."""
from app.constants import ROLE_DIRECTOR, ROLE_SITE_MANAGER


def test_management_pack_data_has_7_sections(db, seed):
    from app.services.reports import SECTION_TITLES, build_management_pack_data

    company = seed["a"]["company"]
    data = build_management_pack_data(db, company, "Haziran 2026")

    # Seven sections, in order, covering the full management pack.
    assert data["section_titles"] == SECTION_TITLES
    assert len(SECTION_TITLES) == 7
    titles = " ".join(SECTION_TITLES)
    assert "Yönetici Özeti" in titles
    assert "Proje Finansal KPI" in titles
    assert "Marj Hareketi" in titles
    assert "Nakit Akışı ve Tahsilat" in titles
    assert "Bütçe Kategori Detayı" in titles
    assert "Alt Yüklenici ve Tedarikçi Riski" in titles
    assert "Eylem Listesi" in titles
    assert data["company_name"] == company.name
    assert "ai_summary" in data and "ai_actions" in data


def test_management_pack_endpoint(client, seed, monkeypatch):
    # Stub the ReportLab renderer so no rendering libs are needed in tests.
    import app.services.reports as reports

    monkeypatch.setattr(reports, "_management_pack_pdf", lambda data: b"%PDF-1.4 stub")
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.get("/api/v1/reports/management-pack", params={"period": "2026-06"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_management_pack_site_manager_forbidden(client, seed):
    # Site managers cannot export reports (InvoiceCreatorUser gate).
    client.login(seed["a"]["users"][ROLE_SITE_MANAGER])
    assert client.get("/api/v1/reports/management-pack").status_code == 403
