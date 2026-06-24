// CR-011-D (UI) — Claude-Cowork-style agent "thinking steps".
//
// While the agent runs we show each step live (auto-expanded). When the answer
// is committed the steps collapse into a compact group toggle ("N adım
// tamamlandı"); past turns keep their collapsed group so any earlier turn can be
// re-expanded. Inside the group each step is its own collapsible row.
//
// HONESTY: the agent stream only carries, per step, a Turkish `label` (present
// tense, from the SSE `step` event) and the raw `tool` name (may be empty for a
// reasoning step). The final payload adds per-tool `row_counts`. We render ONLY
// those real fields — there is no reasoning transcript or tool output in the
// stream to reveal, so the detail never fabricates one.
import { Check, ChevronDown, ChevronRight, Lightbulb, Loader2, Terminal } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { TOOL_LABELS } from "./toolLabels";

// One recorded step. `tool === ""` ⇒ a reasoning/thinking step (no tool call).
export interface AgentStep {
  label: string;
  tool: string;
}

interface Props {
  steps: AgentStep[];
  // True only for the turn currently streaming: auto-expanded, last row spins.
  running?: boolean;
  // Per-tool row counts from the final payload (completed turns only).
  rowCounts?: Record<string, number>;
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

function StepRow({
  step,
  rowCount,
  active,
}: {
  step: AgentStep;
  rowCount?: number;
  active: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { label, Icon } = stepKind(step);
  // The non-stream fallback records steps with no live label — fall back to the
  // header label so the comment line is never empty.
  const comment = step.label || label;
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
      {/* Revealed detail — only the real fields the stream actually carries. */}
      {open && (
        <div className="space-y-1 px-3 pb-2 pl-8 text-[11px] text-text-secondary">
          <p className="whitespace-pre-wrap text-text-primary">{comment}</p>
          {step.tool && (
            <div>
              <span className="font-medium text-text-primary">Araç:</span>{" "}
              <code className="rounded bg-bg px-1 py-0.5 text-[10px]">{step.tool}</code>
            </div>
          )}
          {typeof rowCount === "number" && rowCount > 0 && <div>{rowCount} kayıt okundu</div>}
        </div>
      )}
    </div>
  );
}

/**
 * Collapsible agent step group. Renders nothing when there are no steps (a pure
 * LLM answer with no tool calls) — no empty panel, no flicker.
 */
export function AgentSteps({ steps, running = false, rowCounts = {} }: Props) {
  // Completed turns start collapsed; the running turn is always expanded.
  const [groupOpen, setGroupOpen] = useState(false);
  if (steps.length === 0) return null;

  const expanded = running || groupOpen;

  return (
    <div className={cn("rounded-lg border border-border bg-bg/50", running ? "mb-2" : "mt-2")}>
      {running ? (
        // Live: a static header (no toggle) — the steps stay expanded below.
        <div className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-text-secondary">
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-brand" />
          İşlem adımları
        </div>
      ) : (
        // Completed: compact group toggle.
        <button
          type="button"
          onClick={() => setGroupOpen((o) => !o)}
          aria-expanded={groupOpen}
          className="flex w-full items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-text-secondary transition hover:text-brand"
        >
          {groupOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          <Check className="h-3.5 w-3.5 text-success" />
          {groupSummary(steps)}
        </button>
      )}

      {expanded && (
        <div className="border-t border-border">
          {steps.map((s, i) => (
            <StepRow
              key={i}
              step={s}
              rowCount={s.tool ? rowCounts[s.tool] : undefined}
              // While running, the last recorded step is the one in progress.
              active={running && i === steps.length - 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}
