import { DataTable, type Column } from "@/components/DataTable";
import { ExportMenu, type ExportColumn } from "@/components/ExportMenu";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Input, Label, Select, Textarea } from "@/components/ui";
import { SideDrawer } from "@/components/SideDrawer";
import { StatusBadge } from "@/components/StatusBadge";
import { COST_CATEGORY_OPTIONS } from "@/constants";
import { useFetch } from "@/hooks/useFetch";
import { apiPost, apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { Variation } from "@/types";
import { formatCurrency, formatDate, toNumber } from "@/utils/format";
import { FileText, Pencil, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

const STATUS_LABELS: Record<string, string> = { pending: "Beklemede", approved: "Onaylandı", rejected: "Reddedildi", disputed: "İhtilaflı" };

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-2">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="tabular text-base font-semibold text-primary">{value}</div>
    </div>
  );
}

export default function VariationsPage() {
  const { id } = useParams();
  const { data, meta, loading, refetch, error } = useFetch<Variation[]>(`/projects/${id}/variations`);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Variation | null>(null);
  const rows = data ?? [];

  const columns: Column<Variation>[] = [
    { key: "variation_number", header: "EK İş No", render: (r) => <span className="font-medium text-primary">{r.variation_number}</span> },
    { key: "title", header: "Başlık" },
    { key: "submitted_date", header: "Sunulma", render: (r) => formatDate(r.submitted_date) },
    { key: "value_try", header: "Talep Edilen", align: "right", render: (r) => formatCurrency(r.value_try) },
    { key: "approved_value_try", header: "Onaylanan", align: "right", render: (r) => (r.approved_value_try ? formatCurrency(r.approved_value_try) : "—") },
    { key: "cost_impact_try", header: "Maliyet Etkisi", align: "right", render: (r) => formatCurrency(r.cost_impact_try) },
    { key: "margin_impact_try", header: "Marj Etkisi", align: "right", render: (r) => <span className={toNumber(r.margin_impact_try) < 0 ? "text-danger" : "text-success"}>{formatCurrency(r.margin_impact_try)}</span> },
    { key: "status", header: "Durum", render: (r) => <span className="rounded-full bg-bg px-2 py-0.5 text-xs">{STATUS_LABELS[r.status] ?? r.status}</span> },
    { key: "doc", header: "Belge", render: (r) => (r.document_url ? <a href={r.document_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}><FileText className="h-4 w-4 text-primary-light" /></a> : "—") },
    { key: "actions", header: "", render: (r) => <button onClick={() => { setEditing(r); setOpen(true); }} className="text-text-secondary hover:text-primary"><Pencil className="h-4 w-4" /></button> },
  ];

  const nextNumber = `EK-${String(rows.length + 1).padStart(3, "0")}`;

  const exportColumns: ExportColumn<Variation>[] = [
    { header: "EK İş No", value: (r) => r.variation_number },
    { header: "Başlık", value: (r) => r.title },
    { header: "Sunulma", value: (r) => (r.submitted_date ? formatDate(r.submitted_date) : ""), type: "date" },
    { header: "Talep Edilen", value: (r) => toNumber(r.value_try), type: "currency" },
    { header: "Onaylanan", value: (r) => (r.approved_value_try ? toNumber(r.approved_value_try) : ""), type: "currency" },
    { header: "Maliyet Etkisi", value: (r) => toNumber(r.cost_impact_try), type: "currency" },
    { header: "Marj Etkisi", value: (r) => toNumber(r.margin_impact_try), type: "currency" },
    { header: "Durum", value: (r) => STATUS_LABELS[r.status] ?? r.status },
  ];

  return (
    <div>
      <PageHeader
        title="Ek İşler"
        action={
          <div className="flex items-center gap-2">
            <ExportMenu rows={rows} columns={exportColumns} filename="ek-isler" />
            <Button onClick={() => { setEditing(null); setOpen(true); }}><Plus className="h-4 w-4" /> Ek İş Ekle</Button>
          </div>
        }
      />
      {meta && (
        <div className="mb-4 flex flex-wrap gap-3">
          <Chip label="Toplam Talep Edilen" value={formatCurrency(meta.total_requested)} />
          <Chip label="Onaylanan" value={formatCurrency(meta.approved)} />
          <Chip label="Beklemede" value={formatCurrency(meta.pending)} />
          <Chip label="Reddedilen" value={formatCurrency(meta.rejected)} />
          <Chip label="Net Marj Etkisi" value={formatCurrency(meta.net_margin_impact)} />
        </div>
      )}
      <DataTable columns={columns} rows={rows} loading={loading} error={error} onRetry={refetch} emptyMessage="Bu proje için henüz ek iş yok." emptyAction={{ label: "Ek İş Ekle", onClick: () => setOpen(true) }} />
      <VariationDrawer open={open} projectId={id!} editing={editing} defaultNumber={nextNumber} onClose={() => { setOpen(false); setEditing(null); }} onSaved={() => { setEditing(null); refetch(); }} />
    </div>
  );
}

function VariationDrawer({ open, projectId, editing, defaultNumber, onClose, onSaved }: { open: boolean; projectId: string; editing?: Variation | null; defaultNumber: string; onClose: () => void; onSaved: () => void }) {
  const empty = { variation_number: defaultNumber, title: "", description: "", submitted_date: new Date().toISOString().slice(0, 10), status: "pending", value_try: "", cost_impact_try: "0", approved_value_try: "", approved_date: "", cost_category: "", document_url: "" };
  const [form, setForm] = useState<any>(empty);
  const [saving, setSaving] = useState(false);
  const set = (k: string, v: string) => setForm((f: any) => ({ ...f, [k]: v }));

  useEffect(() => {
    if (open && editing) {
      setForm({
        variation_number: editing.variation_number, title: editing.title, description: editing.description ?? "",
        submitted_date: editing.submitted_date, status: editing.status, value_try: editing.value_try,
        cost_impact_try: editing.cost_impact_try, approved_value_try: editing.approved_value_try ?? "",
        approved_date: editing.approved_date ?? "", cost_category: editing.cost_category ?? "", document_url: editing.document_url ?? "",
      });
    } else if (open && !editing) setForm({ ...empty, variation_number: defaultNumber });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

  const save = async () => {
    if (form.status === "approved" && !form.approved_date) { toast.error("Onaylandı durumunda onay tarihi zorunludur"); return; }
    setSaving(true);
    try {
      const body = { ...form, approved_value_try: form.approved_value_try || null, approved_date: form.approved_date || null, cost_category: form.cost_category || null };
      if (editing) await apiPut(`/projects/${projectId}/variations/${editing.id}`, body);
      else await apiPost(`/projects/${projectId}/variations`, body);
      toast.success(editing ? "Ek iş güncellendi" : "Ek iş kaydedildi");
      onSaved();
      onClose();
    } catch (e: any) {
      toast.error(e.message ?? "Kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  return (
    <SideDrawer open={open} title={editing ? "Ek İş Düzenle" : "Ek İş Ekle"} onClose={onClose} onSave={save} saving={saving} dirty={!!form.title}>
      <div className="space-y-3">
        <div><Label required>EK İş No</Label><Input value={form.variation_number} onChange={(e) => set("variation_number", e.target.value)} /></div>
        <div><Label required>Başlık</Label><Input value={form.title} onChange={(e) => set("title", e.target.value)} /></div>
        <div><Label>Açıklama</Label><Textarea value={form.description} onChange={(e) => set("description", e.target.value)} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label required>Sunulma Tarihi</Label><Input type="date" value={form.submitted_date} onChange={(e) => set("submitted_date", e.target.value)} /></div>
          <div><Label required>Talep Edilen (TRY)</Label><Input type="number" value={form.value_try} onChange={(e) => set("value_try", e.target.value)} /></div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label>Maliyet Etkisi (TRY)</Label><Input type="number" value={form.cost_impact_try} onChange={(e) => set("cost_impact_try", e.target.value)} /></div>
          <div><Label>Bütçe Kategorisi</Label><Select value={form.cost_category} onChange={(e) => set("cost_category", e.target.value)}><option value="">—</option>{COST_CATEGORY_OPTIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</Select></div>
        </div>
        <div><Label>Durum</Label><Select value={form.status} onChange={(e) => set("status", e.target.value)}>{Object.entries(STATUS_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></div>
        {form.status === "approved" && (
          <div className="grid grid-cols-2 gap-3">
            <div><Label required>Onay Tarihi</Label><Input type="date" value={form.approved_date} onChange={(e) => set("approved_date", e.target.value)} /></div>
            <div><Label>Onaylanan Değer (TRY)</Label><Input type="number" value={form.approved_value_try} onChange={(e) => set("approved_value_try", e.target.value)} /></div>
          </div>
        )}
      </div>
    </SideDrawer>
  );
}
