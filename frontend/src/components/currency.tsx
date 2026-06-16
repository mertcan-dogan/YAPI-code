import { cn } from "@/lib/cn";
import { useCurrency, type CurrencyMode } from "@/store/currency";
import { formatDate, formatNumber, formatUSD } from "@/utils/format";
import { AlertTriangle } from "lucide-react";

const OPTIONS: { key: CurrencyMode; label: string; title: string }[] = [
  { key: "try", label: "₺", title: "Sadece TRY" },
  { key: "usd", label: "$", title: "Sadece USD" },
  { key: "both", label: "İkisi de", title: "TRY ve USD birlikte" },
];

/** Three-way ₺ / $ / İkisi de display toggle (per-user, persisted). */
export function CurrencyToggle() {
  const { mode, setMode } = useCurrency();
  return (
    <div className="flex gap-0.5 rounded-md border border-border p-0.5" role="group" aria-label="Para birimi görünümü">
      {OPTIONS.map((o) => (
        <button
          key={o.key}
          onClick={() => setMode(o.key)}
          title={o.title}
          className={cn(
            "rounded px-2.5 py-1 text-sm transition-colors",
            mode === o.key ? "bg-primary text-white" : "text-text-secondary hover:text-primary"
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** True when the USD column/figures should be visible (not in TRY-only mode). */
export function useShowUsd(): boolean {
  return useCurrency((s) => s.mode) !== "try";
}

/**
 * A USD amount snapshotted at a row's relevant date. Renders "—" when the
 * snapshot is missing (null) — never $0. Shows the snapshot rate + date on hover,
 * and visibly marks PROVISIONAL (unpaid) rows whose rate is not the
 * payment-date rate yet (italic + "~" + tooltip).
 */
export function UsdAmountCell({
  amountUsd,
  rate,
  relevantDate,
  paid,
}: {
  amountUsd?: string | null;
  rate?: string | null;
  relevantDate?: string | null;
  paid: boolean;
}) {
  if (amountUsd === null || amountUsd === undefined) {
    return <span className="text-text-disabled">—</span>;
  }
  const dateStr = relevantDate ? formatDate(relevantDate) : "—";
  const title = rate
    ? paid
      ? `Ödeme günü kuru: ${formatNumber(rate)} ₺ — ${dateStr}`
      : `Tahmini kur: ${formatNumber(rate)} ₺ — ${dateStr} · ödeme yapılınca güncellenecek`
    : undefined;
  return (
    <span title={title} className={cn("tabular", !paid && "italic text-text-secondary")}>
      {!paid && "~"}
      {formatUSD(amountUsd)}
    </span>
  );
}

/**
 * Honesty note shown next to a USD total: a SQL SUM silently drops rows with a
 * null snapshot, so warn when some are missing (the total is understated).
 */
export function UsdMissingNote({ count }: { count?: number | null }) {
  if (!count || count <= 0) return null;
  return (
    <span
      className="ml-2 inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-accent"
      title="Bu kayıtlar için kur bulunamadı; USD toplamı eksik olabilir."
    >
      <AlertTriangle className="h-3 w-3" /> {count} kayıt için kur bulunamadı
    </span>
  );
}
