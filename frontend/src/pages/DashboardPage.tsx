import { CashFlowChart } from "@/components/charts";
import { Card, CardBody } from "@/components/ui";
import { KPICard } from "@/components/KPICard";
import { PageHeader } from "@/components/layout/AppLayout";
import { RAGIndicator } from "@/components/RAGIndicator";
import { DataTable, type Column } from "@/components/DataTable";
import { useFetch } from "@/hooks/useFetch";
import { apiGet } from "@/lib/api";
import { formatCurrency, formatCurrencyAbbrev, formatDate, formatPct, toNumber } from "@/utils/format";
import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

interface DashboardData {
  kpis: {
    active_project_count: number;
    total_contract_value_try: string;
    weighted_avg_margin_pct: string;
    overdue_payment_count: number;
  };
  projects: any[];
  cashflow_chart: { month: string; out: string; in: string; net_cumulative: string }[];
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { data, loading } = useFetch<DashboardData>("/dashboard");
  const [briefing, setBriefing] = useState<any[]>([]);

  useEffect(() => {
    apiGet("/ai/daily-briefing").then((r) => setBriefing(r.data)).catch(() => setBriefing([]));
  }, []);

  const k = data?.kpis;
  const marginNum = toNumber(k?.weighted_avg_margin_pct);

  const columns: Column<any>[] = [
    {
      key: "name",
      header: "Proje Adı",
      sortable: true,
      render: (r) => (
        <span className="flex items-center gap-2 font-medium text-primary">
          <RAGIndicator status={r.rag_status} reason={r.rag_label_tr} /> {r.name}
        </span>
      ),
    },
    { key: "client_name", header: "İşveren" },
    { key: "contract_value_try", header: "Sözleşme Değeri", align: "right", render: (r) => formatCurrency(r.contract_value_try), sortValue: (r) => toNumber(r.contract_value_try) },
    {
      key: "spent_pct",
      header: "Harcanan %",
      align: "right",
      render: (r) => (
        <div className="flex items-center justify-end gap-2">
          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-border">
            <div className="h-full bg-primary" style={{ width: `${Math.min(toNumber(r.spent_pct), 100)}%` }} />
          </div>
          {formatPct(r.spent_pct)}
        </div>
      ),
    },
    { key: "completion_pct", header: "Tamamlanma %", align: "right", render: (r) => formatPct(r.completion_pct) },
    {
      key: "margin_pct",
      header: "Kar Marjı %",
      align: "right",
      sortable: true,
      sortValue: (r) => toNumber(r.margin_pct),
      render: (r) => {
        const m = toNumber(r.margin_pct);
        const color = m < 5 ? "text-danger" : m < 10 ? "text-accent" : "text-success";
        return <span className={`font-semibold ${color}`}>{formatPct(r.margin_pct)}</span>;
      },
    },
    {
      key: "net_cash_position_try",
      header: "Nakit Durumu",
      align: "right",
      render: (r) => <span className={toNumber(r.net_cash_position_try) < 0 ? "text-danger" : ""}>{formatCurrency(r.net_cash_position_try)}</span>,
    },
    { key: "rag_label_tr", header: "Durum", render: (r) => <RAGIndicator status={r.rag_status} label={r.rag_label_tr} reason={r.rag_label_tr} /> },
    {
      key: "planned_end_date",
      header: "Bitiş Tarihi",
      align: "right",
      render: (r) => <span className={r.overdue ? "text-danger" : ""}>{formatDate(r.planned_end_date)}</span>,
    },
  ];

  const chartData = (data?.cashflow_chart ?? []).map((c) => ({
    month: c.month,
    out: toNumber(c.out),
    in: toNumber(c.in),
    cumulative: toNumber(c.net_cumulative),
  }));

  return (
    <div>
      <PageHeader title="Ana Sayfa" subtitle="Tüm aktif projelerin finansal durumu" />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KPICard loading={loading} label="Aktif Proje Sayısı" value={String(k?.active_project_count ?? 0)} />
        <KPICard loading={loading} label="Toplam Sözleşme Değeri" value={formatCurrencyAbbrev(k?.total_contract_value_try)} />
        <KPICard
          loading={loading}
          label="Ağırlıklı Ort. Kar Marjı"
          value={formatPct(k?.weighted_avg_margin_pct)}
          alert={marginNum < 5 ? "red" : marginNum < 10 ? "amber" : null}
        />
        <KPICard
          loading={loading}
          label="Vadesi Geçmiş Ödemeler"
          value={String(k?.overdue_payment_count ?? 0)}
          alert={(k?.overdue_payment_count ?? 0) > 0 ? "red" : null}
        />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h2 className="mb-3 text-lg font-semibold text-primary">Proje Durumu</h2>
          <DataTable columns={columns} rows={data?.projects ?? []} loading={loading} emptyMessage="Henüz proje yok. İlk projenizi oluşturun." emptyAction={{ label: "Yeni Proje", onClick: () => navigate("/projects/new") }} onRowClick={(r) => navigate(`/projects/${r.id}/dashboard`)} />
        </div>

        <div>
          <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold text-primary">
            <Sparkles className="h-4 w-4 text-accent" /> Bugün Ne Yapmalısın
          </h2>
          <Card>
            <CardBody className="space-y-3">
              {briefing.length === 0 && <p className="text-sm text-text-secondary">Bugün için öncelikli bir işlem bulunmuyor.</p>}
              {briefing.slice(0, 8).map((item, i) => (
                <div key={i} className="border-b border-border pb-2 last:border-0">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-primary">{item.project_name}</span>
                    <SeverityBadge severity={item.severity} />
                  </div>
                  <p className="mt-1 text-sm">{item.issue}</p>
                  <p className="mt-0.5 text-xs text-text-secondary">→ {item.recommended_action}</p>
                </div>
              ))}
            </CardBody>
          </Card>
        </div>
      </div>

      <div className="mt-6">
        <h2 className="mb-3 text-lg font-semibold text-primary">Birleşik Nakit Akışı (Son 6 Ay)</h2>
        <Card>
          <CardBody>
            <CashFlowChart data={chartData} />
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const map: Record<string, string> = { high: "bg-danger", medium: "bg-accent", low: "bg-text-secondary" };
  const label: Record<string, string> = { high: "Yüksek", medium: "Orta", low: "Düşük" };
  return <span className={`rounded-full px-2 py-0.5 text-[10px] text-white ${map[severity] ?? "bg-text-secondary"}`}>{label[severity] ?? severity}</span>;
}
