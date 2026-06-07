import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Checkbox, Input, Label, Select } from "@/components/ui";
import { SideDrawer } from "@/components/SideDrawer";
import { useFetch } from "@/hooks/useFetch";
import { apiPost, apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { Equipment } from "@/types";
import { formatCurrency, formatDate } from "@/utils/format";
import { Pencil, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

export default function EquipmentPage() {
  const { id } = useParams();
  const { data, meta, loading, refetch } = useFetch<Equipment[]>(`/projects/${id}/equipment`);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Equipment | null>(null);

  const columns: Column<Equipment>[] = [
    { key: "equipment_name", header: "Ekipman", render: (r) => <span className="font-medium text-primary">{r.equipment_name}</span> },
    { key: "ownership_type", header: "Sahiplik", render: (r) => (r.ownership_type === "owned" ? "Şirkete Ait" : "Kiralık") },
    { key: "supplier_name", header: "Tedarikçi", render: (r) => r.supplier_name ?? "—" },
    { key: "rate_try", header: "Birim Ücret", align: "right", render: (r) => (r.rate_try ? `${formatCurrency(r.rate_try)} / ${r.rate_unit === "month" ? "ay" : "gün"}` : "—") },
    { key: "deployment_start", header: "Başlangıç", align: "right", render: (r) => formatDate(r.deployment_start) },
    { key: "deployment_end", header: "Bitiş", align: "right", render: (r) => formatDate(r.deployment_end) },
    { key: "duration_days", header: "Süre (gün)", align: "right", render: (r) => r.duration_days ?? "—" },
    { key: "total_cost_try", header: "Toplam Maliyet", align: "right", render: (r) => formatCurrency(r.total_cost_try) },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <div className="flex justify-end">
          <button onClick={() => { setEditing(r); setOpen(true); }} className="text-text-secondary hover:text-primary" aria-label="Düzenle">
            <Pencil className="h-4 w-4" />
          </button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Ekipman"
        subtitle={meta ? `Toplam Ekipman Maliyeti: ${formatCurrency(meta.total_cost_try)} · Bütçenin %${meta.pct_of_budget}'i` : undefined}
        action={<Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Ekipman Ekle</Button>}
      />
      <DataTable columns={columns} rows={data ?? []} loading={loading} emptyMessage="Bu proje için henüz ekipman kaydı yok." emptyAction={{ label: "Ekipman Ekle", onClick: () => setOpen(true) }} />
      <EquipDrawer open={open} projectId={id!} editing={editing} onClose={() => { setOpen(false); setEditing(null); }} onSaved={() => { setEditing(null); refetch(); }} />
    </div>
  );
}

function EquipDrawer({ open, projectId, editing, onClose, onSaved }: { open: boolean; projectId: string; editing?: Equipment | null; onClose: () => void; onSaved: () => void }) {
  const empty = { equipment_name: "", ownership_type: "rented", supplier_name: "", rate_try: "", rate_unit: "day", deployment_start: new Date().toISOString().slice(0, 10), deployment_end: "", fuel_maintenance_try: "0", notes: "", add_to_budget: true };
  const [form, setForm] = useState<any>(empty);
  const [saving, setSaving] = useState(false);
  const set = (k: string, v: any) => setForm((f: any) => ({ ...f, [k]: v }));

  useEffect(() => {
    if (open && editing) {
      setForm({
        equipment_name: editing.equipment_name,
        ownership_type: editing.ownership_type,
        supplier_name: editing.supplier_name ?? "",
        rate_try: editing.rate_try ?? "",
        rate_unit: editing.rate_unit ?? "day",
        deployment_start: editing.deployment_start,
        deployment_end: editing.deployment_end ?? "",
        fuel_maintenance_try: editing.fuel_maintenance_try ?? "0",
        notes: (editing as any).notes ?? "",
        add_to_budget: false, // editing does not re-create budget entries
      });
    } else if (open && !editing) {
      setForm(empty);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

  const save = async () => {
    setSaving(true);
    try {
      const body = { ...form, rate_try: form.rate_try || null, deployment_end: form.deployment_end || null };
      if (editing) {
        await apiPut(`/projects/${projectId}/equipment/${editing.id}`, body);
        toast.success("Ekipman güncellendi");
      } else {
        await apiPost(`/projects/${projectId}/equipment`, body);
        toast.success(form.add_to_budget ? "Ekipman kaydedildi ve bütçeye eklendi" : "Ekipman kaydedildi");
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
    <SideDrawer open={open} title={editing ? "Ekipman Düzenle" : "Ekipman Ekle"} onClose={onClose} onSave={save} saving={saving} dirty={!!form.equipment_name}>
      <div className="space-y-3">
        <div><Label required>Ekipman Adı</Label><Input value={form.equipment_name} onChange={(e) => set("equipment_name", e.target.value)} /></div>
        <div><Label required>Sahiplik</Label><Select value={form.ownership_type} onChange={(e) => set("ownership_type", e.target.value)}><option value="rented">Kiralık</option><option value="owned">Şirkete Ait</option></Select></div>
        {form.ownership_type === "rented" && <div><Label>Tedarikçi</Label><Input value={form.supplier_name} onChange={(e) => set("supplier_name", e.target.value)} /></div>}
        <div className="grid grid-cols-2 gap-3">
          <div><Label>Ücret (TRY)</Label><Input type="number" value={form.rate_try} onChange={(e) => set("rate_try", e.target.value)} /></div>
          <div><Label>Birim</Label><Select value={form.rate_unit} onChange={(e) => set("rate_unit", e.target.value)}><option value="day">Gün</option><option value="month">Ay</option></Select></div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label required>Başlangıç</Label><Input type="date" value={form.deployment_start} onChange={(e) => set("deployment_start", e.target.value)} /></div>
          <div><Label>Bitiş</Label><Input type="date" value={form.deployment_end} onChange={(e) => set("deployment_end", e.target.value)} /></div>
        </div>
        <div><Label>Yakıt / Bakım (TRY)</Label><Input type="number" value={form.fuel_maintenance_try} onChange={(e) => set("fuel_maintenance_try", e.target.value)} /></div>
        {!editing && (
          <div className="rounded-md border border-border bg-bg p-3">
            <Checkbox
              id="add_to_budget"
              checked={form.add_to_budget}
              onChange={(v) => set("add_to_budget", v)}
              label="Bu ekipman maliyetini bütçe takibine otomatik ekle"
            />
          </div>
        )}
      </div>
    </SideDrawer>
  );
}
