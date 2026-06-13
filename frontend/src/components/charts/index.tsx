import { COLORS } from "@/constants";
import { formatCurrencyAbbrev } from "@/utils/format";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const axisProps = { tick: { fontSize: 11, fill: COLORS.muted }, stroke: COLORS.border };

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-md">
      <div className="mb-1 font-semibold text-text-primary">{label}</div>
      {payload.filter((p: any) => p.value != null).map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color ?? p.stroke ?? p.fill }} />
          <span className="text-text-secondary">{p.name}:</span>
          <span className="tabular font-medium text-text-primary">{formatCurrencyAbbrev(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

function moneyTooltip(value: any) {
  return formatCurrencyAbbrev(value);
}

// Cash Flow — ComposedChart (Bars out/in + cumulative line). Appendix D.
export function CashFlowChart({
  data,
  height = 280,
}: {
  data: { month: string; out: number; in: number; cumulative: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="cfNet" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={COLORS.brand} stopOpacity={0.18} />
            <stop offset="100%" stopColor={COLORS.brand} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F6" vertical={false} />
        <XAxis dataKey="month" tickLine={false} axisLine={false} {...axisProps} />
        <YAxis tickFormatter={(v) => formatCurrencyAbbrev(v)} tickLine={false} axisLine={false} {...axisProps} width={70} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(37,99,235,0.05)" }} />
        <Legend iconType="circle" wrapperStyle={{ fontSize: 11, paddingTop: 6 }} />
        <Bar dataKey="in" name="Gelir" fill={COLORS.success} radius={[3, 3, 0, 0]} maxBarSize={22} />
        <Bar dataKey="out" name="Gider" fill={COLORS.danger} fillOpacity={0.85} radius={[3, 3, 0, 0]} maxBarSize={22} />
        <Area type="monotone" dataKey="cumulative" name="Kümülatif Net" stroke="none" fill="url(#cfNet)" isAnimationActive={false} legendType="none" />
        <Line type="monotone" dataKey="cumulative" name="Kümülatif Net" stroke={COLORS.brand} strokeWidth={2.5} dot={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// S-Curve — planned (dashed) vs actual cumulative cost. Appendix D.
export function SCurveChart({
  data,
  height = 280,
}: {
  data: { month: string; planned: number; actual: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={COLORS.border} vertical={false} />
        <XAxis dataKey="month" {...axisProps} />
        <YAxis tickFormatter={(v) => formatCurrencyAbbrev(v)} {...axisProps} width={70} />
        <Tooltip formatter={moneyTooltip} />
        <Line type="monotone" dataKey="planned" name="Planlanan Kümülatif" stroke={COLORS.lightBlue} strokeWidth={2} strokeDasharray="6 4" dot={false} />
        <Line type="monotone" dataKey="actual" name="Gerçekleşen Kümülatif" stroke={COLORS.primary} strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// Margin Bridge — waterfall (CR-003-G, CR-004-J). Each column starts where the
// previous one ended; colours follow the step's meaning, not just its sign.
export function MarginBridgeChart({ bridge, height = 300 }: { bridge: Record<string, string>; height?: number }) {
  const n = (k: string) => Number(bridge?.[k] ?? 0);
  const steps = [
    { name: "Orijinal Marj", value: n("original_margin_try"), kind: "total" as const, color: COLORS.primary },
    { name: "Onaylı Ek İş", value: n("approved_variations_try"), kind: "delta" as const, color: COLORS.success },
    { name: "Bekleyen Ek İş", value: n("pending_variations_try"), kind: "delta" as const, color: COLORS.warning },
    { name: "Maliyet Aşımı", value: n("cost_overruns_try"), kind: "delta" as const, color: COLORS.danger },
    { name: "Tasarruf", value: n("cost_savings_try"), kind: "delta" as const, color: COLORS.success },
    { name: "Güncel Marj", value: n("current_margin_try"), kind: "total" as const, color: COLORS.primary },
  ];

  // Two stacked bars: an invisible offset (base) + the coloured value segment,
  // so each delta floats from the running total — the standard Recharts waterfall.
  let running = 0;
  const data = steps.map((s) => {
    if (s.kind === "total") {
      running = s.value;
      return { name: s.name, base: 0, val: s.value, raw: s.value, fill: s.color };
    }
    const base = s.value >= 0 ? running : running + s.value;
    running += s.value;
    return { name: s.name, base, val: Math.abs(s.value), raw: s.value, fill: s.color };
  });

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={COLORS.border} vertical={false} />
        <XAxis dataKey="name" {...axisProps} interval={0} angle={-15} textAnchor="end" height={60} />
        <YAxis tickFormatter={(v) => formatCurrencyAbbrev(v)} {...axisProps} width={70} />
        <Tooltip
          cursor={{ fill: "transparent" }}
          formatter={(_v: any, _n: any, p: any) => [formatCurrencyAbbrev(p?.payload?.raw ?? 0), "Tutar"]}
        />
        <Bar dataKey="base" stackId="a" fill="transparent" fillOpacity={0} isAnimationActive={false} legendType="none" />
        <Bar dataKey="val" stackId="a" radius={[2, 2, 0, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.fill} />
          ))}
        </Bar>
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// Mini monthly bar chart (CR-004-L) — compact spend trend inside a drawer.
export function MiniBarChart({ data, height = 120 }: { data: { month: string; value: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={COLORS.border} vertical={false} />
        <XAxis dataKey="month" tick={{ fontSize: 9, fill: COLORS.primary }} stroke={COLORS.border} />
        <YAxis tickFormatter={(v) => formatCurrencyAbbrev(v)} tick={{ fontSize: 9, fill: COLORS.primary }} stroke={COLORS.border} width={48} />
        <Tooltip formatter={moneyTooltip} />
        <Bar dataKey="value" name="Harcama" fill={COLORS.primary} radius={[2, 2, 0, 0]} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// Margin Trend — AreaChart. Appendix D.
export function MarginAreaChart({ data, height = 220 }: { data: { month: string; margin: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="marginFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={COLORS.primary} stopOpacity={0.4} />
            <stop offset="100%" stopColor={COLORS.primary} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={COLORS.border} vertical={false} />
        <XAxis dataKey="month" {...axisProps} />
        <YAxis {...axisProps} width={40} />
        <Tooltip />
        <ReferenceLine y={10} stroke={COLORS.success} strokeDasharray="4 4" />
        <ReferenceLine y={5} stroke={COLORS.danger} strokeDasharray="4 4" />
        <Area type="monotone" dataKey="margin" name="Kar Marjı %" stroke={COLORS.primary} fill="url(#marginFill)" strokeWidth={2} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// Portfolio Budget — company-wide contract / budget / committed / actual / forecast (Ana Sayfa).
export function PortfolioBudgetChart({ data, height = 260 }: { data: { name: string; value: number; fill: string }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F6" vertical={false} />
        <XAxis dataKey="name" tickLine={false} axisLine={false} {...axisProps} />
        <YAxis tickFormatter={(v) => formatCurrencyAbbrev(v)} tickLine={false} axisLine={false} {...axisProps} width={70} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(37,99,235,0.05)" }} />
        <Bar dataKey="value" name="Tutar" radius={[4, 4, 0, 0]} maxBarSize={70}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.fill} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// Portföy Performansı — per-project actual vs forecast vs contract (multi-line).
export function PortfolioPerformanceChart({
  data,
  height = 320,
}: {
  data: { project: string; contract: number; actual: number; forecast: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 10, right: 14, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F6" vertical={false} />
        <XAxis
          dataKey="project"
          tickLine={false}
          axisLine={false}
          interval={0}
          tickFormatter={(v: string) => (v && v.length > 12 ? v.slice(0, 12) + "…" : v)}
          {...axisProps}
        />
        <YAxis tickFormatter={(v) => formatCurrencyAbbrev(v)} tickLine={false} axisLine={false} {...axisProps} width={70} />
        <Tooltip content={<ChartTooltip />} />
        <Legend iconType="plainline" wrapperStyle={{ fontSize: 11, paddingTop: 6 }} />
        <Line type="monotone" dataKey="actual" name="Gerçekleşen Maliyet" stroke={COLORS.brand} strokeWidth={2.5} dot={{ r: 3 }} />
        <Line type="monotone" dataKey="forecast" name="Tahmini Final Maliyet" stroke={COLORS.accent} strokeWidth={2} strokeDasharray="5 4" dot={false} />
        <Line type="monotone" dataKey="contract" name="Sözleşme Bedeli" stroke={COLORS.success} strokeWidth={2} strokeDasharray="5 4" dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// Bütçe Dağılımı — horizontal bar chart of cost categories (calm cycling palette).
const BUDGET_BAR_COLORS = [COLORS.brand, COLORS.brand2, COLORS.accent, COLORS.success, COLORS.primary];

function BudgetBreakdownTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-md">
      <div className="mb-1 font-semibold text-text-primary">{d.label}</div>
      <div className="tabular text-text-secondary">
        {formatCurrencyAbbrev(d.value)} · %{d.pct}
      </div>
    </div>
  );
}

export function BudgetBreakdownChart({
  data,
  mode,
  height = 300,
}: {
  data: { label: string; value: number; pct: number }[];
  mode: "value" | "pct";
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 64 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F6" vertical={false} />
        <XAxis
          dataKey="label"
          interval={0}
          angle={-40}
          textAnchor="end"
          height={70}
          tickFormatter={(v: string) => (v && v.length > 14 ? v.slice(0, 14) + "…" : v)}
          tickLine={false}
          axisLine={false}
          tick={{ fontSize: 10, fill: COLORS.muted }}
        />
        <YAxis
          tickFormatter={(v) => (mode === "pct" ? `%${v}` : formatCurrencyAbbrev(v))}
          tickLine={false}
          axisLine={false}
          {...axisProps}
          width={56}
        />
        <Tooltip cursor={{ fill: "rgba(37,99,235,0.05)" }} content={<BudgetBreakdownTooltip />} />
        <Bar dataKey={mode === "pct" ? "pct" : "value"} radius={[4, 4, 0, 0]} maxBarSize={40}>
          {data.map((_, i) => (
            <Cell key={i} fill={BUDGET_BAR_COLORS[i % BUDGET_BAR_COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
