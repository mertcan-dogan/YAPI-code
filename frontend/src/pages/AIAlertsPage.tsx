import { EmptyState, LoadError } from "@/components/EmptyState";
import { PageHeader } from "@/components/layout/AppLayout";
import { AIDisclaimer, Button, Card, CardBody } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useFetch } from "@/hooks/useFetch";
import { apiPost, apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { AIAlert } from "@/types";
import { formatDateTime } from "@/utils/format";
import { RefreshCw, Sparkles, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { useState } from "react";

const SEV_BORDER: Record<string, string> = { high: "border-l-danger", medium: "border-l-accent", low: "border-l-text-secondary" };

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
  const alerts = data ?? [];
  const count = (sev: string) => alerts.filter((a) => a.severity === sev).length;

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

  return (
    <div>
      <PageHeader
        title="Yapay Zeka Uyarıları"
        subtitle={meta && !meta.ai_available ? "AI şu an kullanılamıyor — kurallar tabanlı uyarılar gösteriliyor" : undefined}
        action={<Button variant="outline" loading={refreshing} onClick={refreshAll}><RefreshCw className="h-4 w-4" /> Tüm Uyarıları Yenile</Button>}
      />

      {/* CR-003-M: severity summary */}
      <div className="mb-4 flex flex-wrap gap-3">
        <SummaryChip label="Kritik" value={count("high")} color="#EF4444" />
        <SummaryChip label="Yüksek" value={count("medium")} color="#F59E0B" />
        <SummaryChip label="Orta" value={count("low")} color="#64748B" />
      </div>

      {loading ? (
        <p className="text-sm text-text-secondary">Yükleniyor...</p>
      ) : error ? (
        <Card><CardBody><LoadError onRetry={refetch} /></CardBody></Card>
      ) : alerts.length === 0 ? (
        <Card><CardBody><EmptyState message="Aktif yapay zeka uyarısı bulunmuyor." /></CardBody></Card>
      ) : (
        <div className="space-y-3">
          {alerts.map((a) => (
            <div key={a.id} className={cn("rounded-xl border border-l-4 border-border bg-surface p-4 shadow-sm", SEV_BORDER[a.severity])}>
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-brand" />
                  <h3 className="font-semibold text-primary">{a.title_tr}</h3>
                  <span className="rounded bg-navy-50 px-1.5 py-0.5 text-[10px] text-primary-light">AI Önerisi</span>
                </div>
                <button onClick={() => dismiss(a.id)} className="text-text-secondary hover:text-danger"><X className="h-4 w-4" /></button>
              </div>
              <p className="mt-2 text-sm">{a.body_tr}</p>
              {a.recommended_action && <p className="mt-1 text-sm text-primary-light">→ {a.recommended_action}</p>}
              {a.reasoning && <p className="mt-2 rounded bg-bg p-2 text-xs text-text-secondary">{a.reasoning}</p>}
              <div className="mt-2 flex items-center justify-between">
                <p className="text-[11px] text-text-secondary">{formatDateTime(a.created_at)}</p>
                {/* CR-003-M: feedback buttons */}
                <div className="flex items-center gap-1 text-xs">
                  <span className="text-text-secondary">Yararlı mı?</span>
                  <button onClick={() => sendFeedback(a.id, "useful")} className={cn("rounded p-1 hover:bg-green-50", (a as any).feedback === "useful" && "text-success")} title="Kullanışlı"><ThumbsUp className="h-3.5 w-3.5" /></button>
                  <button onClick={() => sendFeedback(a.id, "wrong")} className={cn("rounded p-1 hover:bg-red-50", (a as any).feedback === "wrong" && "text-danger")} title="Yanlış"><ThumbsDown className="h-3.5 w-3.5" /></button>
                  <button onClick={() => sendFeedback(a.id, "irrelevant")} className={cn("rounded px-1 hover:bg-bg", (a as any).feedback === "irrelevant" && "text-text-primary")} title="İlgisiz">İlgisiz</button>
                </div>
              </div>
              <AIDisclaimer />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
