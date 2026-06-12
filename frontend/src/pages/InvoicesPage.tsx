import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Input, Label, Select, Textarea } from "@/components/ui";
import { SideDrawer } from "@/components/SideDrawer";
import { StatusBadge } from "@/components/StatusBadge";
import { INVOICE_TYPE_LABELS, STATUS_LABELS, VAT_RATES } from "@/constants";
import { useFetch } from "@/hooks/useFetch";
import { api, apiPost, apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { ClientInvoice } from "@/types";
import { daysUntil, formatCurrency, formatDate, toNumber } from "@/utils/format";
import { FileText, Pencil, Plus, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-2">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="tabular text-base font-semibold text-primary">{value}</div>
    </div>
  );
}

export default function InvoicesPage() {
  const { id } = useParams();
  const { data, loading, refetch, error } = useFetch<ClientInvoice[]>(`/projects/${id}/invoices`);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<ClientInvoice | null>(null);
  const [collecting, setCollecting] = useState<ClientInvoice | null>(null);

  const rows = data ?? [];
  const sum = (k: keyof ClientInvoice) => rows.reduce((s, r) => s + toNumber(r[k] as string), 0);

  const columns: Column<ClientInvoice>[] = [
    { key: "invoice_number", header: "Fatura No", render: (r) => <span className="font-medium text-primary">{r.invoice_number}</span> },
    { key: "invoice_date", header: "Tarih", render: (r) => formatDate(r.invoice_date), sortable: true },
    { key: "hakkedis_period", header: "Dönem", render: (r) => r.hakkedis_period ?? r.description ?? "—" },
    { key: "invoice_type", header: "Tür", render: (r) => INVOICE_TYPE_LABELS[r.invoice_type] ?? r.invoice_type },
    { key: "amount_try", header: "Tutar", align: "right", render: (r) => formatCurrency(r.amount_try) },
    { key: "vat_amount_try", header: "KDV", align: "right", render: (r) => formatCurrency(r.vat_amount_try) },
    { key: "retention_amount_try", header: "Kesinti", align: "right", render: (r) => formatCurrency(r.retention_amount_try) },
    { key: "net_due_try", header: "Net Tahsil", align: "right", render: (r) => formatCurrency(r.net_due_try) },
    { key: "due_date", header: "Vade", align: "right", render: (r) => <span className={daysUntil(r.due_date) < 0 && r.payment_status !== "paid" ? "text-danger" : ""}>{formatDate(r.due_date)}</span> },
    { key: "payment_status", header: "Durum", render: (r) => <StatusBadge status={r.payment_status} /> },
    { key: "outstanding_try", header: "Bakiye", align: "right", render: (r) => formatCurrency(r.outstanding_try) },
    {
      // CR-002-D: Gecikme (Gün) — empty unless overdue & unpaid.
      key: "gecikme",
      header: "Gecikme",
      align: "right",
      render: (r) => {
        const d = daysUntil(r.due_date);
        if (r.payment_status === "paid" || d >= 0) return <span className="text-text-disabled">—</span>;
        return <span className="font-medium text-danger">{Math.abs(d)} gün</span>;
      },
    },
    {
      key: "doc",
      header: "Belge",
      render: (r) =>
        r.document_url ? (
          <a href={r.document_url} target="_blank" rel="noreferrer" className="text-primary-light hover:text-primary" onClick={(e) => e.stopPropagation()}>
            <FileText className="h-4 w-4" />
          </a>
        ) : (
          <span className="text-text-disabled">—</span>
        ),
    },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <div className="flex items-center justify-end gap-2">
          {r.payment_status !== "paid" && (
            <Button variant="outline" className="px-2 py-1 text-xs" onClick={(e) => { e.stopPropagation(); setCollecting(r); }}>
              Tahsil Edildi İşaretle
            </Button>
          )}
          <button onClick={() => { setEditing(r); setOpen(true); }} className="text-text-secondary hover:text-primary" aria-label="Düzenle">
            <Pencil className="h-4 w-4" />
          </button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader title="Faturalar & Hakediş" action={<Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Fatura Ekle</Button>} />
      <div className="mb-4 flex flex-wrap gap-3">
        <Chip label="Toplam Faturalanan" value={formatCurrency(sum("amount_try"))} />
        <Chip label="Tahsil Edilen" value={formatCurrency(sum("amount_received_try"))} />
        <Chip label="Bekleyen" value={formatCurrency(sum("outstanding_try"))} />
        <Chip label="Kesinti" value={formatCurrency(sum("retention_amount_try"))} />
      </div>
      <DataTable columns={columns} rows={rows} loading={loading} error={error} onRetry={refetch} emptyMessage="Bu proje için henüz hakediş faturası yok." emptyAction={{ label: "Fatura Ekle", onClick: () => setOpen(true) }} />
      <InvoiceDrawer open={open} projectId={id!} editing={editing} onClose={() => { setOpen(false); setEditing(null); }} onSaved={() => { setEditing(null); refetch(); }} />
      {collecting && (
        <CollectModal
          projectId={id!}
          invoice={collecting}
          onClose={() => setCollecting(null)}
          onSaved={() => { setCollecting(null); refetch(); }}
        />
      )}
    </div>
  );
}

// CR-002-D: collection modal — asks amount + date; status auto-derived by backend.
function CollectModal({ projectId, invoice, onClose, onSaved }: { projectId: string; invoice: ClientInvoice; onClose: () => void; onSaved: () => void }) {
  const [amount, setAmount] = useState(invoice.net_due_try);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      await apiPut(`/projects/${projectId}/invoices/${invoice.id}`, { amount_received_try: amount, date_received: date });
      toast.success(toNumber(amount) >= toNumber(invoice.net_due_try) ? "Tahsilat kaydedildi" : "Kısmi ödeme kaydedildi");
      onSaved();
    } catch (e: any) {
      toast.error(e.message ?? "Kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-sm rounded-xl bg-surface p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-3 text-base font-semibold text-primary">Tahsilat Bilgisi</h3>
        <div className="space-y-3">
          <div><Label required>Tahsil Edilen Tutar (TRY)</Label><Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
          <div><Label required>Tahsilat Tarihi</Label><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
          <p className="text-xs text-text-secondary">Net tutar: {formatCurrency(invoice.net_due_try)}. Daha az girilirse durum "Kısmi Ödeme" olur.</p>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>İptal</Button>
          <Button onClick={save} loading={saving}>Kaydet</Button>
        </div>
      </div>
    </div>
  );
}

function InvoiceDrawer({ open, projectId, editing, onClose, onSaved }: { open: boolean; projectId: string; editing?: ClientInvoice | null; onClose: () => void; onSaved: () => void }) {
  const empty = { invoice_number: "", invoice_date: new Date().toISOString().slice(0, 10), hakkedis_period: "", invoice_type: "hakedis", description: "", amount_try: "", vat_rate: "20", retention_amount_try: "0", due_date: "", payment_status: "unpaid", amount_received_try: "0", date_received: "", document_url: "" };
  const [form, setForm] = useState<any>(empty);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const set = (k: string, v: string) => setForm((f: any) => ({ ...f, [k]: v }));

  // CR-002-D: upload the invoice PDF to Supabase Storage and store the URL.
  const uploadDoc = async (file: File) => {
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.post("/upload/document", fd);
      set("document_url", res.data.data.document_url);
      toast.success("Belge yüklendi");
    } catch (e: any) {
      toast.error(e.message ?? "Belge yüklenemedi");
    } finally {
      setUploading(false);
    }
  };

  // CR-001-G: prefill when editing (enables status revert).
  useEffect(() => {
    if (open && editing) {
      setForm({
        invoice_number: editing.invoice_number,
        invoice_date: editing.invoice_date,
        hakkedis_period: editing.hakkedis_period ?? "",
        invoice_type: editing.invoice_type,
        description: editing.description ?? "",
        amount_try: editing.amount_try,
        vat_rate: editing.vat_rate,
        retention_amount_try: editing.retention_amount_try,
        due_date: editing.due_date,
        payment_status: editing.payment_status,
        amount_received_try: editing.amount_received_try ?? "0",
        date_received: editing.date_received ?? "",
        document_url: editing.document_url ?? "",
      });
    } else if (open && !editing) {
      setForm(empty);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

  const save = async () => {
    setSaving(true);
    try {
      if (editing) {
        await apiPut(`/projects/${projectId}/invoices/${editing.id}`, {
          ...form,
          amount_eur: null,
          date_received: form.date_received || null,
        });
        toast.success("Fatura güncellendi");
      } else {
        await apiPost(`/projects/${projectId}/invoices`, { ...form, amount_eur: null });
        toast.success("Fatura kaydedildi");
      }
      setForm(empty);
      onSaved();
      onClose();
    } catch (e: any) {
      toast.error(e.message ?? "Kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  return (
    <SideDrawer open={open} title={editing ? "Fatura Düzenle" : "Fatura Ekle"} onClose={onClose} onSave={save} saving={saving} dirty={!!form.invoice_number}>
      <div className="space-y-3">
        <div><Label required>Fatura No</Label><Input value={form.invoice_number} onChange={(e) => set("invoice_number", e.target.value)} /></div>
        <div><Label required>Fatura Tarihi</Label><Input type="date" value={form.invoice_date} onChange={(e) => set("invoice_date", e.target.value)} /></div>
        <div><Label>Hakediş Dönemi</Label><Input value={form.hakkedis_period} onChange={(e) => set("hakkedis_period", e.target.value)} placeholder="Mayıs 2025 — 3. Hakediş" /></div>
        <div><Label>Fatura Türü</Label><Select value={form.invoice_type} onChange={(e) => set("invoice_type", e.target.value)}>{Object.entries(INVOICE_TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></div>
        <div><Label>Açıklama</Label><Textarea value={form.description} onChange={(e) => set("description", e.target.value)} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label required>Tutar (TRY)</Label><Input type="number" value={form.amount_try} onChange={(e) => set("amount_try", e.target.value)} /></div>
          <div><Label>KDV Oranı</Label><Select value={form.vat_rate} onChange={(e) => set("vat_rate", e.target.value)}>{VAT_RATES.map((v) => <option key={v} value={v}>%{v}</option>)}</Select></div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label>Kesinti Tutarı (TRY)</Label><Input type="number" value={form.retention_amount_try} onChange={(e) => set("retention_amount_try", e.target.value)} /></div>
          <div><Label required>Vade Tarihi</Label><Input type="date" value={form.due_date} onChange={(e) => set("due_date", e.target.value)} /></div>
        </div>
        <div>
          <Label>Fatura Belgesi (PDF)</Label>
          <div className="flex items-center gap-2">
            <Button variant="outline" type="button" loading={uploading} onClick={() => fileRef.current?.click()}>
              <Upload className="h-4 w-4" /> {form.document_url ? "Belgeyi Değiştir" : "PDF Yükle"}
            </Button>
            {form.document_url && (
              <a href={form.document_url} target="_blank" rel="noreferrer" className="text-sm text-primary-light hover:underline">Mevcut belge</a>
            )}
            <input ref={fileRef} type="file" accept="application/pdf" hidden onChange={(e) => e.target.files?.[0] && uploadDoc(e.target.files[0])} />
          </div>
        </div>
        {editing && (
          <div className="rounded-md border border-border bg-bg p-3">
            <Label>Ödeme Durumu</Label>
            <Select value={form.payment_status} onChange={(e) => set("payment_status", e.target.value)}>
              {["unpaid", "partial", "paid", "disputed"].map((s) => (
                <option key={s} value={s}>{STATUS_LABELS[s] ?? s}</option>
              ))}
            </Select>
            <div className="mt-2 grid grid-cols-2 gap-3">
              <div><Label>Tahsil Edilen (TRY)</Label><Input type="number" value={form.amount_received_try} onChange={(e) => set("amount_received_try", e.target.value)} /></div>
              <div><Label>Tahsilat Tarihi</Label><Input type="date" value={form.date_received} onChange={(e) => set("date_received", e.target.value)} /></div>
            </div>
            <p className="mt-1 text-xs text-text-secondary">"Tahsil Edildi"yi geri almak için durumu "Ödenmedi" veya "Kısmi Ödeme" yapın.</p>
          </div>
        )}
      </div>
    </SideDrawer>
  );
}
