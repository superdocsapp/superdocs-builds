import { describe, expect, it } from "vitest";
import { loadSource } from "./load-source";

const { readRosterRows, findHeaderColumn } = loadSource<{
  readRosterRows: (sheet: any, startRow?: number, endRow?: number) => Array<{ rowNumber: number; values: Record<string, unknown> }>;
  findHeaderColumn: (sheet: any, header: string) => number;
}>("sheets.ts", ["readRosterRows", "findHeaderColumn"]);

function fakeSheet(headers: string[], rows: unknown[][]) {
  return {
    getLastRow: () => rows.length + 1,
    getLastColumn: () => headers.length,
    getRange: (row: number, _column: number, rowCount?: number) => ({
      getDisplayValues: () => [headers],
      getValues: () => rows.slice(row - 2, row - 2 + (rowCount || 1))
    })
  };
}

describe("roster row reading", () => {
  it("maps values to the right row numbers when reading a slice", () => {
    const sheet = fakeSheet(["Name", "Email"], [["Asha", "a@example.com"], ["Ben", "b@example.com"], ["Cy", "c@example.com"]]);
    expect(readRosterRows(sheet, 3, 4)).toEqual([
      { rowNumber: 3, values: { Name: "Ben", Email: "b@example.com" } },
      { rowNumber: 4, values: { Name: "Cy", Email: "c@example.com" } }
    ]);
  });

  it("trims headers and ignores blank header cells", () => {
    const sheet = fakeSheet([" Name ", "", "Email"], [["Asha", "ignored", "a@example.com"]]);
    expect(readRosterRows(sheet)).toEqual([{ rowNumber: 2, values: { Name: "Asha", Email: "a@example.com" } }]);
  });

  it("returns no rows for an empty roster or an inverted range", () => {
    expect(readRosterRows(fakeSheet(["Name"], []))).toEqual([]);
    expect(readRosterRows(fakeSheet(["Name"], [["Asha"]]), 4, 2)).toEqual([]);
  });

  it("finds headers case-insensitively and reports missing headers", () => {
    const sheet = fakeSheet(["Name", " eMaIl "], []);
    expect(findHeaderColumn(sheet, "email")).toBe(2);
    expect(findHeaderColumn(sheet, "Department")).toBe(-1);
  });
});
