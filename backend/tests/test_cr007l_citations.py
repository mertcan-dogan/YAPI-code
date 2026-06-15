"""CR-007 citation-chip polish: Turkish amounts, distinguishable labels, and
source-based type detection (not invoice_number presence)."""
from app.services import agent as agent_service


def _cite(records: list) -> list:
    citations: list = []
    agent_service._add_citations({"records": records}, citations, set())
    return citations


# --------------------------------------------------------------------------- #
# Turkish amount formatting
# --------------------------------------------------------------------------- #
def test_amount_formatted_turkish_whole_try():
    c = _cite([{
        "id": "1", "supplier_name": "Bozkurt Beton", "total_with_vat_try": "2778000.00",
        "entry_date": "2026-01-15", "cost_category": "material_concrete",
        "deep_link": "/projects/p/dashboard?highlight=1",
    }])[0]
    assert "2.778.000 ₺" in c["label"]
    assert "2778000" not in c["label"]  # no raw unformatted number


def test_client_invoice_label_has_invoice_number_and_amount():
    c = _cite([{
        "id": "9", "invoice_number": "HAK-2026-004", "total_with_vat_try": "11400000.00",
        "deep_link": "/projects/p/invoices?highlight=9",
    }])[0]
    assert c["type"] == "client_invoice"
    assert c["label"] == "HAK-2026-004 — 11.400.000 ₺"


# --------------------------------------------------------------------------- #
# Type detection by source, not by invoice_number presence
# --------------------------------------------------------------------------- #
def test_cost_entry_with_invoice_number_is_not_mislabeled():
    """A cost entry that carries an invoice_number must stay type 'cost_entry'
    because its deep_link points at the cost surface (dashboard)."""
    c = _cite([{
        "id": "5", "supplier_name": "Bozkurt Beton", "invoice_number": "FT-123",
        "amount_try": "1000.00", "entry_date": "2026-02-01",
        "deep_link": "/projects/p/dashboard?highlight=5",
    }])[0]
    assert c["type"] == "cost_entry"  # not "client_invoice"


def test_overdue_receivable_typed_client_invoice():
    c = _cite([{
        "id": "7", "type": "receivable", "invoice_number": "HAK-OD",
        "outstanding_try": "20000.00", "deep_link": "/projects/p/invoices?highlight=7",
    }])[0]
    assert c["type"] == "client_invoice"


# --------------------------------------------------------------------------- #
# Distinguishable chips for the same supplier
# --------------------------------------------------------------------------- #
def test_same_supplier_chips_are_distinguishable():
    cs = _cite([
        {"id": "a", "supplier_name": "Bozkurt Beton", "amount_try": "1000.00",
         "entry_date": "2026-01-15", "cost_category": "material_concrete",
         "deep_link": "/projects/p/dashboard?highlight=a"},
        {"id": "b", "supplier_name": "Bozkurt Beton", "amount_try": "2000.00",
         "entry_date": "2026-02-20", "cost_category": "material_concrete",
         "deep_link": "/projects/p/dashboard?highlight=b"},
    ])
    labels = [c["label"] for c in cs]
    assert labels[0] != labels[1]                 # not identical vendor names
    assert "15.01.2026" in labels[0]              # entry_date distinguisher
    assert "20.02.2026" in labels[1]
    assert "Bozkurt Beton" in labels[0]


def test_cost_entry_falls_back_to_category_when_no_date():
    c = _cite([{
        "id": "c", "supplier_name": "Bozkurt Beton", "amount_try": "500.00",
        "cost_category": "material_steel", "deep_link": "/projects/p/dashboard?highlight=c",
    }])[0]
    assert "Malzeme — Çelik/Demir" in c["label"]  # COST_CATEGORIES label


def test_no_amount_keeps_label_clean():
    c = _cite([{
        "id": "d", "supplier_name": "Bozkurt Beton",
        "entry_date": "2026-01-15", "deep_link": "/projects/p/dashboard?highlight=d",
    }])[0]
    assert c["label"].endswith("15.01.2026")  # no trailing " — " dangling
    assert "₺" not in c["label"]
