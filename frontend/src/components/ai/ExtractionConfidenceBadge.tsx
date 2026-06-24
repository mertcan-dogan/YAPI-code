import { Sparkles } from "lucide-react";
import { Badge } from "@/components/ui";
import { cn } from "@/lib/cn";

// CR-024: surface the AI document-extraction confidence (0..1) we already persist
// on cost entries and client invoices. This is a DISPLAY-ONLY signal — it never
// touches the financial math. Manual / standard-Excel rows have no score (NULL),
// so the badge renders nothing and those rows look untouched (graceful fallback).
type Band = "high" | "medium" | "low";

function band(c: number): Band {
  if (c >= 0.85) return "high";
  if (c >= 0.6) return "medium";
  return "low";
}

const VARIANT: Record<Band, "success" | "warning" | "danger"> = {
  high: "success",
  medium: "warning",
  low: "danger",
};

// Turkish (tr-TR) band labels shown in the tooltip / optional inline label.
const LABEL: Record<Band, string> = {
  high: "Yüksek güven",
  medium: "Orta güven",
  low: "Düşük güven — kontrol edin",
};

/**
 * Small AI-extraction confidence indicator for captured / AI-imported rows.
 * `confidence` is the persisted 0..1 score (string or number). When it is
 * null/undefined/blank/non-numeric the component renders nothing.
 */
export function ExtractionConfidenceBadge({
  confidence,
  showLabel = false,
  className = "",
}: {
  confidence: number | string | null | undefined;
  showLabel?: boolean;
  className?: string;
}) {
  if (confidence == null || confidence === "") return null;
  const c = typeof confidence === "string" ? Number(confidence) : confidence;
  if (!Number.isFinite(c)) return null;
  // Defensive clamp into [0, 1]; the backend already clamps on write.
  const clamped = Math.min(1, Math.max(0, c));
  const pct = Math.round(clamped * 100);
  const b = band(clamped);
  const title = `Yapay zekâ ile okundu — belge çıkarım güveni %${pct}. ${LABEL[b]}.`;

  return (
    <Badge variant={VARIANT[b]} title={title} aria-label={title} className={cn("gap-1", className)}>
      <Sparkles className="h-3 w-3 shrink-0" aria-hidden="true" />
      <span className="tabular">AI %{pct}</span>
      {showLabel && <span>· {LABEL[b]}</span>}
    </Badge>
  );
}
