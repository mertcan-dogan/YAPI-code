// Unit tests for the reusable ExportMenu's pure helpers: raw-value matrix
// extraction (no JSX), CSV escaping, and the date-stamp used in filenames.
import { describe, expect, it } from "vitest";
import { buildMatrix, dateStamp, toCSV, type ExportColumn } from "./ExportMenu";

interface Row {
  name: string;
  amount: string;
  count: number;
}

const rows: Row[] = [
  { name: "Akçansa", amount: "1234.56", count: 3 },
  { name: 'Demir, "Çelik"', amount: "0", count: 0 },
];

const columns: ExportColumn<Row>[] = [
  { header: "Tedarikçi", value: (r) => r.name },
  { header: "Tutar", value: (r) => Number(r.amount) },
  { header: "Kayıt", value: (r) => r.count },
];

describe("buildMatrix", () => {
  it("uses raw values + headers, keeping numbers as numbers", () => {
    const { headers, data } = buildMatrix(rows, columns);
    expect(headers).toEqual(["Tedarikçi", "Tutar", "Kayıt"]);
    expect(data[0]).toEqual(["Akçansa", 1234.56, 3]);
    // numeric cells are real numbers, not formatted strings
    expect(typeof data[0][1]).toBe("number");
  });
});

describe("toCSV", () => {
  it("emits header + rows, plain numbers, CRLF separated", () => {
    const { headers, data } = buildMatrix(rows, columns);
    const csv = toCSV(headers, data);
    const lines = csv.split("\r\n");
    expect(lines[0]).toBe("Tedarikçi,Tutar,Kayıt");
    expect(lines[1]).toBe("Akçansa,1234.56,3");
  });

  it("escapes commas and quotes per RFC-4180", () => {
    const { headers, data } = buildMatrix(rows, columns);
    const csv = toCSV(headers, data);
    const lines = csv.split("\r\n");
    // name contains a comma and embedded quotes -> quoted with doubled quotes
    expect(lines[2]).toBe('"Demir, ""Çelik""",0,0');
  });
});

describe("dateStamp", () => {
  it("formats as YYYY-MM-DD with zero padding", () => {
    expect(dateStamp(new Date(2026, 5, 6))).toBe("2026-06-06");
  });
});
