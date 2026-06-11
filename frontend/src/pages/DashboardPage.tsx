import { CashFlowChart } from "@/components/charts";
import { AIDisclaimer, Card, CardBody } from "@/components/ui";
import { KPICard } from "@/components/KPICard";
import { OverduePaymentsModal, LowMarginModal } from "@/components/dashboard/DashboardModals";
import { PageHeader } from "@/components/layout/AppLayout";
import { RAGIndicator } from "@/components/RAGIndicator";
import { DataTable, type Column } from "@/components/DataTable";
import { useFetch } from "@/hooks/useFetch";
import { apiGet } from "@/lib/api";
import { useAISummaryStore } from "@/store/aiSummary";
import { formatCurrency, formatCurrencyAbbrev, formatDate, formatDateTime, formatPct, toNumber } from "@/utils/format";
import { CheckCircle2, Info, RefreshCw, Sparkles } from "lucide-react";
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
  const { data, loading, refetch } = useFetch<DashboardData>("/dashboard");
  const [briefing, setBriefing] = useState<any[]>([]);
  const [briefingState, setBriefingState] = useState<"loading" | "ready" | "error">("loading");
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [overdueOpen, setOverdueOpen] = useState(false);
  const [marginOpen, setMarginOpen] = useState(false);
  const { getSummary, setSummary, clearSummary } = useAISummaryStore();
  const CACHE_KEY = "dashboard-summary";

  // CR-005-G: fetch the briefing and cache it (per-page) so navigating away and
  // back does not re-trigger the AI call.
  const fetchBriefing = () => {
    setBriefingState("loading");
    apiGet("/ai/daily-briefing")
      .then((r) => {
        setBriefing(r.data);
        setBriefingState("ready");
        setSummary(CACHE_KEY, JSON.stringify(r.data));
        setGeneratedAt(getSummary(CACHE_KEY)?.generatedAt ?? new Date().toISOString());
      })
      .catch(() => {
        setBriefing([]);
        setBriefingState("error");
      });
  };

  useEffect(() => {
    const cached = getSummary(CACHE_KEY);
    if (cached) {
      // Cache hit — show stored briefing, skip the API call.
      try {
        setBriefing(JSON.parse(cached.content));
      } catch {
        setBriefing([]);
      }
      setGeneratedAt(cached.generatedAt);
      setBriefingState("ready");
      return;
    }
    fetchBriefing();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRefreshBriefing = () => {
    clearSummary(CACHE_KEY);
    fetchBriefing();
  };

  const k = data?.kpis;
  const marginNum = toNumber(k?.weighted_avg_margin_pct);

  const columns: Column<any>[] = [
    {
      key: "name",
      header: "Proje Adı",
      sortable: true,
      maxWidth: 220,
      render: (r) => (
        <span className="flex items-center gap-2 truncate font-medium text-primary" title={r.name}>
          <RAGIndicator status={r.rag_status} reason={r.rag_label_tr} /> <span className="truncate">{r.name}</span>
        </span>
      ),
    },
    { key: "client_name", header: "İşveren", maxWidth: 160 },
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
        <KPICard
          loading={loading}
          label="Aktif Proje Sayısı"
          value={String(k?.active_project_count ?? 0)}
          onClick={() => navigate("/projects")}
        />
        <KPICard loading={loading} label="Toplam Sözleşme Değeri" value={formatCurrencyAbbrev(k?.total_contract_value_try)} />
        <KPICard
          loading={loading}
          label="Ağırlıklı Ort. Kar Marjı"
          value={formatPct(k?.weighted_avg_margin_pct)}
          alert={marginNum < 5 ? "red" : marginNum < 10 ? "amber" : null}
          onClick={() => setMarginOpen(true)}
        />
        <KPICard
          loading={loading}
          label="Vadesi Geçmiş Ödemeler"
          value={String(k?.overdue_payment_count ?? 0)}
          alert={(k?.overdue_payment_count ?? 0) > 0 ? "red" : null}
          onClick={() => setOverdueOpen(true)}
        />
      </div>

      <OverduePaymentsModal
        open={overdueOpen}
        onClose={() => setOverdueOpen(false)}
        onChanged={refetch}
        onGoToReminders={() => navigate("/reminders")}
      />
      <LowMarginModal open={marginOpen} onClose={() => setMarginOpen(false)} projects={data?.projects ?? []} onSelect={(id) => { setMarginOpen(false); navigate(`/projects/${id}/dashboard`); }} />

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h2 className="mb-3 text-lg font-semibold text-primary">Proje Durumu</h2>
          <DataTable columns={columns} rows={data?.projects ?? []} loading={loading} minWidth={900} emptyMessage="Henüz proje yok. İlk projenizi oluşturun." emptyAction={{ label: "Yeni Proje", onClick: () => navigate("/projects/new") }} onRowClick={(r) => navigate(`/projects/${r.id}/dashboard`)} />
        </div>

        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-primary">
              <Sparkles className="h-4 w-4 text-accent" /> Bugün Ne Yapmalısın
            </h2>
            <div className="flex items-center gap-2">
              {generatedAt && (
                <span className="text-[11px] italic text-text-secondary">
                  Son güncelleme: {formatDateTime(generatedAt)}
                </span>
              )}
              <button
                onClick={handleRefreshBriefing}
                disabled={briefingState === "loading"}
                title="Yenile"
                className="rounded p-1 text-text-secondary hover:text-primary disabled:opacity-50"
                aria-label="Yenile"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${briefingState === "loading" ? "animate-spin" : ""}`} />
              </button>
            </div>
          </div>
          <Card>
            <CardBody className="space-y-3">
              {briefingState === "loading" && (
                <div className="flex items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-accent">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />
                  Yapay zeka projelerinizi analiz ediyor…
                </div>
              )}
              {briefingState === "error" && (
                <div className="flex items-center gap-2 rounded-md bg-bg px-3 py-2 text-sm text-text-secondary">
                  <Info className="h-4 w-4" />
                  Yapay zeka şu an kullanılamıyor. Lütfen bekleyin.
                </div>
              )}
              {briefingState === "ready" && briefing.length === 0 && (
                <div className="flex items-center gap-2 rounded-md bg-green-50 px-3 py-2 text-sm text-success">
                  <CheckCircle2 className="h-4 w-4" />
                  Bugün için öncelikli işlem bulunmuyor.
                </div>
              )}
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
              {briefingState === "ready" && <AIDisclaimer />}
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
