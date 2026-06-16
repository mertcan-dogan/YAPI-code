// CR-008-H — "Tedarikçiler": canonical vendor list with spend, merge-suggestion
// confirmation, alias editing, and linking of legacy (vendor_id NULL) rows.
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Input, Label, Modal, Select } from "@/components/ui";
import { useFetch } from "@/hooks/useFetch";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { toast } from "@/store/toast";
import { formatCurrency } from "@/utils/format";
import { Plus, Tags, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

interface VendorRow {
  id: string;
  canonical_name: string;
  total_try: string;
  cost_entry_count: number;
  project_count: number;
  alias_count: number;
}
interface ClusterMember { id: string; canonical_name: string }
interface Unlinked {
  suppliers: { supplier_name: string; count: number }[];
  subcontractors: { id: string; name: string; project_id: string }[];
}
interface Alias { id: string; alias_name: string }

export default function VendorsPage() {
  const vendorsQ = useFetch<VendorRow[]>("/vendors");
  const suggestionsQ = useFetch<ClusterMember[][]>("/vendors/suggestions");
  const unlinkedQ = useFetch<Unlinked>("/vendors/unlinked");
  const vendors = vendorsQ.data ?? [];

  const [mergeCluster, setMergeCluster] = useState<ClusterMember[] | null>(null);
  const [aliasVendor, setAliasVendor] = useState<VendorRow | null>(null);
  const [detailVendor, setDetailVendor] = useState<VendorRow | null>(null);
  const [linkSupplier, setLinkSupplier] = useState<string | null>(null);

  const refetchAll = () => {
    vendorsQ.refetch();
    suggestionsQ.refetch();
    unlinkedQ.refetch();
  };

  const columns: Column<VendorRow>[] = [
    { key: "canonical_name", header: "Tedarikçi", render: (v) => <span className="font-medium text-primary">{v.canonical_name}</span> },
    { key: "total_try", header: "Toplam Harcama", align: "right", sortable: true, sortValue: (v) => Number(v.total_try), render: (v) => formatCurrency(v.total_try) },
    { key: "project_count", header: "Proje", align: "right", render: (v) => v.project_count },
    { key: "cost_entry_count", header: "Kayıt", align: "right", render: (v) => v.cost_entry_count },
    {
      key: "alias_count", header: "Takma Adlar", align: "right",
      render: (v) => (
        <Button variant="outline" className="px-2 py-1 text-xs" onClick={(e) => { e.stopPropagation(); setAliasVendor(v); }}>
          <Tags className="h-3.5 w-3.5" /> {v.alias_count}
        </Button>
      ),
    },
  ];

  const clusters = suggestionsQ.data ?? [];
  const unlinked = unlinkedQ.data ?? { suppliers: [], subcontractors: [] };

  return (
    <div>
      <PageHeader title="Tedarikçiler" subtitle="Kanonik tedarikçiler, harcama ve birleştirme" />

      {/* Merge suggestions */}
      {clusters.length > 0 && (
        <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
          <h2 className="mb-2 text-sm font-semibold text-primary">Birleştirme Önerileri</h2>
          <p className="mb-3 text-xs text-text-secondary">Aşağıdaki tedarikçiler birbirine benziyor — aynı firma iseler birleştirin.</p>
          <div className="space-y-2">
            {clusters.map((cluster, i) => (
              <div key={i} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface px-3 py-2">
                <span className="text-sm text-text-primary">{cluster.map((c) => c.canonical_name).join("  ·  ")}</span>
                <Button variant="outline" className="px-2.5 py-1 text-xs" onClick={() => setMergeCluster(cluster)}>Birleştir</Button>
              </div>
            ))}
          </div>
        </div>
      )}

      <DataTable
        columns={columns}
        rows={vendors}
        loading={vendorsQ.loading}
        error={vendorsQ.error}
        onRetry={vendorsQ.refetch}
        onRowClick={(v) => setDetailVendor(v)}
        emptyMessage="Henüz tedarikçi yok. Tedarikçi tablosunu doldurmak için backfill çalıştırın."
      />

      {/* Unlinked legacy rows */}
      {(unlinked.suppliers.length > 0 || unlinked.subcontractors.length > 0) && (
        <div className="mt-5 rounded-xl border border-border bg-surface p-4">
          <h2 className="mb-2 text-sm font-semibold text-primary">Bağlanmamış Kayıtlar</h2>
          <p className="mb-3 text-xs text-text-secondary">Bir tedarikçiye bağlı olmayan eski maliyet kayıtları. Bağladığınızda gelecekteki eşleşmeler kesinleşir.</p>
          <div className="space-y-1">
            {unlinked.suppliers.map((s) => (
              <div key={s.supplier_name} className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-1.5 text-sm">
                <span className="truncate text-text-primary">{s.supplier_name} <span className="text-text-secondary">({s.count})</span></span>
                <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setLinkSupplier(s.supplier_name)}>Tedarikçiye Bağla</Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {mergeCluster && (
        <MergeModal cluster={mergeCluster} onClose={() => setMergeCluster(null)} onDone={() => { setMergeCluster(null); refetchAll(); }} />
      )}
      {aliasVendor && (
        <AliasModal vendor={aliasVendor} onClose={() => setAliasVendor(null)} onChanged={() => vendorsQ.refetch()} />
      )}
      {detailVendor && (
        <VendorDetailModal vendor={detailVendor} onClose={() => setDetailVendor(null)} />
      )}
      {linkSupplier && (
        <LinkModal supplierName={linkSupplier} vendors={vendors} onClose={() => setLinkSupplier(null)} onDone={() => { setLinkSupplier(null); refetchAll(); }} />
      )}
    </div>
  );
}

interface VendorDetail {
  id: string;
  canonical_name: string;
  tax_id: string | null;
  aliases: string[];
  total_try: string;
  cost_entry_count: number;
  project_count: number;
  subcontractor_count: number;
  by_project: { project_id: string; project_name: string; total_try: string }[];
  by_category: { category: string; category_label: string; total_try: string }[];
}

function VendorDetailModal({ vendor, onClose }: { vendor: VendorRow; onClose: () => void }) {
  const [detail, setDetail] = useState<VendorDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    apiGet<VendorDetail>(`/vendors/${vendor.id}`)
      .then((r) => setDetail(r.data))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [vendor.id]);

  const Breakdown = ({ title, rows }: { title: string; rows: { label: string; total_try: string }[] }) => {
    const max = Math.max(...rows.map((r) => Number(r.total_try)), 1);
    return (
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-secondary">{title}</h3>
        {rows.length === 0 ? (
          <p className="text-sm text-text-secondary">Kayıt yok.</p>
        ) : (
          <div className="space-y-1.5">
            {rows.map((r, i) => (
              <div key={i}>
                <div className="flex items-center justify-between gap-2 text-sm">
                  <span className="min-w-0 truncate text-text-primary" title={r.label}>{r.label}</span>
                  <span className="tabular shrink-0 font-medium text-primary">{formatCurrency(r.total_try)}</span>
                </div>
                <div className="mt-0.5 h-1.5 w-full overflow-hidden rounded-full bg-bg">
                  <div className="h-full rounded-full bg-brand" style={{ width: `${(Number(r.total_try) / max) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <Modal open title={vendor.canonical_name} onClose={onClose} size="lg" footer={<Button onClick={onClose}>Kapat</Button>}>
      {loading ? (
        <p className="py-6 text-center text-sm text-text-secondary">Yükleniyor…</p>
      ) : !detail ? (
        <p className="py-6 text-center text-sm text-text-secondary">Tedarikçi detayları yüklenemedi.</p>
      ) : (
        <div className="space-y-5">
          {/* Headline figures */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-lg border border-border p-3">
              <div className="text-xs text-text-secondary">Toplam Harcama</div>
              <div className="tabular mt-1 text-lg font-bold text-primary">{formatCurrency(detail.total_try)}</div>
            </div>
            <div className="rounded-lg border border-border p-3">
              <div className="text-xs text-text-secondary">Proje</div>
              <div className="tabular mt-1 text-lg font-bold text-primary">{detail.project_count}</div>
            </div>
            <div className="rounded-lg border border-border p-3">
              <div className="text-xs text-text-secondary">Maliyet Kaydı</div>
              <div className="tabular mt-1 text-lg font-bold text-primary">{detail.cost_entry_count}</div>
            </div>
            <div className="rounded-lg border border-border p-3">
              <div className="text-xs text-text-secondary">Alt Yüklenici</div>
              <div className="tabular mt-1 text-lg font-bold text-primary">{detail.subcontractor_count}</div>
            </div>
          </div>

          {/* Aliases */}
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-secondary">Takma Adlar</h3>
            {detail.aliases.length === 0 ? (
              <p className="text-sm text-text-secondary">Takma ad yok.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {detail.aliases.map((a) => (
                  <span key={a} className="rounded-full bg-navy-50 px-2.5 py-0.5 text-xs text-brand">{a}</span>
                ))}
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <Breakdown title="Projeye Göre" rows={detail.by_project.map((p) => ({ label: p.project_name, total_try: p.total_try }))} />
            <Breakdown title="Kategoriye Göre" rows={detail.by_category.map((c) => ({ label: c.category_label, total_try: c.total_try }))} />
          </div>
        </div>
      )}
    </Modal>
  );
}

function MergeModal({ cluster, onClose, onDone }: { cluster: ClusterMember[]; onClose: () => void; onDone: () => void }) {
  const [survivor, setSurvivor] = useState(cluster[0].id);
  const [saving, setSaving] = useState(false);
  const confirm = async () => {
    setSaving(true);
    try {
      await apiPost("/vendors/merge", { survivor_id: survivor, merged_ids: cluster.filter((c) => c.id !== survivor).map((c) => c.id) });
      toast.success("Tedarikçiler birleştirildi");
      onDone();
    } catch (e: any) {
      toast.error(e.message ?? "Birleştirilemedi");
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal open title="Tedarikçileri Birleştir" onClose={onClose} size="md"
      footer={<><Button variant="ghost" onClick={onClose}>İptal</Button><Button onClick={confirm} loading={saving}>Birleştir</Button></>}>
      <p className="mb-3 text-sm text-text-secondary">Hangi ad korunsun? Diğerleri takma ad olur ve kayıtları bu tedarikçiye taşınır.</p>
      <div className="space-y-2">
        {cluster.map((c) => (
          <label key={c.id} className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm">
            <input type="radio" name="survivor" checked={survivor === c.id} onChange={() => setSurvivor(c.id)} />
            {c.canonical_name}
          </label>
        ))}
      </div>
    </Modal>
  );
}

function AliasModal({ vendor, onClose, onChanged }: { vendor: VendorRow; onClose: () => void; onChanged: () => void }) {
  const [aliases, setAliases] = useState<Alias[]>([]);
  const [adding, setAdding] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => apiGet<Alias[]>(`/vendors/${vendor.id}/aliases`).then((r) => setAliases(r.data)).catch(() => {});
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [vendor.id]);

  const add = async () => {
    if (!adding.trim()) return;
    setBusy(true);
    try {
      await apiPost(`/vendors/${vendor.id}/aliases`, { alias_name: adding.trim() });
      setAdding("");
      await load();
      onChanged();
    } catch (e: any) {
      toast.error(e.message ?? "Eklenemedi");
    } finally {
      setBusy(false);
    }
  };
  const remove = async (id: string) => {
    try {
      await apiDelete(`/vendors/${vendor.id}/aliases/${id}`);
      await load();
      onChanged();
    } catch {
      toast.error("Silinemedi");
    }
  };

  return (
    <Modal open title={`Takma Adlar — ${vendor.canonical_name}`} onClose={onClose} size="md"
      footer={<Button onClick={onClose}>Kapat</Button>}>
      <div className="space-y-2">
        {aliases.length === 0 && <p className="text-sm text-text-secondary">Takma ad yok.</p>}
        {aliases.map((a) => (
          <div key={a.id} className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-1.5 text-sm">
            <span className="truncate">{a.alias_name}</span>
            <button onClick={() => remove(a.id)} aria-label="Sil" className="text-text-secondary hover:text-danger"><Trash2 className="h-3.5 w-3.5" /></button>
          </div>
        ))}
      </div>
      <div className="mt-3">
        <Label>Yeni takma ad</Label>
        <div className="flex gap-2">
          <Input value={adding} onChange={(e) => setAdding(e.target.value)} placeholder="örn. Bozkurt Beton A.Ş." />
          <Button onClick={add} loading={busy}><Plus className="h-4 w-4" /> Ekle</Button>
        </div>
      </div>
    </Modal>
  );
}

function LinkModal({ supplierName, vendors, onClose, onDone }: { supplierName: string; vendors: VendorRow[]; onClose: () => void; onDone: () => void }) {
  const [vendorId, setVendorId] = useState(vendors[0]?.id ?? "");
  const [saving, setSaving] = useState(false);
  const confirm = async () => {
    if (!vendorId) return;
    setSaving(true);
    try {
      await apiPost(`/vendors/${vendorId}/link`, { supplier_names: [supplierName] });
      toast.success("Kayıtlar bağlandı");
      onDone();
    } catch (e: any) {
      toast.error(e.message ?? "Bağlanamadı");
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal open title="Tedarikçiye Bağla" onClose={onClose} size="md"
      footer={<><Button variant="ghost" onClick={onClose}>İptal</Button><Button onClick={confirm} loading={saving} disabled={!vendorId}>Bağla</Button></>}>
      <p className="mb-3 text-sm text-text-secondary">"<b>{supplierName}</b>" adlı kayıtları hangi tedarikçiye bağlamak istiyorsunuz?</p>
      <Select value={vendorId} onChange={(e) => setVendorId(e.target.value)}>
        {vendors.map((v) => <option key={v.id} value={v.id}>{v.canonical_name}</option>)}
      </Select>
    </Modal>
  );
}
