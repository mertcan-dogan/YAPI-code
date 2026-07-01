import { AIDisclaimer } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { AIAlert } from "@/types";
import { formatDateTime } from "@/utils/format";
import { ExternalLink, Sparkles, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { Link } from "react-router-dom";

const SEV_BORDER: Record<string, string> = {
  high: "border-l-danger",
  medium: "border-l-accent",
  low: "border-l-text-secondary",
};

interface Props {
  alert: AIAlert;
  onDismiss: (id: string) => void;
  onFeedback: (id: string, feedback: string) => void;
  // CR-022-C: optional deep-link to the offending record (assurance findings).
  deepLinkHref?: string | null;
}

/**
 * Shared alert/finding card — used by both the health-alert list and the Finans
 * Güvence (assurance) view so dismiss + feedback + presentation stay identical.
 */
export function AlertCard({ alert: a, onDismiss, onFeedback, deepLinkHref }: Props) {
  return (
    <div className={cn("rounded-xl border border-l-4 border-border bg-surface p-4 shadow-sm", SEV_BORDER[a.severity])}>
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-brand" />
          <h3 className="font-semibold text-primary">{a.title_tr}</h3>
          <span className="rounded bg-navy-50 px-1.5 py-0.5 text-[10px] text-primary-light">AI Önerisi</span>
        </div>
        <button onClick={() => onDismiss(a.id)} className="text-text-secondary hover:text-danger" aria-label="Kapat">
          <X className="h-4 w-4" />
        </button>
      </div>
      <p className="mt-2 text-sm">{a.body_tr}</p>
      {a.recommended_action && <p className="mt-1 text-sm text-primary-light">→ {a.recommended_action}</p>}
      {a.reasoning && <p className="mt-2 rounded bg-bg p-2 text-xs text-text-secondary">{a.reasoning}</p>}
      {deepLinkHref && (
        <Link
          to={deepLinkHref}
          className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
        >
          <ExternalLink className="h-3.5 w-3.5" /> Kaydı incele
        </Link>
      )}
      <div className="mt-2 flex items-center justify-between">
        <p className="text-[11px] text-text-secondary">{formatDateTime(a.created_at)}</p>
        <div className="flex items-center gap-1 text-xs">
          <span className="text-text-secondary">Yararlı mı?</span>
          <button
            onClick={() => onFeedback(a.id, "useful")}
            className={cn("rounded p-1 hover:bg-green-50", a.feedback === "useful" && "text-success")}
            title="Kullanışlı"
            aria-label="Yararlı"
          >
            <ThumbsUp className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => onFeedback(a.id, "wrong")}
            className={cn("rounded p-1 hover:bg-red-50", a.feedback === "wrong" && "text-danger")}
            title="Yanlış"
            aria-label="Yararsız"
          >
            <ThumbsDown className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => onFeedback(a.id, "irrelevant")}
            className={cn("rounded px-1 hover:bg-bg", a.feedback === "irrelevant" && "text-text-primary")}
            title="İlgisiz"
          >
            İlgisiz
          </button>
        </div>
      </div>
      <AIDisclaimer />
    </div>
  );
}

/** Deep-link to the offending record for an assurance finding (mirrors the
 *  backend citation URLs). Returns null when there's nothing to link to. */
export function findingDeepLink(a: AIAlert): string | null {
  if (!a.project_id) return null;
  const pid = a.project_id;
  if (a.source_type === "client_invoice" && a.source_id) return `/projects/${pid}/invoices?highlight=${a.source_id}`;
  if (a.source_type === "cost_entry" && a.source_id) return `/projects/${pid}/dashboard?highlight=${a.source_id}`;
  if (a.source_type === "project") return `/projects/${pid}/dashboard`;
  return null;
}
