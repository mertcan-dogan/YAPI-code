import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Card, CardBody } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useFetch } from "@/hooks/useFetch";
import { apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { AIAlert } from "@/types";
import { formatDateTime } from "@/utils/format";
import { Sparkles, X } from "lucide-react";

const SEV_BORDER: Record<string, string> = { high: "border-l-danger", medium: "border-l-accent", low: "border-l-text-secondary" };

export default function AIAlertsPage() {
  const { data, meta, loading, refetch } = useFetch<AIAlert[]>("/ai/alerts");
  const alerts = data ?? [];

  const dismiss = async (id: string) => {
    try {
      await apiPut(`/ai/alerts/${id}/dismiss`, {});
      toast.success("Uyarı kapatıldı");
      refetch();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  return (
    <div>
      <PageHeader title="Yapay Zeka Uyarıları" subtitle={meta && !meta.ai_available ? "AI şu an kullanılamıyor — kurallar tabanlı uyarılar gösteriliyor" : undefined} />
      {loading ? (
        <p className="text-sm text-text-secondary">Yükleniyor...</p>
      ) : alerts.length === 0 ? (
        <Card><CardBody><EmptyState message="Aktif yapay zeka uyarısı bulunmuyor." /></CardBody></Card>
      ) : (
        <div className="space-y-3">
          {alerts.map((a) => (
            <div key={a.id} className={cn("rounded-lg border border-l-4 border-border bg-surface p-4", SEV_BORDER[a.severity])}>
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-accent" />
                  <h3 className="font-semibold text-primary">{a.title_tr}</h3>
                  <span className="rounded bg-navy-50 px-1.5 py-0.5 text-[10px] text-primary-light">AI Önerisi</span>
                </div>
                <button onClick={() => dismiss(a.id)} className="text-text-secondary hover:text-danger"><X className="h-4 w-4" /></button>
              </div>
              <p className="mt-2 text-sm">{a.body_tr}</p>
              {a.recommended_action && <p className="mt-1 text-sm text-primary-light">→ {a.recommended_action}</p>}
              {a.reasoning && <p className="mt-2 rounded bg-bg p-2 text-xs text-text-secondary">{a.reasoning}</p>}
              <p className="mt-2 text-[11px] text-text-secondary">{formatDateTime(a.created_at)}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
