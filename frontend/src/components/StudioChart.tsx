// CR-033/CR-034 — shared Rapor Stüdyosu rendering kit.
//
// Extracted from StudioReportEditorPage so BOTH the report editor and the pano
// (dashboard) canvas render charts + the Veri/Grafik config picker IDENTICALLY.
// Everything here is presentational/pure — no page state, no data fetching — so a
// widget on the canvas and a preview in the editor look and behave the same.
import { EmptyState } from "@/components/EmptyState";
import { Switch } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { CatalogDimension, CatalogMetric, RunResult, Viz } from "@/types/studio";
import { formatCurrency, formatCurrencyAbbrev, formatNumber, formatPct, formatUSD } from "@/utils/format";
import { ChevronDown, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export const COLORS = ["#2563EB", "#14B8A6", "#10B981", "#F59E0B", "#8B5CF6", "#F97316"];
export const WINDOW_TAG = "tüm proje, bugüne kadar";

// --------------------------------------------------------------------------- #
// Formatting helpers
// --------------------------------------------------------------------------- #
export function formatMetricValue(
  type: string | undefined,
  value: number | null | undefined,
  currency: string
): string {
  if (value === null || value === undefined) return "—";
  if (type === "currency") return currency === "usd" ? formatUSD(value) : formatCurrency(value);
  if (type === "percent") return formatPct(value);
  return formatNumber(value);
}

// Windowing badge — a project/unit-grain metric (catalog `windowed===false`) is a
// whole-project snapshot that ignores the selected date range (CR-032). The tag
// makes that explicit so a global range isn't misread.
export function WindowTag() {
  return (
    <span
      title="Bu metrik tüm proje anlık görüntüsüdür; seçili tarih aralığını yok sayar (CR-032)."
      className="rounded-sm border border-border bg-surface px-1.5 py-px text-[9px] font-medium uppercase tracking-wide text-text-muted"
    >
      {WINDOW_TAG}
    </span>
  );
}

export function DeltaText({
  value,
  unit,
  type,
  currency,
}: {
  value: number;
  unit: "pct" | "abs";
  type: string;
  currency: string;
}) {
  const up = value >= 0;
  const sign = up ? "+" : "−";
  const text =
    unit === "abs"
      ? `${sign}${formatMetricValue(type, Math.abs(value), currency)}`
      : `${sign}${formatPct(Math.abs(value) * 100)}`;
  return <span className={cn("text-[10px] font-medium tabular", up ? "text-success" : "text-danger")}>{text}</span>;
}

// --------------------------------------------------------------------------- #
// Catalog picker — grouped, searchable; coming_soon greyed + non-selectable.
// --------------------------------------------------------------------------- #
export function CatalogPicker({
  title,
  hint,
  items,
  selected,
  onToggle,
}: {
  title: string;
  hint: string;
  items: (CatalogDimension | CatalogMetric)[];
  selected: string[];
  onToggle: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLocaleLowerCase("tr");
  const filtered = items.filter(
    (it) => !q || it.label.toLocaleLowerCase("tr").includes(q) || it.description.toLocaleLowerCase("tr").includes(q)
  );
  const groups: [string, (CatalogDimension | CatalogMetric)[]][] = [];
  for (const it of filtered) {
    const g = groups.find((x) => x[0] === it.group);
    if (g) g[1].push(it);
    else groups.push([it.group, [it]]);
  }
  const selectedItems = items.filter((it) => selected.includes(it.id));

  return (
    <div>
      <div className="mb-1.5 text-[11px] font-semibold text-text-secondary">
        {title} <span className="font-normal text-text-faint">({hint})</span>
      </div>
      {selectedItems.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {selectedItems.map((it) => (
            <span
              key={it.id}
              className="inline-flex items-center gap-1 rounded-control border border-blue-border bg-blue-soft px-2 py-1 text-[11px] text-brand"
            >
              {it.label}
              <button type="button" aria-label={`${it.label} kaldır`} onClick={() => onToggle(it.id)} className="opacity-70 hover:opacity-100">
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Ara…"
        aria-label={`${title} ara`}
        className="mb-2 w-full rounded-control border border-border bg-surface px-2.5 py-1.5 text-xs outline-none focus:border-brand"
      />
      <div className="max-h-72 overflow-y-auto rounded-control border border-border bg-surface">
        {groups.length === 0 && <div className="px-3 py-3 text-xs text-text-muted">Sonuç yok.</div>}
        {groups.map(([group, groupItems]) => (
          <div key={group}>
            <div className="bg-surface-soft px-3 py-1 text-[10px] font-semibold uppercase tracking-wide text-text-faint">
              {group}
            </div>
            {groupItems.map((it) => {
              const isSelected = selected.includes(it.id);
              if (it.status === "coming_soon") {
                return (
                  <div
                    key={it.id}
                    aria-disabled="true"
                    className="flex cursor-not-allowed items-start gap-2 px-3 py-2 opacity-60"
                  >
                    <span className="mt-0.5 h-3.5 w-3.5 shrink-0 rounded-sm border border-border" />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5 text-[13px] text-text-muted">
                        {it.label}
                        <span className="rounded-sm bg-surface-hover px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-text-faint">
                          Yakında
                        </span>
                      </span>
                      <span className="block text-[11px] text-text-faint">{it.description}</span>
                    </span>
                  </div>
                );
              }
              return (
                <button
                  key={it.id}
                  type="button"
                  onClick={() => onToggle(it.id)}
                  className="flex w-full items-start gap-2 px-3 py-2 text-left transition-colors hover:bg-surface-hover"
                >
                  <span
                    className={cn(
                      "mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border",
                      isSelected ? "border-brand bg-brand text-white" : "border-border"
                    )}
                  >
                    {isSelected && <span className="text-[9px] leading-none">✓</span>}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] text-text-primary">{it.label}</span>
                    <span className="block text-[11px] text-text-faint">{it.description}</span>
                  </span>
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- #
// Chart canvas (line / area / bar) — fed by the run result's `series`.
// (DashboardCharts is hardcoded to the dashboard payload shape and cannot render a
//  generic studio series, so we render the studio series directly here.)
// --------------------------------------------------------------------------- #
export function StudioChart({ result, viz, legend }: { result: RunResult; viz: Viz; legend: boolean }) {
  const series = result.series ?? [];
  if (series.length === 0) return <EmptyState message="Grafik için veri yok." />;
  const xs = new Set<string>();
  series.forEach((s) => s.points.forEach((p) => xs.add(p.x)));
  const data = [...xs]
    .sort()
    .map((x) => {
      const row: Record<string, string | number | null> = { x };
      series.forEach((s) => {
        row[s.metric] = s.points.find((p) => p.x === x)?.y ?? null;
      });
      return row;
    });
  const axisTick = { fontSize: 10, fill: "var(--color-text-faint)" };
  const ChartEl: any = viz === "bar" ? BarChart : viz === "area" ? AreaChart : LineChart;
  return (
    <div className="rounded-card border border-border bg-surface p-3 shadow-card">
      <ResponsiveContainer width="100%" height={320}>
        <ChartEl data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#EEF2F7" vertical={false} />
          <XAxis dataKey="x" tickLine={false} axisLine={false} tick={axisTick} />
          <YAxis tickFormatter={(v) => formatCurrencyAbbrev(v)} tickLine={false} axisLine={false} tick={axisTick} width={60} />
          <Tooltip formatter={(v: any) => formatCurrency(v)} contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid var(--color-border)" }} />
          {legend && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {series.map((s, i) => {
            const color = COLORS[i % COLORS.length];
            if (viz === "bar") return <Bar key={s.metric} dataKey={s.metric} name={s.name} fill={color} radius={[2, 2, 0, 0]} />;
            if (viz === "area")
              return <Area key={s.metric} type="monotone" dataKey={s.metric} name={s.name} stroke={color} fill={color} fillOpacity={0.15} strokeWidth={2} />;
            return <Line key={s.metric} type="monotone" dataKey={s.metric} name={s.name} stroke={color} strokeWidth={2} dot={false} />;
          })}
        </ChartEl>
      </ResponsiveContainer>
    </div>
  );
}

// --------------------------------------------------------------------------- #
// Small shared controls (used by the report editor config panel + the pano
// canvas toolbar / widget config).
// --------------------------------------------------------------------------- #
export function ToggleRow({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-[12.5px] text-text-secondary">{label}</span>
      <Switch checked={checked} onChange={onChange} label={label} />
    </div>
  );
}

export function Segmented({
  value,
  options,
  onChange,
  full,
}: {
  value: string;
  options: { id: string; label: string; disabled?: boolean; badge?: string }[];
  onChange: (id: string) => void;
  full?: boolean;
}) {
  return (
    <div className={cn("inline-flex overflow-hidden rounded-control border border-border", full && "w-full")}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          disabled={o.disabled}
          onClick={() => !o.disabled && onChange(o.id)}
          className={cn(
            "flex items-center justify-center gap-1 px-3 py-1.5 text-xs transition-colors",
            full && "flex-1",
            value === o.id ? "bg-brand font-semibold text-white" : "bg-surface text-text-secondary hover:bg-surface-hover",
            o.disabled && "cursor-not-allowed opacity-60 hover:bg-surface"
          )}
        >
          {o.label}
          {o.badge && (
            <span className="rounded-sm bg-surface-hover px-1 py-px text-[8px] font-semibold uppercase tracking-wide text-text-faint">
              {o.badge}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

export function PresetMenu({
  label,
  icon,
  options,
  onPick,
}: {
  label: string;
  icon: ReactNode;
  options: { id: string; label: string }[];
  onPick: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex h-9 items-center gap-2 rounded-control border border-border bg-surface px-3 text-[13px] text-text-secondary hover:bg-surface-hover"
      >
        {icon}
        <span>{label}</span>
        <ChevronDown className="h-4 w-4 text-text-muted" />
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-1 min-w-[180px] overflow-hidden rounded-control border border-border bg-surface py-1 shadow-pop">
          {options.map((o) => (
            <button
              key={o.id}
              type="button"
              onClick={() => {
                onPick(o.id);
                setOpen(false);
              }}
              className="flex w-full items-center px-3 py-1.5 text-left text-sm text-text-primary hover:bg-surface-hover"
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
