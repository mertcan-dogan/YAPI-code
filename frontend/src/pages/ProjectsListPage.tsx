import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/layout/AppLayout";
import { RAGIndicator } from "@/components/RAGIndicator";
import { Badge, Button } from "@/components/ui";
import { PROJECT_TYPES } from "@/constants";
import { useFetch } from "@/hooks/useFetch";
import { useAuth } from "@/store/auth";
import type { Project } from "@/types";
import { formatCurrency, formatDate, formatPct, toNumber } from "@/utils/format";
import { Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";

const RISK_MAP: Record<string, { l: string; c: string }> = {
  green: { l: "Düşük", c: "bg-green-50 text-success" },
  amber: { l: "Orta", c: "bg-amber-50 text-warning" },
  red: { l: "Yüksek", c: "bg-red-50 text-danger" },
};

export default function ProjectsListPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data, loading, error, refetch } = useFetch<Project[]>("/projects");

  // Proje Performans Sıralaması — projects ranked by estimated margin (desc).
  const ranked = [...(data ?? [])]
    .sort((a, b) => toNumber(b.financials?.margin_pct) - toNumber(a.financials?.margin_pct))
    .map((r, i) => ({ ...r, _rank: i + 1 }));

  const rankingColumns: Column<any>[] = [
    { key: "_rank", header: "#", maxWidth: 44, render: (r) => <span className="tabular text-text-secondary">{r._rank}</span> },
    {
      key: "name",
      header: "Proje",
      sortable: true,
      render: (r) => (
        <span className="flex items-center gap-2 truncate font-medium text-primary" title={r.name}>
          {r.financials && <RAGIndicator status={r.financials.rag_status} reason={r.financials.rag_reason_tr} />}
          <span className="truncate">{r.name}</span>
        </span>
      ),
    },
    {
      key: "margin_pct",
      header: "Marj % (Tahmini)",
      align: "right",
      sortable: true,
      sortValue: (r) => toNumber(r.financials?.margin_pct),
      render: (r) => {
        const m = toNumber(r.financials?.margin_pct);
        const c = m < 5 ? "text-danger" : m < 10 ? "text-accent" : "text-success";
        return <span className={`font-semibold ${c}`}>{formatPct(r.financials?.margin_pct)}</span>;
      },
    },
    {
      key: "margin_try",
      header: "Marj ₺ (Tahmini)",
      align: "right",
      sortValue: (r) => toNumber(r.financials?.current_profit_try),
      render: (r) => <span className={toNumber(r.financials?.current_profit_try) < 0 ? "text-danger" : ""}>{formatCurrency(r.financials?.current_profit_try)}</span>,
    },
    {
      key: "risk",
      header: "Risk",
      render: (r) => {
        const x = RISK_MAP[r.financials?.rag_status] ?? { l: "—", c: "bg-bg text-text-secondary" };
        return <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${x.c}`}>{x.l}</span>;
      },
    },
  ];

  const columns: Column<Project>[] = [
    {
      key: "name",
      header: "Proje",
      sortable: true,
      render: (r) => (
        <span className="flex items-center gap-2 font-medium text-primary">
          {r.financials && <RAGIndicator status={r.financials.rag_status} reason={r.financials.rag_reason_tr} />}
          {r.name}
        </span>
      ),
    },
    { key: "project_code", header: "Kod" },
    { key: "project_type", header: "Tür", render: (r) => PROJECT_TYPES[r.project_type] ?? r.project_type },
    { key: "client_name", header: "İşveren" },
    { key: "contract_value_try", header: "Sözleşme", align: "right", sortable: true, sortValue: (r) => toNumber(r.contract_value_try), render: (r) => formatCurrency(r.contract_value_try) },
    {
      // Project lifecycle status — Aktif until the closeout marks it Tamamlandı.
      key: "status",
      header: "Durum",
      render: (r) =>
        r.status === "completed" ? (
          <Badge variant="success">Tamamlandı</Badge>
        ) : (
          <Badge variant="info">Aktif</Badge>
        ),
    },
    {
      key: "margin",
      header: "Kar Marjı",
      align: "right",
      render: (r) => {
        const m = toNumber(r.financials?.margin_pct);
        const c = m < 5 ? "text-danger" : m < 10 ? "text-accent" : "text-success";
        return <span className={`font-semibold ${c}`}>{formatPct(r.financials?.margin_pct)}</span>;
      },
    },
    { key: "planned_end_date", header: "Bitiş", align: "right", render: (r) => formatDate(r.planned_end_date) },
  ];

  return (
    <div>
      <PageHeader
        title="Projeler"
        subtitle={`${data?.length ?? 0} proje`}
        action={
          user?.role === "director" && (
            <Button onClick={() => navigate("/projects/new")}>
              <Plus className="h-4 w-4" /> Yeni Proje
            </Button>
          )
        }
      />

      {/* Proje Performans Sıralaması — moved here from Ana Sayfa. */}
      <h2 className="mb-3 text-lg font-semibold text-primary">Proje Performans Sıralaması</h2>
      <p className="mb-3 -mt-2 text-xs text-text-secondary">Tahmini kar marjına göre sıralı projeler.</p>
      <DataTable
        columns={rankingColumns}
        rows={ranked}
        loading={loading}
        error={error}
        onRetry={refetch}
        minWidth={560}
        emptyMessage="Henüz proje yok."
        onRowClick={(r) => navigate(`/projects/${r.id}/dashboard`)}
      />

      <h2 className="mb-3 mt-4 text-lg font-semibold text-primary">Tüm Projeler</h2>
      <DataTable
        columns={columns}
        rows={data ?? []}
        loading={loading}
        error={error}
        onRetry={refetch}
        emptyMessage="Henüz proje yok. İlk projenizi oluşturun."
        emptyAction={user?.role === "director" ? { label: "Yeni Proje", onClick: () => navigate("/projects/new") } : undefined}
        onRowClick={(r) => navigate(`/projects/${r.id}/dashboard`)}
      />
    </div>
  );
}
