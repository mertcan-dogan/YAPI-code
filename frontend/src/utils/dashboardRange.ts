// CR: dashboard date-range filter — preset/custom → the params the page sends.
// Mirrors the CashFlowPage preset pattern. "all" (Tümü) = no range: the period
// summary uses wide bounds (whole project) and the charts use the default window,
// so the default view is unchanged.
export type DashPreset = "all" | "3m" | "6m" | "12m" | "year" | "custom";

export interface DashRange {
  rangeActive: boolean;
  from_month?: string; // YYYY-MM (charts / cashflow endpoint)
  to_month?: string;
  from_date: string; // YYYY-MM-DD (period-summary endpoint)
  to_date: string;
  label: string;
  invalid: boolean; // custom range with from > to
}

const PRESET_LABELS: Record<string, string> = {
  "3m": "Son 3 Ay", "6m": "Son 6 Ay", "12m": "Son 12 Ay", "year": "Bu Yıl",
};

const mk = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
const lastDay = (ym: string) => {
  const [y, m] = ym.split("-").map(Number);
  return `${ym}-${String(new Date(y, m, 0).getDate()).padStart(2, "0")}`;
};

export function dashRangeParams(
  preset: DashPreset, customFrom: string, customTo: string, now: Date = new Date(),
): DashRange {
  const back = (n: number) => mk(new Date(now.getFullYear(), now.getMonth() - n, 1));
  const thisMonth = mk(now);
  let from: string | undefined;
  let to: string | undefined;
  if (preset === "3m") [from, to] = [back(2), thisMonth];
  else if (preset === "6m") [from, to] = [back(5), thisMonth];
  else if (preset === "12m") [from, to] = [back(11), thisMonth];
  else if (preset === "year") [from, to] = [`${now.getFullYear()}-01`, thisMonth];
  else if (preset === "custom") [from, to] = [customFrom || undefined, customTo || undefined];

  const invalid = preset === "custom" && !!from && !!to && from > to;
  if (preset === "custom" && (!from || !to || invalid)) {
    from = undefined;
    to = undefined;
  }
  const rangeActive = preset !== "all" && !!from && !!to;
  const label =
    preset === "all" ? "Tüm Proje"
      : preset === "custom" ? `${customFrom || "…"} → ${customTo || "…"}`
        : PRESET_LABELS[preset];

  return {
    rangeActive,
    from_month: from,
    to_month: to,
    // "Tümü": wide bounds capture all activity = whole project.
    from_date: rangeActive ? `${from}-01` : "2000-01-01",
    to_date: rangeActive ? lastDay(to!) : "2100-12-31",
    label,
    invalid,
  };
}
