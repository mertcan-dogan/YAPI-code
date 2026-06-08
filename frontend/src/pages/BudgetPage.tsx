import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Card, CardBody, Input, Label, Select, Textarea } from "@/components/ui";
import { SideDrawer } from "@/components/SideDrawer";
import { ImportPreview } from "@/components/ImportPreview";
import { AIImportPreview } from "@/components/AIImportPreview";
import { StatusBadge } from "@/components/StatusBadge";
import { COST_CATEGORIES, COST_CATEGORY_OPTIONS, VAT_RATES } from "@/constants";
import { useFetch } from "@/hooks/useFetch";
import { apiDelete, apiGet, apiPost, apiPut, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import type { BudgetCategoryRow, CostEntry } from "@/types";
import { formatCurrency, formatDate, formatPct, toNumber } from "@/utils/format";
import { Download, Pencil, Plus, Sparkles, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

const RAG_BG: Record<string, string> = { red: "bg-red-50", amber: "bg-amber-50", green: "" };

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
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingCost, setEditingCost] = useState<CostEntry | null>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [aiImportFile, setAiImportFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const aiFileRef = useRef<HTMLInputElement>(null);
  const { user } = useAuth();
  const canDelete = user?.role === "director" || user?.role === "project_manager";

  const refetchAll = () => {
    costs.refetch();
    budget.refetch();
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
    { key: "label_tr", header: "Kategori", render: (r) => r.label_tr ?? COST_CATEGORIES[r.cost_category] },
    {
      key: "revised_budget_try",
      header: "Revize Bütçe",
      align: "right",
      render: (r) => (
        <Input
          defaultValue={toNumber(r.revised_budget_try) ? r.revised_budget_try : ""}
          type="number"
          placeholder="0"
          className="w-32 bg-amber-50 text-right"
          onBlur={(e) => e.target.value !== r.revised_budget_try && editRevised(r.cost_category, e.target.value)}
        />
      ),
    },
    { key: "committed_try", header: "Taahhüt", align: "right", render: (r) => formatCurrency(r.committed_try) },
    { key: "invoiced_try", header: "Faturalanan", align: "right", render: (r) => formatCurrency(r.invoiced_try) },
    { key: "paid_try", header: "Ödenen", align: "right", render: (r) => formatCurrency(r.paid_try) },
    { key: "remaining_try", header: "Kalan", align: "right", render: (r) => <span className={toNumber(r.remaining_try) < 0 ? "text-danger" : ""}>{formatCurrency(r.remaining_try)}</span> },
    { key: "pct_spent", header: "% Harcanan", align: "right", render: (r) => formatPct(r.pct_spent) },
    {
      key: "forecast_final",
      header: "Final Tahmin",
      align: "right",
      render: (r) => (
        <Input
          defaultValue={r.forecast_final}
          type="number"
          className="w-28 text-right"
          onBlur={(e) => e.target.value !== r.forecast_final && editForecast(r.cost_category, e.target.value)}
        />
      ),
    },
    { key: "variance_try", header: "Sapma", align: "right", render: (r) => <span className={toNumber(r.variance_try) > 0 ? "text-danger" : "text-success"}>{formatCurrency(r.variance_try)}</span> },
    { key: "status", header: "Durum", render: (r) => <span className={cn("inline-block h-3 w-3 rounded-full", r.status === "red" ? "bg-danger" : r.status === "amber" ? "bg-accent" : "bg-success")} /> },
  ];

  const costColumns: Column<CostEntry>[] = [
    { key: "entry_date", header: "Tarih", render: (r) => formatDate(r.entry_date), sortable: true },
    { key: "cost_category", header: "Kategori", render: (r) => COST_CATEGORIES[r.cost_category] ?? r.cost_category },
    { key: "supplier_name", header: "Tedarikçi", render: (r) => r.supplier_name ?? "—" },
    { key: "description", header: "Açıklama", render: (r) => r.description ?? "—" },
    { key: "amount_try", header: "Tutar", align: "right", render: (r) => formatCurrency(r.amount_try), sortable: true, sortValue: (r) => toNumber(r.amount_try) },
    { key: "total_with_vat_try", header: "KDV Dahil", align: "right", render: (r) => formatCurrency(r.total_with_vat_try) },
    { key: "payment_due_date", header: "Vade", align: "right", render: (r) => formatDate(r.payment_due_date) },
    { key: "payment_status", header: "Durum", render: (r) => <StatusBadge status={r.payment_status} /> },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <div className="flex justify-end gap-2">
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
          <div className="flex gap-2">
            <Button variant="outline" onClick={downloadTemplate}>
              <Download className="h-4 w-4" /> Şablon
            </Button>
            <Button variant="outline" onClick={() => fileRef.current?.click()}>
              <Upload className="h-4 w-4" /> Excel'den İçe Aktar
            </Button>
            <Button variant="outline" className="border-accent text-accent" onClick={() => aiFileRef.current?.click()}>
              <Sparkles className="h-4 w-4" /> AI ile İçe Aktar
            </Button>
            <input
              ref={aiFileRef}
              type="file"
              accept=".xlsx"
              hidden
              onChange={(e) => {
                if (e.target.files?.[0]) setAiImportFile(e.target.files[0]);
                e.target.value = "";
              }}
            />
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx"
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

      <h2 className="mb-2 text-lg font-semibold text-primary">Bütçe & Gerçekleşen</h2>
      <DataTable columns={budgetColumns} rows={budget.data?.categories ?? []} loading={budget.loading} emptyMessage="Bu proje için henüz bütçe verisi yok." />
      {budget.data?.totals && (
        <div className="mt-1 flex flex-wrap items-center gap-x-8 gap-y-1 rounded-md bg-primary px-4 py-3 text-sm text-white">
          <span className="font-semibold">Toplam</span>
          <span className="tabular">Revize Bütçe: <b>{formatCurrency(budget.data.totals.revised_budget_try)}</b></span>
          <span className="tabular">Taahhüt: <b>{formatCurrency(budget.data.totals.committed_try)}</b></span>
          <span className="tabular">Faturalanan: <b>{formatCurrency(budget.data.totals.invoiced_try)}</b></span>
          <span className="tabular">Ödenen: <b>{formatCurrency(budget.data.totals.paid_try)}</b></span>
          <span className="tabular">Genel Kalan: <b>{formatCurrency(budget.data.totals.remaining_try)}</b></span>
        </div>
      )}

      <div className="mt-6 flex items-center justify-between">
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
        <DataTable columns={costColumns} rows={costs.data ?? []} loading={costs.loading} emptyMessage="Bu proje için henüz maliyet girişi yapılmamış." emptyAction={{ label: "Maliyet Ekle", onClick: () => setDrawerOpen(true) }} rowClassName={(r) => (r.payment_status === "overdue" ? "!bg-red-50" : "")} />
      </div>

      <CostDrawer
        open={drawerOpen}
        projectId={id!}
        editing={editingCost}
        onClose={() => { setDrawerOpen(false); setEditingCost(null); }}
        onSaved={() => { setEditingCost(null); refetchAll(); }}
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

function CostDrawer({ open, projectId, editing, onClose, onSaved }: { open: boolean; projectId: string; editing?: CostEntry | null; onClose: () => void; onSaved: () => void }) {
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
  };
  const [form, setForm] = useState<any>(empty);
  const [saving, setSaving] = useState(false);
  const [aiFields, setAiFields] = useState<Set<string>>(new Set());
  const [customCats, setCustomCats] = useState<{ id: string; name: string }[]>([]);
  const extractRef = useRef<HTMLInputElement>(null);
  const set = (k: string, v: string) => setForm((f: any) => ({ ...f, [k]: v }));

  // CR-001-G: prefill the form when editing an existing entry.
  useEffect(() => {
    if (open && editing) {
      setForm({
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
      });
    } else if (open && !editing) {
      setForm(empty);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

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
    <SideDrawer open={open} title={editing ? "Maliyet Düzenle" : "Maliyet Ekle"} onClose={onClose} onSave={save} saving={saving} dirty={!!form.amount_try || !!form.cost_category}>
      <div className="space-y-3">
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
        <div><Label>Alt Kategori</Label><Input value={form.subcategory} onChange={(e) => set("subcategory", e.target.value)} /></div>
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
