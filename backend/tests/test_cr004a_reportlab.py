"""CR-004-A: ReportLab report generation (data builders + renderer indirection)."""
from app.constants import ROLE_DIRECTOR


def test_project_report_data_has_expected_keys(db, seed):
    from app.services.reports import build_project_report_data

    a = seed["a"]
    d = build_project_report_data(db, a["project"], a["company"])
    for key in (
        "company_name", "report_title", "report_date", "generated_at",
        "project_name", "client_name", "contract_value", "total_actual",
        "forecast_final", "margin_pct", "categories", "total_invoiced",
        "total_collected", "total_outstanding", "net_cash",
    ):
        assert key in d
    assert d["report_title"] == "Proje Durum Raporu"
    assert d["company_name"] == a["company"].name


def test_project_report_renderer_is_stubbable(client, seed, monkeypatch):
    """The PDF renderer is isolated so it can be stubbed without ReportLab."""
    import app.services.reports as reports

    monkeypatch.setattr(reports, "_project_report_pdf", lambda d: b"%PDF-1.4 stub")
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.get(f"/api/v1/reports/project/{seed['a']['project'].id}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_management_pack_disclaimer_constant():
    from app.services.reports import AI_DISCLAIMER

    assert "yapay zeka" in AI_DISCLAIMER.lower()
    assert "doğrulayın" in AI_DISCLAIMER
