import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Input, Label } from "@/components/ui";
import { useFetch } from "@/hooks/useFetch";
import { apiPut } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import { formatCurrency, formatDateTime } from "@/utils/format";
import { useState } from "react";
import { Navigate } from "react-router-dom";

interface ApprovalItem {
  kind: string;
  kind_label?: string;
  id: string;
  request_id?: string;
  project_name: string;
  description: string;
  amount_try: string | null;
  created_at: string;
}

const KIND_LABELS: Record<string, string> = {
  cost_entry: "Maliyet Girişi",
  budget_change: "Bütçe Değişikliği",
  subcontractor_change: "Alt Yüklenici Değişikliği",
  cost_deletion: "Maliyet Silme",
  variation_approval: "Ek İş Onayı",
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
  const [rejecting, setRejecting] = useState<ApprovalItem | null>(null);

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
    { key: "kind", header: "İşlem Türü", render: (r) => r.kind_label ?? KIND_LABELS[r.kind] ?? r.kind },
    { key: "project_name", header: "Proje" },
    { key: "description", header: "Açıklama" },
    { key: "amount_try", header: "Tutar", align: "right", render: (r) => (r.amount_try ? formatCurrency(r.amount_try) : "—") },
    { key: "created_at", header: "Tarih", render: (r) => formatDateTime(r.created_at) },
    {
      key: "actions",
      header: "",
      render: (r) => (
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
      <div className="w-full max-w-sm rounded-lg bg-surface p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
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
