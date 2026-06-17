// Proje Sağlığı — on-track health math (CR redesign). Pure + deterministic so it
// can be unit-tested. Compares three percentages to flag when a project is
// spending (or burning calendar) faster than it is building.
//
// All percentages are on a 0–100 scale (e.g. 40 means 40%), matching the
// backend's completion_pct / margin_pct convention.
//
// Graceful "not enough data": a percentage whose denominator is 0 (no budget) or
// whose input is a blank default (completion 0 with no milestones, missing dates)
// is treated as UNKNOWN — it renders "—", not "%0,0", and is excluded from the
// red/amber/green verdict so missing inputs never produce a false "Riskli".

export type HealthSignal = "green" | "amber" | "red" | "unknown";

export interface ProjectHealthInput {
  completionPct: number; // % işin tamamlanma oranı (0–100)
  hasMilestones?: boolean; // milestone-derived progress exists → completion is real even at 0
  actualCostTry: number; // gerçekleşen maliyet (₺)
  revisedBudgetTry: number; // revize bütçe (₺)
  startDate: string | null | undefined;
  plannedEndDate: string | null | undefined;
  today?: Date; // injectable for tests; defaults to now
}

export interface ProjectHealth {
  completionPct: number; // clamped 0–100 (meaningful only when completionKnown)
  costPct: number | null; // gerçekleşen ÷ revize bütçe × 100; null when budget is 0
  timePct: number | null; // geçen süre oranı 0–100; null when dates missing/invalid
  completionKnown: boolean;
  costKnown: boolean;
  timeKnown: boolean;
  costGap: number | null; // costPct − completionPct (>0 ⇒ spending ahead); null if either side unknown
  timeGap: number | null; // timePct − completionPct (>0 ⇒ calendar ahead); null if either side unknown
  signal: HealthSignal;
}

/** Clamp any number into the 0–100 band (non-finite → 0). */
export function clampPct(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

/** Whether start/end define a usable, positive schedule span. */
export function hasValidSpan(
  startDate: string | null | undefined,
  plannedEndDate: string | null | undefined,
): boolean {
  if (!startDate || !plannedEndDate) return false;
  const start = new Date(startDate).getTime();
  const end = new Date(plannedEndDate).getTime();
  return Number.isFinite(start) && Number.isFinite(end) && end > start;
}

/**
 * Share of the planned schedule that has elapsed today, clamped 0–100.
 * Returns 0 for missing/invalid dates or a non-positive span.
 */
export function timeElapsedPct(
  startDate: string | null | undefined,
  plannedEndDate: string | null | undefined,
  today: Date = new Date(),
): number {
  if (!hasValidSpan(startDate, plannedEndDate)) return 0;
  const start = new Date(startDate!).getTime();
  const end = new Date(plannedEndDate!).getTime();
  return clampPct(((today.getTime() - start) / (end - start)) * 100);
}

// A project is "in line" while cost/time stay within this many points of
// completion; beyond RED_GAP the lead is treated as a real risk.
const IN_LINE_TOLERANCE = 5;
const RED_GAP = 20;

/**
 * Health verdict computed ONLY from inputs that actually exist:
 * - completion is "known" when milestones exist or a real (>0) completion% is set;
 * - cost% is known only when there is a revize bütçe (>0);
 * - time% is known only when the schedule span is valid.
 * The signal compares the known lead indicators (cost/time) against completion.
 * With no usable comparison the signal is "unknown" — never a false red.
 */
export function computeProjectHealth(input: ProjectHealthInput): ProjectHealth {
  const completionPct = clampPct(input.completionPct);
  const completionKnown = !!input.hasMilestones || input.completionPct > 0;

  const costKnown = input.revisedBudgetTry > 0;
  const costPct = costKnown ? (input.actualCostTry / input.revisedBudgetTry) * 100 : null;

  const timeKnown = hasValidSpan(input.startDate, input.plannedEndDate);
  const timePct = timeKnown ? timeElapsedPct(input.startDate, input.plannedEndDate, input.today ?? new Date()) : null;

  const costGap = completionKnown && costPct != null ? costPct - completionPct : null;
  const timeGap = completionKnown && timePct != null ? timePct - completionPct : null;

  const leads = [costGap, timeGap].filter((g): g is number => g != null);
  let signal: HealthSignal;
  if (!completionKnown || leads.length === 0) {
    signal = "unknown";
  } else {
    const lead = Math.max(...leads);
    signal = lead <= IN_LINE_TOLERANCE ? "green" : lead <= RED_GAP ? "amber" : "red";
  }

  return { completionPct, costPct, timePct, completionKnown, costKnown, timeKnown, costGap, timeGap, signal };
}

/** A short Turkish risk sentence for the health modal / card. */
export function healthExplanation(h: ProjectHealth): string {
  if (h.signal === "unknown") {
    if (!h.completionKnown) {
      return "İlerleme verisi yok — sağlık değerlendirmesi için tamamlanma yüzdesi girin veya kilometre taşı ekleyin.";
    }
    return "Karşılaştırma için yeterli veri yok — revize bütçe veya proje takvimi eksik.";
  }
  const c = Math.round(h.completionPct);
  if (h.signal === "green") {
    if (h.costPct != null) {
      return `Maliyetin %${Math.round(h.costPct)}'i harcandı, proje %${c} tamamlandı — harcama ilerleme ile uyumlu.`;
    }
    return `Sürenin %${Math.round(h.timePct ?? 0)}'i geçti, proje %${c} tamamlandı — ilerleme ile uyumlu.`;
  }
  // amber/red: explain via whichever known indicator leads progress the most.
  const costGap = h.costGap ?? Number.NEGATIVE_INFINITY;
  const timeGap = h.timeGap ?? Number.NEGATIVE_INFINITY;
  if (costGap >= timeGap && h.costPct != null) {
    return `Bütçenin %${Math.round(h.costPct)}'i harcandı ama proje %${c} tamamlandı — maliyet ilerlemenin önünde.`;
  }
  return `Sürenin %${Math.round(h.timePct ?? 0)}'i geçti ama proje %${c} tamamlandı — takvim ilerlemenin önünde.`;
}

/** Display tokens (label + bar/badge colour) for a signal. */
export const HEALTH_SIGNAL_META: Record<HealthSignal, { label: string; color: string; bg: string }> = {
  green: { label: "Yolunda", color: "#10B981", bg: "bg-green-50 text-success" },
  amber: { label: "İzlenmeli", color: "#F59E0B", bg: "bg-amber-50 text-warning" },
  red: { label: "Riskli", color: "#EF4444", bg: "bg-red-50 text-danger" },
  unknown: { label: "Yeterli veri yok", color: "#94A3B8", bg: "bg-bg text-text-secondary" },
};
