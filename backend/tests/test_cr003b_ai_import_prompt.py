"""CR-003-B: AI import prompt classification instruction."""
from app.services.ai import build_import_prompt


def test_prompt_distinguishes_supplier_vs_client_invoice():
    p = build_import_prompt("örnek veri")
    # The supplier-vs-client invoice instruction must be present.
    assert "Tedarikçi faturası" in p
    assert "maliyet_girisleri" in p
    assert "Fatura numarası olması bir kaydı otomatik olarak faturalar kategorisine sokmaz" in p


def test_prompt_includes_excel_content_and_schema():
    p = build_import_prompt("HÜCRE-A | HÜCRE-B")
    assert "HÜCRE-A | HÜCRE-B" in p
    assert "confidence" in p
    assert "tanimsiz" in p
