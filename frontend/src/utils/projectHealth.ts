// Proje Sağlığı — on-track health math (CR redesign). Pure + deterministic so it
// can be unit-tested. Compares three percentages to flag when a project is
// spending (or burning calendar) faster than it is building.
//
// All percentages are on a 0–100 scale (e.g. 40 means 40%), matching the
// backend's completion_pct / margin_pct convention.

export type HealthSignal = "green" | "amber" | "red";

export interface ProjectHealthInput {
  completionPct: number; // % işin tamamlanma oranı (0–100)
  actualCostTry: number; // gerçekleşen maliyet (₺)
  revisedBudgetTry: number; // revize bütçe (₺)
  startDate: string | null | undefined;
  plannedEndDate: string | null | undefined;
  today?: Date; // injectable for tests; defaults to now
}

export interface ProjectHealth {
  completionPct: number; // clamped 0–100
  costPct: number; // gerçekleşen ÷ revize bütçe × 100 (can exceed 100 = over budget)
  timePct: number; // geçen süre oranı, clamped 0–100
  costGap: number; // costPct − completionPct (>0 ⇒ spending ahead of progress)
  timeGap: number; // timePct − completionPct (>0 ⇒ calendar ahead of progress)
  signal: HealthSignal;
}

/** Clamp any number into the 0–100 band (non-finite → 0). */
export function clampPct(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
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
  if (!startDate || !plannedEndDate) return 0;
  const start = new Date(startDate).getTime();
  const end = new Date(plannedEndDate).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return 0;
  return clampPct(((today.getTime() - start) / (end - start)) * 100);
}

// A project is "in line" while cost/time stay within this many points of
// completion; beyond RED_GAP the lead is treated as a real risk.
const IN_LINE_TOLERANCE = 5;
const RED_GAP = 20;

/**
 * Health verdict: green when spending matches (or trails) progress; amber/red
 * when either cost% or time% runs ahead of completion% (burning faster than
 * building). The worse of the two leads drives the signal.
 */
export function computeProjectHealth(input: ProjectHealthInput): ProjectHealth {
  const completionPct = clampPct(input.completionPct);
  const costPct =
    input.revisedBudgetTry > 0 ? (input.actualCostTry / input.revisedBudgetTry) * 100 : 0;
  const timePct = timeElapsedPct(input.startDate, input.plannedEndDate, input.today ?? new Date());

  const costGap = costPct - completionPct;
  const timeGap = timePct - completionPct;
  const lead = Math.max(costGap, timeGap);

  const signal: HealthSignal = lead <= IN_LINE_TOLERANCE ? "green" : lead <= RED_GAP ? "amber" : "red";
  return { completionPct, costPct, timePct, costGap, timeGap, signal };
}

/** A short Turkish risk sentence for the health modal / card. */
export function healthExplanation(h: ProjectHealth): string {
  const c = Math.round(h.completionPct);
  const cost = Math.round(h.costPct);
  const time = Math.round(h.timePct);
  if (h.signal === "green") {
    return `Maliyetin %${cost}'i harcandı, proje %${c} tamamlandı — harcama ilerleme ile uyumlu.`;
  }
  // Whichever indicator leads progress the most explains the risk.
  if (h.costGap >= h.timeGap) {
    return `Bütçenin %${cost}'i harcandı ama proje %${c} tamamlandı — maliyet ilerlemenin önünde.`;
  }
  return `Sürenin %${time}'i geçti ama proje %${c} tamamlandı — takvim ilerlemenin önünde.`;
}

/** Display tokens (label + bar/badge colour) for a signal. */
export const HEALTH_SIGNAL_META: Record<HealthSignal, { label: string; color: string; bg: string }> = {
  green: { label: "Yolunda", color: "#10B981", bg: "bg-green-50 text-success" },
  amber: { label: "İzlenmeli", color: "#F59E0B", bg: "bg-amber-50 text-warning" },
  red: { label: "Riskli", color: "#EF4444", bg: "bg-red-50 text-danger" },
};
