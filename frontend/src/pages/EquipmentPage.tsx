import { DataTable, type Column } from "@/components/DataTable";
import { ExportMenu, type ExportColumn } from "@/components/ExportMenu";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Checkbox, Input, Label, Modal, Select } from "@/components/ui";
import { SideDrawer } from "@/components/SideDrawer";
import { useFetch } from "@/hooks/useFetch";
import { api, apiPost, apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { Equipment } from "@/types";
import { formatCurrency, formatDate, toNumber } from "@/utils/format";
import { ImagePlus, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

export default function EquipmentPage() {
  const { id } = useParams();
  const { data, meta, loading, refetch, error } = useFetch<Equipment[]>(`/projects/${id}/equipment`);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Equipment | null>(null);
  const [detail, setDetail] = useState<Equipment | null>(null);

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
          <button onClick={(e) => { e.stopPropagation(); setEditing(r); setOpen(true); }} className="text-text-secondary hover:text-primary" aria-label="Düzenle">
            <Pencil className="h-4 w-4" />
          </button>
        </div>
      ),
    },
  ];

  const exportColumns: ExportColumn<Equipment>[] = [
    { header: "Ekipman", value: (r) => r.equipment_name },
    { header: "Sahiplik", value: (r) => (r.ownership_type === "owned" ? "Şirkete Ait" : "Kiralık") },
    { header: "Tedarikçi", value: (r) => r.supplier_name ?? "" },
    { header: "Birim Ücret", value: (r) => (r.rate_try ? toNumber(r.rate_try) : ""), type: "currency" },
    { header: "Birim", value: (r) => (r.rate_unit ? (r.rate_unit === "month" ? "Ay" : "Gün") : "") },
    { header: "Başlangıç", value: (r) => (r.deployment_start ? formatDate(r.deployment_start) : ""), type: "date" },
    { header: "Bitiş", value: (r) => (r.deployment_end ? formatDate(r.deployment_end) : ""), type: "date" },
    { header: "Süre (gün)", value: (r) => r.duration_days ?? "", type: "number" },
    { header: "Toplam Maliyet", value: (r) => toNumber(r.total_cost_try), type: "currency" },
  ];

  return (
    <div>
      <PageHeader
        title="Ekipman"
        subtitle={meta ? `Toplam Ekipman Maliyeti: ${formatCurrency(meta.total_cost_try)} · Bütçenin %${meta.pct_of_budget}'i` : undefined}
        action={
          <div className="flex items-center gap-2">
            <ExportMenu rows={data ?? []} columns={exportColumns} filename="ekipman" />
            <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Ekipman Ekle</Button>
          </div>
        }
      />
      <DataTable columns={columns} rows={data ?? []} loading={loading} error={error} onRetry={refetch} onRowClick={(r) => setDetail(r)} emptyMessage="Bu proje için henüz ekipman kaydı yok." emptyAction={{ label: "Ekipman Ekle", onClick: () => setOpen(true) }} />
      <EquipDrawer open={open} projectId={id!} editing={editing} onClose={() => { setOpen(false); setEditing(null); }} onSaved={() => { setEditing(null); refetch(); }} onPhotosChanged={refetch} />
      <EquipDetailModal
        equipment={detail}
        projectId={id!}
        onClose={() => setDetail(null)}
        onChanged={refetch}
        onEdit={(eq) => { setDetail(null); setEditing(eq); setOpen(true); }}
      />
    </div>
  );
}

// Reusable equipment photo gallery — view, upload (PNG/JPEG ≤5MB) and
// remove. Mirrors the company-logo upload path. `equipmentId` is null while a
// new record is still unsaved (photos become available after the first save).
function PhotoGallery({ projectId, equipmentId, photos, onChange }: { projectId: string; equipmentId: string | null; photos: string[]; onChange: (eq: Equipment) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const pick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (!f || !equipmentId) return;
    if (!["image/png", "image/jpeg"].includes(f.type)) {
      toast.error("Sadece PNG veya JPEG yükleyebilirsiniz");
      return;
    }
    if (f.size > 5 * 1024 * 1024) {
      toast.error("Fotoğraf en fazla 5MB olabilir");
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const res = await api.post(`/projects/${projectId}/equipment/${equipmentId}/photos`, fd);
      toast.success("Fotoğraf yüklendi");
      onChange(res.data.data);
    } catch (err: any) {
      toast.error(err?.message ?? "Fotoğraf yüklenemedi");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (url: string) => {
    if (!equipmentId || !window.confirm("Bu fotoğrafı kaldırmak istediğinize emin misiniz?")) return;
    setBusy(true);
    try {
      const res = await api.delete(`/projects/${projectId}/equipment/${equipmentId}/photos`, { data: { url } });
      toast.success("Fotoğraf kaldırıldı");
      onChange(res.data.data);
    } catch (err: any) {
      toast.error(err?.message ?? "Fotoğraf kaldırılamadı");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <Label>Fotoğraflar</Label>
        <Button
          type="button"
          variant="outline"
          className="px-2 py-1 text-xs"
          disabled={!equipmentId || busy}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ImagePlus className="h-3.5 w-3.5" />} Fotoğraf Ekle
        </Button>
      </div>
      {!equipmentId ? (
        <p className="rounded-md border border-dashed border-border bg-bg px-3 py-2 text-xs text-text-secondary">
          Fotoğraf eklemek için önce ekipmanı kaydedin.
        </p>
      ) : photos.length === 0 ? (
        <p className="rounded-md border border-dashed border-border bg-bg px-3 py-4 text-center text-xs text-text-secondary">
          Henüz fotoğraf yok. PNG veya JPEG (max 5MB) ekleyin.
        </p>
      ) : (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {photos.map((url) => (
            <div key={url} className="group relative aspect-square overflow-hidden rounded-lg border border-border bg-bg">
              <img src={url} alt="Ekipman fotoğrafı" className="h-full w-full object-cover" />
              <button
                type="button"
                onClick={() => remove(url)}
                disabled={busy}
                aria-label="Fotoğrafı kaldır"
                className="absolute right-1 top-1 rounded-md bg-black/55 p-1 text-white opacity-0 transition-opacity hover:bg-danger group-hover:opacity-100"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
      <input ref={inputRef} type="file" accept="image/png,image/jpeg" className="hidden" onChange={pick} />
    </div>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-text-secondary">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium text-text-primary">{value}</dd>
    </div>
  );
}

function EquipDetailModal({ equipment, projectId, onClose, onChanged, onEdit }: { equipment: Equipment | null; projectId: string; onClose: () => void; onChanged: () => void; onEdit: (eq: Equipment) => void }) {
  const [eq, setEq] = useState<Equipment | null>(equipment);
  useEffect(() => { setEq(equipment); }, [equipment]);
  if (!eq) return null;

  const updated = (next: Equipment) => { setEq(next); onChanged(); };

  return (
    <Modal
      open={!!equipment}
      title={eq.equipment_name}
      onClose={onClose}
      size="lg"
      footer={<><Button variant="ghost" onClick={onClose}>Kapat</Button><Button onClick={() => onEdit(eq)}><Pencil className="h-4 w-4" /> Düzenle</Button></>}
    >
      <div className="space-y-5">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
          <Field label="Sahiplik" value={eq.ownership_type === "owned" ? "Şirkete Ait" : "Kiralık"} />
          <Field label="Tedarikçi" value={eq.supplier_name ?? "—"} />
          <Field label="Birim Ücret" value={eq.rate_try ? `${formatCurrency(eq.rate_try)} / ${eq.rate_unit === "month" ? "ay" : "gün"}` : "—"} />
          <Field label="Başlangıç" value={formatDate(eq.deployment_start)} />
          <Field label="Bitiş" value={formatDate(eq.deployment_end)} />
          <Field label="Süre (gün)" value={eq.duration_days ?? "—"} />
          <Field label="Yakıt / Bakım" value={formatCurrency(eq.fuel_maintenance_try)} />
          <Field label="Toplam Maliyet" value={formatCurrency(eq.total_cost_try)} />
        </dl>
        {eq.notes && (
          <div>
            <dt className="text-xs text-text-secondary">Notlar</dt>
            <dd className="mt-0.5 whitespace-pre-wrap text-sm text-text-primary">{eq.notes}</dd>
          </div>
        )}
        <div className="border-t border-border pt-4">
          <PhotoGallery projectId={projectId} equipmentId={eq.id} photos={eq.photo_urls ?? []} onChange={updated} />
        </div>
      </div>
    </Modal>
  );
}

function EquipDrawer({ open, projectId, editing, onClose, onSaved, onPhotosChanged }: { open: boolean; projectId: string; editing?: Equipment | null; onClose: () => void; onSaved: () => void; onPhotosChanged?: () => void }) {
  const empty = { equipment_name: "", ownership_type: "rented", supplier_name: "", rate_try: "", rate_unit: "day", deployment_start: new Date().toISOString().slice(0, 10), deployment_end: "", fuel_maintenance_try: "0", notes: "", add_to_budget: true };
  const [form, setForm] = useState<any>(empty);
  const [photos, setPhotos] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const set = (k: string, v: any) => setForm((f: any) => ({ ...f, [k]: v }));

  // CR-006-E: süre + tahmini toplam maliyet anlık hesaplanır (tarihler değiştikçe).
  const preview = computeEquipmentCost(form);

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
      setPhotos(editing.photo_urls ?? []);
    } else if (open && !editing) {
      setForm(empty);
      setPhotos([]);
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
        <div><Label>Notlar</Label><Input value={form.notes} onChange={(e) => set("notes", e.target.value)} /></div>

        {/* Photo control. New records upload after the first save. */}
        <div className="border-t border-border pt-3">
          <PhotoGallery
            projectId={projectId}
            equipmentId={editing?.id ?? null}
            photos={photos}
            onChange={(eq) => { setPhotos(eq.photo_urls ?? []); onPhotosChanged?.(); }}
          />
        </div>

        {/* Anlık hesaplanan süre + tahmini toplam maliyet */}
        <div className="rounded-md border border-border bg-bg p-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-text-secondary">Süre</span>
            <span className="font-medium text-text-primary">
              {form.ownership_type === "owned"
                ? "—"
                : preview.hasDates
                  ? `${preview.units} ${form.rate_unit === "month" ? "ay" : "gün"}`
                  : "Bitiş tarihi girin"}
            </span>
          </div>
          <div className="mt-1 flex items-center justify-between">
            <span className="text-text-secondary">Tahmini Toplam Maliyet</span>
            <span className="font-bold text-primary">{formatCurrency(preview.total)}</span>
          </div>
        </div>

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

// CR-006-E: ekipman maliyet önizlemesi (backend app/calculations/equipment.py ile aynı mantık).
//   Kiralık (gün):  ücret × (bitiş - başlangıç + 1 gün) + yakıt/bakım
//   Kiralık (ay):   ücret × max(1, ay) + yakıt/bakım
//   Şirkete ait:    yalnızca yakıt/bakım
export function computeEquipmentCost(form: {
  ownership_type: string;
  rate_try: string | number;
  rate_unit: string;
  deployment_start: string;
  deployment_end: string;
  fuel_maintenance_try: string | number;
}): { units: number; total: number; hasDates: boolean } {
  const fuel = Number(form.fuel_maintenance_try) || 0;
  const hasDates = Boolean(form.deployment_start && form.deployment_end);
  if (form.ownership_type === "owned" || !hasDates) {
    return { units: 0, total: fuel, hasDates };
  }
  const start = new Date(form.deployment_start);
  const end = new Date(form.deployment_end);
  const days = Math.max(Math.floor((end.getTime() - start.getTime()) / 86400000) + 1, 0);
  const units = form.rate_unit === "month" ? Math.max(1, Math.round(days / 30)) : days;
  const rate = Number(form.rate_try) || 0;
  return { units, total: rate * units + fuel, hasDates };
}
