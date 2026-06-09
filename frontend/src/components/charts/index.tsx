import { COLORS } from "@/constants";
import { formatCurrencyAbbrev } from "@/utils/format";
import {
  Area,
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const axisProps = { tick: { fontSize: 11, fill: COLORS.primary }, stroke: COLORS.border };

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
        <CartesianGrid strokeDasharray="3 3" stroke={COLORS.border} vertical={false} />
        <XAxis dataKey="month" {...axisProps} />
        <YAxis tickFormatter={(v) => formatCurrencyAbbrev(v)} {...axisProps} width={70} />
        <Tooltip formatter={moneyTooltip} />
        <Bar dataKey="out" name="Gider" fill={COLORS.danger} radius={[2, 2, 0, 0]} />
        <Bar dataKey="in" name="Gelir" fill={COLORS.success} radius={[2, 2, 0, 0]} />
        <Line type="monotone" dataKey="cumulative" name="Kümülatif Net" stroke={COLORS.primary} strokeWidth={2} dot={false} />
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

// Margin Bridge — waterfall (CR-003-G). Components flow left-to-right.
export function MarginBridgeChart({ bridge, height = 300 }: { bridge: Record<string, string>; height?: number }) {
  const n = (k: string) => Number(bridge?.[k] ?? 0);
  const steps = [
    { name: "Orijinal Marj", value: n("original_margin_try"), kind: "total" as const },
    { name: "Onaylı Ek İş", value: n("approved_variations_try"), kind: "delta" as const },
    { name: "Bekleyen Ek İş", value: n("pending_variations_try"), kind: "delta" as const },
    { name: "Maliyet Aşımı", value: n("cost_overruns_try"), kind: "delta" as const },
    { name: "Tasarruf", value: n("cost_savings_try"), kind: "delta" as const },
    { name: "Güncel Marj", value: n("current_margin_try"), kind: "total" as const },
  ];

  // Build stacked bars: a transparent base + a coloured value segment.
  let running = 0;
  const data = steps.map((s) => {
    if (s.kind === "total") {
      const row = { name: s.name, base: 0, val: s.value, fill: COLORS.primary };
      running = s.value;
      return row;
    }
    const base = s.value >= 0 ? running : running + s.value;
    const fill = s.value >= 0 ? COLORS.success : COLORS.danger;
    const row = { name: s.name, base, val: Math.abs(s.value), fill };
    running += s.value;
    return row;
  });

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={COLORS.border} vertical={false} />
        <XAxis dataKey="name" {...axisProps} interval={0} angle={-15} textAnchor="end" height={60} />
        <YAxis tickFormatter={(v) => formatCurrencyAbbrev(v)} {...axisProps} width={70} />
        <Tooltip formatter={(v: any, _n: any, p: any) => [formatCurrencyAbbrev(p?.payload?.name?.includes("Aşım") ? -v : v), "Tutar"]} />
        <Bar dataKey="base" stackId="a" fill="transparent" />
        <Bar dataKey="val" stackId="a" radius={[2, 2, 0, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.fill} />
          ))}
        </Bar>
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
