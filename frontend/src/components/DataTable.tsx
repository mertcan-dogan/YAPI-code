import { cn } from "@/lib/cn";
import { ChevronDown, ChevronUp } from "lucide-react";
import * as React from "react";
import { Skeleton } from "./ui";
import { EmptyState, LoadError } from "./EmptyState";

export interface Column<T> {
  key: string;
  header: string;
  align?: "left" | "right" | "center";
  sortable?: boolean;
  render?: (row: T) => React.ReactNode;
  sortValue?: (row: T) => string | number;
  maxWidth?: number; // CR-004-E: truncate long text with ellipsis
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  loading?: boolean;
  emptyMessage?: string;
  emptyAction?: { label: string; onClick: () => void };
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T) => string;
  minWidth?: number; // CR-004-E: minimum table width before horizontal scroll kicks in
  error?: string | null; // when set (and not loading) shows a retry state, not "empty"
  onRetry?: () => void;
  highlightId?: string | null; // CR-007-H: scroll to + flash the row whose id matches
  dense?: boolean; // CR-028: tighter ~36px rows for the data-dense look
}

// Data Table — sticky navy header, zebra rows, sortable (Section 6.5)
export function DataTable<T extends Record<string, any>>({
  columns,
  rows,
  loading,
  emptyMessage = "Henüz veri yok",
  emptyAction,
  onRowClick,
  rowClassName,
  minWidth = 640,
  error,
  onRetry,
  highlightId,
  dense,
}: DataTableProps<T>) {
  const cellPad = dense ? "px-3 py-2" : "px-3 py-2.5"; // CR-028: configurable density
  const [sortKey, setSortKey] = React.useState<string | null>(null);
  const [sortDir, setSortDir] = React.useState<"asc" | "desc">("asc");
  const highlightRef = React.useRef<HTMLTableRowElement>(null);

  // CR-007-H: bring the cited row into view once it (and the data) are present.
  React.useEffect(() => {
    if (highlightId && highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlightId, rows]);

  const sorted = React.useMemo(() => {
    if (!sortKey) return rows;
    const col = columns.find((c) => c.key === sortKey);
    if (!col) return rows;
    const val = col.sortValue ?? ((r: T) => r[sortKey]);
    return [...rows].sort((a, b) => {
      const av = val(a);
      const bv = val(b);
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
  }, [rows, sortKey, sortDir, columns]);

  const toggleSort = (key: string) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  if (loading) {
    return (
      <div className="overflow-hidden rounded-card border border-border bg-surface shadow-card">
        <div className="border-b border-border bg-bg px-4 py-3" />
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="border-b border-border px-4 py-3 last:border-0">
            <Skeleton />
          </div>
        ))}
      </div>
    );
  }

  if (error && !loading) {
    return (
      <div className="rounded-card border border-border bg-surface shadow-card">
        <LoadError onRetry={onRetry} />
      </div>
    );
  }

  if (sorted.length === 0) {
    return (
      <div className="rounded-card border border-border bg-surface shadow-card">
        <EmptyState message={emptyMessage} actionLabel={emptyAction?.label} onAction={emptyAction?.onClick} />
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-card border border-border bg-surface shadow-card">
      <table className="w-full border-collapse text-sm" style={{ minWidth: minWidth }}>
        <thead className="sticky top-0 z-10">
          <tr className="border-b border-border bg-bg">
            {columns.map((c) => (
              <th
                key={c.key}
                style={c.maxWidth ? { maxWidth: c.maxWidth } : undefined}
                className={cn(
                  // CR-028: small muted uppercase column headers (overline style).
                  cellPad,
                  "text-left text-[11px] font-semibold uppercase tracking-wide text-text-muted",
                  c.align === "right" && "text-right",
                  c.align === "center" && "text-center",
                  c.sortable && "cursor-pointer select-none"
                )}
                onClick={() => c.sortable && toggleSort(c.key)}
              >
                <span className="inline-flex items-center gap-1">
                  {c.header}
                  {c.sortable && sortKey === c.key && (sortDir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />)}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => {
            const isHighlighted = highlightId != null && row.id === highlightId;
            return (
            <tr
              key={row.id ?? i}
              ref={isHighlighted ? highlightRef : undefined}
              className={cn(
                "border-b border-border transition-colors last:border-0 hover:bg-surface-hover",
                onRowClick && "cursor-pointer",
                isHighlighted && "yapi-row-flash",
                rowClassName?.(row)
              )}
              onClick={() => onRowClick?.(row)}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  style={c.maxWidth ? { maxWidth: c.maxWidth } : undefined}
                  className={cn(
                    cellPad,
                    c.align === "right" && "text-right tabular",
                    c.align === "center" && "text-center",
                    c.maxWidth && "truncate"
                  )}
                  title={c.maxWidth && typeof row[c.key] === "string" ? row[c.key] : undefined}
                >
                  {c.render ? c.render(row) : row[c.key]}
                </td>
              ))}
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
