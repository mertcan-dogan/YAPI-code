"""CR-037 §6 — PDF design rollout to the project report + Proje Sonu Raporu.

Proves the spec §6 acceptance gates for the *project* report path (the Studio
chart gates live in ``test_cr037_studio_charts``):

* ``render_project_report`` produces a valid, non-empty toolkit PDF (Lato /
  FontFile2 embedded) for a HAKEDİŞ project — and the new build emits the
  ``sales_pnl`` block + per-category numeric mirrors that feed the chart;
* the same renderer for a SELL-SIDE (yap_sat) project → valid PDF, and
  ``sales_pnl.revenue_source`` correctly flips to ``sales`` (vs ``hakedis``);
* THE KEY REGRESSION: an OLD-shape frozen closeout snapshot (pre-CR-031 keys, no
  ``sales_pnl``, no ``*_num`` mirrors) still renders defensively — no KeyError —
  with and without ``closeout_ctx``; a near-empty / empty dict never raises;
* the closeout HTTP path (``/closeout/report.pdf``) exercises ``closeout_ctx``
  end-to-end on real frozen data → 200 application/pdf %PDF;
* ``/health`` surfaces the new ``version`` field alongside the migration fields;
* read-only: rendering the project report writes zero business rows.

Runs on the SQLite ``client`` / ``seed`` / ``db`` fixtures (conftest). No network.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.constants import ROLE_DIRECTOR
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.unit_sale import UnitSale

D = Decimal


# --------------------------------------------------------------------------- #
# Seed helpers
# --------------------------------------------------------------------------- #
def _cost(db, p, amount, uid, *, cat="material_steel", d=date(2026, 1, 10)):
    amt = D(str(amount))
    vat = (amt * D("20") / D("100")).quantize(D("0.01"))
    db.add(CostEntry(
        project_id=p.id, company_id=p.company_id, entry_date=d, cost_category=cat,
        amount_try=amt, vat_rate=D("20"), vat_amount_try=vat, total_with_vat_try=amt + vat,
        payment_status="unpaid", entry_type="actual", created_by=uid,
    ))
    db.commit()


def _seed_hakedis(db, seed, label="a"):
    """A few costs across categories so categories[] (and its chart) is non-trivial."""
    p = seed[label]["project"]
    uid = seed[label]["users"][ROLE_DIRECTOR].id
    _cost(db, p, "300000", uid, cat="material_steel")
    _cost(db, p, "150000", uid, cat="material_concrete")
    _cost(db, p, "50000", uid, cat="other")
    return p, seed[label]["company"]


def _seed_sell_side(db, seed, label="a"):
    """Turn the project into a yap-sat development with real unit sales so the P&L
    is genuinely sell-side (revenue_source == 'sales')."""
    p = seed[label]["project"]
    uid = seed[label]["users"][ROLE_DIRECTOR].id
    p.revenue_model = "yap_sat"
    p.construction_net_m2 = D("200")
    p.unit_count = 4
    db.add(p)
    db.add(CostEntry(
        project_id=p.id, company_id=p.company_id, entry_date=date(2026, 1, 10),
        cost_category="other", amount_try=D("1000000"), vat_rate=D("0"),
        vat_amount_try=D("0"), total_with_vat_try=D("1000000"),
        payment_status="unpaid", entry_type="actual", created_by=uid,
    ))
    for label_u, price, ut in (("A-1", "1500000", "2_plus_1"), ("A-2", "1500000", "3_plus_1")):
        db.add(UnitSale(
            project_id=p.id, company_id=p.company_id, created_by=uid,
            unit_label=label_u, unit_type=ut, net_m2=D("100"),
            sale_price_try=D(price), sale_date=date(2026, 1, 10), owner_side="yuklenici",
        ))
    db.commit()
    db.expire_all()
    return p, seed[label]["company"]


def _count(db, model) -> int:
    db.expire_all()
    return db.execute(select(func.count()).select_from(model)).scalar_one()


# --------------------------------------------------------------------------- #
# 1) Project report — hakediş → toolkit PDF (Lato/FontFile2), new data keys
# --------------------------------------------------------------------------- #
def test_render_project_report_hakedis_is_toolkit_pdf(db, seed):
    from app.services.reports import build_project_report_data, render_project_report

    p, company = _seed_hakedis(db, seed)

    data = build_project_report_data(db, p, company)
    # The new build emits the sales_pnl block (revenue-model-aware) ...
    assert data["sales_pnl"]["revenue_source"] == "hakedis"
    # ... and the additive per-category numeric mirrors that feed the budget chart.
    assert data["categories"], "expected at least one cost category"
    for c in data["categories"]:
        assert {"revised_num", "invoiced_num", "forecast_num"} <= set(c)
        assert all(isinstance(c[k], float) for k in ("revised_num", "invoiced_num", "forecast_num"))

    pdf = render_project_report(db, p, company)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 1000
    # The new toolkit embeds the Lato TrueType program (design system, not the old look).
    assert b"FontFile2" in pdf
    assert b"Lato" in pdf


# --------------------------------------------------------------------------- #
# 2) Project report — sell-side → PDF + revenue_source flips to 'sales'
# --------------------------------------------------------------------------- #
def test_render_project_report_sell_side_revenue_source(db, seed):
    from app.services.reports import build_project_report_data, render_project_report

    p, company = _seed_sell_side(db, seed)

    data = build_project_report_data(db, p, company)
    assert "sales_pnl" in data
    assert data["sales_pnl"]["revenue_source"] == "sales"  # sell-side, not hakediş

    pdf = render_project_report(db, p, company)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 1000


# --------------------------------------------------------------------------- #
# 3) REGRESSION — an OLD-shape frozen snapshot still renders (no KeyError)
# --------------------------------------------------------------------------- #
# A minimal dict built with ONLY the pre-CR-031 keys: NO sales_pnl, NO *_num on
# categories. The restyled (CR-037) renderer must guard every section and omit the
# ones a stale snapshot lacks, never KeyError. (Old Kesin-Hesap closeouts.)
OLD_MIN_DICT = {
    "company_name": "Eski Şirket",
    "logo_url": None,
    "report_title": "Proje Durum Raporu",
    "report_date": "26 Haziran 2026",
    "generated_at": "26 Haziran 2026 10:00",
    "project_name": "Eski Proje",
    "client_name": "Eski İşveren",
    "contract_value": "1.000.000 ₺",
    "total_actual": "750.000 ₺",
    "forecast_final": "900.000 ₺",
    "margin_pct": "%10,0",
    "rag_status": "amber",
    "categories": [
        {"label": "Çelik", "revised": "400.000 ₺", "invoiced": "300.000 ₺",
         "forecast": "420.000 ₺", "variance": "-20.000 ₺", "status": "amber",
         "status_label": "Dikkat"},
    ],
    "total_invoiced": "800.000 ₺",
    "total_collected": "600.000 ₺",
    "total_outstanding": "200.000 ₺",
    "total_retention": "40.000 ₺",
    "net_cash": "560.000 ₺",
}


def test_old_shape_snapshot_renders_without_keyerror():
    from app.services.reports import _project_report_pdf

    pdf = _project_report_pdf(dict(OLD_MIN_DICT))
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 500


def test_old_shape_snapshot_renders_with_closeout_ctx():
    from app.services.reports import _project_report_pdf

    ctx = {"stage_label": "Kesin Hesap",
           "frozen_at_label": "26 Haziran 2026 10:00", "frozen": True}
    pdf = _project_report_pdf(dict(OLD_MIN_DICT), closeout_ctx=ctx)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 500


def test_near_empty_dict_never_raises():
    from app.services.reports import _project_report_pdf

    for d in ({}, {"company_name": "Sadece İsim"}):
        pdf = _project_report_pdf(dict(d))
        assert pdf[:4] == b"%PDF"


# --------------------------------------------------------------------------- #
# 4) Closeout HTTP path — closeout_ctx end-to-end on real frozen data
# --------------------------------------------------------------------------- #
def test_closeout_report_pdf_renders_frozen_with_context(client, seed, db):
    # Seed real costs so the frozen snapshot carries categories + a budget chart.
    _seed_hakedis(db, seed)
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])

    assert client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul",
                       json={"date": "2026-06-25"}).status_code == 200
    assert client.post(f"/api/v1/projects/{pid}/closeout/kesin-hesap",
                       json={"date": "2026-07-01"}).status_code == 200

    r = client.get(f"/api/v1/projects/{pid}/closeout/report.pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"
    assert len(r.content) > 1000


# --------------------------------------------------------------------------- #
# 5) /health — new version field alongside the migration fields
# --------------------------------------------------------------------------- #
def test_health_exposes_version_and_migration_fields(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("version"), str) and body["version"]
    # The pre-existing migration fields are kept (resilient liveness contract).
    assert "db_revision" in body
    assert "expected_revision" in body


# --------------------------------------------------------------------------- #
# 6) Read-only — rendering the project report writes zero business rows
# --------------------------------------------------------------------------- #
def test_render_project_report_is_read_only(db, seed):
    from app.services.reports import render_project_report

    p, company = _seed_hakedis(db, seed)
    cost_before = _count(db, CostEntry)
    inv_before = _count(db, ClientInvoice)
    sale_before = _count(db, UnitSale)

    pdf = render_project_report(db, p, company)
    assert pdf[:4] == b"%PDF"

    assert _count(db, CostEntry) == cost_before
    assert _count(db, ClientInvoice) == inv_before
    assert _count(db, UnitSale) == sale_before
