import { ChevronDown, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { formatDateTime } from "@/utils/format";
import { toolLabel } from "./toolLabels";

interface Props {
  toolsUsed?: string[];
  rowCounts?: Record<string, number>;
  // Citations stay rendered inline under the answer; we only summarise the count
  // here (cleaner than relocating them — see CR-024 §2.2 decision).
  citationCount?: number;
  generatedAt?: string;
}

/**
 * CR-024-B — "AI nasıl çalıştı?" explainability panel.
 *
 * Built ONLY from the real agent response fields (tools_used, row_counts,
 * citations, generated_at). Never fabricates: a degraded answer with no tools
 * shows an honest empty state. Collapsed by default.
 */
export function AiExplainPanel({ toolsUsed = [], rowCounts = {}, citationCount = 0, generatedAt }: Props) {
  const [open, setOpen] = useState(false);
  const totalRows = Object.values(rowCounts).reduce((sum, n) => sum + (Number(n) || 0), 0);
  const hasTools = toolsUsed.length > 0;

  // Collapse repeated identical tool calls into one line with a count
  // (e.g. the same tool called 6× → "… ×6"), preserving first-use order.
  const groupedTools = useMemo(() => {
    const order: string[] = [];
    const counts: Record<string, number> = {};
    for (const t of toolsUsed) {
      if (!(t in counts)) order.push(t);
      counts[t] = (counts[t] ?? 0) + 1;
    }
    return order.map((name) => ({ name, count: counts[name] }));
  }, [toolsUsed]);

  return (
    <div className="mt-2 rounded-lg border border-border bg-bg/50">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-text-secondary transition hover:text-brand"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        AI nasıl çalıştı?
      </button>

      {open && (
        <div className="space-y-2 border-t border-border px-3 py-2 text-[11px] text-text-secondary">
          {/* Kullanılan araçlar */}
          <div>
            <div className="font-medium text-text-primary">Kullanılan araçlar</div>
            {hasTools ? (
              <ul className="mt-1 space-y-0.5">
                {groupedTools.map((t) => (
                  <li key={t.name}>
                    • {toolLabel(t.name)}
                    {t.count > 1 && <span className="text-text-faint"> ×{t.count}</span>}
                  </li>
                ))}
              </ul>
            ) : (
              // Honest empty state for degraded / no-tool answers (§0.2.2).
              <p className="mt-1">Bu yanıt için veri aracı kullanılmadı.</p>
            )}
          </div>

          {/* Okunan kayıt sayısı — omitted when empty */}
          {totalRows > 0 && (
            <div>
              <span className="font-medium text-text-primary">Okunan kayıt:</span> {totalRows} kayıt okundu
            </div>
          )}

          {/* Kaynaklar — citations are listed inline; summarise the count here */}
          {citationCount > 0 && (
            <div>
              <span className="font-medium text-text-primary">Kaynaklar:</span> {citationCount} kayıt yanıtın altında bağlantı olarak gösterildi
            </div>
          )}

          {/* Zaman */}
          {generatedAt && (
            <div>
              <span className="font-medium text-text-primary">Zaman:</span> {formatDateTime(generatedAt)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
