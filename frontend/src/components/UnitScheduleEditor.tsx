// CR-016-C: residential details editor — İnşaat Brüt/Net m² (project-level) +
// the daire dağılımı (unit schedule) repeatable row list with a live mini-summary.
// Shared by the New Project wizard and the project detail page.
import { Button, Input, Label, Select } from "@/components/ui";
import { UNIT_TYPE_OPTIONS } from "@/constants";
import { formatCurrency, toNumber } from "@/utils/format";
import { Plus, X } from "lucide-react";

// A schedule row in the form. Numbers are kept as strings (controlled inputs);
// `id` is present for rows that already exist server-side (upsert target).
export interface UnitRow {
  id?: string;
  unit_type: string;
  custom_label?: string | null;
  count: string;
  gross_m2_each: string;
  net_m2_each?: string;
  sale_price_try?: string;
  notes?: string | null;
}

export const emptyUnitRow = (): UnitRow => ({
  unit_type: "2+1",
  custom_label: "",
  count: "",
  gross_m2_each: "",
  net_m2_each: "",
  sale_price_try: "",
});

const has = (v: unknown) => v !== undefined && v !== null && String(v).trim() !== "";

// Live summary — mirrors the CR-016-B backend aggregate definitions exactly:
//   total_units              = Σ count
//   total_sellable_gross_m2  = Σ count × gross_m2_each
//   total_sellable_net_m2    = Σ count × net_m2_each   (only rows with a net)
//   total_estimated_sales_try= Σ count × sale_price_try (null when no prices)
export function computeScheduleSummary(units: UnitRow[]) {
  let totalUnits = 0;
  let grossM2 = 0;
  let netM2 = 0;
  let estimatedSales = 0;
  let hasSales = false;
  for (const u of units) {
    const c = Math.max(0, Math.floor(toNumber(u.count)));
    totalUnits += c;
    grossM2 += c * toNumber(u.gross_m2_each);
    if (has(u.net_m2_each)) netM2 += c * toNumber(u.net_m2_each);
    if (has(u.sale_price_try)) {
      estimatedSales += c * toNumber(u.sale_price_try);
      hasSales = true;
    }
  }
  return { totalUnits, grossM2, netM2, estimatedSales: hasSales ? estimatedSales : null };
}

// Keep only rows complete enough to satisfy backend validation (count ≥ 1, gross > 0,
// and a custom label when "Diğer"); drop blank/half-filled rows so a stray empty row
// never 422s the whole save (non-blocking, §3.1).
export function unitsForPayload(units: UnitRow[]) {
  return units
    .filter((u) => toNumber(u.count) >= 1 && toNumber(u.gross_m2_each) > 0)
    .filter((u) => u.unit_type !== "other" || has(u.custom_label))
    .map((u) => ({
      ...(u.id ? { id: u.id } : {}),
      unit_type: u.unit_type,
      custom_label: u.unit_type === "other" ? (u.custom_label || null) : null,
      count: parseInt(u.count || "0", 10),
      gross_m2_each: u.gross_m2_each,
      net_m2_each: has(u.net_m2_each) ? u.net_m2_each : null,
      sale_price_try: has(u.sale_price_try) ? u.sale_price_try : null,
      notes: has(u.notes) ? u.notes : null,
    }));
}

const fmtM2 = (n: number) => `${n.toLocaleString("tr-TR", { maximumFractionDigits: 2 })} m²`;

interface Props {
  grossM2: string;
  netM2: string;
  units: UnitRow[];
  onGrossChange: (v: string) => void;
  onNetChange: (v: string) => void;
  onUnitsChange: (rows: UnitRow[]) => void;
  disabled?: boolean;
}

export function ResidentialDetailsEditor({
  grossM2, netM2, units, onGrossChange, onNetChange, onUnitsChange, disabled,
}: Props) {
  const summary = computeScheduleSummary(units);
  const patch = (i: number, k: keyof UnitRow, v: string) =>
    onUnitsChange(units.map((r, j) => (j === i ? { ...r, [k]: v } : r)));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <Label>İnşaat Brüt m²</Label>
          <Input type="number" value={grossM2} disabled={disabled} onChange={(e) => onGrossChange(e.target.value)} placeholder="örn. 5000" />
        </div>
        <div>
          <Label>İnşaat Net m²</Label>
          <Input type="number" value={netM2} disabled={disabled} onChange={(e) => onNetChange(e.target.value)} placeholder="örn. 4200" />
        </div>
      </div>

      <div>
        <Label>Daire Dağılımı</Label>
        <p className="mb-2 text-xs text-text-secondary">Daire tiplerini ve adetlerini girin — toplam daire sayısı buradan hesaplanır.</p>
        <div className="space-y-2">
          {units.map((u, i) => (
            <div key={i} className="rounded-md border border-border bg-bg p-2">
              <div className="flex flex-wrap items-end gap-2">
                <div className="w-32">
                  <Label className="text-[11px]">Daire Tipi</Label>
                  <Select value={u.unit_type} disabled={disabled} onChange={(e) => patch(i, "unit_type", e.target.value)}>
                    {UNIT_TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </Select>
                </div>
                {u.unit_type === "other" && (
                  <div className="w-32">
                    <Label className="text-[11px]">Açıklama</Label>
                    <Input value={u.custom_label ?? ""} disabled={disabled} maxLength={100} onChange={(e) => patch(i, "custom_label", e.target.value)} placeholder="örn. Sığınak" />
                  </div>
                )}
                <div className="w-20">
                  <Label className="text-[11px]">Adet</Label>
                  <Input type="number" value={u.count} disabled={disabled} onChange={(e) => patch(i, "count", e.target.value)} />
                </div>
                <div className="w-24">
                  <Label className="text-[11px]">Brüt m²/adet</Label>
                  <Input type="number" value={u.gross_m2_each} disabled={disabled} onChange={(e) => patch(i, "gross_m2_each", e.target.value)} />
                </div>
                <div className="w-24">
                  <Label className="text-[11px]">Net m²/adet</Label>
                  <Input type="number" value={u.net_m2_each ?? ""} disabled={disabled} onChange={(e) => patch(i, "net_m2_each", e.target.value)} placeholder="ops." />
                </div>
                <div className="w-32">
                  <Label className="text-[11px]">Satış Fiyatı (TRY)</Label>
                  <Input type="number" value={u.sale_price_try ?? ""} disabled={disabled} onChange={(e) => patch(i, "sale_price_try", e.target.value)} placeholder="ops." />
                </div>
                {!disabled && (
                  <button
                    type="button"
                    onClick={() => onUnitsChange(units.filter((_, j) => j !== i))}
                    className="mb-1.5 text-text-secondary hover:text-danger"
                    aria-label="Satırı sil"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
        {!disabled && (
          <Button type="button" variant="outline" className="mt-2 w-full" onClick={() => onUnitsChange([...units, emptyUnitRow()])}>
            <Plus className="h-4 w-4" /> Daire Tipi Ekle
          </Button>
        )}
      </div>

      {/* Live mini-summary */}
      <div className="grid grid-cols-2 gap-2 rounded-md border border-border bg-surface p-3 text-sm sm:grid-cols-4">
        <Stat label="Toplam Daire" value={String(summary.totalUnits)} />
        <Stat label="Toplam Brüt Satılabilir" value={fmtM2(summary.grossM2)} />
        <Stat label="Toplam Net Satılabilir" value={fmtM2(summary.netM2)} />
        <Stat label="Tahmini Toplam Satış" value={summary.estimatedSales === null ? "—" : formatCurrency(summary.estimatedSales)} />
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-text-secondary">{label}</div>
      <div className="font-semibold text-primary">{value}</div>
    </div>
  );
}
