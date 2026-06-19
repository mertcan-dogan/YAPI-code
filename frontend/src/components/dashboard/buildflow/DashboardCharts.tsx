import { CashFlowChart, MetricLineChart } from "@/components/charts";
import { Menu, MenuItem, Skeleton } from "@/components/ui";
import { toast } from "@/store/toast";
import { formatCurrency, formatCurrencyAbbrev, toNumber } from "@/utils/format";
import { GripVertical, Info, MoreVertical } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

// CR-029-D §8: three chart cards. Reuses the app's themed chart components +
// a compact grouped bar chart; all wired to the real /dashboard payload. The
// Taahhüt (committed) series is the honest CR-023 placeholder — not fabricated.

function ChartCard({ title, sub, info, children }: { title: string; sub?: string; info?: string; children: React.ReactNode }) {
  const stub = (what: string) => toast.info(`${what} — yakında`);
  return (
    <div className="rounded-card border border-border bg-surface shadow-lg">
      <div className="flex items-center gap-2 px-3.5 py-3">
        <GripVertical className="h-[15px] w-[15px] cursor-grab text-text-faint" />
        <span className="text-[13px] font-semibold">{title}</span>
        {sub && <span className="text-[10px] text-text-faint">{sub}</span>}
        <div className="ml-auto flex items-center gap-2">
          {info && <span title={info}><Info className="h-[15px] w-[15px] cursor-help text-text-faint" /></span>}
          <Menu align="right" triggerLabel="Grafik menüsü" trigger={<MoreVertical className="h-[15px] w-[15px] text-text-faint" />}>
            {(close) => (
              <>
                <MenuItem onClick={() => { close(); stub("Detaylar"); }}>Detaylar</MenuItem>
                <MenuItem onClick={() => { close(); stub("Ayarlar"); }}>Ayarlar</MenuItem>
                <MenuItem onClick={() => { close(); stub("Özelleştir"); }}>Özelleştir</MenuItem>
                <MenuItem onClick={() => { close(); stub("Gizle"); }}>Gizle</MenuItem>
              </>
            )}
          </Menu>
        </div>
      </div>
      {children}
    </div>
  );
}

function LegendRow({ items }: { items: { label: string; color: string; dashed?: boolean; muted?: boolean }[] }) {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 px-3.5 pb-2 text-[10px] text-text-muted">
      {items.map((it) => (
        <span key={it.label} className={it.muted ? "opacity-60" : ""}>
          <span className="mr-1.5 inline-block h-[3px] w-[9px] rounded-sm align-middle" style={{ background: it.color }} />
          {it.label}
        </span>
      ))}
    </div>
  );
}

export function DashboardCharts({ data, loading }: { data: any; loading?: boolean }) {
  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-2.5 xl:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="rounded-card border border-border bg-surface p-3.5 shadow-lg">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="mt-4 h-[150px] w-full" />
          </div>
        ))}
      </div>
    );
  }

  // 1) Cash flow forecast
  const cashData = (data?.cash_forecast?.months ?? []).map((m: any) => ({
    month: m.month,
    in: toNumber(m.inflow_try),
    out: toNumber(m.outflow_try),
    cumulative: toNumber(m.cumulative_try),
  }));
  const shortfall = data?.cash_forecast?.shortfall;
  const minCash = data?.cash_forecast?.min_cash_try;

  // 2) Budget (Sözleşme) vs Gerçekleşen vs Tahmin per project (+ Taahhüt = CR-023)
  const budgetData = (data?.portfolio_performance ?? []).map((p: any) => ({
    project: p.project,
    contract: toNumber(p.contract_try),
    actual: toNumber(p.actual_try),
    forecast: toNumber(p.forecast_final_try),
  }));

  // 3) Portfolio margin trend (real series; per-project monthly history is thin)
  const marginSeries: number[] = data?.kpi_trends?.weighted_avg_margin_pct?.series ?? [];
  const marginData = marginSeries.map((v, i) => ({ name: i === marginSeries.length - 1 ? "Bugün" : `T-${marginSeries.length - 1 - i}`, value: v }));

  return (
    <div className="grid grid-cols-1 gap-2.5 xl:grid-cols-3">
      <ChartCard title="Nakit Akışı Projeksiyonu" sub="30 / 60 / 90 Gün" info="Bekleyen tahsilat ve ödemelerden öngörülen aylık nakit akışı.">
        <LegendRow items={[{ label: "Giriş", color: "var(--color-teal)" }, { label: "Çıkış", color: "var(--color-brand)" }, { label: "Net (kümülatif)", color: "#0F172A" }]} />
        <div className="px-2.5 pb-3">
          {cashData.length ? <CashFlowChart data={cashData} height={170} /> : <EmptyChart />}
          {shortfall && (
            <div className="mt-1 inline-block rounded-md border border-[#FECACA] bg-red-50 px-2 py-1 text-[11px]">
              <span className="text-text-secondary">En düşük öngörülen nakit: </span>
              <span className="font-semibold text-danger tabular">{formatCurrency(minCash)}</span>
            </div>
          )}
        </div>
      </ChartCard>

      <ChartCard title="Bütçe vs Gerçekleşen vs Taahhüt vs Tahmin" info="Proje bazında sözleşme, gerçekleşen ve tahmini final maliyet. Taahhüt CR-023 ile gelecek.">
        <LegendRow items={[
          { label: "Sözleşme", color: "#CBD5E1" },
          { label: "Gerçekleşen", color: "var(--color-brand)" },
          { label: "Tahmin", color: "#0F172A" },
          { label: "Taahhüt (yakında)", color: "var(--color-teal)", muted: true },
        ]} />
        <div className="px-2.5 pb-3">
          {budgetData.length ? (
            <ResponsiveContainer width="100%" height={170}>
              <BarChart data={budgetData} margin={{ top: 6, right: 8, left: 0, bottom: 0 }} barGap={1} barCategoryGap="22%">
                <CartesianGrid strokeDasharray="3 3" stroke="#EEF2F7" vertical={false} />
                <XAxis dataKey="project" tickLine={false} axisLine={false} interval={0} tick={{ fontSize: 9, fill: "var(--color-text-faint)" }} tickFormatter={(v: string) => (v?.length > 10 ? v.slice(0, 10) + "…" : v)} />
                <YAxis tickFormatter={(v) => formatCurrencyAbbrev(v)} tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: "var(--color-text-faint)" }} width={58} />
                <Tooltip formatter={(v: any) => formatCurrency(v)} contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid var(--color-border)" }} />
                <Bar dataKey="contract" name="Sözleşme" fill="#CBD5E1" radius={[2, 2, 0, 0]} />
                <Bar dataKey="actual" name="Gerçekleşen" fill="var(--color-brand)" radius={[2, 2, 0, 0]} />
                <Bar dataKey="forecast" name="Tahmin" fill="#0F172A" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyChart />}
        </div>
      </ChartCard>

      <ChartCard title="Proje Bazında Marj Trendi" info="Portföy ağırlıklı marj eğilimi. Proje bazında aylık geçmiş biriktikçe ayrı çizgiler eklenecek.">
        <LegendRow items={[{ label: "Portföy Marjı", color: "#0F172A" }]} />
        <div className="px-2.5 pb-3">
          {marginData.length >= 2 ? (
            <MetricLineChart data={marginData} height={170} color="#0F172A" unit="percent" />
          ) : (
            <EmptyChart message="Marj trendi için yeterli geçmiş veri yok." />
          )}
        </div>
      </ChartCard>
    </div>
  );
}

function EmptyChart({ message = "Veri yok." }: { message?: string }) {
  return <div className="flex h-[150px] items-center justify-center text-xs text-text-muted">{message}</div>;
}
