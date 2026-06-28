"""CR-036: Aylık Yönetim Raporu (rebuilt 11-section management pack).

Covers the spec §5 acceptance gates for the new report:

* render_management_pack returns a valid, multi-page PDF for a HAKEDİŞ company,
  a SELL-SIDE company (§9 Satış appears) and an EMPTY company (graceful omit);
* the new build_management_pack_data keys RECONCILE with the authoritative
  services (project_financials / sales / the cost ledger) — no invented numbers;
* AR-aging matches the dashboard helper EXACTLY (founder requirement);
* read-only: rendering writes zero business rows (proves collect_findings, not
  scan_company, is used);
* honesty: no fabricated Güven/Veri-kapsama/%confidence tokens, and the margin
  bridge is built from REAL category variances;
* the bundled Lato fonts register (6 weights) idempotently and embed in the PDF.

No network: the single AI call (ai.management_summary) is stubbed; conftest keeps
the live TCMB FX feed off. matplotlib runs on the headless Agg backend.
"""
import re
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.api.projects import _ar_aging as dashboard_ar_aging
from app.calculations.money import D, money
from app.constants import COST_CATEGORIES, ROLE_DIRECTOR
from app.models.ai_alert import AIAlert
from app.models.client_invoice import ClientInvoice
from app.models.company import Company
from app.models.cost_entry import CostEntry
from app.models.subcontractor import Subcontractor
from app.models.unit_sale import UnitSale
from app.models.vendor import Vendor
from app.services import reports
from app.services.financials import project_financials
from app.utils.format import format_currency_tr

PERIOD = "2026-06"
TODAY = date.today()


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _stub_ai(monkeypatch):
    """Stub the ONLY AI call build_management_pack_data makes (no network)."""
    import app.services.ai as ai

    monkeypatch.setattr(
        ai, "management_summary",
        lambda ctx: "Portföy genel olarak sağlıklı görünmektedir. "
                    "Üç başarı, üç risk ve üç öncelikli eylem belirlenmiştir.",
    )


def _ctx(seed, label="a"):
    s = seed[label]
    return {"company": s["company"], "project": s["project"],
            "user": s["users"][ROLE_DIRECTOR]}


def _m(x):
    return money(D(x))


def _cost(ctx, *, amount, category="material_steel", entry_type="actual",
          commitment_id=None, vendor_id=None, amount_usd=None, fx_rate_usd=None,
          supplier_name=None, description=None, entry_date=date(2025, 3, 1),
          vat_rate="20", payment_status="unpaid", amount_paid="0",
          payment_due_date=None):
    amt = D(amount)
    vr = D(vat_rate)
    vat = _m(amt * vr / 100)
    return CostEntry(
        project_id=ctx["project"].id, company_id=ctx["company"].id,
        created_by=ctx["user"].id, entry_date=entry_date, cost_category=category,
        amount_try=amt, vat_rate=vr, vat_amount_try=vat,
        total_with_vat_try=_m(amt + vat), entry_type=entry_type,
        commitment_id=commitment_id, vendor_id=vendor_id,
        amount_usd=(D(amount_usd) if amount_usd is not None else None),
        fx_rate_usd=(D(fx_rate_usd) if fx_rate_usd is not None else None),
        supplier_name=supplier_name, description=description,
        payment_status=payment_status, amount_paid_try=D(amount_paid),
        payment_due_date=payment_due_date,
    )


def _invoice(ctx, *, number, amount, invoice_date, due_date, received="0", vat_rate="0"):
    amt = D(amount)
    vr = D(vat_rate)
    vat = _m(amt * vr / 100)
    total = _m(amt + vat)
    return ClientInvoice(
        project_id=ctx["project"].id, company_id=ctx["company"].id,
        created_by=ctx["user"].id, invoice_number=number, invoice_date=invoice_date,
        amount_try=amt, vat_rate=vr, vat_amount_try=vat, total_with_vat_try=total,
        net_due_try=total, retention_amount_try=D("0"),
        amount_received_try=D(received), due_date=due_date,
        payment_status=("paid" if D(received) >= total else "unpaid"),
    )


def _unit_sale(ctx, *, label, net_m2, price, sale_date=date(2025, 3, 1),
               price_usd=None, unit_type="2_plus_1"):
    return UnitSale(
        project_id=ctx["project"].id, company_id=ctx["company"].id,
        created_by=ctx["user"].id, unit_label=label, unit_type=unit_type,
        net_m2=D(net_m2), sale_price_try=D(price), sale_date=sale_date,
        sale_price_usd=(D(price_usd) if price_usd is not None else None),
        owner_side="yuklenici",
    )


def seed_hakedis(db, ctx):
    """A realistic hakediş portfolio: vendor-linked costs (one FX), a committed
    cost partly relieved, an overdue payable, AR invoices spanning every aging
    bucket, and an active subcontractor. Returns the created vendor ids by key."""
    v_steel = Vendor(company_id=ctx["company"].id, canonical_name="Çelik Demir A.Ş.")
    v_concrete = Vendor(company_id=ctx["company"].id, canonical_name="Beton Hazır Ltd.")
    v_haul = Vendor(company_id=ctx["company"].id, canonical_name="Nakliye Lojistik")
    db.add_all([v_steel, v_concrete, v_haul])
    db.flush()

    # Actual costs across categories (no budgets ⇒ every category has a real,
    # positive variance the margin bridge can rank). One carries a USD snapshot.
    db.add_all([
        _cost(ctx, amount="300000", category="material_steel", vendor_id=v_steel.id,
              amount_usd="10000", fx_rate_usd="30", supplier_name="Çelik Demir A.Ş."),
        _cost(ctx, amount="100000", category="material_steel", vendor_id=v_steel.id,
              supplier_name="Çelik Demir A.Ş."),
        _cost(ctx, amount="200000", category="material_concrete", vendor_id=v_concrete.id,
              supplier_name="Beton Hazır Ltd."),
        _cost(ctx, amount="50000", category="other", vendor_id=v_haul.id,
              supplier_name="Nakliye Lojistik"),
    ])

    # A committed cost (open taahhüt) partly relieved by a linked actual.
    commit = _cost(ctx, amount="150000", category="material_steel", entry_type="committed")
    db.add(commit)
    db.flush()
    db.add(_cost(ctx, amount="60000", category="material_steel", entry_type="actual",
                 commitment_id=commit.id, vendor_id=v_steel.id, supplier_name="Çelik Demir A.Ş."))

    # An overdue payable (drives §2 decisions / §11 risk).
    db.add(_cost(ctx, amount="80000", category="material_other", vendor_id=v_haul.id,
                 supplier_name="Nakliye Lojistik", payment_status="unpaid",
                 payment_due_date=TODAY - timedelta(days=40)))

    # AR invoices — one per aging bucket (all dates set ⇒ dashboard parity holds).
    db.add_all([
        _invoice(ctx, number="HAK-1", amount="500000",
                 invoice_date=TODAY - timedelta(days=90), due_date=TODAY + timedelta(days=10)),
        _invoice(ctx, number="HAK-2", amount="300000",
                 invoice_date=TODAY - timedelta(days=60), due_date=TODAY - timedelta(days=15)),
        _invoice(ctx, number="HAK-3", amount="200000", received="50000",
                 invoice_date=TODAY - timedelta(days=100), due_date=TODAY - timedelta(days=45)),
        _invoice(ctx, number="HAK-4", amount="400000",
                 invoice_date=TODAY - timedelta(days=120), due_date=TODAY - timedelta(days=90)),
    ])

    db.add(Subcontractor(
        project_id=ctx["project"].id, company_id=ctx["company"].id,
        name="Demir Alt Yüklenici", scope_of_work="Kaba inşaat",
        contract_value_try=D("500000")))
    db.commit()
    db.expire_all()
    return {"steel": v_steel.id, "concrete": v_concrete.id, "haul": v_haul.id}


def seed_sell_side(db, ctx):
    """Turn the project into a sell-side (yap-sat) development with real unit
    sales + a construction cost so unit_sales_pnl / m² economics have data."""
    p = ctx["project"]
    p.revenue_model = "yap_sat"
    p.construction_net_m2 = D("200")
    p.unit_count = 4
    db.add(p)
    db.add(_cost(ctx, amount="1000000", category="other", supplier_name="Genel Müteahhit"))
    db.add_all([
        _unit_sale(ctx, label="A-1", net_m2="100", price="1500000", unit_type="2_plus_1"),
        _unit_sale(ctx, label="A-2", net_m2="100", price="1500000", unit_type="3_plus_1"),
    ])
    db.commit()
    db.expire_all()


def _page_count(pdf: bytes) -> int:
    """Count PDF page objects (mirrors test_cr006a's byte-count approach)."""
    return pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ")


# --------------------------------------------------------------------------- #
# DELIVERABLE 1 — render_management_pack PDF smoke + structural gates
# --------------------------------------------------------------------------- #
def test_hakedis_company_renders_multipage_pdf(db, seed):
    ctx = _ctx(seed, "a")
    seed_hakedis(db, ctx)

    pdf = reports.render_management_pack(db, ctx["company"], PERIOD)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 5000
    # The old pack was 7 pages; the rebuilt 11-section pack is larger.
    assert _page_count(pdf) > 7, _page_count(pdf)


def test_sell_side_company_renders_with_satis_section(db, seed):
    ctx = _ctx(seed, "a")
    seed_sell_side(db, ctx)

    data = reports.build_management_pack_data(db, ctx["company"], PERIOD)
    # §9 toggles on for a sell-side company and carries real rows.
    assert data["has_sell_side"] is True
    assert data["sell_side"] is not None
    assert data["sell_side"]["unit_type_pnl"], "expected per-unit-type P&L rows"
    assert data["sell_side"]["m2_economics"], "expected per-m² economics rows"

    pdf = reports.render_management_pack(db, ctx["company"], PERIOD)
    assert pdf.startswith(b"%PDF")
    assert _page_count(pdf) > 7


def test_hakedis_only_company_omits_satis_section(db, seed):
    ctx = _ctx(seed, "a")
    seed_hakedis(db, ctx)  # default revenue_model == hakedis, no unit sales

    data = reports.build_management_pack_data(db, ctx["company"], PERIOD)
    assert data["has_sell_side"] is False
    assert data["sell_side"] is None


def test_empty_company_renders_without_crash(db):
    empty = Company(name="Boş Şirket", slug="bos-sirket-cr036",
                    require_budget_approval=False, require_subcontractor_approval=False,
                    require_deletion_approval=False, require_variation_approval=False)
    db.add(empty)
    db.commit()

    data = reports.build_management_pack_data(db, empty, PERIOD)
    assert data["has_sell_side"] is False
    assert data["has_fx"] is False
    assert data["rows"] == []
    assert data["section_titles"] == list(reports.SECTION_TITLES)

    pdf = reports.render_management_pack(db, empty, PERIOD)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2000


# --------------------------------------------------------------------------- #
# DELIVERABLE 1 — read-only invariant (CR-036 acceptance gate)
# --------------------------------------------------------------------------- #
def _business_counts(db):
    return {
        m.__name__: db.execute(select(func.count()).select_from(m)).scalar()
        for m in (AIAlert, CostEntry, ClientInvoice, UnitSale, Vendor, Subcontractor)
    }


def test_render_is_read_only_no_mutation(db, seed):
    ctx = _ctx(seed, "a")
    seed_hakedis(db, ctx)
    # Two identical vendor-linked actuals ⇒ a guaranteed duplicate finding, so the
    # gate is meaningful: a scan_company() slip would CREATE AIAlert rows.
    v = db.execute(select(Vendor).where(Vendor.canonical_name == "Çelik Demir A.Ş.")).scalars().first()
    db.add_all([
        _cost(ctx, amount="999000", category="material_steel", vendor_id=v.id,
              supplier_name="Çelik Demir A.Ş.", entry_date=date(2025, 5, 1)),
        _cost(ctx, amount="999000", category="material_steel", vendor_id=v.id,
              supplier_name="Çelik Demir A.Ş.", entry_date=date(2025, 5, 1)),
    ])
    db.commit()
    db.expire_all()

    before = _business_counts(db)
    assert before["AIAlert"] == 0

    data = reports.build_management_pack_data(db, ctx["company"], PERIOD)
    # Findings DO exist (so an accidental write would be observable)...
    assert data["assurance"]["total_found"] >= 1
    assert data["assurance"]["high_count"] >= 1

    reports.render_management_pack(db, ctx["company"], PERIOD)
    db.expire_all()
    after = _business_counts(db)

    assert after == before, f"render mutated rows: {before} -> {after}"
    assert after["AIAlert"] == 0  # collect_findings, NOT scan_company


# --------------------------------------------------------------------------- #
# DELIVERABLE 1 — fonts
# --------------------------------------------------------------------------- #
def test_register_lato_fonts_all_weights_and_idempotent():
    from reportlab.pdfbase import pdfmetrics

    from app.services.report_theme import (
        register_lato_fonts, LATO_LIGHT, LATO_REGULAR, LATO_MEDIUM,
        LATO_SEMIBOLD, LATO_BOLD, LATO_BLACK,
    )

    register_lato_fonts()
    register_lato_fonts()  # idempotent — must not raise

    for name in (LATO_LIGHT, LATO_REGULAR, LATO_MEDIUM, LATO_SEMIBOLD, LATO_BOLD, LATO_BLACK):
        assert pdfmetrics.getFont(name).fontName == name


def test_pdf_embeds_lato_and_renders_turkish(db, seed):
    ctx = _ctx(seed, "a")
    seed_hakedis(db, ctx)
    pdf = reports.render_management_pack(db, ctx["company"], PERIOD)
    assert pdf.startswith(b"%PDF")
    # Lato is the primary embedded face (subset names look like 'ABCDEF+Lato').
    assert b"Lato" in pdf
    assert b"FontFile2" in pdf  # an actual TrueType program is embedded


# --------------------------------------------------------------------------- #
# DELIVERABLE 2 — reconciliation (no invented numbers)
# --------------------------------------------------------------------------- #
def test_commitment_categories_reconcile_with_project_financials(db, seed):
    ctx = _ctx(seed, "a")
    seed_hakedis(db, ctx)
    company = ctx["company"]

    projects = reports._active_projects(db, company)
    ref_open = sum((D(project_financials(db, p)["total_open_committed_try"]) for p in projects), D(0))
    ref_exposure = sum((D(project_financials(db, p)["total_committed_exposure_try"]) for p in projects), D(0))

    data = reports.build_management_pack_data(db, company, PERIOD)
    cats = data["commitment_categories"]
    got_open = sum((D(c["open_committed"]) for c in cats), D(0))
    got_exposure = sum((D(c["invoiced"]) + D(c["open_committed"]) for c in cats), D(0))

    assert got_open == ref_open
    assert got_exposure == ref_exposure
    assert ref_open > 0  # the committed cost left 90k open — gate is non-trivial

    # The §4 exposure KPI is the same number, formatted.
    assert data["commitment_kpis"][2][1] == format_currency_tr(ref_exposure)


def test_fx_usd_reconciles_with_cost_ledger(db, seed):
    ctx = _ctx(seed, "a")
    seed_hakedis(db, ctx)
    company = ctx["company"]

    ref_usd = db.execute(
        select(func.coalesce(func.sum(CostEntry.amount_usd), 0)).where(
            CostEntry.company_id == company.id,
            CostEntry.is_deleted.is_(False),
            CostEntry.pending_approval.is_(False),
            CostEntry.entry_type != "forecast",
        )
    ).scalar()

    agg = reports._fx_cost_aggregates(db, company)
    assert agg["usd"] == D(ref_usd)
    assert D(ref_usd) > 0

    data = reports.build_management_pack_data(db, company, PERIOD)
    assert data["has_fx"] is True


def test_has_fx_false_when_no_usd(db, seed):
    ctx = _ctx(seed, "b")  # company B: only a plain TRY cost, no USD snapshot
    db.add(_cost(ctx, amount="100000", category="material_steel"))
    db.commit()

    data = reports.build_management_pack_data(db, ctx["company"], PERIOD)
    assert data["has_fx"] is False


def test_vendor_spend_reconciles_with_grouped_query(db, seed):
    ctx = _ctx(seed, "a")
    seed_hakedis(db, ctx)
    company = ctx["company"]

    grouped = db.execute(
        select(CostEntry.vendor_id, func.coalesce(func.sum(CostEntry.total_with_vat_try), 0))
        .where(
            CostEntry.company_id == company.id,
            CostEntry.is_deleted.is_(False),
            CostEntry.pending_approval.is_(False),
            CostEntry.entry_type != "forecast",
            CostEntry.vendor_id.is_not(None),
        )
        .group_by(CostEntry.vendor_id)
    ).all()
    names = {v.id: v.canonical_name for v in db.execute(
        select(Vendor).where(Vendor.company_id == company.id)).scalars().all()}
    expected = sorted(
        [(names[vid], D(amt)) for vid, amt in grouped],
        key=lambda t: t[1], reverse=True)

    data = reports.build_management_pack_data(db, company, PERIOD)
    got = [(v["name"], D(v["amount_d"])) for v in data["vendor_spend"]]

    assert got == expected[:8]
    assert len(got) >= 2  # several vendors → a real ranking


def test_ar_aging_matches_dashboard_helper_exactly(db, seed):
    """FOUNDER REQUIREMENT: the report's AR aging == app/api/projects.py _ar_aging."""
    ctx = _ctx(seed, "a")
    seed_hakedis(db, ctx)
    company = ctx["company"]

    active_ids = [p.id for p in reports._active_projects(db, company)]
    expected = dashboard_ar_aging(db, active_ids, TODAY)

    data = reports.build_management_pack_data(db, company, PERIOD)
    assert data["ar_aging"] == expected
    # And the seed actually populated multiple buckets (gate is non-trivial).
    assert D(expected["total_outstanding_try"]) > 0
    assert D(expected["d60_plus_try"]) > 0
    assert expected["dso_days"] is not None


# --------------------------------------------------------------------------- #
# DELIVERABLE 2 — honesty (FOUNDER REQUIREMENTS)
# --------------------------------------------------------------------------- #
def test_early_warning_footer_has_no_fabricated_confidence(db, seed):
    ctx = _ctx(seed, "a")
    seed_hakedis(db, ctx)

    data = reports.build_management_pack_data(db, ctx["company"], PERIOD)
    footer = data["early_warning"]["footer"]

    assert "Güven" not in footer
    assert "Veri kapsama" not in footer
    # No fabricated "%85"-style confidence/coverage token.
    assert re.search(r"%\s*\d", footer) is None
    # Only the honest tokens survive.
    assert "İnsan onayı gerekir" in footer


def test_margin_bridge_rows_are_real_cost_categories(db, seed):
    ctx = _ctx(seed, "a")
    seed_hakedis(db, ctx)

    data = reports.build_management_pack_data(db, ctx["company"], PERIOD)
    bridge = data["margin_bridge"]
    rows = bridge["rows"]
    assert rows, "expected margin-bridge rows derived from real variances"

    valid_labels = set(COST_CATEGORIES.values())
    for r in rows:
        # Each bridge row is a REAL seeded cost category, not a narrative string.
        assert r["kalem"] in valid_labels, r["kalem"]
        assert "Hacim" not in r["kalem"]
        assert "karışım" not in r["kalem"]
    # The seeded categories that overran appear in the bridge.
    labels = {r["kalem"] for r in rows}
    assert COST_CATEGORIES["material_steel"] in labels
    # Opening/closing are %-strings derived from contract vs budget/forecast.
    assert bridge["opening_pct"] and bridge["closing_pct"]


# --------------------------------------------------------------------------- #
# Security regression — user strings escaped before ReportLab Paragraph (H1).
# A '&' or '<' in a vendor / supplier / project / subcontractor name must NOT
# crash doc.build() (DoS) nor inject markup / links into the confidential PDF.
# --------------------------------------------------------------------------- #
def test_render_escapes_markup_in_user_strings(db, seed):
    ctx = _ctx(seed, "a")
    seed_hakedis(db, ctx)
    # Names with ReportLab-hostile characters + a stored link/markup payload that
    # flow into §6 (project), §8 (vendor + subcontractor) and §2/§11 (supplier).
    ctx["project"].name = "İnşaat & Yapı <Faz 2>"
    db.add(ctx["project"])
    evil_vendor = Vendor(
        company_id=ctx["company"].id,
        canonical_name='Acme <Ltd> & "Co" <a href="https://evil.example">Onayla</a>')
    db.add(evil_vendor)
    db.flush()
    db.add(_cost(ctx, amount="123456", category="material_steel", vendor_id=evil_vendor.id,
                 supplier_name="Tedarikçi & <b>Ortak</b>", payment_status="unpaid",
                 payment_due_date=TODAY - timedelta(days=33)))
    db.add(Subcontractor(
        project_id=ctx["project"].id, company_id=ctx["company"].id,
        name="Taşeron <X> & Co", scope_of_work="Mekanik & <i>Elektrik</i>",
        contract_value_try=D("400000")))
    db.commit()
    db.expire_all()

    # Before the escape fix the '&'/'<' crashed Paragraph during doc.build(); now it
    # builds a valid, non-trivial PDF with the names rendered as literal text.
    pdf = reports.render_management_pack(db, ctx["company"], PERIOD)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 5000


def test_esc_helper_escapes_markup_chars():
    from app.services.report_theme import _esc

    assert _esc('a & b <c> "d"') == 'a &amp; b &lt;c&gt; "d"'
    assert _esc('<a href="https://evil">x</a>') == '&lt;a href="https://evil"&gt;x&lt;/a&gt;'
    assert _esc(1234) == "1234"   # numbers stringify harmlessly
    assert _esc(None) == "None"
