import { cn } from "@/lib/cn";
import { CalendarRange, Filter as FilterIcon, X } from "lucide-react";
import { useState } from "react";

/** Dashboard filter state (wired into the data fetch in Phase 6). */
export interface DashboardFilters {
  /** Date-range preset key. */
  range: "all" | "this_month" | "last_3_months" | "this_year";
  /** RAG statuses to include; empty = all. */
  rag: string[];
}

export const DEFAULT_FILTERS: DashboardFilters = { range: "all", rag: [] };

const RANGE_LABELS: Record<DashboardFilters["range"], string> = {
  all: "Tüm Zamanlar",
  this_month: "Bu Ay",
  last_3_months: "Son 3 Ay",
  this_year: "Bu Yıl",
};

const RAG_OPTIONS = [
  { key: "green", label: "Sağlıklı", dot: "bg-success" },
  { key: "amber", label: "İzlenmeli", dot: "bg-warning" },
  { key: "red", label: "Riskli", dot: "bg-danger" },
];

function greeting(name?: string): string {
  const h = new Date().getHours();
  const part = h < 12 ? "Günaydın" : h < 18 ? "İyi günler" : "İyi akşamlar";
  return name ? `${part}, ${name} 👋` : `${part} 👋`;
}

/**
 * Page-level dashboard toolbar: time-aware greeting + portfolio sub-line on the
 * left; date-range select and a Filtreler popover (RAG) on the right. The global
 * notification bell, help and profile live in the app TopNav (not duplicated).
 */
export function DashboardToolbar({
  firstName,
  filters,
  onChange,
}: {
  firstName?: string;
  filters: DashboardFilters;
  onChange: (f: DashboardFilters) => void;
}) {
  const [filterOpen, setFilterOpen] = useState(false);
  const activeCount = filters.rag.length + (filters.range !== "all" ? 1 : 0);

  const toggleRag = (key: string) => {
    const next = filters.rag.includes(key) ? filters.rag.filter((r) => r !== key) : [...filters.rag, key];
    onChange({ ...filters, rag: next });
  };

  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <h1 className="truncate text-2xl font-bold text-primary">{greeting(firstName)}</h1>
        <p className="mt-0.5 text-sm text-text-secondary">Portföy Görünümü · Tüm Projeler</p>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {/* Date-range select */}
        <div className="relative">
          <CalendarRange className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-text-secondary" />
          <select
            value={filters.range}
            onChange={(e) => onChange({ ...filters, range: e.target.value as DashboardFilters["range"] })}
            className="appearance-none rounded-lg border border-border bg-surface py-2 pl-8 pr-8 text-sm text-text-primary outline-none transition-colors hover:border-brand focus:border-brand"
            aria-label="Tarih aralığı"
          >
            {Object.entries(RANGE_LABELS).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </div>

        {/* Filtreler popover */}
        <div className="relative">
          <button
            onClick={() => setFilterOpen((o) => !o)}
            className={cn(
              "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors",
              activeCount > 0 ? "border-brand bg-navy-50 text-brand" : "border-border bg-surface text-text-primary hover:border-brand"
            )}
          >
            <FilterIcon className="h-4 w-4" /> Filtreler
            {activeCount > 0 && (
              <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-brand px-1 text-[10px] font-bold text-white">{activeCount}</span>
            )}
          </button>
          {filterOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setFilterOpen(false)} />
              <div className="absolute right-0 top-11 z-20 w-60 rounded-xl border border-border bg-surface p-3 shadow-lg">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Proje Durumu (RAG)</span>
                  {activeCount > 0 && (
                    <button onClick={() => onChange(DEFAULT_FILTERS)} className="flex items-center gap-1 text-[11px] text-text-secondary hover:text-danger">
                      <X className="h-3 w-3" /> Temizle
                    </button>
                  )}
                </div>
                <div className="space-y-1">
                  {RAG_OPTIONS.map((o) => (
                    <label key={o.key} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-bg">
                      <input type="checkbox" checked={filters.rag.includes(o.key)} onChange={() => toggleRag(o.key)} className="h-4 w-4 accent-[var(--color-brand)]" />
                      <span className={cn("h-2.5 w-2.5 rounded-full", o.dot)} />
                      {o.label}
                    </label>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
