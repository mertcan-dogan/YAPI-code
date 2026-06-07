import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Select } from "@/components/ui";
import { api, apiGet } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import { formatDateTime, formatNumber, toNumber } from "@/utils/format";
import { Download } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";

interface AuditRow {
  id: string;
  user_name: string;
  action: string;
  action_label: string;
  table_label: string;
  table_name: string;
  old_values: Record<string, any> | null;
  new_values: Record<string, any> | null;
  created_at: string;
}

const ACTION_BADGE: Record<string, string> = {
  INSERT: "bg-green-50 text-success",
  UPDATE: "bg-amber-50 text-accent",
  DELETE: "bg-red-50 text-danger",
};

// Numeric fields worth surfacing in the "Fark" column.
const NUMERIC_KEYS = ["amount_try", "total_with_vat_try", "contract_value_try", "amount_received_try", "net_due_try", "forecast_final_try", "original_budget_try"];

function diff(row: AuditRow): string {
  if (!row.old_values || !row.new_values) return "—";
  for (const k of NUMERIC_KEYS) {
    if (k in row.old_values && k in row.new_values) {
      const o = toNumber(row.old_values[k]);
      const n = toNumber(row.new_values[k]);
      if (o !== n) {
        const d = n - o;
        return `${d > 0 ? "↑" : "↓"} ${formatNumber(Math.abs(d))} ₺`;
      }
    }
  }
  return "—";
}

function JsonCell({ data }: { data: Record<string, any> | null }) {
  if (!data) return <span className="text-text-disabled">—</span>;
  const keys = Object.keys(data).slice(0, 40);
  return (
    <details className="max-w-[220px]">
      <summary className="cursor-pointer text-xs text-primary-light">{keys.length} alan</summary>
      <pre className="mt-1 max-h-48 overflow-auto rounded bg-bg p-2 text-[10px] leading-snug">
        {JSON.stringify(data, null, 1)}
      </pre>
    </details>
  );
}

export default function AuditLogPage() {
  const { user } = useAuth();
  const [filters, setFilters] = useState({ action: "", table_name: "", user_id: "", date_from: "", date_to: "" });
  const [users, setUsers] = useState<{ id: string; full_name: string }[]>([]);

  // Access control (CR-001-H 9.2.4): director only.
  if (user && user.role !== "director") return <Navigate to="/dashboard" replace />;

  const params = useMemo(
    () => Object.fromEntries(Object.entries(filters).filter(([, v]) => v)),
    [filters]
  );
  const { data, loading } = useFetchAudit(params);

  useEffect(() => {
    apiGet<{ id: string; full_name: string }[]>("/settings/users").then(({ data }) => setUsers(data ?? [])).catch(() => setUsers([]));
  }, []);

  const exportXlsx = async () => {
    try {
      const res = await api.get("/audit-log/export", { params, responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = "denetim-izi.xlsx";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      toast.error(e.message ?? "Dışa aktarılamadı");
    }
  };

  const columns: Column<AuditRow>[] = [
    { key: "created_at", header: "Tarih & Saat", render: (r) => formatDateTime(r.created_at) },
    { key: "user_name", header: "Kullanıcı" },
    {
      key: "action",
      header: "İşlem",
      render: (r) => <span className={`rounded-full px-2 py-0.5 text-xs ${ACTION_BADGE[r.action] ?? "bg-bg"}`}>{r.action_label}</span>,
    },
    { key: "table_label", header: "Kayıt Türü" },
    { key: "old_values", header: "Eski Değer", render: (r) => <JsonCell data={r.old_values} /> },
    { key: "new_values", header: "Yeni Değer", render: (r) => <JsonCell data={r.new_values} /> },
    { key: "diff", header: "Fark", align: "right", render: (r) => <span className={diff(r).startsWith("↑") ? "text-danger" : diff(r).startsWith("↓") ? "text-success" : ""}>{diff(r)}</span> },
  ];

  return (
    <div>
      <PageHeader
        title="Denetim İzi"
        subtitle="Tüm finansal değişikliklerin kaydı"
        action={<Button variant="outline" onClick={exportXlsx}><Download className="h-4 w-4" /> Excel'e Aktar</Button>}
      />
      <div className="mb-3 flex flex-wrap gap-2">
        <input type="date" className="rounded-md border border-border bg-surface px-3 py-2 text-sm" value={filters.date_from} onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))} />
        <input type="date" className="rounded-md border border-border bg-surface px-3 py-2 text-sm" value={filters.date_to} onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))} />
        <Select className="w-44" value={filters.user_id} onChange={(e) => setFilters((f) => ({ ...f, user_id: e.target.value }))}>
          <option value="">Tüm Kullanıcılar</option>
          {users.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
        </Select>
        <Select className="w-40" value={filters.action} onChange={(e) => setFilters((f) => ({ ...f, action: e.target.value }))}>
          <option value="">Tüm İşlemler</option>
          <option value="INSERT">Eklendi</option>
          <option value="UPDATE">Güncellendi</option>
          <option value="DELETE">Silindi</option>
        </Select>
        <Select className="w-44" value={filters.table_name} onChange={(e) => setFilters((f) => ({ ...f, table_name: e.target.value }))}>
          <option value="">Tüm Kayıt Türleri</option>
          <option value="cost_entries">Maliyet</option>
          <option value="client_invoices">Fatura</option>
          <option value="subcontractors">Alt Yüklenici</option>
          <option value="budget_line_items">Bütçe Kalemi</option>
          <option value="projects">Proje</option>
        </Select>
      </div>
      <DataTable columns={columns} rows={data ?? []} loading={loading} emptyMessage="Kayıtlı değişiklik bulunmuyor." />
    </div>
  );
}

// Local fetch hook that re-runs when filter params change.
function useFetchAudit(params: Record<string, string>) {
  const [data, setData] = useState<AuditRow[]>([]);
  const [loading, setLoading] = useState(true);
  const key = JSON.stringify(params);
  useEffect(() => {
    setLoading(true);
    apiGet<AuditRow[]>("/audit-log", params)
      .then(({ data }) => setData(data ?? []))
      .catch(() => setData([]))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return { data, loading };
}
