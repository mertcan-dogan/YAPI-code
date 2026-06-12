import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Select } from "@/components/ui";
import { api, apiGet } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import { formatCurrency, formatDate, formatDateTime, formatNumber, toNumber } from "@/utils/format";
import { Download } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";

interface ChangedField {
  field: string;
  old: any;
  new: any;
}

interface AuditRow {
  id: string;
  user_name: string;
  action: string;
  action_label: string;
  table_label: string;
  table_name: string;
  old_values: Record<string, any> | null;
  new_values: Record<string, any> | null;
  changed_fields: ChangedField[];
  created_at: string;
}

const ACTION_BADGE: Record<string, string> = {
  INSERT: "bg-green-50 text-success",
  UPDATE: "bg-amber-50 text-accent",
  DELETE: "bg-red-50 text-danger",
};

// Numeric fields worth surfacing in the "Fark" column.
const NUMERIC_KEYS = ["amount_try", "total_with_vat_try", "contract_value_try", "amount_received_try", "net_due_try", "forecast_final_try", "original_budget_try"];

// CR-005-E: friendly Turkish labels for the common changed fields.
const FIELD_LABELS: Record<string, string> = {
  amount_try: "Tutar",
  total_with_vat_try: "KDV Dahil Tutar",
  amount_paid_try: "Ödenen",
  amount_received_try: "Tahsil Edilen",
  net_due_try: "Net Tutar",
  contract_value_try: "Sözleşme Bedeli",
  original_budget_try: "Orijinal Bütçe",
  approved_variations_try: "Onaylı Ek İş",
  forecast_final_try: "Final Tahmin",
  payment_due_date: "Vade Tarihi",
  due_date: "Vade Tarihi",
  date_paid: "Ödeme Tarihi",
  date_received: "Tahsilat Tarihi",
  entry_date: "Giriş Tarihi",
  payment_status: "Ödeme Durumu",
  cost_category: "Kategori",
  supplier_name: "Tedarikçi",
  description: "Açıklama",
  invoice_number: "Fatura No",
  vat_rate: "KDV Oranı",
};

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}

// CR-005-E: Türkçe formatting per field type — money "1.234.567,89 ₺", dates
// DD.MM.YYYY, booleans Evet/Hayır.
function formatAuditValue(field: string, value: any): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Evet" : "Hayır";
  if (field.endsWith("_try") || field.includes("amount") || field.includes("budget") || field === "contract_value_try") {
    return formatCurrency(value);
  }
  if (field.includes("date") && /^\d{4}-\d{2}-\d{2}/.test(String(value))) {
    return formatDate(String(value));
  }
  return String(value);
}

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

// CR-005-E: show only the changed fields as "alan: eski → yeni" — no JSON dump.
function ChangedFieldsCell({ row }: { row: AuditRow }) {
  const changed = row.changed_fields ?? [];
  if (changed.length === 0) {
    // INSERT/DELETE (or no-op): describe the action instead of an empty diff.
    const label =
      row.action === "INSERT" ? "Kayıt eklendi" : row.action === "DELETE" ? "Kayıt silindi" : row.action_label;
    return <span className="text-xs text-text-secondary">{label}</span>;
  }
  return (
    <div className="max-w-[320px] space-y-0.5">
      {changed.map((c) => (
        <div key={c.field} className="text-xs">
          <span className="font-medium text-text-secondary">{fieldLabel(c.field)}: </span>
          <span className="tabular text-text-disabled line-through">{formatAuditValue(c.field, c.old)}</span>
          <span className="px-1">→</span>
          <span className="tabular font-medium">{formatAuditValue(c.field, c.new)}</span>
        </div>
      ))}
    </div>
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
  const { data, loading, error, refetch } = useFetchAudit(params);

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
    { key: "changed_fields", header: "Değişiklik Detayı", render: (r) => <ChangedFieldsCell row={r} /> },
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
      <DataTable columns={columns} rows={data ?? []} loading={loading} error={error} onRetry={refetch} emptyMessage="Kayıtlı değişiklik bulunmuyor." />
    </div>
  );
}

// Local fetch hook that re-runs when filter params change.
function useFetchAudit(params: Record<string, string>) {
  const [data, setData] = useState<AuditRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const key = JSON.stringify(params);
  useEffect(() => {
    setLoading(true);
    setError(null);
    apiGet<AuditRow[]>("/audit-log", params)
      .then(({ data }) => setData(data ?? []))
      .catch((e: any) => { setData([]); setError(e?.message ?? "Yükleme hatası"); })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, nonce]);
  return { data, loading, error, refetch: () => setNonce((n) => n + 1) };
}
