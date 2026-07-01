"""CR-003-K: monthly management pack report.

CR-036 rebuilt this as the 11-section "Aylık Yönetim Raporu" (ReportLab + matplotlib
toolkit). The data layer (build_management_pack_data) now exposes the eleven
SECTION_TITLES and the new per-section keys; the old 7-section keys
(ai_actions / margin_movement / action_items) are gone.
"""
import pytest

from app.constants import ROLE_DIRECTOR, ROLE_SITE_MANAGER


@pytest.fixture(autouse=True)
def _stub_ai(monkeypatch):
    """No network: stub the single AI call the data layer makes."""
    import app.services.ai as ai

    monkeypatch.setattr(ai, "management_summary", lambda ctx: "Yönetici özeti (test).")


def test_management_pack_data_has_11_sections(db, seed):
    from app.services.reports import SECTION_TITLES, build_management_pack_data

    company = seed["a"]["company"]
    data = build_management_pack_data(db, company, "Haziran 2026")

    # CR-036: eleven sections, in order, covering the rebuilt management pack.
    assert data["section_titles"] == SECTION_TITLES
    assert len(SECTION_TITLES) == 11
    titles = " ".join(SECTION_TITLES)
    for expected in (
        "Yönetici Özeti",
        "Finansal Performans",
        "Taahhüt & Maliyet Maruziyeti",
        "Kur & Döviz",
        "Kritik Projeler",
        "Nakit & İşletme Sermayesi",
        "Tedarikçi & Taşeron",
        "Satış, m² & Getiri",
        "Veri Güvence & Anomali",
        "Risk & Aksiyon Planı",
    ):
        assert expected in titles
    assert data["company_name"] == company.name

    # New CR-036 keys are present...
    assert "ai_summary" in data
    for key in ("cover_kpis", "exec_kpis", "decisions", "early_warning",
                "commitment_categories", "ar_aging", "assurance", "risk_register"):
        assert key in data, key
    # ...and the removed 7-section keys are gone.
    for removed in ("ai_actions", "margin_movement", "action_items", "budget_summary"):
        assert removed not in data, removed


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
