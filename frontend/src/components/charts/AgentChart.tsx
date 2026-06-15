// CR-007-G — generic renderer for an agent chart spec (CR-007-C).
// Renders line / bar / composed with Recharts. Charts render from spec.data ONLY
// — never re-fetch or recompute on the client (§8.1). Colours/formatters reuse
// the Yapı palette and number formatters.
import { COLORS } from "@/constants";
import type { AgentChartSpec } from "@/types/agent";
import { formatCurrencyAbbrev } from "@/utils/format";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const axisProps = { tick: { fontSize: 11, fill: COLORS.muted }, stroke: COLORS.border };

const CURRENCY_SYMBOL: Record<string, string> = { TRY: "₺", EUR: "€", USD: "$" };

function symbolFor(currency?: string | null): string {
  return (currency && CURRENCY_SYMBOL[currency]) || "₺";
}

function AgentTooltip({ active, payload, label, symbol }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-md">
      <div className="mb-1 font-semibold text-text-primary">{label}</div>
      {payload
        .filter((p: any) => p.value != null)
        .map((p: any, i: number) => (
          <div key={i} className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full" style={{ background: p.color ?? p.stroke ?? p.fill }} />
            <span className="text-text-secondary">{p.name}:</span>
            <span className="tabular font-medium text-text-primary">{formatCurrencyAbbrev(p.value, symbol)}</span>
          </div>
        ))}
    </div>
  );
}

export function AgentChart({ spec, height = 280 }: { spec: AgentChartSpec; height?: number }) {
  if (!spec?.data?.length || !spec.series?.length) return null;

  const symbol = symbolFor(spec.currency);
  const tooltip = <Tooltip content={(props: any) => <AgentTooltip {...props} symbol={symbol} />} cursor={{ fill: "rgba(37,99,235,0.05)" }} />;
  const common = {
    data: spec.data,
    margin: { top: 10, right: 10, left: 0, bottom: 0 },
  };
  const axes = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F6" vertical={false} />
      <XAxis dataKey={spec.x_key} tickLine={false} axisLine={false} {...axisProps} />
      <YAxis tickFormatter={(v) => formatCurrencyAbbrev(v, symbol)} tickLine={false} axisLine={false} width={70} {...axisProps} />
      {tooltip}
      <Legend iconType="circle" wrapperStyle={{ fontSize: 11, paddingTop: 6 }} />
    </>
  );

  const palette = [COLORS.primary, COLORS.accent, COLORS.success, COLORS.danger, COLORS.brand, COLORS.brand2, COLORS.lightBlue, COLORS.warning];
  const colorAt = (i: number, c?: string) => c || palette[i % palette.length];

  let chart: JSX.Element;
  if (spec.chart_type === "bar") {
    chart = (
      <BarChart {...common}>
        {axes}
        {spec.series.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} name={s.label} fill={colorAt(i, s.color)} radius={[3, 3, 0, 0]} maxBarSize={28} />
        ))}
      </BarChart>
    );
  } else if (spec.chart_type === "composed") {
    chart = (
      <ComposedChart {...common}>
        {axes}
        {spec.series.map((s, i) =>
          s.type === "bar" ? (
            <Bar key={s.key} dataKey={s.key} name={s.label} fill={colorAt(i, s.color)} radius={[3, 3, 0, 0]} maxBarSize={28} />
          ) : (
            <Line key={s.key} type="linear" dataKey={s.key} name={s.label} stroke={colorAt(i, s.color)} strokeWidth={2.5} dot={false} />
          )
        )}
      </ComposedChart>
    );
  } else {
    chart = (
      <LineChart {...common}>
        {axes}
        {spec.series.map((s, i) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={colorAt(i, s.color)} strokeWidth={2.5} dot={false} />
        ))}
      </LineChart>
    );
  }

  return (
    <figure className="my-3 rounded-xl border border-border bg-surface p-3">
      {spec.title && <figcaption className="mb-2 text-sm font-semibold text-text-primary">{spec.title}</figcaption>}
      <ResponsiveContainer width="100%" height={height}>
        {chart}
      </ResponsiveContainer>
      {spec.source_note && <p className="mt-2 text-[11px] text-text-secondary">{spec.source_note}</p>}
    </figure>
  );
}
