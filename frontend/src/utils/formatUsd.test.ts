// CR-014-D: USD formatting — $ grouping, and a MISSING snapshot renders "—"
// (never $0), so a pre-backfill / null value never reads as a real figure.
import { describe, expect, it } from "vitest";
import { formatUSD, formatUSDAbbrev } from "./format";

describe("formatUSD", () => {
  it("formats with $ + en-US grouping to the cent", () => {
    expect(formatUSD("1234567.5")).toBe("$1,234,567.50");
    expect(formatUSD(1000)).toBe("$1,000.00");
    expect(formatUSD("0")).toBe("$0.00");
  });

  it('renders "—" for a missing snapshot (null/undefined/empty), never $0', () => {
    expect(formatUSD(null)).toBe("—");
    expect(formatUSD(undefined)).toBe("—");
    expect(formatUSD("")).toBe("—");
  });
});

describe("formatUSDAbbrev", () => {
  it("abbreviates millions/billions and handles null", () => {
    expect(formatUSDAbbrev("2500000")).toBe("$2.5 Mn");
    expect(formatUSDAbbrev("3200000000")).toBe("$3.2 Mr");
    expect(formatUSDAbbrev(null)).toBe("—");
  });
});
