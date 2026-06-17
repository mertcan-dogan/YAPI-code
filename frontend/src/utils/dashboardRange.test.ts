import { describe, expect, it } from "vitest";
import { dashRangeParams } from "./dashboardRange";

const NOW = new Date(2026, 5, 17); // 2026-06-17 (month is 0-based)

describe("dashRangeParams", () => {
  it("default 'Tümü' is not a range — wide bounds = whole project (no regression)", () => {
    const r = dashRangeParams("all", "", "", NOW);
    expect(r.rangeActive).toBe(false);
    expect(r.from_month).toBeUndefined();
    expect(r.from_date).toBe("2000-01-01");
    expect(r.to_date).toBe("2100-12-31");
    expect(r.label).toBe("Tüm Proje");
  });

  it("'Son 3 Ay' spans this month and the two prior", () => {
    const r = dashRangeParams("3m", "", "", NOW);
    expect(r.rangeActive).toBe(true);
    expect([r.from_month, r.to_month]).toEqual(["2026-04", "2026-06"]);
    expect(r.from_date).toBe("2026-04-01");
    expect(r.to_date).toBe("2026-06-30"); // last day of June
  });

  it("'Son 12 Ay' and 'Bu Yıl' compute correctly", () => {
    expect(dashRangeParams("12m", "", "", NOW).from_month).toBe("2025-07");
    const year = dashRangeParams("year", "", "", NOW);
    expect([year.from_month, year.to_month]).toEqual(["2026-01", "2026-06"]);
  });

  it("custom range uses the picked months + last day; invalid when from>to", () => {
    const ok = dashRangeParams("custom", "2025-02", "2025-05", NOW);
    expect(ok.rangeActive).toBe(true);
    expect(ok.from_date).toBe("2025-02-01");
    expect(ok.to_date).toBe("2025-05-31");

    const bad = dashRangeParams("custom", "2025-06", "2025-03", NOW);
    expect(bad.invalid).toBe(true);
    expect(bad.rangeActive).toBe(false); // inverted range isn't fetched
  });

  it("incomplete custom range is inactive (falls back to whole project)", () => {
    const r = dashRangeParams("custom", "2025-02", "", NOW);
    expect(r.rangeActive).toBe(false);
    expect(r.from_date).toBe("2000-01-01");
  });

  it("changing preset changes the emitted params (so the page refetches)", () => {
    const a = dashRangeParams("3m", "", "", NOW);
    const b = dashRangeParams("6m", "", "", NOW);
    expect(a.from_date).not.toBe(b.from_date);
  });
});
