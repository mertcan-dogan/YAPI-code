import { AlertCard } from "@/components/ai/AlertCard";
import { FinansGuvence } from "@/components/ai/FinansGuvence";
import { EmptyState, LoadError } from "@/components/EmptyState";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Card, CardBody } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useFetch } from "@/hooks/useFetch";
import { apiPost, apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { AIAlert } from "@/types";
import { RefreshCw } from "lucide-react";
import { useState } from "react";

function SummaryChip({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-2">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="text-lg font-bold" style={{ color }}>{value}</div>
    </div>
  );
}

export default function AIAlertsPage() {
  const { data, meta, loading, refetch, error } = useFetch<AIAlert[]>("/ai/alerts");
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<"health" | "assurance">("health");
  const alerts = data ?? [];

  // CR-022-C: assurance findings carry a dedup_key; legacy health alerts do not.
  const findings = alerts.filter((a) => !!a.dedup_key);
  const healthAlerts = alerts.filter((a) => !a.dedup_key);
  const count = (sev: string) => healthAlerts.filter((a) => a.severity === sev).length;

  const dismiss = async (id: string) => {
    try {
      await apiPut(`/ai/alerts/${id}/dismiss`, {});
      toast.success("Uyarı kapatıldı");
      refetch();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const sendFeedback = async (id: string, feedback: string) => {
    try {
      await apiPut(`/ai/alerts/${id}/feedback`, { feedback });
      toast.success("Geri bildiriminiz kaydedildi");
      refetch();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const refreshAll = async () => {
    setRefreshing(true);
    try {
      await apiPost("/ai/analyze-all");
      toast.success("Uyarılar yenilendi");
      refetch();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setRefreshing(false);
    }
  };

  const TabButton = ({ id, label, n }: { id: "health" | "assurance"; label: string; n: number }) => (
    <button
      onClick={() => setTab(id)}
      className={cn(
        "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
        tab === id ? "bg-brand text-white" : "bg-surface text-text-secondary hover:bg-navy-50"
      )}
    >
      {label} ({n})
    </button>
  );

  return (
    <div>
      <PageHeader
        title="Yapay Zeka Uyarıları"
        subtitle={meta && !meta.ai_available ? "AI şu an kullanılamıyor — kurallar tabanlı uyarılar gösteriliyor" : undefined}
        action={<Button variant="outline" loading={refreshing} onClick={refreshAll}><RefreshCw className="h-4 w-4" /> Tüm Uyarıları Yenile</Button>}
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <TabButton id="health" label="Sağlık Uyarıları" n={healthAlerts.length} />
        <TabButton id="assurance" label="Finans Güvence" n={findings.length} />
      </div>

      {loading ? (
        <p className="text-sm text-text-secondary">Yükleniyor...</p>
      ) : error ? (
        <Card><CardBody><LoadError onRetry={refetch} /></CardBody></Card>
      ) : tab === "assurance" ? (
        <FinansGuvence findings={findings} onDismiss={dismiss} onFeedback={sendFeedback} onRefetch={refetch} />
      ) : (
        <>
          {/* CR-003-M: severity summary for health alerts. */}
          <div className="mb-4 flex flex-wrap gap-3">
            <SummaryChip label="Kritik" value={count("high")} color="#EF4444" />
            <SummaryChip label="Yüksek" value={count("medium")} color="#F59E0B" />
            <SummaryChip label="Orta" value={count("low")} color="#64748B" />
          </div>
          {healthAlerts.length === 0 ? (
            <Card><CardBody><EmptyState message="Aktif yapay zeka uyarısı bulunmuyor." /></CardBody></Card>
          ) : (
            <div className="space-y-3">
              {healthAlerts.map((a) => (
                <AlertCard key={a.id} alert={a} onDismiss={dismiss} onFeedback={sendFeedback} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
