import { Skeleton } from "@/components/ui";
import { useFetch } from "@/hooks/useFetch";
import { cn } from "@/lib/cn";
import { formatCurrencyAbbrev, formatDate } from "@/utils/format";
import { FileText, Inbox } from "lucide-react";
import { useState } from "react";

interface FeedItem {
  id: string;
  label: string;
  title?: string;
  source?: string | null;
  project?: string | null;
  category?: string;
  amount_try: string;
  status: string;
  date: string;
}

interface DocumentFeed {
  faturalar: FeedItem[];
  hakedisler: FeedItem[];
  ek_isler: FeedItem[];
}

const TABS: { key: keyof DocumentFeed; label: string }[] = [
  { key: "faturalar", label: "Faturalar" },
  { key: "hakedisler", label: "Hakedişler" },
  { key: "ek_isler", label: "Ek İşler" },
];

function statusPill(status: string): { label: string; cls: string } {
  switch (status) {
    case "paid":
      return { label: "Ödendi", cls: "bg-green-50 text-success" };
    case "unpaid":
      return { label: "Ödenmedi", cls: "bg-amber-50 text-warning" };
    case "incelemede":
      return { label: "İncelemede", cls: "bg-navy-50 text-brand" };
    case "pending":
      return { label: "Beklemede", cls: "bg-amber-50 text-warning" };
    case "approved":
      return { label: "Onaylandı", cls: "bg-green-50 text-success" };
    case "rejected":
      return { label: "Reddedildi", cls: "bg-red-50 text-danger" };
    default:
      return { label: status, cls: "bg-bg text-text-secondary" };
  }
}

/**
 * Gelen Belgeler — tabbed feed of recent supplier invoices (Faturalar), client
 * applications for payment (Hakedişler) and variations (Ek İşler), from the
 * /dashboard/document-feed endpoint. Real records & statuses only.
 */
export function IncomingWorkflowCard() {
  const { data, loading } = useFetch<DocumentFeed>("/dashboard/document-feed");
  const [tab, setTab] = useState<keyof DocumentFeed>("faturalar");
  const items = data?.[tab] ?? [];

  return (
    <div className="border-t border-border">
        <div className="flex items-center gap-1 border-b border-border px-3 pt-2">
          {TABS.map((t) => {
            const count = data?.[t.key]?.length ?? 0;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cn(
                  "flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm transition-colors",
                  tab === t.key ? "border-brand font-medium text-primary" : "border-transparent text-text-secondary hover:text-text-primary"
                )}
              >
                {t.label}
                <span className={cn("rounded-full px-1.5 text-[10px] font-semibold", tab === t.key ? "bg-navy-50 text-brand" : "bg-bg text-text-secondary")}>{count}</span>
              </button>
            );
          })}
        </div>

        <div className="divide-y divide-border">
          {loading ? (
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex items-center justify-between gap-3 px-4 py-3">
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-4 w-16" />
              </div>
            ))
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-bg">
                <Inbox className="h-5 w-5 text-text-disabled" />
              </div>
              <p className="text-sm text-text-secondary">Bu sekmede gösterilecek kayıt yok.</p>
            </div>
          ) : (
            items.map((it) => {
              const pill = statusPill(it.status);
              return (
                <div key={it.id} className="flex items-center justify-between gap-3 px-4 py-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-navy-50 text-brand">
                      <FileText className="h-4 w-4" />
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-text-primary" title={it.title ?? it.label}>
                        {it.title ?? it.label}
                      </p>
                      <p className="truncate text-xs text-text-secondary">
                        {[it.project, it.source || it.category].filter(Boolean).join(" · ") || "—"}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <div className="text-right">
                      <p className="tabular text-sm font-semibold text-text-primary">{formatCurrencyAbbrev(it.amount_try)}</p>
                      <p className="text-[11px] text-text-secondary">{formatDate(it.date)}</p>
                    </div>
                    <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium", pill.cls)}>{pill.label}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>
    </div>
  );
}
