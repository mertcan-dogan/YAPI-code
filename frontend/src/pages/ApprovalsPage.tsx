import { DataTable, type Column } from "@/components/DataTable";
import { AiTrustBadge } from "@/components/ai/AiTrustBadge";
import { PageHeader } from "@/components/layout/AppLayout";
import { Badge, Button, Input, Label, Select } from "@/components/ui";
import { COST_CATEGORIES, VAT_RATES } from "@/constants";
import { useFetch } from "@/hooks/useFetch";
import { apiPut } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import { formatCurrency, formatDateTime } from "@/utils/format";
import { FileScan, Sparkles } from "lucide-react";
import { useState } from "react";
import { Navigate } from "react-router-dom";

interface ApprovalItem {
  kind: string;
  kind_label?: string;
  id: string;
  request_id?: string;
  project_id?: string | null;
  project_name: string;
  description: string;
  amount_try: string | null;
  created_at: string;
  proposed_by_agent?: boolean;
  // CR-012 auto-file proposal payload (destination + editable fields + confidence).
  payload?: {
    destination?: string;
    fields?: Record<string, any>;
    confidence?: number;
    original_filename?: string;
    project_id_guess?: string | null;
  } | null;
}

const KIND_LABELS: Record<string, string> = {
  cost_entry: "Maliyet Girişi",
  budget_change: "Bütçe Değişikliği",
  subcontractor_change: "Alt Yüklenici Değişikliği",
  cost_deletion: "Maliyet Silme",
  variation_approval: "Ek İş Onayı",
  agent_file_document: "Belge Dosyalama (AI önerisi)",
};

// CR-004-N: cost-entry items use the legacy cost endpoint; everything else is a
// generic approval request.
function decideUrl(it: ApprovalItem, action: "approve" | "reject"): string {
  return it.kind === "cost_entry"
    ? `/approvals/cost/${it.id}/${action}`
    : `/approvals/request/${it.request_id}/${action}`;
}

export default function ApprovalsPage() {
  const { user } = useAuth();
  const { data, loading, refetch, error } = useFetch<ApprovalItem[]>("/approvals");
  const { data: projects } = useFetch<{ id: string; name: string }[]>("/projects");
  const [rejecting, setRejecting] = useState<ApprovalItem | null>(null);
  const [reviewing, setReviewing] = useState<ApprovalItem | null>(null);

  if (user && user.role !== "director") return <Navigate to="/dashboard" replace />;

  const approve = async (it: ApprovalItem) => {
    try {
      await apiPut(decideUrl(it, "approve"), {});
      toast.success("Onaylandı");
      refetch();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const columns: Column<ApprovalItem>[] = [
    {
      key: "kind",
      header: "İşlem Türü",
      render: (r) => (
        <span className="flex items-center gap-1.5">
          {r.kind === "agent_file_document" && <FileScan className="h-3.5 w-3.5 text-brand" />}
          {r.kind_label ?? KIND_LABELS[r.kind] ?? r.kind}
          {r.proposed_by_agent && (
            <Badge variant="info" className="gap-1"><Sparkles className="h-3 w-3" /> AI</Badge>
          )}
        </span>
      ),
    },
    { key: "project_name", header: "Proje", render: (r) => r.project_name || (r.kind === "agent_file_document" ? "— (seçilecek)" : "") },
    { key: "description", header: "Açıklama" },
    { key: "amount_try", header: "Tutar", align: "right", render: (r) => (r.amount_try ? formatCurrency(r.amount_try) : "—") },
    { key: "created_at", header: "Tarih", render: (r) => formatDateTime(r.created_at) },
    {
      key: "actions",
      header: "",
      render: (r) =>
        r.kind === "agent_file_document" ? (
          <div className="flex justify-end">
            <Button className="px-3 py-1 text-xs" onClick={() => setReviewing(r)}>İncele &amp; Onayla</Button>
          </div>
        ) : (
          <div className="flex justify-end gap-2">
            <Button className="px-3 py-1 text-xs" onClick={() => approve(r)}>Onayla</Button>
            <Button variant="danger" className="px-3 py-1 text-xs" onClick={() => setRejecting(r)}>Reddet</Button>
          </div>
        ),
    },
  ];

  return (
    <div>
      <PageHeader title="Onay Bekleyenler" subtitle="Eşiği aşan işlemler onayınızı bekliyor" />
      <DataTable columns={columns} rows={data ?? []} loading={loading} error={error} onRetry={refetch} emptyMessage="Onay bekleyen işlem yok." />
      {rejecting && <RejectModal item={rejecting} onClose={() => setRejecting(null)} onDone={() => { setRejecting(null); refetch(); }} />}
      {reviewing && (
        <AutoFileReviewModal
          item={reviewing}
          projects={projects ?? []}
          onClose={() => setReviewing(null)}
          onReject={() => { setRejecting(reviewing); setReviewing(null); }}
          onDone={() => { setReviewing(null); refetch(); }}
        />
      )}
    </div>
  );
}

// CR-012 §5 — auto-file approval card: proposed destination, editable extracted
// fields, the CR-024 trust label + a confidence badge, and a required project
// pick when the AI had no guess. On approve, the corrections + project are sent
// and the record is created server-side (the proposal never wrote it).
function AutoFileReviewModal({
  item,
  projects,
  onClose,
  onReject,
  onDone,
}: {
  item: ApprovalItem;
  projects: { id: string; name: string }[];
  onClose: () => void;
  onReject: () => void;
  onDone: () => void;
}) {
  const destination = item.payload?.destination ?? "cost";
  const isCost = destination === "cost";
  const [fields, setFields] = useState<Record<string, any>>({ ...(item.payload?.fields ?? {}) });
  const [projectId, setProjectId] = useState<string>(item.project_id ?? item.payload?.project_id_guess ?? "");
  const [saving, setSaving] = useState(false);
  const set = (k: string, v: any) => setFields((f) => ({ ...f, [k]: v }));

  const conf = item.payload?.confidence != null ? Math.round(item.payload.confidence * 100) : null;
  const confVariant = conf == null ? "neutral" : conf >= 80 ? "success" : conf >= 50 ? "warning" : "danger";

  const approve = async () => {
    if (!projectId) { toast.error("Lütfen bir proje seçin"); return; }
    setSaving(true);
    try {
      await apiPut(`/approvals/request/${item.request_id ?? item.id}/approve`, { project_id: projectId, fields });
      toast.success("Onaylandı — kayıt oluşturuldu");
      onDone();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  const dateField = isCost ? "entry_date" : "invoice_date";
  const dueField = isCost ? "payment_due_date" : "due_date";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl bg-surface p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-start justify-between gap-3">
          <h3 className="flex items-center gap-2 text-base font-semibold text-primary">
            <FileScan className="h-4 w-4 text-brand" /> Belge Dosyalama Önerisi
          </h3>
          {conf != null && <Badge variant={confVariant as any}>Güven %{conf}</Badge>}
        </div>

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Badge variant="info">{isCost ? "Gider" : "Hakediş"} olarak önerildi</Badge>
          {item.payload?.original_filename && (
            <span className="text-xs text-text-muted">«{item.payload.original_filename}»</span>
          )}
        </div>
        <AiTrustBadge compact className="mb-3" />

        <div className="space-y-3">
          <div>
            <Label required>Proje {!item.project_id && <span className="ml-1 text-[10px] font-medium text-warning">(seçilmeli)</span>}</Label>
            <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">Proje seçin…</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
          </div>

          {isCost && (
            <div><Label>Tedarikçi</Label><Input value={fields.supplier_name ?? ""} onChange={(e) => set("supplier_name", e.target.value)} /></div>
          )}
          <div className="grid grid-cols-2 gap-2">
            <div><Label>Fatura No</Label><Input value={fields.invoice_number ?? ""} onChange={(e) => set("invoice_number", e.target.value)} /></div>
            <div><Label required>{isCost ? "Fatura Tarihi" : "Fatura Tarihi"}</Label><Input type="date" value={fields[dateField] ?? ""} onChange={(e) => set(dateField, e.target.value)} /></div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div><Label required>Tutar (KDV hariç ₺)</Label><Input type="number" value={fields.amount_try ?? ""} onChange={(e) => set("amount_try", e.target.value)} /></div>
            <div><Label>KDV %</Label><Select value={String(fields.vat_rate ?? "20")} onChange={(e) => set("vat_rate", e.target.value)}>{VAT_RATES.map((v) => <option key={v} value={v}>%{v}</option>)}</Select></div>
          </div>
          {isCost ? (
            <div>
              <Label required>Maliyet Kategorisi</Label>
              <Select value={fields.cost_category ?? "material_other"} onChange={(e) => set("cost_category", e.target.value)}>
                {Object.entries(COST_CATEGORIES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </Select>
            </div>
          ) : (
            <div><Label>Hakediş Kesintisi (₺)</Label><Input type="number" value={fields.retention_amount_try ?? "0"} onChange={(e) => set("retention_amount_try", e.target.value)} /></div>
          )}
          <div className="grid grid-cols-2 gap-2">
            <div><Label>{isCost ? "Vade Tarihi" : "Son Ödeme Tarihi"}</Label><Input type="date" value={fields[dueField] ?? ""} onChange={(e) => set(dueField, e.target.value)} /></div>
            <div><Label>Açıklama</Label><Input value={fields.description ?? ""} onChange={(e) => set("description", e.target.value)} /></div>
          </div>
        </div>

        <div className="mt-5 flex items-center justify-between gap-2">
          <Button variant="danger" className="px-3 py-1.5 text-xs" onClick={onReject}>Reddet</Button>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>İptal</Button>
            <Button loading={saving} onClick={approve}>Onayla &amp; Oluştur</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function RejectModal({ item, onClose, onDone }: { item: ApprovalItem; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const reject = async () => {
    if (!reason.trim()) { toast.error("Red nedeni zorunludur"); return; }
    setSaving(true);
    try {
      await apiPut(decideUrl(item, "reject"), { reason });
      toast.success("Reddedildi");
      onDone();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-sm rounded-xl bg-surface p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-3 text-base font-semibold text-primary">İşlemi Reddet</h3>
        <Label required>Red Nedeni</Label>
        <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Neden bu işlemi reddediyorsunuz?" />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>İptal</Button>
          <Button variant="danger" loading={saving} onClick={reject}>Reddet</Button>
        </div>
      </div>
    </div>
  );
}
