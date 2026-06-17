import { describe, expect, it } from "vitest";
import { shouldShowFinancingHint } from "./financing";

describe("shouldShowFinancingHint", () => {
  it("shows the hint to a director when financing is off", () => {
    expect(shouldShowFinancingHint(true, { enabled: false, total_try: "0.00" })).toBe(true);
  });

  it("hides it when financing is enabled (the card shows instead)", () => {
    expect(shouldShowFinancingHint(true, { enabled: true, total_try: "0.00" })).toBe(false);
    expect(shouldShowFinancingHint(true, { enabled: true, total_try: "2000.00" })).toBe(false);
  });

  it("hides it from non-directors (they can't change company settings)", () => {
    expect(shouldShowFinancingHint(false, { enabled: false })).toBe(false);
  });

  it("hides it until the dashboard payload (financing block) has loaded", () => {
    expect(shouldShowFinancingHint(true, null)).toBe(false);
    expect(shouldShowFinancingHint(true, undefined)).toBe(false);
  });
});
