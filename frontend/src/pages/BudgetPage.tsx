import { DataTable, type Column } from "@/components/DataTable";
import { CurrencyToggle, UsdAmountCell, useShowUsd } from "@/components/currency";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Card, CardBody, Input, Label, Select, Textarea } from "@/components/ui";
import { SideDrawer } from "@/components/SideDrawer";
import { BudgetCategoryDrawer } from "@/components/budget/BudgetCategoryDrawer";
import { BudgetSummaryCharts } from "@/components/budget/BudgetSummaryCharts";
import { ImportPreview } from "@/components/ImportPreview";
import { AIImportPreview } from "@/components/AIImportPreview";
import { ExtractionConfidenceBadge } from "@/components/ai/ExtractionConfidenceBadge";
import { ExportMenu, type ExportColumn } from "@/components/ExportMenu";
import { StatusBadge } from "@/components/StatusBadge";
import { COST_CATEGORIES, COST_CATEGORY_OPTIONS, STATUS_LABELS, VAT_RATES } from "@/constants";
import { useFetch } from "@/hooks/useFetch";
import { apiDelete, apiGet, apiPost, apiPut, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import type { BudgetCategoryRow, CostEntry } from "@/types";
import { formatCurrency, formatDate, formatPct, toNumber } from "@/utils/format";
import { AlertTriangle, ArrowUpRight, Download, FileText, Pencil, Plus, RefreshCw, Sparkles, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

const RAG_BG: Record<string, string> = { red: "bg-red-50", amber: "bg-amber-50", green: "" };

// CR-023: a commitment with its relief progress (from /projects/:id/commitments).
type Commitment = {
  id: string;
  cost_category: string;
  label_tr: string;
  supplier_name: string | null;
  description: string | null;
  po_number: string | null;
  amount_try: string;
  invoiced_try: string;
  open_try: string;
  pct_relieved: string;
  invoice_count: number;
  fully_relieved: boolean;
};

export default function BudgetPage() {
  const { id } = useParams();
  const budget = useFetch<{ categories: BudgetCategoryRow[]; totals: any }>(`/projects/${id}/budget`);
  const [filters, setFilters] = useState({ category: "", payment_status: "", entry_type: "" });
  const costs = useFetch<CostEntry[]>(`/projects/${id}/costs`, {
    category: filters.category || undefined,
    payment_status: filters.payment_status || undefined,
    entry_type: filters.entry_type || undefined,
    per_page: 100,
  });
  // CR-023: per-commitment relief progress, keyed by commitment id.
  const commitments = useFetch<{ commitments: Commitment[] }>(`/projects/${id}/commitments`);
  const reliefById: Record<string, Commitment> = {};
  for (const c of commitments.data?.commitments ?? []) reliefById[c.id] = c;
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [billing, setBilling] = useState<Commitment | null>(null); // commitment being invoiced
  const [editingCost, setEditingCost] = useState<CostEntry | null>(null);
  const [catRow, setCatRow] = useState<BudgetCategoryRow | null>(null); // CR-004-L
  const [importFile, setImportFile] = useState<File | null>(null);
  const [aiImportFile, setAiImportFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const aiFileRef = useRef<HTMLInputElement>(null);
  const { user } = useAuth();
  const canDelete = user?.role === "director" || user?.role === "project_manager";
  const budgetFailed = !!budget.error && !budget.loading;
  const showUsd = useShowUsd(); // CR-014-D

  const [rollupKey, setRollupKey] = useState(0);
  const refetchAll = () => {
    costs.refetch();
    budget.refetch();
    commitments.refetch(); // CR-023: relief progress changes when an actual is linked
    setRollupKey((k) => k + 1); // CR-018-C: refresh the subcategory breakdown
  };

  const openEdit = (c: CostEntry) => {
    setEditingCost(c);
    setDrawerOpen(true);
  };

  const removeCost = async (c: CostEntry) => {
    try {
      await apiDelete(`/projects/${id}/costs/${c.id}`);
      toast.success("Maliyet kaydı silindi");
      refetchAll();
    } catch (e: any) {
      toast.error(e.message ?? "Silinemedi");
    }
  };

  const editForecast = async (cat: string, value: string) => {
    try {
      await apiPut(`/projects/${id}/budget/${cat}`, { forecast_final_try: value });
      toast.success("Tahmin güncellendi");
      budget.refetch();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  // CR-002-A: edit the revised budget inline (saved as original_budget_try).
  const editRevised = async (cat: string, value: string) => {
    try {
      await apiPut(`/projects/${id}/budget/${cat}`, { original_budget_try: value || "0", approved_variations_try: "0" });
      toast.success("Revize bütçe güncellendi");
      budget.refetch();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const budgetColumns: Column<BudgetCategoryRow>[] = [
    {
      key: "label_tr",
      header: "Kategori",
      render: (r) => (
        <button onClick={() => setCatRow(r)} className="group inline-flex items-center gap-1 text-left font-medium text-primary hover:underline">
          {r.label_tr ?? COST_CATEGORIES[r.cost_category]}
          <ArrowUpRight className="h-3 w-3 opacity-0 group-hover:opacity-100" />
        </button>
      ),
    },
    {
      key: "revised_budget_try",
      header: "Revize Bütçe",
      align: "right",
      render: (r) => <EditableMoneyCell value={r.revised_budget_try} onSave={(v) => editRevised(r.cost_category, v)} />,
    },
    // CR-023.1: "Taahhüt" = exposure (gerçekleşen + açık taahhüt), the textbook
    // committed-cost figure. The row adds up: Taahhüt = Faturalanan + Açık Taahhüt
    // (no double-count). The legacy gross committed_try stays in the payload for
    // reports/agent_tools but is no longer displayed.
    { key: "exposure_try", header: "Taahhüt", align: "right", render: (r) => formatCurrency(r.exposure_try ?? r.committed_try) },
    // CR-023: açık taahhüt = committed minus what's already been invoiced against it.
    { key: "open_committed_try", header: "Açık Taahhüt", align: "right", render: (r) => <span className="text-accent" title="Taahhüt edilen ama henüz faturalanmamış tutar">{formatCurrency(r.open_committed_try ?? "0")}</span> },
    { key: "invoiced_try", header: "Faturalanan", align: "right", render: (r) => formatCurrency(r.invoiced_try) },
    { key: "paid_try", header: "Ödenen", align: "right", render: (r) => formatCurrency(r.paid_try) },
    { key: "remaining_try", header: "Kalan", align: "right", render: (r) => <span className={toNumber(r.remaining_try) < 0 ? "text-danger" : ""}>{formatCurrency(r.remaining_try)}</span> },
    {
      key: "pct_spent",
      header: "% Harcanan",
      align: "right",
      // CR-005-C: <%85 normal, %85–%100 amber, >%100 kırmızı + kalın. Tıklanınca
      // ilgili kategorinin detay drawer'ını açar.
      render: (r) => {
        const pct = toNumber(r.pct_spent);
        const cls = pct > 100 ? "text-danger font-bold" : pct >= 85 ? "text-accent" : "";
        return (
          <button onClick={() => setCatRow(r)} className={cn("tabular cursor-pointer hover:underline", cls)} title="Kategori detayını aç">
            {formatPct(r.pct_spent)}
          </button>
        );
      },
    },
    {
      key: "forecast_final",
      header: "Final Tahmin",
      align: "right",
      render: (r) => <EditableMoneyCell value={r.forecast_final} onSave={(v) => editForecast(r.cost_category, v)} />,
    },
    {
      key: "variance_try",
      header: "Sapma",
      align: "right",
      // CR-003-A: positive (over budget) = red, negative (under) = green, zero = gray.
      render: (r) => {
        const v = toNumber(r.variance_try);
        const color = v > 0 ? "text-danger" : v < 0 ? "text-success" : "text-text-secondary";
        return <span className={cn("tabular", color)}>{formatCurrency(r.variance_try)}</span>;
      },
    },
    {
      key: "status",
      header: "Durum",
      render: (r) => (
        <span
          className={cn(
            "inline-block h-3 w-3 rounded-full",
            r.status === "red" ? "bg-danger" : r.status === "amber" ? "bg-accent" : r.status === "gray" ? "bg-text-secondary" : "bg-success"
          )}
        />
      ),
    },
  ];

  const costColumns: Column<CostEntry>[] = [
    { key: "entry_date", header: "Tarih", render: (r) => formatDate(r.entry_date), sortable: true },
    { key: "cost_category", header: "Kategori", render: (r) => COST_CATEGORIES[r.cost_category] ?? r.cost_category },
    // CR-018-C: subcategory column; null/blank rolls up as "Belirtilmemiş".
    { key: "subcategory", header: "Alt Kategori", render: (r) => (r.subcategory && r.subcategory.trim()) ? r.subcategory : "Belirtilmemiş" },
    { key: "supplier_name", header: "Tedarikçi", render: (r) => r.supplier_name ?? "—" },
    {
      key: "description",
      header: "Açıklama",
      render: (r) => {
        const rel = r.entry_type === "committed" ? reliefById[r.id] : undefined;
        return (
          <div>
            <span>{r.description ?? "—"}</span>
            {/* CR-023: relief progress on each commitment row. */}
            {rel && (
              <div className="mt-0.5 text-xs text-text-secondary">
                {formatCurrency(rel.invoiced_try)} faturalandı / {formatCurrency(rel.amount_try)} taahhüt
                {" · "}
                <span className={toNumber(rel.open_try) > 0 ? "text-accent" : "text-success"}>
                  {toNumber(rel.open_try) > 0 ? `${formatCurrency(rel.open_try)} açık` : "tamamlandı"}
                </span>
              </div>
            )}
          </div>
        );
      },
    },
    { key: "amount_try", header: "Tutar", align: "right", render: (r) => formatCurrency(r.amount_try), sortable: true, sortValue: (r) => toNumber(r.amount_try) },
    { key: "total_with_vat_try", header: "KDV Dahil", align: "right", render: (r) => formatCurrency(r.total_with_vat_try) },
    // CR-014-D: USD snapshot (point-in-time). "—" while null (pre-backfill).
    ...(showUsd ? [{
      key: "amount_usd",
      header: "USD (Anlık)",
      align: "right" as const,
      render: (r: CostEntry) => (
        <UsdAmountCell
          amountUsd={r.amount_usd}
          rate={r.fx_rate_usd}
          paid={r.payment_status === "paid"}
          relevantDate={r.payment_status === "paid" ? r.date_paid : r.entry_date}
        />
      ),
    }] : []),
    { key: "payment_due_date", header: "Vade", align: "right", render: (r) => formatDate(r.payment_due_date) },
    {
      key: "payment_status",
      header: "Durum",
      render: (r) => (
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusBadge status={r.payment_status} />
          {/* CR-024: AI-read rows carry a confidence pill; manual rows show nothing. */}
          <ExtractionConfidenceBadge confidence={r.extraction_confidence} />
        </div>
      ),
    },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <div className="flex justify-end gap-2">
          {/* CR-023: invoice an open commitment — opens the form prefilled + linked. */}
          {r.entry_type === "committed" && !reliefById[r.id]?.fully_relieved && (
            <button
              onClick={() => setBilling(reliefById[r.id] ?? null)}
              className="inline-flex items-center gap-1 rounded border border-accent px-1.5 py-0.5 text-xs text-accent hover:bg-amber-50"
              title="Bu taahhüde karşı fatura gir"
            >
              <FileText className="h-3.5 w-3.5" /> Faturala
            </button>
          )}
          <button onClick={() => openEdit(r)} className="text-text-secondary hover:text-primary" aria-label="Düzenle">
            <Pencil className="h-4 w-4" />
          </button>
          {canDelete && (
            <button onClick={() => removeCost(r)} className="text-text-secondary hover:text-danger" aria-label="Sil">
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      ),
    },
  ];

  // CR-009: export the cost rows. Columns mirror the table — including the CR-014
  // USD snapshot (amount_usd, fx_rate_usd) and the CR-018 subcategory — and are
  // always present regardless of the ₺/$ toggle so the file is self-contained.
  const ENTRY_TYPE_LABELS: Record<string, string> = { actual: "Gerçekleşen", committed: "Taahhüt", forecast: "Tahmin" };
  const exportColumns: ExportColumn<CostEntry>[] = [
    { header: "Tarih", value: (r) => (r.entry_date ? formatDate(r.entry_date) : "") },
    { header: "Giriş Tipi", value: (r) => ENTRY_TYPE_LABELS[r.entry_type] ?? r.entry_type },
    { header: "Kategori", value: (r) => COST_CATEGORIES[r.cost_category] ?? r.cost_category },
    { header: "Alt Kategori", value: (r) => (r.subcategory && r.subcategory.trim() ? r.subcategory : "Belirtilmemiş") },
    { header: "Tedarikçi", value: (r) => r.supplier_name ?? "" },
    { header: "Açıklama", value: (r) => r.description ?? "" },
    { header: "Fatura No", value: (r) => r.invoice_number ?? "" },
    { header: "Tutar (TRY)", value: (r) => toNumber(r.amount_try) },
    { header: "KDV Oranı (%)", value: (r) => toNumber(r.vat_rate) },
    { header: "KDV Dahil (TRY)", value: (r) => toNumber(r.total_with_vat_try) },
    { header: "USD (Anlık)", value: (r) => (r.amount_usd != null ? Number(r.amount_usd) : "") },
    { header: "USD Kuru", value: (r) => (r.fx_rate_usd != null ? Number(r.fx_rate_usd) : "") },
    { header: "Vade", value: (r) => (r.payment_due_date ? formatDate(r.payment_due_date) : "") },
    { header: "Durum", value: (r) => STATUS_LABELS[r.payment_status] ?? r.payment_status },
  ];

  // The costs endpoint caps per_page at 100, so the visible table is just one
  // page. Export the FULL filtered set by walking every page — a silently
  // truncated financial export is worse than none.
  const fetchAllCosts = async (): Promise<CostEntry[]> => {
    const params = {
      category: filters.category || undefined,
      payment_status: filters.payment_status || undefined,
      entry_type: filters.entry_type || undefined,
      per_page: 100,
    };
    const first = await apiGet<CostEntry[]>(`/projects/${id}/costs`, { ...params, page: 1 });
    const all = [...(first.data ?? [])];
    const total = first.meta?.total ?? all.length;
    const perPage = first.meta?.per_page ?? 100;
    const pages = Math.ceil(total / perPage);
    for (let p = 2; p <= pages; p++) {
      const r = await apiGet<CostEntry[]>(`/projects/${id}/costs`, { ...params, page: p });
      all.push(...(r.data ?? []));
    }
    return all;
  };

  const onImport = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    // CR-001-F: no longer used (kept for reference) — preview flow handles import.
    void fd;
  };

  // CR-001-F/G: download the template with the auth header (fixes the 401 that
  // window.open caused — it cannot attach the Bearer token).
  const downloadTemplate = async () => {
    try {
      const res = await api.get(`/projects/${id}/costs/import/template`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = "yapi-maliyet-sablonu.xlsx";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      toast.error(e.message ?? "Şablon indirilemedi");
    }
  };

  return (
    <div>
      <PageHeader
        title="Bütçe & Maliyetler"
        action={
          <div className="flex flex-wrap items-center gap-2">
            <CurrencyToggle />
            {/* CR-009: export the cost rows (full filtered set, all pages). */}
            <ExportMenu rows={costs.data ?? []} columns={exportColumns} filename="maliyetler" fetchRows={fetchAllCosts} />
            <Button variant="outline" onClick={downloadTemplate}>
              <Download className="h-4 w-4" /> Şablon
            </Button>
            <Button variant="outline" onClick={() => fileRef.current?.click()}>
              <Upload className="h-4 w-4" /> Excel'den İçe Aktar
            </Button>
            <Button variant="outline" className="border-brand text-brand" onClick={() => aiFileRef.current?.click()}>
              <Sparkles className="h-4 w-4" /> AI ile İçe Aktar
            </Button>
            <input
              ref={aiFileRef}
              type="file"
              accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel.sheet.macroEnabled.12"
              hidden
              onChange={(e) => {
                if (e.target.files?.[0]) setAiImportFile(e.target.files[0]);
                e.target.value = "";
              }}
            />
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel.sheet.macroEnabled.12"
              hidden
              onChange={(e) => {
                if (e.target.files?.[0]) setImportFile(e.target.files[0]);
                e.target.value = "";
              }}
            />
            <Button onClick={() => setDrawerOpen(true)}>
              <Plus className="h-4 w-4" /> Maliyet Ekle
            </Button>
          </div>
        }
      />

      {budgetFailed ? (
        <div className="mb-4 flex flex-col items-center justify-center gap-3 rounded-xl border border-danger/40 bg-red-50 py-10 text-center">
          <AlertTriangle className="h-8 w-8 text-danger" />
          <p className="text-sm text-text-secondary">Bütçe verileri yüklenemedi. Lütfen tekrar deneyin.</p>
          <Button variant="outline" onClick={() => budget.refetch()}><RefreshCw className="h-4 w-4" /> Tekrar Dene</Button>
        </div>
      ) : (
      <>
      {/* CR-005-H: sayfa üstü özet — 4 KPI kartı + bütçe kullanım bar chart. */}
      <BudgetSummaryCharts
        categories={budget.data?.categories ?? []}
        totals={budget.data?.totals}
        loading={budget.loading}
        onAddBudget={() => setDrawerOpen(true)}
      />

      <h2 className="mb-2 text-lg font-semibold text-primary">Bütçe & Gerçekleşen</h2>
      <DataTable columns={budgetColumns} rows={budget.data?.categories ?? []} loading={budget.loading} emptyMessage="Bu proje için henüz bütçe verisi yok." />
      {budget.data?.totals && (
        <div className="mt-1 flex flex-wrap items-center gap-x-8 gap-y-1 rounded-md bg-primary px-4 py-3 text-sm text-white">
          <span className="font-semibold">Toplam</span>
          <span className="tabular">Revize Bütçe: <b>{formatCurrency(budget.data.totals.revised_budget_try)}</b></span>
          {/* CR-023.1: Taahhüt total = exposure (gerçekleşen + açık) — reconciles
              with Faturalanan + Açık Taahhüt, no double-count. */}
          <span className="tabular">Taahhüt: <b>{formatCurrency(budget.data.totals.exposure_try ?? budget.data.totals.committed_try)}</b></span>
          <span className="tabular">Açık Taahhüt: <b>{formatCurrency(budget.data.totals.open_committed_try ?? "0")}</b></span>
          <span className="tabular">Faturalanan: <b>{formatCurrency(budget.data.totals.invoiced_try)}</b></span>
          <span className="tabular">Ödenen: <b>{formatCurrency(budget.data.totals.paid_try)}</b></span>
          <span className="tabular">Genel Kalan: <b>{formatCurrency(budget.data.totals.remaining_try)}</b></span>
        </div>
      )}
      </>
      )}

      <div className="mt-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-primary">Maliyet Girişleri</h2>
        <div className="flex gap-2">
          <Select value={filters.category} onChange={(e) => setFilters((f) => ({ ...f, category: e.target.value }))} className="w-44">
            <option value="">Tüm Kategoriler</option>
            {COST_CATEGORY_OPTIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </Select>
          <Select value={filters.payment_status} onChange={(e) => setFilters((f) => ({ ...f, payment_status: e.target.value }))} className="w-40">
            <option value="">Tüm Durumlar</option>
            <option value="unpaid">Ödenmemiş</option>
            <option value="paid">Ödendi</option>
            <option value="overdue">Vadesi Geçmiş</option>
          </Select>
        </div>
      </div>
      <div className="mt-2">
        <DataTable columns={costColumns} rows={costs.data ?? []} loading={costs.loading} error={costs.error} onRetry={costs.refetch} emptyMessage="Bu proje için henüz maliyet girişi yapılmamış." emptyAction={{ label: "Maliyet Ekle", onClick: () => setDrawerOpen(true) }} rowClassName={(r) => (r.payment_status === "overdue" ? "!bg-red-50" : "")} />
      </div>

      {/* CR-018-C: costs grouped by (category → subcategory) */}
      <SubcategoryBreakdown projectId={id!} refreshKey={rollupKey} />

      <CostDrawer
        open={drawerOpen}
        projectId={id!}
        editing={editingCost}
        onClose={() => { setDrawerOpen(false); setEditingCost(null); }}
        onSaved={() => { setEditingCost(null); refetchAll(); }}
      />

      {/* CR-023: dedicated drawer for invoicing against a commitment (Faturala). */}
      <CostDrawer
        open={!!billing}
        projectId={id!}
        billing={billing}
        onClose={() => setBilling(null)}
        onSaved={() => { setBilling(null); refetchAll(); }}
      />

      {/* CR-004-L: budget category detail drawer */}
      <BudgetCategoryDrawer
        open={!!catRow}
        row={catRow}
        projectId={id!}
        onClose={() => setCatRow(null)}
        onEdit={(c) => { setCatRow(null); openEdit(c); }}
      />

      {importFile && (
        <ImportPreview
          projectId={id!}
          file={importFile}
          onClose={() => setImportFile(null)}
          onDone={() => {
            setImportFile(null);
            costs.refetch();
            budget.refetch();
          }}
        />
      )}

      {aiImportFile && (
        <AIImportPreview
          projectId={id!}
          file={aiImportFile}
          onClose={() => setAiImportFile(null)}
          onDone={() => {
            setAiImportFile(null);
            costs.refetch();
            budget.refetch();
          }}
        />
      )}
    </div>
  );
}

// CR-003-A: shows the value in Turkish currency format; click to edit inline.
function EditableMoneyCell({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  if (editing) {
    return (
      <Input
        autoFocus
        type="number"
        value={draft}
        className="w-32 bg-amber-50 text-right tabular"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => { setEditing(false); if (draft !== "" && draft !== value) onSave(draft); }}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
      />
    );
  }
  return (
    <button
      className="tabular w-full cursor-text rounded px-2 py-1 text-right hover:bg-amber-50"
      onClick={() => { setDraft(toNumber(value) ? value : ""); setEditing(true); }}
      title="Düzenlemek için tıklayın"
    >
      {formatCurrency(value)}
    </button>
  );
}

// CR-018-C: cascading Alt Kategori selector. For a STANDARD category it loads
// presets + company customs from GET /cost-subcategories and offers "+ Yeni alt
// kategori" (creates a custom under the current category) and "Diğer" (free text).
// For a company custom category (no standard parent) it falls back to free text.
// The chosen value is stored as the subcategory label text (legacy/free-text safe).
const SUB_OTHER = "__other__";
const SUB_ADD = "__add__";
type SubOption = { key: string; label: string; custom: boolean };

function SubcategorySelect({ category, value, onChange }: { category: string; value: string; onChange: (v: string) => void }) {
  const isStandard = !!category && category in COST_CATEGORIES;
  const [options, setOptions] = useState<SubOption[]>([]);
  const [free, setFree] = useState(false);

  const loadOptions = (cat: string) =>
    apiGet<SubOption[]>("/cost-subcategories", { category: cat })
      .then(({ data }) => setOptions(data ?? []))
      .catch(() => setOptions([]));

  useEffect(() => {
    if (!isStandard) { setOptions([]); return; }
    loadOptions(category);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, isStandard]);

  // An existing value not in the preset/custom list is legacy free text -> free mode.
  useEffect(() => {
    if (isStandard && value) setFree(!options.some((o) => o.label === value));
    else if (!value) setFree(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options, value, isStandard]);

  if (!isStandard) {
    return <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder="Alt kategori (opsiyonel)" />;
  }

  const addCustom = async () => {
    const name = window.prompt("Yeni alt kategori adı:");
    if (!name || !name.trim()) return;
    try {
      await apiPost("/custom-categories", { name: name.trim(), parent_category: category });
      await loadOptions(category);
      setFree(false);
      onChange(name.trim());
      toast.success("Alt kategori eklendi");
    } catch (e: any) {
      toast.error(e.message ?? "Alt kategori eklenemedi");
    }
  };

  const handle = (v: string) => {
    if (v === SUB_ADD) return void addCustom();
    if (v === SUB_OTHER) { setFree(true); onChange(""); return; }
    setFree(false);
    onChange(v);
  };

  const selectValue = free ? SUB_OTHER : (options.some((o) => o.label === value) ? value : "");

  return (
    <>
      <Select value={selectValue} onChange={(e) => handle(e.target.value)}>
        <option value="">Belirtilmemiş</option>
        {options.map((o) => (
          <option key={(o.custom ? "c:" : "p:") + o.key} value={o.label}>
            {o.label}{o.custom ? " (özel)" : ""}
          </option>
        ))}
        <option value={SUB_OTHER}>Diğer (serbest metin)…</option>
        <option value={SUB_ADD}>+ Yeni alt kategori…</option>
      </Select>
      {free && (
        <Input className="mt-2" autoFocus value={value} onChange={(e) => onChange(e.target.value)} placeholder="Alt kategori girin" />
      )}
    </>
  );
}

// CR-018-C: a dedicated "costs by subcategory" breakdown panel (the simpler option
// from §3.1 — not full budget-tree nesting). Each category expands to its
// (category → subcategory) SUMs from GET /projects/{id}/costs/by-subcategory.
type SubRollup = { subcategory: string; amount_try: string; total_with_vat_try: string };
type CatRollup = { cost_category: string; label_tr: string; amount_try: string; total_with_vat_try: string; subcategories: SubRollup[] };

function SubcategoryBreakdown({ projectId, refreshKey }: { projectId: string; refreshKey: number }) {
  const [cats, setCats] = useState<CatRollup[]>([]);
  const [open, setOpen] = useState<Record<string, boolean>>({});

  useEffect(() => {
    apiGet<{ categories: CatRollup[] }>(`/projects/${projectId}/costs/by-subcategory`)
      .then(({ data }) => setCats(data?.categories ?? []))
      .catch(() => setCats([]));
  }, [projectId, refreshKey]);

  if (cats.length === 0) return null;

  return (
    <div className="mt-6">
      <h2 className="mb-2 text-lg font-semibold text-primary">Alt Kategori Dağılımı</h2>
      <Card>
        <CardBody className="space-y-1">
          {cats.map((c) => {
            const expanded = open[c.cost_category] ?? false;
            return (
              <div key={c.cost_category} className="border-b border-border last:border-0">
                <button
                  className="flex w-full items-center justify-between py-2 text-left"
                  onClick={() => setOpen((o) => ({ ...o, [c.cost_category]: !expanded }))}
                >
                  <span className="font-medium text-primary">
                    <span className="mr-1 inline-block w-3 text-text-secondary">{expanded ? "▾" : "▸"}</span>
                    {c.label_tr}
                  </span>
                  <span className="tabular text-sm">{formatCurrency(c.total_with_vat_try)}</span>
                </button>
                {expanded && (
                  <div className="pb-2 pl-4">
                    {c.subcategories.map((s) => (
                      <div key={s.subcategory} className="flex items-center justify-between py-1 text-sm text-text-secondary">
                        <span>{s.subcategory}</span>
                        <span className="tabular">{formatCurrency(s.total_with_vat_try)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </CardBody>
      </Card>
    </div>
  );
}

function CostDrawer({ open, projectId, editing, billing, onClose, onSaved }: { open: boolean; projectId: string; editing?: CostEntry | null; billing?: Commitment | null; onClose: () => void; onSaved: () => void }) {
  const empty = {
    entry_date: new Date().toISOString().slice(0, 10),
    entry_type: "actual",
    cost_category: "",
    subcategory: "",
    supplier_name: "",
    description: "",
    invoice_number: "",
    amount_try: "",
    amount_eur: "",
    vat_rate: "20",
    payment_due_date: "",
    notes: "",
    commitment_id: "", // CR-023: set in billing (Faturala) mode
  };
  const [form, setForm] = useState<any>(empty);
  const [saving, setSaving] = useState(false);
  const [aiFields, setAiFields] = useState<Set<string>>(new Set());
  const [customCats, setCustomCats] = useState<{ id: string; name: string }[]>([]);
  const extractRef = useRef<HTMLInputElement>(null);
  const set = (k: string, v: string) => setForm((f: any) => ({ ...f, [k]: v }));

  // CR-001-G: prefill the form when editing an existing entry.
  // CR-023: in billing mode prefill a linked actual against the open commitment.
  useEffect(() => {
    if (open && editing) {
      setForm({
        ...empty,
        entry_date: editing.entry_date ?? empty.entry_date,
        entry_type: editing.entry_type ?? "actual",
        cost_category: editing.cost_category ?? "",
        subcategory: editing.subcategory ?? "",
        supplier_name: editing.supplier_name ?? "",
        description: editing.description ?? "",
        invoice_number: editing.invoice_number ?? "",
        amount_try: editing.amount_try ?? "",
        amount_eur: (editing as any).amount_eur ?? "",
        vat_rate: editing.vat_rate ?? "20",
        payment_due_date: editing.payment_due_date ?? "",
        notes: editing.notes ?? "",
        commitment_id: editing.commitment_id ?? "",
      });
    } else if (open && billing) {
      setForm({
        ...empty,
        entry_type: "actual",
        cost_category: billing.cost_category ?? "",
        supplier_name: billing.supplier_name ?? "",
        amount_try: billing.open_try ?? "",
        commitment_id: billing.id,
      });
    } else if (open && !editing) {
      setForm(empty);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing, billing]);

  // CR-001-D: company custom categories appear under their own group.
  useEffect(() => {
    if (open) apiGet<{ id: string; name: string }[]>("/custom-categories").then(({ data }) => setCustomCats(data ?? [])).catch(() => setCustomCats([]));
  }, [open]);

  const save = async () => {
    if (!form.cost_category || toNumber(form.amount_try) <= 0) {
      toast.error("Kategori ve tutar zorunludur");
      return;
    }
    setSaving(true);
    try {
      const body = {
        ...form,
        amount_eur: form.amount_eur || null,
        payment_due_date: form.payment_due_date || null,
        // CR-023: only send a relief link when one is set (Faturala flow).
        commitment_id: form.commitment_id || null,
      };
      if (editing) {
        await apiPut(`/projects/${projectId}/costs/${editing.id}`, body);
        toast.success("Maliyet güncellendi");
      } else {
        await apiPost(`/projects/${projectId}/costs`, body);
        toast.success("Maliyet kaydedildi");
      }
      setForm(empty);
      setAiFields(new Set());
      onSaved();
      onClose();
    } catch (e: any) {
      toast.error(e.message ?? "Kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  const extract = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await api.post(`/ai/extract-invoice`, fd);
      const ex = res.data.data.extracted;
      const filled = new Set<string>();
      const next = { ...form };
      const map: Record<string, string> = { supplier_name: "supplier_name", invoice_number: "invoice_number", invoice_date: "entry_date", amount_try: "amount_try", vat_rate: "vat_rate", description: "description" };
      for (const [src, dst] of Object.entries(map)) {
        if (ex[src] != null) {
          next[dst] = String(ex[src]);
          filled.add(dst);
        }
      }
      setForm(next);
      setAiFields(filled);
      toast.info("AI tarafından dolduruldu — lütfen kontrol edin");
    } catch (e: any) {
      toast.error(e.message ?? "AI şu an kullanılamıyor");
    }
  };

  const aiClass = (k: string) => (aiFields.has(k) ? "bg-navy-50" : "");

  return (
    <SideDrawer open={open} title={billing ? "Taahhüde Karşı Faturala" : editing ? "Maliyet Düzenle" : "Maliyet Ekle"} onClose={onClose} onSave={save} saving={saving} dirty={!!form.amount_try || !!form.cost_category}>
      <div className="space-y-3">
        {/* CR-024: this entry was captured/imported by AI — surface the confidence. */}
        {editing?.extraction_confidence != null && (
          <div className="flex items-center gap-2 rounded-md border border-border bg-bg px-3 py-2 text-xs text-text-secondary">
            <span>Bu kayıt yapay zeka ile okundu.</span>
            <ExtractionConfidenceBadge confidence={editing.extraction_confidence} showLabel />
          </div>
        )}
        {/* CR-023: billing-against-commitment context banner. */}
        {billing && (
          <div className="rounded-md border border-accent bg-amber-50 px-3 py-2 text-xs text-text-secondary">
            <b className="text-primary">{billing.label_tr}</b> taahhüdüne karşı fatura giriliyor.
            {" "}Açık tutar: <b>{formatCurrency(billing.open_try)}</b> / {formatCurrency(billing.amount_try)} taahhüt.
            <div className="mt-0.5">Tutarı değiştirebilirsiniz; girilen fatura bu taahhüdü düşer (mükerrer saymaz).</div>
          </div>
        )}
        <div>
          <Button variant="outline" className="w-full" onClick={() => extractRef.current?.click()}>
            PDF Fatura Yükle (AI ile doldur)
          </Button>
          <input ref={extractRef} type="file" accept="application/pdf" hidden onChange={(e) => e.target.files?.[0] && extract(e.target.files[0])} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label required>Tarih</Label><Input type="date" className={aiClass("entry_date")} value={form.entry_date} onChange={(e) => set("entry_date", e.target.value)} /></div>
          <div><Label required>Giriş Tipi</Label><Select value={form.entry_type} onChange={(e) => set("entry_type", e.target.value)}><option value="actual">Gerçekleşen</option><option value="committed">Taahhüt</option><option value="forecast">Tahmin</option></Select></div>
        </div>
        <div><Label required>Kategori</Label><Select value={form.cost_category} onChange={(e) => set("cost_category", e.target.value)}>
          <option value="">Seçiniz</option>
          <optgroup label="Standart Kategoriler">
            {COST_CATEGORY_OPTIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </optgroup>
          {customCats.length > 0 && (
            <optgroup label="Şirket Kategorileri">
              {customCats.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
            </optgroup>
          )}
        </Select></div>
        <div><Label>Alt Kategori</Label><SubcategorySelect category={form.cost_category} value={form.subcategory} onChange={(v) => set("subcategory", v)} /></div>
        <div><Label>Tedarikçi / Alt Yüklenici</Label><Input className={aiClass("supplier_name")} value={form.supplier_name} onChange={(e) => set("supplier_name", e.target.value)} /></div>
        <div><Label>Açıklama</Label><Textarea className={aiClass("description")} value={form.description} onChange={(e) => set("description", e.target.value)} /></div>
        <div><Label>Fatura No</Label><Input className={aiClass("invoice_number")} value={form.invoice_number} onChange={(e) => set("invoice_number", e.target.value)} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label required>Tutar (TRY)</Label><Input type="number" className={aiClass("amount_try")} value={form.amount_try} onChange={(e) => set("amount_try", e.target.value)} /></div>
          <div><Label>Tutar (EUR)</Label><Input type="number" value={form.amount_eur} onChange={(e) => set("amount_eur", e.target.value)} /></div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label required>KDV Oranı</Label><Select className={aiClass("vat_rate")} value={form.vat_rate} onChange={(e) => set("vat_rate", e.target.value)}>{VAT_RATES.map((v) => <option key={v} value={v}>%{v}</option>)}</Select></div>
          <div><Label>Vade Tarihi</Label><Input type="date" value={form.payment_due_date} onChange={(e) => set("payment_due_date", e.target.value)} /></div>
        </div>
        <div><Label>Notlar</Label><Textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} maxLength={1000} /></div>
        {aiFields.size > 0 && <p className="text-xs text-primary-light">Mavi alanlar AI tarafından dolduruldu — lütfen kontrol edin.</p>}
      </div>
    </SideDrawer>
  );
}
