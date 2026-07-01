import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";
import { ChevronDown, Download, FileSpreadsheet, FileText } from "lucide-react";
import { useState } from "react";

/**
 * One export column: a Turkish header plus an accessor that returns the RAW
 * underlying value (string/number/date) — never rendered JSX. Amounts should be
 * returned as plain `number`s so Excel can compute on them; dates as strings.
 *
 * CR-055 — `type` drives the xlsx cell number format so amounts show as `288.810 ₺`
 * (not `288810`): `currency` → ₺, `usd` → $, `percent` → literal `0.0"%"` (the value is
 * already in percent-units, no ×100), `number` → thousands. `date`/`text`/undefined are
 * left unformatted. CSV output ignores `type` and stays raw.
 */
export type ExportColumnType = "currency" | "usd" | "percent" | "number" | "date" | "text";

export interface ExportColumn<T> {
  header: string;
  value: (row: T) => string | number | null | undefined;
  type?: ExportColumnType;
}

// xlsx cell number formats per numeric column type (mirror backend excel_report ₺/$/%).
export const XLSX_FORMATS: Partial<Record<ExportColumnType, string>> = {
  currency: '#,##0" ₺"',
  usd: '#,##0" $"',
  percent: '0.0"%"',
  number: "#,##0",
};

/**
 * CR-055 — apply each column's number format to its numeric xlsx cells (header is row 0).
 * Only numeric cells are touched, so a blank/"–" USD or a formatted-date STRING is left
 * as-is (no fabrication). `XLSX` is passed in so this stays free of a static SheetJS
 * import (the library is lazy-loaded on export).
 */
export function applyColumnFormats<T>(
  ws: Record<string, { v?: unknown; t?: string; z?: string }>,
  columns: ExportColumn<T>[],
  nRows: number,
  XLSX: { utils: { encode_cell: (a: { r: number; c: number }) => string } },
): void {
  columns.forEach((col, ci) => {
    const z = col.type ? XLSX_FORMATS[col.type] : undefined;
    if (!z) return;
    for (let r = 1; r <= nRows; r++) {
      const cell = ws[XLSX.utils.encode_cell({ r, c: ci })];
      if (cell && typeof cell.v === "number") {
        cell.t = "n";
        cell.z = z;
      }
    }
  });
}

type Cell = string | number | null | undefined;

/** Headers + a matrix of raw cell values (numbers stay numbers). */
export function buildMatrix<T>(rows: T[], columns: ExportColumn<T>[]): { headers: string[]; data: Cell[][] } {
  const headers = columns.map((c) => c.header);
  const data = rows.map((r) => columns.map((c) => c.value(r)));
  return { headers, data };
}

/** RFC-4180-ish CSV: quote cells containing the delimiter, quotes or newlines. */
export function toCSV(headers: string[], data: Cell[][], delimiter = ","): string {
  const esc = (v: Cell): string => {
    if (v === null || v === undefined) return "";
    const s = typeof v === "number" ? String(v) : String(v);
    return /[",\r\n]/.test(s) || s.includes(delimiter) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [headers, ...data].map((row) => row.map(esc).join(delimiter));
  return lines.join("\r\n");
}

/** Today's date as YYYY-MM-DD for filenames. */
export function dateStamp(d: Date = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * Reusable export dropdown — exports the CURRENT (already-filtered) `rows` to
 * Excel (.xlsx, via SheetJS, lazy-loaded) or CSV (native, no dependency).
 * Place next to a page's primary header action.
 *
 * `fetchRows` (optional): when the visible `rows` are only one paginated page of
 * a larger set, supply an async resolver that returns the FULL filtered set. It
 * is awaited on click so the export is never silently truncated; `rows` is used
 * only to gate the disabled/empty state.
 *
 * `csvOnly` (optional): hide the Excel (.xlsx) option and offer only raw CSV — used
 * as the secondary "raw data" control on pages whose primary export is a backend
 * decision-grade workbook (CR-054). `triggerLabel` overrides the button text.
 */
export function ExportMenu<T>({ rows, columns, filename, disabled, fetchRows, csvOnly, triggerLabel }: { rows: T[]; columns: ExportColumn<T>[]; filename: string; disabled?: boolean; fetchRows?: () => Promise<T[]>; csvOnly?: boolean; triggerLabel?: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const empty = !rows || rows.length === 0;

  // Resolve the full set to export — all pages when `fetchRows` is given.
  const resolveRows = async (): Promise<T[]> => (fetchRows ? await fetchRows() : rows);

  const exportCSV = async () => {
    setBusy(true);
    try {
      const all = await resolveRows();
      const { headers, data } = buildMatrix(all, columns);
      // Prepend a UTF-8 BOM so Excel renders Turkish characters correctly.
      const blob = new Blob(["﻿" + toCSV(headers, data)], { type: "text/csv;charset=utf-8;" });
      download(blob, `${filename}-${dateStamp()}.csv`);
    } catch {
      toast.error("Dışa aktarma başarısız oldu");
    } finally {
      setBusy(false);
      setOpen(false);
    }
  };

  const exportXLSX = async () => {
    setBusy(true);
    try {
      const all = await resolveRows();
      const XLSX = await import("xlsx");
      const { headers, data } = buildMatrix(all, columns);
      const ws = XLSX.utils.aoa_to_sheet([headers, ...data]);
      // CR-055 — apply a per-column number format so amounts show as ₺/$/% (not raw
      // General numbers). CSV stays raw (exportCSV is untouched).
      applyColumnFormats(ws as any, columns, data.length, XLSX);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, "Veri");
      XLSX.writeFile(wb, `${filename}-${dateStamp()}.xlsx`);
    } catch {
      toast.error("Excel dosyası oluşturulamadı");
    } finally {
      setBusy(false);
      setOpen(false);
    }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={disabled || empty || busy}
        title={empty ? "Dışa aktarılacak veri yok" : "Dışa aktar"}
        className={cn(
          "flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-primary transition-colors hover:border-brand disabled:cursor-not-allowed disabled:opacity-50"
        )}
      >
        <Download className="h-4 w-4" /> {triggerLabel ?? "Dışa Aktar"}
        <ChevronDown className="h-3.5 w-3.5 text-text-secondary" />
      </button>
      {open && !empty && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full z-30 mt-2 w-44 overflow-hidden rounded-xl border border-border bg-surface py-1 shadow-lg">
            {!csvOnly && (
              <button onClick={exportXLSX} disabled={busy} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text-primary hover:bg-navy-50 disabled:opacity-50">
                <FileSpreadsheet className="h-4 w-4 text-success" /> Excel (.xlsx)
              </button>
            )}
            <button onClick={exportCSV} disabled={busy} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text-primary hover:bg-navy-50 disabled:opacity-50">
              <FileText className="h-4 w-4 text-brand" /> CSV
            </button>
          </div>
        </>
      )}
    </div>
  );
}
