import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Card, CardBody, Input, Label, Select } from "@/components/ui";
import { SideDrawer } from "@/components/SideDrawer";
import { COST_CATEGORIES, ROLE_LABELS, VAT_RATES } from "@/constants";
import { useFetch } from "@/hooks/useFetch";
import { api, apiDelete, apiPost, apiPut } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import type { User } from "@/types";
import { formatDateTime } from "@/utils/format";
import { useRef, useState } from "react";
import { Navigate } from "react-router-dom";

const TABS = [
  { key: "company", label: "Şirket" },
  { key: "users", label: "Kullanıcılar" },
  { key: "templates", label: "Şablonlar" },
  { key: "notifications", label: "Bildirimler" },
];

export default function SettingsPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState("company");
  if (user && user.role !== "director") return <Navigate to="/dashboard" replace />;

  return (
    <div>
      <PageHeader title="Ayarlar" />
      <div className="mb-4 flex gap-1 rounded-md border border-border p-0.5">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)} className={cn("rounded px-4 py-1.5 text-sm", tab === t.key ? "bg-primary text-white" : "text-text-secondary")}>{t.label}</button>
        ))}
      </div>
      {tab === "company" && <CompanyTab />}
      {tab === "users" && <UsersTab />}
      {tab === "templates" && <TemplatesTab />}
      {tab === "notifications" && <NotificationsTab />}
    </div>
  );
}

// CR-006-D: şirket logosu yükleme bölümü.
function CompanyLogoSection({ logoUrl, onChange }: { logoUrl: string | null; onChange: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  const pick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (!["image/png", "image/jpeg"].includes(f.type)) {
      toast.error("Sadece PNG veya JPEG yükleyebilirsiniz");
      return;
    }
    if (f.size > 2 * 1024 * 1024) {
      toast.error("Logo en fazla 2MB olabilir");
      return;
    }
    setFile(f);
    setPreview(URL.createObjectURL(f));
  };

  const save = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      await api.post("/settings/company/logo", fd);
      toast.success("Logo yüklendi");
      setFile(null);
      setPreview(null);
      onChange();
    } catch (e: any) {
      toast.error(e?.response?.data?.error?.message ?? "Logo yüklenemedi");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await apiDelete("/settings/company/logo");
      toast.success("Logo kaldırıldı");
      setPreview(null);
      setFile(null);
      onChange();
    } catch (e: any) {
      toast.error(e?.response?.data?.error?.message ?? "Logo kaldırılamadı");
    } finally {
      setBusy(false);
    }
  };

  const shown = preview ?? logoUrl;

  // Transparency checkerboard so transparent (no-background) PNG logos are
  // actually visible instead of disappearing against a white box.
  const checkerboard: React.CSSProperties = {
    backgroundImage:
      "linear-gradient(45deg,#e2e8f0 25%,transparent 25%),linear-gradient(-45deg,#e2e8f0 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#e2e8f0 75%),linear-gradient(-45deg,transparent 75%,#e2e8f0 75%)",
    backgroundSize: "14px 14px",
    backgroundPosition: "0 0, 0 7px, 7px -7px, -7px 0",
    backgroundColor: "#fff",
  };

  return (
    <div className="rounded-md border border-border bg-bg p-3">
      <Label>Şirket Logosu</Label>
      <div className="mt-2 flex items-center gap-4">
        {/* Single click target: the whole box opens the file picker. */}
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          title={shown ? "Logoyu değiştirmek için tıklayın" : "Logo yüklemek için tıklayın"}
          className={cn(
            "group relative flex h-[60px] w-[120px] items-center justify-center overflow-hidden rounded border transition-colors",
            shown ? "border-border" : "border-dashed border-border hover:bg-surface"
          )}
          style={shown ? checkerboard : undefined}
        >
          {shown ? (
            <img src={shown} alt="Şirket logosu" className="max-h-full max-w-full object-contain p-1" />
          ) : (
            <span className="px-1 text-center text-[11px] text-text-secondary">Logo yüklemek için tıklayın</span>
          )}
        </button>
        <div className="flex flex-col gap-2">
          <div className="flex gap-2">
            {logoUrl && !preview && (
              <Button type="button" variant="danger" onClick={remove} loading={busy}>Logoyu Kaldır</Button>
            )}
            {file && <Button type="button" onClick={save} loading={busy}>Kaydet</Button>}
          </div>
          <span className="text-[11px] text-text-secondary">PNG veya JPEG, max 2MB — logoyu seçmek için kutuya tıklayın</span>
        </div>
      </div>
      <input ref={inputRef} type="file" accept="image/png,image/jpeg" className="hidden" onChange={pick} />
    </div>
  );
}

function CompanyTab() {
  const { data, refetch } = useFetch<any>("/settings/company");
  const [form, setForm] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const f = form ?? data ?? {};
  const set = (k: string, v: any) => setForm({ ...(form ?? data), [k]: v });

  const save = async () => {
    setSaving(true);
    try {
      await apiPut("/settings/company", form ?? {});
      toast.success("Şirket ayarları kaydedildi");
      setForm(null);
      refetch();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="max-w-2xl">
      <CardBody className="space-y-3">
        <CompanyLogoSection logoUrl={data?.logo_url ?? null} onChange={refetch} />
        <div><Label>Şirket Adı</Label><Input value={f.name ?? ""} onChange={(e) => set("name", e.target.value)} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label>Vergi No</Label><Input value={f.tax_number ?? ""} onChange={(e) => set("tax_number", e.target.value)} /></div>
          <div><Label>Telefon</Label><Input value={f.phone ?? ""} onChange={(e) => set("phone", e.target.value)} /></div>
        </div>
        <div><Label>Adres</Label><Input value={f.address ?? ""} onChange={(e) => set("address", e.target.value)} /></div>
        <div className="grid grid-cols-3 gap-3">
          <div><Label>Varsayılan KDV %</Label><Select value={f.vat_rate_default ?? 20} onChange={(e) => set("vat_rate_default", Number(e.target.value))}>{VAT_RATES.map((v) => <option key={v} value={v}>%{v}</option>)}</Select></div>
          <div><Label>Varsayılan Kesinti %</Label><Input type="number" value={f.retention_default_pct ?? 10} onChange={(e) => set("retention_default_pct", Number(e.target.value))} /></div>
          <div><Label>Para Birimi</Label><Select value={f.default_currency ?? "TRY"} onChange={(e) => set("default_currency", e.target.value)}><option>TRY</option><option>EUR</option><option>USD</option><option>GBP</option></Select></div>
        </div>
        <div><Label>Mali Yıl Başlangıç Ayı</Label><Input type="number" min={1} max={12} value={f.fiscal_year_start_month ?? 1} onChange={(e) => set("fiscal_year_start_month", Number(e.target.value))} /></div>

        {/* CR-003-J: approval thresholds */}
        <div className="mt-2 rounded-md border border-border bg-bg p-3">
          <h3 className="mb-2 text-sm font-semibold text-primary">Onay Eşikleri</h3>
          <label className="flex items-center justify-between py-1 text-sm">
            <span>Onay iş akışı aktif</span>
            <input type="checkbox" className="h-4 w-4 accent-[var(--color-primary)]" checked={f.approvals_enabled ?? true} onChange={(e) => set("approvals_enabled", e.target.checked)} />
          </label>
          <div className="py-1"><Label>Maliyet Girişi Onay Eşiği (TRY)</Label><Input type="number" value={f.cost_approval_threshold_try ?? 500000} onChange={(e) => set("cost_approval_threshold_try", Number(e.target.value))} /></div>
          <label className="flex items-center justify-between py-1 text-sm">
            <span>Bütçe değişikliği onay zorunlu</span>
            <input type="checkbox" className="h-4 w-4 accent-[var(--color-primary)]" checked={f.require_budget_approval ?? true} onChange={(e) => set("require_budget_approval", e.target.checked)} />
          </label>
          <label className="flex items-center justify-between py-1 text-sm">
            <span>Alt yüklenici sözleşmesi değişikliği onay zorunlu</span>
            <input type="checkbox" className="h-4 w-4 accent-[var(--color-primary)]" checked={f.require_subcontractor_approval ?? true} onChange={(e) => set("require_subcontractor_approval", e.target.checked)} />
          </label>
          {/* CR-004-N: deletion + variation triggers */}
          <label className="flex items-center justify-between py-1 text-sm">
            <span>Kayıt silme onay zorunlu</span>
            <input type="checkbox" className="h-4 w-4 accent-[var(--color-primary)]" checked={f.require_deletion_approval ?? true} onChange={(e) => set("require_deletion_approval", e.target.checked)} />
          </label>
          <label className="flex items-center justify-between py-1 text-sm">
            <span>Ek iş onayı onay zorunlu</span>
            <input type="checkbox" className="h-4 w-4 accent-[var(--color-primary)]" checked={f.require_variation_approval ?? true} onChange={(e) => set("require_variation_approval", e.target.checked)} />
          </label>
        </div>

        <div className="pt-2"><Button onClick={save} loading={saving} disabled={!form}>Kaydet</Button></div>
      </CardBody>
    </Card>
  );
}

function UsersTab() {
  const { data, loading, refetch } = useFetch<User[]>("/settings/users");
  const { user: me } = useAuth();
  const [open, setOpen] = useState(false);

  const toggleActive = async (u: User) => {
    try {
      await apiPut(`/settings/users/${u.id}`, { is_active: !u.is_active });
      toast.success("Güncellendi");
      refetch();
    } catch (e: any) {
      toast.error(e.message);
    }
  };
  const changeRole = async (u: User, role: string) => {
    try {
      await apiPut(`/settings/users/${u.id}`, { role });
      toast.success("Rol güncellendi");
      refetch();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const columns: Column<User>[] = [
    { key: "full_name", header: "Ad", render: (u) => <span className="font-medium text-primary">{u.full_name}</span> },
    { key: "email", header: "E-posta" },
    { key: "role", header: "Rol", render: (u) => <Select value={u.role} onChange={(e) => changeRole(u, e.target.value)} className="w-40">{Object.entries(ROLE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select> },
    { key: "last_login_at", header: "Son Giriş", render: (u) => formatDateTime(u.last_login_at) },
    { key: "is_active", header: "Aktif", render: (u) => (
      <button onClick={() => toggleActive(u)} disabled={u.id === me?.id} className={cn("rounded-full px-2 py-0.5 text-xs", u.is_active ? "bg-green-50 text-success" : "bg-red-50 text-danger")}>{u.is_active ? "Aktif" : "Pasif"}</button>
    ) },
  ];

  return (
    <div>
      <div className="mb-3 flex justify-end"><Button onClick={() => setOpen(true)}>Kullanıcı Davet Et</Button></div>
      <DataTable columns={columns} rows={data ?? []} loading={loading} emptyMessage="Henüz kullanıcı yok." />
      <InviteDrawer open={open} onClose={() => setOpen(false)} onSaved={refetch} />
    </div>
  );
}

function InviteDrawer({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ email: "", full_name: "", role: "project_manager" });
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      await apiPost("/settings/users", form);
      toast.success("Davet gönderildi");
      onSaved();
      onClose();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <SideDrawer open={open} title="Kullanıcı Davet Et" onClose={onClose} onSave={save} saving={saving} saveLabel="Davet Gönder">
      <div className="space-y-3">
        <div><Label required>Ad Soyad</Label><Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></div>
        <div><Label required>E-posta</Label><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
        <div><Label required>Rol</Label><Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{Object.entries(ROLE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></div>
      </div>
    </SideDrawer>
  );
}

// CR-003-L: budget templates list (presets + company custom) with a real
// per-category percentage editor (must total 100%) and delete for custom ones.
type Template = { id: string; name: string; is_preset: boolean; distribution: Record<string, number> };

function TemplatesTab() {
  const { data, refetch } = useFetch<Template[]>("/budget-templates");
  const [name, setName] = useState("");
  const [dist, setDist] = useState<Record<string, number>>({});
  const [creating, setCreating] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const total = Object.values(dist).reduce((s, v) => s + (Number(v) || 0), 0);
  const totalRounded = Math.round(total * 100) / 100;
  const isHundred = totalRounded === 100;

  const setPct = (cat: string, value: string) => {
    const n = value === "" ? 0 : Number(value);
    setDist((d) => ({ ...d, [cat]: Number.isFinite(n) ? n : 0 }));
  };

  const create = async () => {
    if (!name.trim() || !isHundred) return;
    setCreating(true);
    try {
      const distribution = Object.fromEntries(Object.entries(dist).filter(([, v]) => Number(v) > 0));
      await apiPost("/budget-templates", { name: name.trim(), distribution });
      toast.success("Şablon oluşturuldu");
      setName("");
      setDist({});
      refetch();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setCreating(false);
    }
  };

  const remove = async (t: Template) => {
    if (!confirm(`"${t.name}" şablonunu silmek istediğinize emin misiniz?`)) return;
    setDeletingId(t.id);
    try {
      await apiDelete(`/budget-templates/${t.id}`);
      toast.success("Şablon silindi");
      refetch();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <Card className="max-w-3xl">
      <CardBody className="space-y-3">
        <p className="text-sm text-text-secondary">Hazır şablonlar ve şirketinize özel şablonlar. Proje sihirbazında "Şablondan Yükle" ile uygulanır.</p>
        {(data ?? []).map((t) => (
          <div key={t.id} className="rounded-md border border-border p-3">
            <div className="flex items-center justify-between">
              <span className="font-medium text-primary">{t.name}</span>
              {t.is_preset ? (
                <span className="rounded bg-navy-50 px-2 py-0.5 text-[10px] text-primary-light">Hazır</span>
              ) : (
                <Button type="button" variant="danger" onClick={() => remove(t)} loading={deletingId === t.id}>Sil</Button>
              )}
            </div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary">
              {Object.entries(t.distribution).map(([cat, pct]) => (
                <span key={cat}>{COST_CATEGORIES[cat] ?? cat}: %{pct}</span>
              ))}
            </div>
          </div>
        ))}

        {/* New custom template — name + per-category percentages totalling 100%. */}
        <div className="border-t border-border pt-3">
          <h3 className="mb-2 text-sm font-semibold text-primary">Yeni Şablon</h3>
          <div className="mb-3"><Label>Şablon Adı</Label><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Örn. Tünel Projesi" /></div>
          <Label>Maliyet Kategorisi Dağılımı (%)</Label>
          <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {Object.entries(COST_CATEGORIES).map(([key, label]) => (
              <div key={key} className="flex items-center gap-2">
                <span className="flex-1 truncate text-xs text-text-secondary" title={label}>{label}</span>
                <Input
                  type="number"
                  min={0}
                  max={100}
                  className="w-20"
                  value={dist[key] ?? ""}
                  onChange={(e) => setPct(key, e.target.value)}
                  placeholder="0"
                />
              </div>
            ))}
          </div>
          <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
            <span className={cn("text-sm font-semibold", isHundred ? "text-success" : "text-danger")}>
              Toplam: %{totalRounded} {isHundred ? "✓" : "(100 olmalı)"}
            </span>
            <Button onClick={create} loading={creating} disabled={!name.trim() || !isHundred}>Oluştur</Button>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

function NotificationsTab() {
  return (
    <Card className="max-w-2xl">
      <CardBody className="space-y-3 text-sm">
        <p className="text-text-secondary">Bildirim tercihleri (her olay için uygulama içi ve e-posta):</p>
        {["Vadesi geçmiş ödeme", "Yaklaşan ödeme (7 gün)", "Kar marjı uyarısı", "Bütçe kategorisi aşımı", "Yeni AI uyarısı", "Haftalık özet"].map((n) => (
          <label key={n} className="flex items-center justify-between border-b border-border py-2">
            <span>{n}</span>
            <input type="checkbox" defaultChecked className="h-4 w-4 accent-[var(--color-primary)]" />
          </label>
        ))}
      </CardBody>
    </Card>
  );
}
