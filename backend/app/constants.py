"""Shared enums, category lists, and Turkish labels (Appendix A & B, Section 4.3)."""

# --- Roles (Section 3.2) ---
ROLE_DIRECTOR = "director"
ROLE_PROJECT_MANAGER = "project_manager"
ROLE_FINANCE = "finance"
ROLE_SITE_MANAGER = "site_manager"
ROLES = [ROLE_DIRECTOR, ROLE_PROJECT_MANAGER, ROLE_FINANCE, ROLE_SITE_MANAGER]

# --- Project types (CR-001-A: 26 types grouped by category) ---
# key (stored in DB) -> (label, category)
PROJECT_TYPE_DEFS = [
    ("road", "Yol", "Ulaşım"),
    ("motorway", "Otoyol", "Ulaşım"),
    ("railway", "Demiryolu", "Ulaşım"),
    ("metro_tram", "Metro / Tramvay", "Ulaşım"),
    ("tunnel", "Tünel", "Ulaşım"),
    ("bridge_viaduct", "Köprü / Viyadük", "Ulaşım"),
    ("marine_coastal", "Denizel / Kıyı", "Denizel"),
    ("dredging", "Tarama (Dredging)", "Denizel"),
    ("port_harbor", "Liman / Rıhtım", "Denizel"),
    ("wastewater", "Atıksu Arıtma", "Su & Altyapı"),
    ("water_supply", "İçmesuyu", "Su & Altyapı"),
    ("sewage", "Kanalizasyon", "Su & Altyapı"),
    ("irrigation", "Sulama / Tarım", "Su & Altyapı"),
    ("building_residential", "Bina (Konut)", "Bina"),
    ("building_commercial", "Bina (Ticari)", "Bina"),
    ("building_industrial", "Bina (Endüstriyel)", "Bina"),
    ("factory", "Fabrika", "Bina"),
    ("warehouse_logistics", "Depo / Lojistik Merkezi", "Bina"),
    ("hospital", "Hastane", "Bina"),
    ("school", "Okul / Eğitim", "Bina"),
    ("hotel", "Otel / Turizm", "Bina"),
    ("renovation", "Renovasyon / Tadilat", "Özel"),
    ("urban_transformation", "Kentsel Dönüşüm", "Özel"),
    ("energy_plant", "Enerji Santrali", "Özel"),
    ("landscaping", "Peyzaj", "Özel"),
    ("other", "Diğer", "Diğer"),
]
PROJECT_TYPES = {key: label for key, label, _cat in PROJECT_TYPE_DEFS}

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
    "contingency": "Öngörülemeyen Giderler",
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
