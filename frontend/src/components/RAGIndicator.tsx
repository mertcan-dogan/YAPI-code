import { COLORS } from "@/constants";
import type { RAG } from "@/types";

const DOT: Record<RAG, string> = {
  green: COLORS.success,
  amber: COLORS.accent,
  red: COLORS.danger,
};

// RAG Indicator — coloured dot with tooltip reason (Section 6.5)
export function RAGIndicator({ status, reason, label }: { status: RAG; reason?: string; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5" title={reason}>
      <span className="inline-block h-3 w-3 rounded-full" style={{ backgroundColor: DOT[status] }} />
      {label && <span className="text-xs text-text-secondary">{label}</span>}
    </span>
  );
}
