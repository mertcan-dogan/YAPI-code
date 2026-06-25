// CR-011-D / CR-011 rich steps (UI) — Claude-Cowork-style agent "thinking steps".
//
// While the agent runs we show each step live (auto-expanded). When the answer
// is committed the steps collapse into a compact group toggle ("N adım
// tamamlandı"); past turns keep their collapsed group so any earlier turn can be
// re-expanded. Inside the group each step is its own collapsible row.
//
// HONESTY: we render ONLY the real fields the stream actually carries — there is
// no fabrication. Per step that can be: the model's reasoning (`thinking`, only
// when the backend thinking flag is on), its pre-tool narration (`note`), the
// cleaned tool args (`input`), the tool's aggregate result summary, and the row
// count. Any field that is absent is simply not rendered.
import { Check, ChevronDown, ChevronRight, Lightbulb, Loader2, Terminal } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { formatCurrency } from "@/utils/format";
import { TOOL_LABELS } from "./toolLabels";

// One recorded step. `tool === ""` ⇒ a reasoning/thinking step (no tool call).
export interface AgentStep {
  label: string;
  tool: string;
  // CR-011 rich steps (in-session only): the model's reasoning, its narration,
  // and the cleaned tool args. All optional — only present on the streamed turn.
  input?: Record<string, unknown> | null;
  note?: string | null;
  thinking?: string | null;
}

interface Props {
  steps: AgentStep[];
  // True only for the turn currently streaming: auto-expanded, last row spins.
  running?: boolean;
  // Per-tool row counts from the final payload (completed turns only).
  rowCounts?: Record<string, number>;
  // Per-tool aggregate result summaries from the final payload (completed turns).
  toolSummaries?: Record<string, Record<string, unknown>>;
  // The turn's total token usage — shown as a subtle per-chat counter.
  usage?: { input_tokens: number; output_tokens: number };
}

// Map a step to its Turkish header label + leading type-icon.
function stepKind(step: AgentStep) {
  if (!step.tool) return { label: "Düşünme süreci", Icon: Lightbulb };
  const mapped = TOOL_LABELS[step.tool];
  // A known tool shows its own Turkish name; an unmapped one the generic verb.
  return { label: mapped ?? "Komut çalıştırıldı", Icon: Terminal };
}

// Group summary: prefer the tool count when every step ran a tool, else steps.
function groupSummary(steps: AgentStep[]): string {
  const toolCount = steps.filter((s) => s.tool).length;
  if (toolCount > 1 && toolCount === steps.length) return `${toolCount} araç kullanıldı`;
  return `${steps.length} adım tamamlandı`;
}

// ≈ token counter, tr-TR. 4.100 → "4,1B" ("B" = bin / thousand).
function formatTokens(total: number): string {
  if (total >= 1000) {
    return `${(total / 1000).toLocaleString("tr-TR", { maximumFractionDigits: 1 })}B`;
  }
  return total.toLocaleString("tr-TR");
}

// --- Tool args ("Parametreler") — only known params, formatted readably. ----
// Mapping the known params keeps the detail clean and hides internal keys.
const PARAM_LABELS: Record<string, string> = {
  status: "Durum",
  project_id: "Proje",
  date_from: "Başlangıç",
  date_to: "Bitiş",
  relative_window: "Dönem",
  cost_category: "Maliyet kategorisi",
  supplier_name: "Tedarikçi",
  vendor_name: "Tedarikçi",
  subcontractor_id: "Alt yüklenici",
  payment_status: "Ödeme durumu",
  entry_type: "Kayıt tipi",
  invoice_type: "Fatura tipi",
  group_by: "Kırılım",
  top_n: "İlk N",
  window_days: "Gün",
  ownership_type: "Sahiplik",
  severity: "Önem",
  name: "Ad",
  title: "Başlık",
  note: "Not",
  due: "Vade",
  due_date: "Vade tarihi",
  target_kind: "Hedef türü",
  target_id: "Hedef",
  reason: "Gerekçe",
};

function formatParamValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "string") {
    // ISO date → tr-TR (gg.aa.yyyy).
    if (/^\d{4}-\d{2}-\d{2}/.test(value)) {
      const [y, m, d] = value.slice(0, 10).split("-");
      return `${d}.${m}.${y}`;
    }
    // UUID → a short, readable token (never the full id).
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-/i.test(value)) return `${value.slice(0, 8)}…`;
    return value;
  }
  return String(value);
}

function paramRows(input?: Record<string, unknown> | null): { label: string; value: string }[] {
  if (!input) return [];
  const rows: { label: string; value: string }[] = [];
  for (const [k, v] of Object.entries(input)) {
    const label = PARAM_LABELS[k];
    if (!label) continue; // hide unknown / internal keys
    const value = formatParamValue(v);
    if (value) rows.push({ label, value });
  }
  return rows;
}

// --- Tool result summary — only known scalar aggregates (totals/counts). -----
const SUMMARY_LABELS: Record<string, string> = {
  project_count: "Proje sayısı",
  active_count: "Aktif",
  ended_count: "Biten",
  category_count: "Kategori sayısı",
  vendor_count: "Tedarikçi sayısı",
  subcontractor_count: "Alt yüklenici sayısı",
  equipment_count: "Ekipman sayısı",
  invoice_count: "Fatura sayısı",
  finding_count: "Bulgu sayısı",
  count: "Adet",
  over_budget_category_count: "Bütçe aşan kategori",
  overdue_payable_count: "Vadesi geçmiş ödenecek (adet)",
  overdue_receivable_count: "Vadesi geçmiş tahsilat (adet)",
  total_try: "Toplam",
  total_amount_try: "Toplam tutar",
  total_with_vat_try: "Toplam (KDV dahil)",
  total_contract_value_try: "Toplam sözleşme",
  total_cost_try: "Toplam maliyet",
  total_paid_try: "Ödenen",
  total_remaining_try: "Kalan",
  total_committed_try: "Taahhüt",
  total_actual_try: "Gerçekleşen",
  total_revised_budget_try: "Revize bütçe",
  total_variance_try: "Sapma",
  total_retention_try: "Teminat",
  total_retention_held_try: "Tutulan teminat",
  total_estimated_rental_try: "Tahmini kira",
  total_fuel_maintenance_try: "Yakıt/bakım",
  estimated_rental_try: "Tahmini kira",
  fuel_maintenance_try: "Yakıt/bakım",
  overdue_payable_total_try: "Vadesi geçmiş ödenecek",
  overdue_receivable_total_try: "Vadesi geçmiş tahsilat",
};

function formatSummaryValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (key.endsWith("_try")) return formatCurrency(value as string | number);
  if (typeof value === "number") return value.toLocaleString("tr-TR");
  if (typeof value === "string" && /^-?\d+$/.test(value)) return Number(value).toLocaleString("tr-TR");
  return String(value);
}

function summaryRows(summary?: Record<string, unknown>): { label: string; value: string }[] {
  if (!summary) return [];
  const rows: { label: string; value: string }[] = [];
  for (const [k, v] of Object.entries(summary)) {
    const label = SUMMARY_LABELS[k];
    if (!label) continue; // skip nested (by_*/ranking) + unmapped keys
    if (v === null || v === undefined || typeof v === "object") continue;
    const value = formatSummaryValue(k, v);
    if (value) rows.push({ label, value });
    if (rows.length >= 6) break; // keep the detail compact
  }
  return rows;
}

function StepRow({
  step,
  rowCount,
  summary,
  active,
}: {
  step: AgentStep;
  rowCount?: number;
  summary?: Record<string, unknown>;
  active: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { label, Icon } = stepKind(step);
  // The non-stream fallback records steps with no live label — fall back to the
  // header label so the comment line is never empty.
  const comment = step.label || label;
  const params = paramRows(step.input);
  const summaries = summaryRows(summary);
  return (
    <div className="border-t border-border first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-[11px] font-medium text-text-secondary transition hover:text-brand"
      >
        {active ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-brand" />
        ) : (
          <Icon className="h-3.5 w-3.5 shrink-0 text-text-faint" />
        )}
        <span className="flex-1 truncate text-text-primary">{label}</span>
        {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
      </button>
      {/* Always-visible one-line comment (the live label, truncated). */}
      <p className="truncate px-3 pb-1.5 pl-8 text-[11px] text-text-secondary">{comment}</p>
      {/* Revealed detail — render ONLY the real fields that exist, in order:
          reasoning → narration → parameters → result summary + row count. */}
      {open && (
        <div className="space-y-2 px-3 pb-2 pl-8 text-[11px] text-text-secondary">
          {/* Model reasoning (only when the thinking flag is on). */}
          {step.thinking && (
            <div>
              <span className="font-medium text-text-primary">Model değerlendirmesi</span>
              <p className="mt-0.5 whitespace-pre-wrap text-text-secondary">{step.thinking}</p>
            </div>
          )}
          {/* Pre-tool narration. */}
          {step.note && <p className="whitespace-pre-wrap text-text-primary">{step.note}</p>}
          {/* Tool + its formatted parameters. */}
          {step.tool && (
            <div>
              <span className="font-medium text-text-primary">Araç:</span>{" "}
              <code className="rounded bg-bg px-1 py-0.5 text-[10px]">{step.tool}</code>
            </div>
          )}
          {params.length > 0 && (
            <div>
              <span className="font-medium text-text-primary">Parametreler</span>
              <ul className="mt-0.5 space-y-0.5">
                {params.map((p) => (
                  <li key={p.label}>
                    <span className="text-text-secondary">{p.label}:</span>{" "}
                    <span className="text-text-primary">{p.value}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {/* Result: the tool's aggregate summary + how many rows it read. */}
          {summaries.length > 0 && (
            <div>
              <span className="font-medium text-text-primary">Sonuç</span>
              <ul className="mt-0.5 space-y-0.5">
                {summaries.map((s) => (
                  <li key={s.label}>
                    <span className="text-text-secondary">{s.label}:</span>{" "}
                    <span className="text-text-primary">{s.value}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {typeof rowCount === "number" && rowCount > 0 && <div>{rowCount.toLocaleString("tr-TR")} kayıt okundu</div>}
        </div>
      )}
    </div>
  );
}

/**
 * Collapsible agent step group. Renders nothing when there are no steps (a pure
 * LLM answer with no tool calls) — no empty panel, no flicker.
 */
export function AgentSteps({ steps, running = false, rowCounts = {}, toolSummaries = {}, usage }: Props) {
  // Completed turns start collapsed; the running turn is always expanded.
  const [groupOpen, setGroupOpen] = useState(false);
  if (steps.length === 0) return null;

  const expanded = running || groupOpen;
  const totalTokens = usage ? (usage.input_tokens || 0) + (usage.output_tokens || 0) : 0;

  return (
    <div className={cn("rounded-lg border border-border bg-bg/50", running ? "mb-2" : "mt-2")}>
      {running ? (
        // Live: a static header (no toggle) — the steps stay expanded below.
        <div className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-text-secondary">
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-brand" />
          İşlem adımları
        </div>
      ) : (
        // Completed: compact group toggle with a subtle per-chat token counter.
        <button
          type="button"
          onClick={() => setGroupOpen((o) => !o)}
          aria-expanded={groupOpen}
          className="flex w-full items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-text-secondary transition hover:text-brand"
        >
          {groupOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          <Check className="h-3.5 w-3.5 text-success" />
          <span className="flex-1 text-left">{groupSummary(steps)}</span>
          {totalTokens > 0 && (
            <span className="shrink-0 font-normal text-text-faint">≈ {formatTokens(totalTokens)} token</span>
          )}
        </button>
      )}

      {expanded && (
        <div className="border-t border-border">
          {steps.map((s, i) => (
            <StepRow
              key={i}
              step={s}
              rowCount={s.tool ? rowCounts[s.tool] : undefined}
              summary={s.tool ? toolSummaries[s.tool] : undefined}
              // While running, the last recorded step is the one in progress.
              active={running && i === steps.length - 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}
