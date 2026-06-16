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

// Abbreviated currency for KPI cards (Mn = milyon, Mr = milyar) — Section 4.1.
// One decimal keeps the figure short enough to stay inside the card; the exact
// value is shown on hover via the card's title attribute.
export function formatCurrencyAbbrev(value: string | number | null | undefined, symbol = "₺"): string {
  const n = toNumber(value);
  const abs = Math.abs(n);
  const f1 = (x: number) => x.toLocaleString("tr-TR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  if (abs >= 1_000_000_000) return `${f1(n / 1_000_000_000)} Mr ${symbol}`;
  if (abs >= 1_000_000) return `${f1(n / 1_000_000)} Mn ${symbol}`;
  return `${trInt.format(n)} ${symbol}`;
}

// CR-014-D: USD figures use $ + en-US grouping (e.g. $1,234,567.00). A null/empty
// value renders "—" (USD snapshot is genuinely MISSING — never show $0 or 0).
const usdNumber = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usdInt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function formatUSD(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : parseFloat(value);
  if (!Number.isFinite(n)) return "—";
  return `$${usdNumber.format(n)}`;
}

// Abbreviated USD for KPI cards (Mn = milyon, Mr = milyar) — mirrors the TRY abbrev.
export function formatUSDAbbrev(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : parseFloat(value);
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  const f1 = (x: number) => x.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  if (abs >= 1_000_000_000) return `$${f1(n / 1_000_000_000)} Mr`;
  if (abs >= 1_000_000) return `$${f1(n / 1_000_000)} Mn`;
  return `$${usdInt.format(n)}`;
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
