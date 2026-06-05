import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Input, Label, Select } from "@/components/ui";
import { SideDrawer } from "@/components/SideDrawer";
import { useFetch } from "@/hooks/useFetch";
import { apiPost } from "@/lib/api";
import { toast } from "@/store/toast";
import type { Equipment } from "@/types";
import { formatCurrency, formatDate } from "@/utils/format";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";

export default function EquipmentPage() {
  const { id } = useParams();
  const { data, meta, loading, refetch } = useFetch<Equipment[]>(`/projects/${id}/equipment`);
  const [open, setOpen] = useState(false);

  const columns: Column<Equipment>[] = [
    { key: "equipment_name", header: "Ekipman", render: (r) => <span className="font-medium text-primary">{r.equipment_name}</span> },
    { key: "ownership_type", header: "Sahiplik", render: (r) => (r.ownership_type === "owned" ? "Şirkete Ait" : "Kiralık") },
    { key: "supplier_name", header: "Tedarikçi", render: (r) => r.supplier_name ?? "—" },
    { key: "rate_try", header: "Birim Ücret", align: "right", render: (r) => (r.rate_try ? `${formatCurrency(r.rate_try)} / ${r.rate_unit === "month" ? "ay" : "gün"}` : "—") },
    { key: "deployment_start", header: "Başlangıç", align: "right", render: (r) => formatDate(r.deployment_start) },
    { key: "deployment_end", header: "Bitiş", align: "right", render: (r) => formatDate(r.deployment_end) },
    { key: "duration_days", header: "Süre (gün)", align: "right", render: (r) => r.duration_days ?? "—" },
    { key: "total_cost_try", header: "Toplam Maliyet", align: "right", render: (r) => formatCurrency(r.total_cost_try) },
  ];

  return (
    <div>
      <PageHeader
        title="Ekipman"
        subtitle={meta ? `Toplam Ekipman Maliyeti: ${formatCurrency(meta.total_cost_try)} · Bütçenin %${meta.pct_of_budget}'i` : undefined}
        action={<Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Ekipman Ekle</Button>}
      />
      <DataTable columns={columns} rows={data ?? []} loading={loading} emptyMessage="Bu proje için henüz ekipman kaydı yok." emptyAction={{ label: "Ekipman Ekle", onClick: () => setOpen(true) }} />
      <EquipDrawer open={open} projectId={id!} onClose={() => setOpen(false)} onSaved={refetch} />
    </div>
  );
}

function EquipDrawer({ open, projectId, onClose, onSaved }: { open: boolean; projectId: string; onClose: () => void; onSaved: () => void }) {
  const empty = { equipment_name: "", ownership_type: "rented", supplier_name: "", rate_try: "", rate_unit: "day", deployment_start: new Date().toISOString().slice(0, 10), deployment_end: "", fuel_maintenance_try: "0", notes: "" };
  const [form, setForm] = useState<any>(empty);
  const [saving, setSaving] = useState(false);
  const set = (k: string, v: string) => setForm((f: any) => ({ ...f, [k]: v }));
  const save = async () => {
    setSaving(true);
    try {
      await apiPost(`/projects/${projectId}/equipment`, { ...form, rate_try: form.rate_try || null, deployment_end: form.deployment_end || null });
      toast.success("Ekipman kaydedildi");
      if (window.confirm("Bu ekipman maliyetini bütçe takibine eklemek ister misiniz?")) {
        // Optional: prompt acknowledged — PM adds via cost page manually (Section 4.8).
        toast.info("Bütçeye eklemek için Maliyet Ekle ekranını kullanın.");
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
    <SideDrawer open={open} title="Ekipman Ekle" onClose={onClose} onSave={save} saving={saving} dirty={!!form.equipment_name}>
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
      </div>
    </SideDrawer>
  );
}
