import { LoadError } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui";
import { useFetch } from "@/hooks/useFetch";
import { formatCurrencyAbbrev } from "@/utils/format";
import { Calculator, CheckCircle2, ClipboardCheck, PlusSquare, Receipt, Trash2, Users, type LucideIcon } from "lucide-react";

interface ApprovalItem {
  kind: string;
  kind_label: string;
  id: string;
  project_name: string;
  description: string;
  amount_try: string | null;
  created_at: string;
}

const KIND_ICON: Record<string, LucideIcon> = {
  cost_entry: Receipt,
  budget_change: Calculator,
  variation: PlusSquare,
  subcontractor: Users,
  deletion: Trash2,
};

function timeAgo(iso: string): string {
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "az önce";
  if (m < 60) return `${m} dk önce`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} sa önce`;
  return `${Math.floor(h / 24)} gün önce`;
}

/**
 * Onay Bekleyenler — director-only panel surfacing the pending /approvals queue
 * on the dashboard. The parent gates rendering on the director role.
 */
export function ApprovalsPanel({ onGoToApprovals }: { onGoToApprovals: () => void }) {
  const { data, loading, error, refetch } = useFetch<ApprovalItem[]>("/approvals");
  const items = data ?? [];

  return (
    <div className="border-t border-border">
      {loading ? (
          <div className="space-y-3 p-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : error ? (
          <LoadError message="Onaylar yüklenemedi." onRetry={refetch} />
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-green-50">
              <CheckCircle2 className="h-5 w-5 text-success" />
            </div>
            <p className="text-sm text-text-secondary">Onay bekleyen işlem yok.</p>
          </div>
        ) : (
          <>
            <div className="divide-y divide-border">
              {items.slice(0, 6).map((it) => {
                const Icon = KIND_ICON[it.kind] ?? ClipboardCheck;
                return (
                  <div key={it.id} className="flex items-center justify-between gap-3 px-4 py-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-warning">
                        <Icon className="h-4 w-4" />
                      </span>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-text-primary" title={it.description || it.kind_label}>
                          {it.description || it.kind_label}
                        </p>
                        <p className="truncate text-xs text-text-secondary">
                          {[it.kind_label, it.project_name].filter(Boolean).join(" · ")} · {timeAgo(it.created_at)}
                        </p>
                      </div>
                    </div>
                    {it.amount_try != null && (
                      <span className="tabular shrink-0 text-sm font-semibold text-text-primary">{formatCurrencyAbbrev(it.amount_try)}</span>
                    )}
                  </div>
                );
              })}
            </div>
            <button
              onClick={onGoToApprovals}
              className="flex w-full items-center justify-center gap-1 border-t border-border py-2.5 text-sm font-medium text-brand hover:bg-navy-50"
            >
              Tüm onaylar →
            </button>
          </>
        )}
    </div>
  );
}
