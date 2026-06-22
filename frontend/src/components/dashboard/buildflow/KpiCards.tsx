import { Skeleton, Sparkline } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useCurrency } from "@/store/currency";
import { formatCurrencyAbbrev, formatCurrency, formatPct, formatUSD, toNumber } from "@/utils/format";
import { Briefcase, Calculator, ClipboardList, FileText, Folder, Landmark, LineChart, Percent, type LucideIcon } from "lucide-react";

interface Trend {
  series?: number[];
  deltaText?: string;
  tone?: "pos" | "neg" | "neu";
}

interface KpiDef {
  label: string;
  value: string;
  valueTitle?: string;
  icon: LucideIcon;
  color: string; // CSS var
  soft: string; // CSS var (soft bg)
  trend?: Trend;
  // CR-014 USD snapshot (fix #3): only figures with a real amount_usd switch on
  // the $ / İkisi toggle. Others stay ₺ (no USD snapshot → never fabricated).
  usd?: { amountUsd: string | null; missing: number };
}

// CR-029-D §7: 8 KPI cards. Real data from /dashboard (exec_kpis/kpis/kpi_trends)
// + approvals. Card 4 (Taahhüt Edilen Maliyet) is wired to the CR-023 açık taahhüt
// (open committed) figure. Trends shown only where kpi_trends provides a real
// series — never fabricated.
export function KpiCards({ data, approvalsCount, loading }: { data: any; approvalsCount: number | null; loading?: boolean }) {
  const k = data?.kpis;
  const ex = data?.exec_kpis;
  const pb = data?.portfolio_budget;
  const tr = data?.kpi_trends ?? {};
  const mode = useCurrency((s) => s.mode); // fix #3: ₺ / $ / İkisi
  const showUsd = mode !== "try";

  const moneyTrend = (key: string, unit: "%" | "₺"): Trend | undefined => {
    const t = tr[key];
    if (!t) return undefined;
    const d = t.delta_pct;
    if (d == null) return { series: t.series };
    const tone = d >= 0 ? "pos" : "neg";
    const txt = unit === "%" ? `${d >= 0 ? "↑" : "↓"} ${Math.abs(d).toFixed(1)}%` : `${d >= 0 ? "↑" : "↓"} %${Math.abs(d).toFixed(1)}`;
    return { series: t.series, deltaText: txt, tone };
  };
  const marginTrend = (): Trend | undefined => {
    const t = tr.weighted_avg_margin_pct;
    if (!t) return undefined;
    const s = t.series;
    const pp = s && s.length >= 2 ? s[s.length - 1] - s[0] : null;
    if (pp == null) return { series: s };
    return { series: s, deltaText: `${pp >= 0 ? "↑" : "↓"} ${Math.abs(pp).toFixed(1)} pp`, tone: pp >= 0 ? "pos" : "neg" };
  };

  const cards: KpiDef[] = [
    {
      label: "Aktif Projeler",
      value: String(k?.active_project_count ?? "—"),
      icon: Folder,
      color: "var(--color-brand)",
      soft: "var(--color-blue-soft)",
    },
    {
      label: "Sözleşme Bedeli",
      value: formatCurrencyAbbrev(k?.total_contract_value_try),
      valueTitle: formatCurrency(k?.total_contract_value_try),
      icon: FileText,
      color: "var(--color-success)",
      soft: "var(--color-green-50)",
      trend: moneyTrend("total_contract_value_try", "%"),
    },
    {
      label: "Gerçekleşen Maliyet",
      value: formatCurrencyAbbrev(pb?.actual_try),
      valueTitle: formatCurrency(pb?.actual_try),
      icon: Calculator,
      color: "var(--color-purple)",
      soft: "var(--color-purple-soft)",
      // Backed by a CR-014 USD snapshot (portfolio cost USD sum) → switches on $.
      usd: { amountUsd: data?.usd?.costs?.amount_usd ?? null, missing: data?.usd?.costs?.usd_missing_count ?? 0 },
    },
    {
      // CR-023: açık taahhüt — committed-but-not-yet-billed exposure. Detail/tooltip
      // shows the full exposure (gerçekleşen + açık taahhüt).
      label: "Taahhüt Edilen Maliyet",
      value: formatCurrencyAbbrev(pb?.open_committed_try ?? pb?.committed_try),
      valueTitle:
        pb?.committed_exposure_try != null
          ? `Açık taahhüt: ${formatCurrency(pb?.open_committed_try ?? pb?.committed_try)} · Toplam maruziyet (gerçekleşen + açık): ${formatCurrency(pb?.committed_exposure_try)}`
          : formatCurrency(pb?.open_committed_try ?? pb?.committed_try),
      icon: Briefcase,
      color: "var(--color-warning)",
      soft: "var(--color-amber-50)",
    },
    {
      label: "Tahmini Final Maliyet",
      value: formatCurrencyAbbrev(pb?.forecast_final_cost_try),
      valueTitle: formatCurrency(pb?.forecast_final_cost_try),
      icon: LineChart,
      color: "var(--color-teal)",
      soft: "var(--color-teal-soft)",
    },
    {
      label: "Tahmini Marj",
      value: formatPct(k?.weighted_avg_margin_pct),
      icon: Percent,
      color: "var(--color-teal)",
      soft: "var(--color-teal-soft)",
      trend: marginTrend(),
    },
    {
      label: "Net Nakit Pozisyonu",
      value: formatCurrencyAbbrev(ex?.net_cash_position_try),
      valueTitle: formatCurrency(ex?.net_cash_position_try),
      icon: Landmark,
      color: "var(--color-brand)",
      soft: "var(--color-blue-soft)",
      trend: moneyTrend("net_cash_position_try", "₺"),
    },
    {
      label: "Onay Bekleyen",
      value: approvalsCount == null ? "—" : String(approvalsCount),
      icon: ClipboardList,
      color: "var(--color-warning)",
      soft: "var(--color-amber-50)",
    },
  ];

  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="rounded-card border border-border bg-surface p-[11px] shadow-card">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="mt-3 h-5 w-20" />
            <Skeleton className="mt-3 h-5 w-full" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
      {cards.map((c) => (
        <div key={c.label} className="rounded-card border border-border bg-surface p-[11px] shadow-card">
          <div className="flex items-start justify-between gap-1">
            <span className="text-[11px] font-medium leading-tight text-text-muted">{c.label}</span>
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[7px]" style={{ background: c.soft, color: c.color }}>
              <c.icon className="h-3.5 w-3.5" />
            </span>
          </div>
          <div
            title={
              showUsd && c.usd && c.usd.missing > 0
                ? `${c.usd.missing} kayıt için kur bulunamadı; USD toplamı eksik olabilir`
                : c.valueTitle
            }
            className="mt-1.5 text-[21px] font-semibold leading-none tabular"
          >
            {showUsd && c.usd ? (
              c.usd.amountUsd == null ? (
                <span className="text-text-faint">—</span>
              ) : mode === "both" ? (
                <span>{c.value}<span className="ml-1 text-[13px] font-medium text-text-muted">· {formatUSD(c.usd.amountUsd)}</span></span>
              ) : (
                formatUSD(c.usd.amountUsd)
              )
            ) : (
              c.value
            )}
          </div>
          <div className="mt-1 h-[14px] text-[11px]">
            {c.trend?.deltaText ? (
              <span className={cn(c.trend.tone === "pos" ? "text-success" : c.trend.tone === "neg" ? "text-danger" : "text-text-muted")}>
                {c.trend.deltaText}
              </span>
            ) : null}
          </div>
          <div className="mt-1.5 h-[26px]">
            {c.trend?.series && c.trend.series.length >= 2 && (
              <Sparkline data={c.trend.series} color={c.color} className="h-[26px] w-full" />
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
