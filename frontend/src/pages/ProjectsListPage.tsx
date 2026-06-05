import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/layout/AppLayout";
import { RAGIndicator } from "@/components/RAGIndicator";
import { Button } from "@/components/ui";
import { PROJECT_TYPES } from "@/constants";
import { useFetch } from "@/hooks/useFetch";
import { useAuth } from "@/store/auth";
import type { Project } from "@/types";
import { formatCurrency, formatDate, formatPct, toNumber } from "@/utils/format";
import { Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";

export default function ProjectsListPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data, loading } = useFetch<Project[]>("/projects");

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
      <DataTable
        columns={columns}
        rows={data ?? []}
        loading={loading}
        emptyMessage="Henüz proje yok. İlk projenizi oluşturun."
        emptyAction={user?.role === "director" ? { label: "Yeni Proje", onClick: () => navigate("/projects/new") } : undefined}
        onRowClick={(r) => navigate(`/projects/${r.id}/dashboard`)}
      />
    </div>
  );
}
