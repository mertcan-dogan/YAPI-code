import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Input, Label, Select, Textarea } from "@/components/ui";
import { SideDrawer } from "@/components/SideDrawer";
import { StatusBadge } from "@/components/StatusBadge";
import { INVOICE_TYPE_LABELS, STATUS_LABELS, VAT_RATES } from "@/constants";
import { useFetch } from "@/hooks/useFetch";
import { apiPost, apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { ClientInvoice } from "@/types";
import { daysUntil, formatCurrency, formatDate, toNumber } from "@/utils/format";
import { Pencil, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-4 py-2">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="tabular text-base font-semibold text-primary">{value}</div>
    </div>
  );
}

export default function InvoicesPage() {
  const { id } = useParams();
  const { data, loading, refetch } = useFetch<ClientInvoice[]>(`/projects/${id}/invoices`);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<ClientInvoice | null>(null);

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
      key: "actions",
      header: "",
      render: (r) => (
        <div className="flex items-center justify-end gap-2">
          {r.payment_status !== "paid" && (
            <Button
              variant="outline"
              className="px-2 py-1 text-xs"
              onClick={async (e) => {
                e.stopPropagation();
                try {
                  await apiPut(`/projects/${id}/invoices/${r.id}`, { date_received: new Date().toISOString().slice(0, 10), payment_status: "paid", amount_received_try: r.net_due_try });
                  toast.success("Tahsilat kaydedildi");
                  refetch();
                } catch (err: any) {
                  toast.error(err.message);
                }
              }}
            >
              Tahsil Edildi
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
      <DataTable columns={columns} rows={rows} loading={loading} emptyMessage="Bu proje için henüz hakediş faturası yok." emptyAction={{ label: "Fatura Ekle", onClick: () => setOpen(true) }} />
      <InvoiceDrawer open={open} projectId={id!} editing={editing} onClose={() => { setOpen(false); setEditing(null); }} onSaved={() => { setEditing(null); refetch(); }} />
    </div>
  );
}

function InvoiceDrawer({ open, projectId, editing, onClose, onSaved }: { open: boolean; projectId: string; editing?: ClientInvoice | null; onClose: () => void; onSaved: () => void }) {
  const empty = { invoice_number: "", invoice_date: new Date().toISOString().slice(0, 10), hakkedis_period: "", invoice_type: "hakedis", description: "", amount_try: "", vat_rate: "20", retention_amount_try: "0", due_date: "", payment_status: "unpaid", amount_received_try: "0", date_received: "" };
  const [form, setForm] = useState<any>(empty);
  const [saving, setSaving] = useState(false);
  const set = (k: string, v: string) => setForm((f: any) => ({ ...f, [k]: v }));

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
