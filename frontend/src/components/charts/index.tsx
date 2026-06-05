import { COLORS } from "@/constants";
import { formatCurrencyAbbrev } from "@/utils/format";
import {
  Area,
  Bar,
  CartesianGrid,
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
