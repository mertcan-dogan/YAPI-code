// Shared constants — Turkish labels, categories, colours (Appendix A/B, Section 6.2)

export const COLORS = {
  primary: "#0E1525",
  primaryLight: "#1E293F",
  brand: "#2563EB",
  brand2: "#06B6D4",
  accent: "#F59E0B",
  success: "#059669",
  danger: "#EF4444",
  warning: "#D97706",
  border: "#E3E8EF",
  lightBlue: "#93C5FD",
  muted: "#94A3B8",
} as const;

// CR-001-A: 26 project types grouped by category.
export const PROJECT_TYPE_GROUPS: { category: string; options: { value: string; label: string }[] }[] = [
  {
    category: "Ulaşım",
    options: [
      { value: "road", label: "Yol" },
      { value: "motorway", label: "Otoyol" },
      { value: "railway", label: "Demiryolu" },
      { value: "metro_tram", label: "Metro / Tramvay" },
      { value: "tunnel", label: "Tünel" },
      { value: "bridge_viaduct", label: "Köprü / Viyadük" },
    ],
  },
  {
    category: "Denizel",
    options: [
      { value: "marine_coastal", label: "Denizel / Kıyı" },
      { value: "dredging", label: "Tarama (Dredging)" },
      { value: "port_harbor", label: "Liman / Rıhtım" },
    ],
  },
  {
    category: "Su & Altyapı",
    options: [
      { value: "wastewater", label: "Atıksu Arıtma" },
      { value: "water_supply", label: "İçmesuyu" },
      { value: "sewage", label: "Kanalizasyon" },
      { value: "irrigation", label: "Sulama / Tarım" },
    ],
  },
  {
    category: "Bina",
    options: [
      { value: "building_residential", label: "Bina (Konut)" },
      { value: "building_commercial", label: "Bina (Ticari)" },
      { value: "building_industrial", label: "Bina (Endüstriyel)" },
      { value: "factory", label: "Fabrika" },
      { value: "warehouse_logistics", label: "Depo / Lojistik Merkezi" },
      { value: "hospital", label: "Hastane" },
      { value: "school", label: "Okul / Eğitim" },
      { value: "hotel", label: "Otel / Turizm" },
    ],
  },
  {
    category: "Özel",
    options: [
      { value: "renovation", label: "Renovasyon / Tadilat" },
      { value: "urban_transformation", label: "Kentsel Dönüşüm" },
      { value: "energy_plant", label: "Enerji Santrali" },
      { value: "landscaping", label: "Peyzaj" },
    ],
  },
  { category: "Diğer", options: [{ value: "other", label: "Diğer" }] },
];

export const PROJECT_TYPES: Record<string, string> = Object.fromEntries(
  PROJECT_TYPE_GROUPS.flatMap((g) => g.options.map((o) => [o.value, o.label]))
);

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
  contingency: "Öngörülemeyen Giderler",
  other: "Diğer",
};

export const COST_CATEGORY_OPTIONS = Object.entries(COST_CATEGORIES).map(([value, label]) => ({
  value,
  label,
}));

// CR-016: unit-schedule (daire dağılımı) preset types — mirrors backend UNIT_TYPES.
export const UNIT_TYPES: Record<string, string> = {
  "1+1": "1+1",
  "2+1": "2+1",
  "3+1": "3+1",
  "4+1": "4+1",
  ticari: "Ticari",
  dukkan: "Dükkan",
  ofis: "Ofis",
  bodrum: "Bodrum",
  depo: "Depo",
  other: "Diğer",
};

export const UNIT_TYPE_OPTIONS = Object.entries(UNIT_TYPES).map(([value, label]) => ({
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
