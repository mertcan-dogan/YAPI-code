// Shared constants — Turkish labels, categories, colours (Appendix A/B, Section 6.2)

export const COLORS = {
  primary: "#1B2B4B",
  primaryLight: "#2E4272",
  accent: "#F59E0B",
  success: "#10B981",
  danger: "#EF4444",
  warning: "#EAB308",
  border: "#E2E8F0",
  lightBlue: "#93C5FD",
} as const;

export const PROJECT_TYPES: Record<string, string> = {
  road: "Yol İnşaatı",
  railway: "Demiryolu",
  marine: "Denizel / Kıyı",
  wastewater: "Atıksu Arıtma",
  building: "Bina İnşaatı",
  tunnel: "Tünel",
  bridge: "Köprü / Viyadük",
  other: "Diğer",
};

export const COST_CATEGORIES: Record<string, string> = {
  labour_direct: "İşçilik — Direkt",
  labour_sub: "İşçilik — Taşeron",
  material_concrete: "Malzeme — Beton",
  material_steel: "Malzeme — Çelik/Demir",
  material_pipes: "Malzeme — Boru/Fitting",
  material_aggregate: "Malzeme — Agrega/Kum",
  material_other: "Malzeme — Diğer",
  equipment_owned: "Ekipman — Şirkete Ait",
  equipment_rented: "Ekipman — Kiralık",
  subcontractor: "Alt Yüklenici",
  permits_fees: "İzin ve Harçlar",
  site_overhead: "Şantiye Genel Giderleri",
  engineering_design: "Mühendislik ve Tasarım",
  contingency: "Beklenmedik Giderler (Kontenjan)",
  other: "Diğer",
};

export const COST_CATEGORY_OPTIONS = Object.entries(COST_CATEGORIES).map(([value, label]) => ({
  value,
  label,
}));

export const VAT_RATES = [0, 1, 10, 20];

export const INVOICE_TYPE_LABELS: Record<string, string> = {
  hakedis: "Hakediş",
  advance: "Avans",
  variation: "Ek İş",
  final: "Kesin Hesap",
};

export const ROLE_LABELS: Record<string, string> = {
  director: "Yönetici",
  project_manager: "Proje Müdürü",
  finance: "Muhasebe",
  site_manager: "Şantiye Şefi",
};

export const STATUS_LABELS: Record<string, string> = {
  active: "Aktif",
  completed: "Tamamlandı",
  suspended: "Askıya Alındı",
  cancelled: "İptal Edildi",
  paid: "Ödendi",
  unpaid: "Ödenmedi",
  overdue: "Vadesi Geçmiş",
  partial: "Kısmi Ödeme",
  disputed: "İhtilaflı",
};

export const RAG_LABELS: Record<string, string> = {
  red: "Kritik",
  amber: "Dikkat",
  green: "İyi",
};
