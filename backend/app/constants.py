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

# --- Unit-schedule types (CR-016 daire dağılımı) ---
# Preset keys for the residential unit schedule; "other" requires a custom_label.
UNIT_TYPES = {
    "1+1": "1+1",
    "2+1": "2+1",
    "3+1": "3+1",
    "4+1": "4+1",
    "ticari": "Ticari",
    "dukkan": "Dükkan",
    "ofis": "Ofis",
    "bodrum": "Bodrum",
    "depo": "Depo",
    "other": "Diğer",
}
UNIT_TYPE_KEYS = list(UNIT_TYPES.keys())

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

# --- Cost subcategory taxonomy (CR-018-A) ---
# Global preset subcategories under each standard cost category. The single source
# of truth: maps a COST_CATEGORIES key -> an ordered list of (subkey, Turkish label).
# Sensible starter set, NOT exhaustive — companies add their own on top (custom
# subcategories, parent_category on custom_cost_categories). cost_entries.subcategory
# stays free-text, so any value here, a company custom, or "Diğer" free-text is valid.
# Keep every key below a valid COST_CATEGORY key (asserted in tests). Empty list =>
# that category has no presets yet (free-text only).
_LABOUR_SUBCATEGORIES = [
    ("kaba_insaat", "Kaba İnşaat"),
    ("ince_iscilik", "İnce İşçilik"),
    ("elektrik", "Elektrik"),
    ("sihhi_tesisat", "Sıhhi Tesisat / Mekanik"),
    ("boya_badana", "Boya / Badana"),
    ("kalip", "Kalıp"),
    ("demir_donati", "Demir / Donatı"),
    ("siva", "Sıva"),
    ("seramik_fayans", "Seramik / Fayans"),
    ("alcipan", "Alçıpan"),
    ("yalitim", "Yalıtım"),
    ("cati", "Çatı"),
    ("dograma", "Doğrama"),
]
COST_SUBCATEGORIES: dict[str, list[tuple[str, str]]] = {
    # Labour — shared trade breakdown for both direct and subcontracted labour.
    "labour_direct": _LABOUR_SUBCATEGORIES,
    "labour_sub": _LABOUR_SUBCATEGORIES,
    # Materials — by material detail relevant to the parent.
    "material_concrete": [
        ("hazir_beton", "Hazır Beton"),
        ("cimento", "Çimento"),
        ("beton_katki", "Beton Katkı Maddesi"),
        ("kalip_malzeme", "Kalıp Malzemesi"),
    ],
    "material_steel": [
        ("nervurlu_demir", "Nervürlü İnşaat Demiri"),
        ("hasir_celik", "Hasır Çelik"),
        ("celik_profil", "Çelik Profil"),
        ("baglanti_elemanlari", "Bağlantı Elemanları"),
    ],
    "material_pipes": [
        ("pvc_boru", "PVC Boru"),
        ("ppr_boru", "PPR Boru"),
        ("pe_boru", "PE Boru"),
        ("fitting", "Fitting / Bağlantı"),
        ("vana_armatur", "Vana / Armatür"),
    ],
    "material_aggregate": [
        ("kum", "Kum"),
        ("cakil", "Çakıl"),
        ("micir", "Mıcır"),
        ("stabilize", "Stabilize / Dolgu"),
    ],
    "material_other": [
        ("tugla_briket", "Tuğla / Briket"),
        ("yalitim_malzeme", "Yalıtım Malzemesi"),
        ("alcipan_malzeme", "Alçıpan / Profil"),
        ("boya_malzeme", "Boya / Vernik"),
        ("seramik_malzeme", "Seramik / Fayans"),
        ("cam", "Cam"),
        ("ahsap", "Ahşap"),
    ],
    # Equipment.
    "equipment_owned": [
        ("yakit", "Yakıt"),
        ("bakim_onarim", "Bakım / Onarım"),
        ("yedek_parca", "Yedek Parça"),
        ("amortisman", "Amortisman"),
    ],
    "equipment_rented": [
        ("is_makinesi", "İş Makinesi Kiralama"),
        ("vinc", "Vinç Kiralama"),
        ("iskele", "İskele / Kalıp Kiralama"),
        ("jenerator", "Jeneratör"),
    ],
    # Subcontractor — by trade package.
    "subcontractor": [
        ("kaba_insaat_taseron", "Kaba İnşaat Taşeronu"),
        ("mekanik_taseron", "Mekanik Tesisat Taşeronu"),
        ("elektrik_taseron", "Elektrik Taşeronu"),
        ("cephe_taseron", "Cephe / Mantolama Taşeronu"),
        ("peyzaj_taseron", "Peyzaj Taşeronu"),
    ],
    # Permits & fees.
    "permits_fees": [
        ("ruhsat", "İnşaat Ruhsatı"),
        ("iskan", "İskan / Yapı Kullanma İzni"),
        ("belediye_harc", "Belediye Harçları"),
        ("proje_onay", "Proje Onay Bedelleri"),
    ],
    # Site overhead.
    "site_overhead": [
        ("santiye_kira", "Şantiye Kira"),
        ("elektrik_su", "Elektrik / Su"),
        ("guvenlik", "Güvenlik"),
        ("temizlik", "Temizlik"),
        ("konaklama", "Personel Konaklama"),
        ("ulasim", "Ulaşım / Nakliye"),
    ],
    # Engineering & design.
    "engineering_design": [
        ("mimari_proje", "Mimari Proje"),
        ("statik_proje", "Statik Proje"),
        ("mekanik_proje", "Mekanik Proje"),
        ("elektrik_proje", "Elektrik Proje"),
        ("zemin_etut", "Zemin Etüdü"),
        ("danismanlik", "Danışmanlık"),
    ],
    # No sensible presets — free-text / company-custom only.
    "contingency": [],
    "other": [],
}


def subcategories_for(category_key: str) -> list[tuple[str, str]]:
    """Ordered preset (subkey, label) subcategories for a cost category.

    Returns [] for an unknown category or one with no presets (free-text only).
    Company-custom subcategories are merged on top of this at the API layer (CR-018-B).
    """
    return COST_SUBCATEGORIES.get(category_key, [])


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
    # CR-003-M: 5 new types
    "duplicate_invoice",
    "unusual_cost",
    "collection_risk",
    "margin_erosion",
    "cash_gap_30",
]
ALERT_SEVERITIES = ["high", "medium", "low"]

# --- Audited tables (Section 8.2) ---
AUDITED_TABLES = {
    "projects",
    "cost_entries",
    "client_invoices",
    "subcontractors",
    "budget_line_items",
    # CR-008-H/I: vendor merges & legacy relinks change financial groupings.
    "vendors",
    # Equipment photos: photo add/remove.
    "equipment_log",
}
