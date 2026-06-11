import { KPICard } from "@/components/KPICard";
import { COST_CATEGORIES } from "@/constants";
import type { BudgetCategoryRow } from "@/types";
import { formatCurrency, formatPct, toNumber } from "@/utils/format";
import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// CR-005-H: page-top summary band for Bütçe & Maliyetler — 4 KPI cards + a
// horizontal budget-usage bar chart. Always visible (not collapsible); data comes
// from the existing budget table API, so no extra endpoint is needed.

const BLUE = "#3B82F6";
const AMBER = "#F59E0B";
const RED = "#EF4444";

function usageColor(pct: number): string {
  if (pct > 100) return RED;
  if (pct >= 85) return AMBER;
  return BLUE;
}

export function BudgetSummaryCharts({
  categories,
  totals,
  loading,
  onAddBudget,
}: {
  categories: BudgetCategoryRow[];
  totals: { revised_budget_try?: string; committed_try?: string; invoiced_try?: string } | null | undefined;
  loading?: boolean;
  onAddBudget?: () => void;
}) {
  if (loading) {
    return <div className="mb-6 h-72 animate-pulse rounded-lg bg-bg" />;
  }

  const withBudget = categories.filter((c) => toNumber(c.revised_budget_try) > 0);

  // Empty state — no budget entered yet.
  if (withBudget.length === 0) {
    return (
      <div className="mb-6 flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-surface py-10">
        <p className="text-sm text-text-secondary">Henüz bütçe girilmemiş.</p>
        {onAddBudget && (
          <button onClick={onAddBudget} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90">
            Bütçe Ekle
          </button>
        )}
      </div>
    );
  }

  const revised = toNumber(totals?.revised_budget_try);
  const committed = toNumber(totals?.committed_try);
  const invoiced = toNumber(totals?.invoiced_try);
  const committedPct = revised > 0 ? (committed / revised) * 100 : 0;
  const overBudgetCount = categories.filter((c) => toNumber(c.pct_spent) > 100).length;

  // Highest usage on top.
  const chartData = withBudget
    .map((c) => ({
      name: c.label_tr ?? COST_CATEGORIES[c.cost_category] ?? c.cost_category,
      pct: Math.round(toNumber(c.pct_spent) * 10) / 10,
    }))
    .sort((a, b) => b.pct - a.pct);

  const chartHeight = Math.max(220, chartData.length * 26 + 40);

  return (
    <div className="mb-6 space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard label="Toplam Revize Bütçe" value={formatCurrency(revised)} />
        <KPICard label="Toplam Taahhüt Edilen" value={formatCurrency(committed)} subtitle={`Bütçenin %${formatPct(committedPct).replace("%", "")} taahhüt edildi`} />
        <KPICard label="Toplam Faturalanan" value={formatCurrency(invoiced)} />
        <KPICard label="Bütçe Aşımı Olan Kategoriler" value={String(overBudgetCount)} alert={overBudgetCount > 0 ? "red" : null} />
      </div>

      <div className="rounded-lg border border-border bg-surface p-4">
        <h3 className="mb-3 text-sm font-semibold text-primary">Bütçe Kullanımı — Kategori Bazında</h3>
        <ResponsiveContainer width="100%" height={chartHeight}>
          <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 48, left: 8, bottom: 4 }}>
            <XAxis type="number" domain={[0, 120]} tickFormatter={(v) => `%${v}`} tick={{ fontSize: 10 }} />
            <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 10 }} />
            <Tooltip formatter={(v: any) => [formatPct(v), "Harcanan"]} />
            <ReferenceLine x={100} stroke={RED} strokeDasharray="4 4" label={{ value: "%100", position: "top", fontSize: 9, fill: RED }} />
            <Bar dataKey="pct" radius={[0, 3, 3, 0]} label={{ position: "right", formatter: (v: any) => formatPct(v), fontSize: 9 }}>
              {chartData.map((d, i) => (
                <Cell key={i} fill={usageColor(d.pct)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <hr className="border-border" />
    </div>
  );
}
