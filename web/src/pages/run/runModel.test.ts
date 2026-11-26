import { describe, expect, it } from "vitest";
import type { StatementRow } from "../../api";
import { gridRows, ruled } from "./runModel";

const value = { figure_id: 1, concept_uuid: "", value: 5, printed: 5, stated: null, certainty: "sure" as const, reason: "", edited: false, origin: "agent", writable: true, agent_writable: true, lines_sum: null };
const r = (kind: StatementRow["kind"], label: string, filled = true): StatementRow => ({
  kind, label, field_label: label, printed_label: label, concept_uuid: label, sheet: "S", row: 1, page: 1, print_order: 1,
  cells: filled && kind !== "heading" ? { "Company:CY": value } : {}, status: null, certainty: "sure", reason: "", edited: false,
});
const shape = (rows: StatementRow[]) => rows.map((x) => `${x.kind}:${x.label}`);

describe("the grid's rows", () => {
  it("in report order, names each report section once and marks only the totals the report prints", () => {
    const rows = [
      r("heading", "Current assets › Trade and other current receivables › Current trade receivables"),
      r("line", "Amounts due from related companies"),
      r("heading", "Current assets › Cash and cash equivalents"),
      r("total", "Cash and bank balances"),
      r("total", "Total current assets"),
      r("heading", "Equity"),
      r("total", "Profit for the year"),
    ];
    expect(shape(gridRows(rows, "report"))).toEqual([
      "heading:Current assets", "line:Amounts due from related companies", "line:Cash and bank balances",
      "total:Total current assets", "heading:Equity", "total:Profit for the year",
    ]);
  });

  it("in template order, hides empty fields and headings with nothing under them until asked", () => {
    const rows = [
      r("heading", "Statement of financial position"), r("heading", "Assets"), r("heading", "Non-current assets"),
      r("line", "Property, plant and equipment"), r("line", "Investment property", false),
      r("heading", "Biological assets"), r("line", "Bearer plants", false),
      r("total", "Total non-current assets"),
    ];
    expect(shape(gridRows(rows, "template"))).toEqual([
      "heading:Non-current assets", "line:Property, plant and equipment", "total:Total non-current assets",
    ]);
    expect(shape(gridRows(rows, "template", true))).toEqual([
      "heading:Non-current assets", "line:Property, plant and equipment", "line:Investment property",
      "heading:Biological assets", "line:Bearer plants", "total:Total non-current assets",
    ]);
  });

  it("draws the total rule on report totals, and on template fields named as totals", () => {
    expect(ruled(r("total", "Profit for the year"), "report")).toBe(true);
    expect(ruled(r("total", "Property, plant and equipment"), "template")).toBe(false);
    expect(ruled(r("total", "Total assets"), "template")).toBe(true);
    expect(ruled(r("line", "Total assets"), "report")).toBe(false);
  });
});
