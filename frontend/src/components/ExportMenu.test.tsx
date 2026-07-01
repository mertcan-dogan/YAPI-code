// Unit tests for the reusable ExportMenu's pure helpers: raw-value matrix
// extraction (no JSX), CSV escaping, the date-stamp used in filenames, and
// (CR-055) the per-column xlsx number formats (₺/$/%).
import * as XLSX from "xlsx";
import { describe, expect, it } from "vitest";
import { applyColumnFormats, buildMatrix, dateStamp, toCSV, type ExportColumn } from "./ExportMenu";

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

describe("applyColumnFormats (CR-055 xlsx number formats)", () => {
  type Cost = { cat: string; amount: number; usd: number | string; vat: number; n: number; date: string };
  const cols: ExportColumn<Cost>[] = [
    { header: "Kategori", value: (r) => r.cat },
    { header: "Tutar", value: (r) => r.amount, type: "currency" },
    { header: "USD", value: (r) => r.usd, type: "usd" },
    { header: "KDV Oranı", value: (r) => r.vat, type: "percent" },
    { header: "Adet", value: (r) => r.n, type: "number" },
    { header: "Tarih", value: (r) => r.date, type: "date" },
  ];

  const buildFormatted = (rows: Cost[]) => {
    const { headers, data } = buildMatrix(rows, cols);
    const ws = XLSX.utils.aoa_to_sheet([headers, ...data]);
    applyColumnFormats(ws as any, cols, data.length, XLSX);
    return ws as Record<string, { z?: string; t?: string }>;
  };

  it("applies ₺/$/%/number formats to numeric cells; leaves text/date alone", () => {
    const ws = buildFormatted([{ cat: "Beton", amount: 288810, usd: 8600, vat: 20, n: 5, date: "01.02.2026" }]);
    // a cost cell carries the ₺ format, NOT General/raw.
    expect(ws["B2"].z).toBe('#,##0" ₺"');
    expect(ws["B2"].z).not.toBe("General");
    expect(ws["C2"].z).toBe('#,##0" $"'); // usd
    expect(ws["D2"].z).toBe('0.0"%"'); // percent — literal, no ×100
    expect(ws["E2"].z).toBe("#,##0"); // number
    expect(ws["A2"].z).toBeUndefined(); // text column untouched
    expect(ws["F2"].z).toBeUndefined(); // date value is a string → not numeric-formatted
  });

  it("does not format a blank/missing USD cell (no fabrication)", () => {
    const ws = buildFormatted([{ cat: "Beton", amount: 1000, usd: "", vat: 20, n: 1, date: "01.02.2026" }]);
    // an empty-string USD cell isn't numeric → left unformatted (renders blank, not 0 $).
    expect(ws["C2"]?.z).toBeUndefined();
    // the ₺ amount beside it is still formatted.
    expect(ws["B2"].z).toBe('#,##0" ₺"');
  });
});
