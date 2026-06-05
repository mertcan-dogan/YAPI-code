"""Shared enums, category lists, and Turkish labels (Appendix A & B, Section 4.3)."""

# --- Roles (Section 3.2) ---
ROLE_DIRECTOR = "director"
ROLE_PROJECT_MANAGER = "project_manager"
ROLE_FINANCE = "finance"
ROLE_SITE_MANAGER = "site_manager"
ROLES = [ROLE_DIRECTOR, ROLE_PROJECT_MANAGER, ROLE_FINANCE, ROLE_SITE_MANAGER]

# --- Project types (Appendix A) ---
PROJECT_TYPES = {
    "road": "Yol İnşaatı",
    "railway": "Demiryolu",
    "marine": "Denizel / Kıyı",
    "wastewater": "Atıksu Arıtma",
    "building": "Bina İnşaatı",
    "tunnel": "Tünel",
    "bridge": "Köprü / Viyadük",
    "other": "Diğer",
}

PROJECT_STATUSES = ["active", "completed", "suspended", "cancelled"]

# --- Cost categories (Section 4.3 / Appendix B) ---
# Order is the canonical display order in the budget tree.
COST_CATEGORIES = {
    "labour_direct": "İşçilik — Direkt",
    "labour_sub": "İşçilik — Taşeron",
    "material_concrete": "Malzeme — Beton",
    "material_steel": "Malzeme — Çelik/Demir",
    "material_pipes": "Malzeme — Boru/Fitting",
    "material_aggregate": "Malzeme — Agrega/Kum",
    "material_other": "Malzeme — Diğer",
    "equipment_owned": "Ekipman — Şirkete Ait",
    "equipment_rented": "Ekipman — Kiralık",
    "subcontractor": "Alt Yüklenici",
    "permits_fees": "İzin ve Harçlar",
    "site_overhead": "Şantiye Genel Giderleri",
    "engineering_design": "Mühendislik ve Tasarım",
    "contingency": "Beklenmedik Giderler (Kontenjan)",
    "other": "Diğer",
}
COST_CATEGORY_KEYS = list(COST_CATEGORIES.keys())

# --- Entry / payment status enums ---
ENTRY_TYPES = ["actual", "committed", "forecast"]
COST_PAYMENT_STATUSES = ["unpaid", "paid", "overdue", "partial"]
INVOICE_PAYMENT_STATUSES = ["unpaid", "partial", "paid", "disputed"]
INVOICE_TYPES = ["hakedis", "advance", "variation", "final"]
SUBCONTRACTOR_STATUSES = ["active", "completed", "disputed", "terminated"]
OWNERSHIP_TYPES = ["owned", "rented"]
RATE_UNITS = ["day", "month"]

# --- AI alert enums (Section 2.3 ai_alerts) ---
ALERT_TYPES = [
    "margin_warning",
    "cashflow_gap",
    "overdue_payment",
    "budget_overrun",
    "subcontractor_anomaly",
]
ALERT_SEVERITIES = ["high", "medium", "low"]

# --- Audited tables (Section 8.2) ---
AUDITED_TABLES = {
    "projects",
    "cost_entries",
    "client_invoices",
    "subcontractors",
    "budget_line_items",
}
