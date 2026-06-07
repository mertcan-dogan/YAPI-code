import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Card, CardBody, Input, Label, Select, Textarea } from "@/components/ui";
import { SideDrawer } from "@/components/SideDrawer";
import { StatusBadge } from "@/components/StatusBadge";
import { useFetch } from "@/hooks/useFetch";
import { apiPost, apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { Subcontractor } from "@/types";
import { formatCurrency, toNumber } from "@/utils/format";
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

export default function SubcontractorsPage() {
  const { id } = useParams();
  const { data, loading, refetch } = useFetch<Subcontractor[]>(`/projects/${id}/subcontractors`);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Subcontractor | null>(null);
  const subs = data ?? [];

  return (
    <div>
      <PageHeader title="Alt Yükleniciler" action={<Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Alt Yüklenici Ekle</Button>} />
      <div className="mb-4 flex flex-wrap gap-3">
        <Chip label="Toplam Sözleşme Değeri" value={formatCurrency(subs.reduce((s, x) => s + toNumber(x.revised_contract_try), 0))} />
        <Chip label="Toplam Ödenen" value={formatCurrency(subs.reduce((s, x) => s + toNumber(x.total_paid_try), 0))} />
        <Chip label="Toplam Kesinti" value={formatCurrency(subs.reduce((s, x) => s + toNumber(x.retention_held_try), 0))} />
      </div>

      {loading ? (
        <p className="text-sm text-text-secondary">Yükleniyor...</p>
      ) : subs.length === 0 ? (
        <Card><CardBody><EmptyState message="Bu proje için henüz alt yüklenici eklenmemiş." actionLabel="Alt Yüklenici Ekle" onAction={() => setOpen(true)} /></CardBody></Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {subs.map((s) => {
            const progress = toNumber(s.progress_pct);
            return (
              <Card key={s.id}>
                <CardBody>
                  <div className="flex items-start justify-between">
                    <h3 className="font-semibold text-primary">{s.name}</h3>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={s.status} />
                      <button onClick={() => { setEditing(s); setOpen(true); }} className="text-text-secondary hover:text-primary" aria-label="Düzenle">
                        <Pencil className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                  <p className="mt-1 text-xs text-text-secondary">{s.scope_of_work ?? "—"}</p>
                  <div className="mt-3 space-y-1 text-sm">
                    <Row label="Sözleşme" value={formatCurrency(s.revised_contract_try)} />
                    <Row label="Ödenen" value={formatCurrency(s.total_paid_try)} />
                    <Row label="Kesinti" value={formatCurrency(s.retention_held_try)} />
                  </div>
                  <div className="mt-3">
                    <div className="mb-1 flex justify-between text-xs text-text-secondary"><span>İlerleme</span><span>{progress.toFixed(0)}%</span></div>
                    <div className="h-2 overflow-hidden rounded-full bg-border">
                      <div className={progress > 90 ? "h-full bg-accent" : "h-full bg-success"} style={{ width: `${Math.min(progress, 100)}%` }} />
                    </div>
                  </div>
                </CardBody>
              </Card>
            );
          })}
        </div>
      )}
      <SubDrawer open={open} projectId={id!} editing={editing} onClose={() => { setOpen(false); setEditing(null); }} onSaved={() => { setEditing(null); refetch(); }} />
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return <div className="flex justify-between"><span className="text-text-secondary">{label}</span><span className="tabular font-medium">{value}</span></div>;
}

function SubDrawer({ open, projectId, editing, onClose, onSaved }: { open: boolean; projectId: string; editing?: Subcontractor | null; onClose: () => void; onSaved: () => void }) {
  const empty = { name: "", scope_of_work: "", contract_value_try: "", retention_pct: "10", contact_name: "", contact_phone: "", contact_email: "", notes: "", status: "active" };
  const [form, setForm] = useState<any>(empty);
  const [saving, setSaving] = useState(false);
  const set = (k: string, v: string) => setForm((f: any) => ({ ...f, [k]: v }));

  useEffect(() => {
    if (open && editing) {
      setForm({
        name: editing.name,
        scope_of_work: editing.scope_of_work ?? "",
        contract_value_try: editing.contract_value_try,
        retention_pct: editing.retention_pct,
        contact_name: editing.contact_name ?? "",
        contact_phone: editing.contact_phone ?? "",
        contact_email: editing.contact_email ?? "",
        notes: (editing as any).notes ?? "",
        status: editing.status,
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
        await apiPut(`/projects/${projectId}/subcontractors/${editing.id}`, form);
        toast.success("Alt yüklenici güncellendi");
      } else {
        await apiPost(`/projects/${projectId}/subcontractors`, form);
        toast.success("Alt yüklenici kaydedildi");
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
    <SideDrawer open={open} title={editing ? "Alt Yüklenici Düzenle" : "Alt Yüklenici Ekle"} onClose={onClose} onSave={save} saving={saving} dirty={!!form.name}>
      <div className="space-y-3">
        <div><Label required>Ad</Label><Input value={form.name} onChange={(e) => set("name", e.target.value)} /></div>
        <div><Label>Kapsam</Label><Textarea value={form.scope_of_work} onChange={(e) => set("scope_of_work", e.target.value)} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label required>Sözleşme Değeri (TRY)</Label><Input type="number" value={form.contract_value_try} onChange={(e) => set("contract_value_try", e.target.value)} /></div>
          <div><Label>Kesinti %</Label><Input type="number" value={form.retention_pct} onChange={(e) => set("retention_pct", e.target.value)} /></div>
        </div>
        {editing && (
          <div><Label>Durum</Label><Select value={form.status} onChange={(e) => set("status", e.target.value)}>
            <option value="active">Aktif</option>
            <option value="completed">Tamamlandı</option>
            <option value="disputed">İhtilaflı</option>
            <option value="terminated">Feshedildi</option>
          </Select></div>
        )}
        <div><Label>İrtibat Kişisi</Label><Input value={form.contact_name} onChange={(e) => set("contact_name", e.target.value)} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label>Telefon</Label><Input value={form.contact_phone} onChange={(e) => set("contact_phone", e.target.value)} /></div>
          <div><Label>E-posta</Label><Input value={form.contact_email} onChange={(e) => set("contact_email", e.target.value)} /></div>
        </div>
      </div>
    </SideDrawer>
  );
}
