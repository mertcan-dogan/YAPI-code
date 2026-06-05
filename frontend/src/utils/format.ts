// Turkish number / currency / date formatting (Section 14.1)
// Turkish format: thousands '.', decimals ',' — e.g. 1.234.567,89 ₺

const trNumber = new Intl.NumberFormat("tr-TR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const trInt = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 0 });

export function toNumber(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const n = typeof value === "number" ? value : parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

export function formatCurrency(value: string | number | null | undefined, symbol = "₺"): string {
  return `${trNumber.format(toNumber(value))} ${symbol}`;
}

export function formatNumber(value: string | number | null | undefined): string {
  return trNumber.format(toNumber(value));
}

// Abbreviated currency for KPI cards (M = milyon, B = milyar) — Section 4.1
export function formatCurrencyAbbrev(value: string | number | null | undefined, symbol = "₺"): string {
  const n = toNumber(value);
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `${trNumber.format(n / 1_000_000_000)} B ${symbol}`;
  if (abs >= 1_000_000) return `${trNumber.format(n / 1_000_000)} M ${symbol}`;
  return `${trInt.format(n)} ${symbol}`;
}

export function formatPct(value: string | number | null | undefined, decimals = 1): string {
  const n = toNumber(value);
  return `%${n.toLocaleString("tr-TR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
}

export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const d = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const d = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function daysUntil(value: string | Date | null | undefined): number {
  if (!value) return 0;
  const d = typeof value === "string" ? new Date(value) : value;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  d.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - today.getTime()) / 86_400_000);
}
