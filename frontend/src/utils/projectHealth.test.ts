import { describe, expect, it } from "vitest";
import { clampPct, computeProjectHealth, healthExplanation, timeElapsedPct } from "./projectHealth";

describe("clampPct", () => {
  it("clamps into 0–100 and zeroes non-finite", () => {
    expect(clampPct(-10)).toBe(0);
    expect(clampPct(150)).toBe(100);
    expect(clampPct(42)).toBe(42);
    expect(clampPct(NaN)).toBe(0);
  });
});

describe("timeElapsedPct", () => {
  const start = "2026-01-01";
  const end = "2026-12-31"; // ~365-day span

  it("is ~50% at the midpoint", () => {
    const mid = new Date("2026-07-02");
    expect(timeElapsedPct(start, end, mid)).toBeGreaterThan(48);
    expect(timeElapsedPct(start, end, mid)).toBeLessThan(52);
  });

  it("clamps before start (0) and after end (100)", () => {
    expect(timeElapsedPct(start, end, new Date("2025-06-01"))).toBe(0);
    expect(timeElapsedPct(start, end, new Date("2027-06-01"))).toBe(100);
  });

  it("returns 0 for missing or inverted dates", () => {
    expect(timeElapsedPct(null, end, new Date("2026-07-02"))).toBe(0);
    expect(timeElapsedPct(end, start, new Date("2026-07-02"))).toBe(0); // end<=start
  });
});

describe("computeProjectHealth", () => {
  const dates = { startDate: "2026-01-01", plannedEndDate: "2026-12-31" };

  it("flags RED when cost runs well ahead of progress (70% spent, 40% built)", () => {
    const h = computeProjectHealth({
      completionPct: 40,
      actualCostTry: 700,
      revisedBudgetTry: 1000,
      today: new Date("2026-06-01"),
      ...dates,
    });
    expect(h.costPct).toBeCloseTo(70, 5);
    expect(h.completionPct).toBe(40);
    expect(h.costGap).toBeCloseTo(30, 5);
    expect(h.signal).toBe("red");
  });

  it("is GREEN when spending matches/trails progress", () => {
    const h = computeProjectHealth({
      completionPct: 40,
      actualCostTry: 380,
      revisedBudgetTry: 1000,
      today: new Date("2026-05-20"), // ~38% of the year → time roughly in line
      ...dates,
    });
    expect(h.costPct).toBeCloseTo(38, 5);
    expect(h.signal).toBe("green");
  });

  it("flags risk when TIME leads progress even if cost is fine", () => {
    const h = computeProjectHealth({
      completionPct: 40,
      actualCostTry: 390, // cost ~in line
      revisedBudgetTry: 1000,
      today: new Date("2026-11-01"), // ~83% of the year elapsed
      ...dates,
    });
    expect(h.timePct).toBeGreaterThan(80);
    expect(h.timeGap).toBeGreaterThan(20);
    expect(h.signal).toBe("red");
  });

  it("a zero budget yields a null cost% (no divide-by-zero, not 0)", () => {
    const h = computeProjectHealth({
      completionPct: 40, // a real completion so only the budget is missing
      actualCostTry: 0,
      revisedBudgetTry: 0,
      today: new Date("2026-06-01"),
      ...dates,
    });
    expect(h.costPct).toBeNull();
    expect(h.costKnown).toBe(false);
    expect(h.costGap).toBeNull();
  });

  it("is UNKNOWN (no false red) when completion is a blank default and there are no milestones", () => {
    // Both dates in the past → time would be 100%, but completion is an unset 0:
    // the old code returned a confident red; now it must stay neutral.
    const h = computeProjectHealth({
      completionPct: 0,
      actualCostTry: 500,
      revisedBudgetTry: 1000,
      startDate: "2020-01-01",
      plannedEndDate: "2020-12-31",
      today: new Date("2026-06-01"),
    });
    expect(h.completionKnown).toBe(false);
    expect(h.signal).toBe("unknown");
  });

  it("treats a 0 completion as REAL when milestones exist, so it can flag risk", () => {
    const h = computeProjectHealth({
      completionPct: 0,
      hasMilestones: true, // objective progress data exists (0% done)
      actualCostTry: 700,
      revisedBudgetTry: 1000,
      startDate: "2020-01-01",
      plannedEndDate: "2020-12-31",
      today: new Date("2026-06-01"),
    });
    expect(h.completionKnown).toBe(true);
    expect(h.signal).toBe("red");
  });

  it("is UNKNOWN when there is nothing to compare against (no budget, no dates)", () => {
    const h = computeProjectHealth({
      completionPct: 40,
      actualCostTry: 0,
      revisedBudgetTry: 0,
      startDate: null,
      plannedEndDate: null,
      today: new Date("2026-06-01"),
    });
    expect(h.signal).toBe("unknown");
  });
});

describe("healthExplanation", () => {
  const dates = { startDate: "2026-01-01", plannedEndDate: "2026-12-31" };

  it("explains a cost-ahead project in Turkish", () => {
    const h = computeProjectHealth({
      completionPct: 40,
      actualCostTry: 700,
      revisedBudgetTry: 1000,
      today: new Date("2026-06-01"),
      ...dates,
    });
    expect(healthExplanation(h)).toContain("maliyet ilerlemenin önünde");
    expect(healthExplanation(h)).toContain("%70");
    expect(healthExplanation(h)).toContain("%40");
  });

  it("explains a healthy project in Turkish", () => {
    const h = computeProjectHealth({
      completionPct: 40,
      actualCostTry: 380,
      revisedBudgetTry: 1000,
      today: new Date("2026-05-20"),
      ...dates,
    });
    expect(healthExplanation(h)).toContain("uyumlu");
  });

  it("gives a neutral note (not a risk verdict) when progress data is missing", () => {
    const h = computeProjectHealth({
      completionPct: 0, // blank default, no milestones
      actualCostTry: 500,
      revisedBudgetTry: 1000,
      startDate: "2020-01-01",
      plannedEndDate: "2020-12-31",
      today: new Date("2026-06-01"),
    });
    const msg = healthExplanation(h);
    expect(msg).toContain("İlerleme verisi yok");
    // The "süre %100 geçti ama %0 tamamlandı" message must NOT fire here.
    expect(msg).not.toContain("ilerlemenin önünde");
  });
});
