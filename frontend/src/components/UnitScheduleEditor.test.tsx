// CR-016-C: the residential editor's pure helpers — live summary math (must
// mirror the CR-016-B backend aggregates) and payload normalisation.
import { describe, expect, it } from "vitest";
import { computeScheduleSummary, unitsForPayload, type UnitRow } from "./UnitScheduleEditor";

const row = (over: Partial<UnitRow>): UnitRow => ({
  unit_type: "2+1",
  count: "10",
  gross_m2_each: "100",
  ...over,
});

describe("computeScheduleSummary", () => {
  it("sums units and count×m² across rows (matches backend)", () => {
    const s = computeScheduleSummary([
      row({ unit_type: "2+1", count: "10", gross_m2_each: "100", net_m2_each: "85", sale_price_try: "3000000" }),
      row({ unit_type: "3+1", count: "4", gross_m2_each: "140", net_m2_each: "120", sale_price_try: "4500000" }),
    ]);
    expect(s.totalUnits).toBe(14);
    expect(s.grossM2).toBe(1560); // 10*100 + 4*140
    expect(s.netM2).toBe(1330); // 10*85 + 4*120
    expect(s.estimatedSales).toBe(48_000_000); // 10*3M + 4*4.5M
  });

  it("estimatedSales is null when no row has a price", () => {
    const s = computeScheduleSummary([row({ count: "5", gross_m2_each: "80" })]);
    expect(s.totalUnits).toBe(5);
    expect(s.grossM2).toBe(400);
    expect(s.netM2).toBe(0); // no net supplied
    expect(s.estimatedSales).toBeNull();
  });

  it("only counts net for rows that supply one", () => {
    const s = computeScheduleSummary([
      row({ count: "2", gross_m2_each: "100", net_m2_each: "90" }),
      row({ count: "3", gross_m2_each: "100" }), // no net
    ]);
    expect(s.netM2).toBe(180); // only the first row contributes
  });
});

describe("unitsForPayload", () => {
  it("drops incomplete rows (no count / no gross / 'other' without label)", () => {
    const out = unitsForPayload([
      row({ count: "10", gross_m2_each: "100" }),
      row({ count: "0", gross_m2_each: "100" }), // count < 1
      row({ count: "5", gross_m2_each: "" }), // no gross
      row({ unit_type: "other", custom_label: "", count: "2", gross_m2_each: "30" }), // other w/o label
    ]);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ unit_type: "2+1", count: 10, gross_m2_each: "100" });
  });

  it("keeps 'other' rows with a label and nulls custom_label otherwise", () => {
    const out = unitsForPayload([
      row({ unit_type: "other", custom_label: "Sığınak", count: "2", gross_m2_each: "30" }),
      row({ unit_type: "2+1", custom_label: "ignored", count: "1", gross_m2_each: "90" }),
    ]);
    expect(out[0]).toMatchObject({ unit_type: "other", custom_label: "Sığınak", count: 2 });
    expect(out[1].custom_label).toBeNull();
  });

  it("preserves id for existing rows (upsert) and omits it for new ones", () => {
    const out = unitsForPayload([
      row({ id: "abc", count: "1", gross_m2_each: "90" }),
      row({ count: "1", gross_m2_each: "90" }),
    ]);
    expect(out[0]).toHaveProperty("id", "abc");
    expect(out[1]).not.toHaveProperty("id");
  });

  it("nulls optional net/price/notes when blank", () => {
    const [u] = unitsForPayload([row({ count: "1", gross_m2_each: "90", net_m2_each: "", sale_price_try: "" })]);
    expect(u.net_m2_each).toBeNull();
    expect(u.sale_price_try).toBeNull();
    expect(u.notes).toBeNull();
  });
});
