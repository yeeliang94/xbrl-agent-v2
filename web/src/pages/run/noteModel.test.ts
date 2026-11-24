import { describe, expect, it } from "vitest";
import type { TableBlock } from "../../api";
import { applyLook, cellTargets, keepUnsure, lookNow, notePart, selectCell, selectionName, toolsFor, unsureItems } from "./noteModel";
import { noteFlags, noteGroups, noteParts } from "./noteList";
import { borrowings, contingent, instruments, noteFields, noteReports, receivables, related1, related2, revenue, summary } from "./noteFixtures";

const words = (blocks: typeof revenue.blocks) =>
  blocks.flatMap((b) => (b.kind === "table" ? b.rows.flatMap((r) => r.cells.map((c) => c.text)) : b.kind === "list" ? b.items.map((i) => i.text) : [b.text]));

describe("Note selection", () => {
  const t = revenue.blocks[2] as TableBlock;

  it("covers a cell, a row, a column or the whole table", () => {
    const at = (scope: "cell" | "row" | "column" | "table") => cellTargets(t, { kind: "table", block: 2, row: 2, column: 1, scope });
    expect(at("cell")).toEqual([[2, 1]]);
    expect(at("row")).toEqual([[2, 0], [2, 1], [2, 2]]);
    expect(at("column")).toEqual([[0, 1], [1, 1], [2, 1], [3, 1]]);
    expect(at("table")).toHaveLength(12);
  });

  it("keeps the chosen scope when another cell of the same table is clicked", () => {
    const row = selectCell({ kind: "table", block: 2, row: 1, column: 1, scope: "row" }, 2, 3, 0);
    expect(row).toEqual({ kind: "table", block: 2, row: 3, column: 0, scope: "row" });
    expect(selectCell({ kind: "block", block: 1 }, 2, 1, 1)).toMatchObject({ scope: "cell" });
  });

  it("names the selection and the part a comment is about", () => {
    const sel = { kind: "table" as const, block: 2, row: 1, column: 1, scope: "cell" as const };
    expect(selectionName(revenue.blocks, sel)).toBe("Sale of hardware, 2025");
    expect(selectionName(revenue.blocks, { ...sel, scope: "row" })).toBe("Row: Sale of hardware");
    expect(selectionName(revenue.blocks, { ...sel, scope: "column" })).toBe("Column: 2025");
    expect(notePart(revenue.blocks, { ...sel, scope: "column" })).toEqual({ block: "p27b2", scope: "column", row: null, column: 1 });
    expect(notePart(revenue.blocks, { kind: "block", block: 1 })).toEqual({ block: "p27b1", scope: "block", row: null, column: null });
  });
});

describe("Look changes", () => {
  const row = { kind: "table" as const, block: 2, row: 1, column: 1, scope: "row" as const };

  it("changes only looks, never a word", () => {
    const next = applyLook(revenue.blocks, row, { k: "bold" })!;
    expect(words(next)).toEqual(words(revenue.blocks));
    expect((next[2] as TableBlock).rows[1].cells.every((c) => c.look.bold)).toBe(true);
    expect(lookNow(next, row).bold).toBe(true);
  });

  it("adds a thick bottom line, and takes it away on a second press", () => {
    const once = applyLook(revenue.blocks, row, { k: "border", v: "thick" })!;
    expect((once[2] as TableBlock).rows[1].line_below).toEqual({ style: "double", columns: [] });
    const twice = applyLook(once, row, { k: "border", v: "thick" })!;
    expect((twice[2] as TableBlock).rows[1].line_below).toBeNull();
  });

  it("puts a top border on the row above, and clears unsure for what it sets", () => {
    const next = applyLook(revenue.blocks, { ...row, row: 3 }, { k: "border", v: "top" })!;
    const t = next[2] as TableBlock;
    expect(t.rows[2].line_below).toEqual({ style: "single", columns: [] });
    expect(t.rows[2].unsure).toEqual([]);
  });

  it("offers borders only for a table, top only below the first row, and no bold for a heading", () => {
    expect(toolsFor(revenue.blocks, { kind: "block", block: 1 })).toMatchObject({ text: true, borders: false });
    expect(toolsFor(revenue.blocks, { kind: "block", block: 0 }).bold).toBe(false);
    expect(toolsFor(revenue.blocks, { ...row, row: 0 }).top).toBe(false);
    expect(applyLook(revenue.blocks, null, { k: "bold" })).toBeNull();
  });

  it("indents a paragraph up to four steps", () => {
    let blocks = revenue.blocks;
    for (let i = 0; i < 6; i++) blocks = applyLook(blocks, { kind: "block", block: 1 }, { k: "indent", d: 1 })!;
    expect(blocks[1].kind === "paragraph" && blocks[1].look.indent).toBe(4);
  });
});

describe("Not sure looks", () => {
  it("lists each one and keeps it as drawn", () => {
    const items = unsureItems(revenue.blocks);
    expect(items.map((i) => i.what)).toEqual(["Paragraph, alignment", "Sale of building materials, line below"]);
    const kept = keepUnsure(revenue.blocks, items[1]);
    expect(unsureItems(kept)).toHaveLength(1);
    expect((kept[2] as TableBlock).rows[2].line_below).toEqual((revenue.blocks[2] as TableBlock).rows[2].line_below);
  });
});

describe("Notes list", () => {
  const notes = [revenue, receivables, borrowings, instruments, contingent, related1, related2].map(summary);

  it("groups notes by template, lists missing fields, and puts not placed notes last", () => {
    const groups = noteGroups(noteFields, notes, noteReports, []);
    expect(groups.map((g) => g.name)).toEqual(["Corporate information", "Accounting policies", "List of notes", "Issued capital", "Related parties", "Not placed"]);
    expect(groups[1].items).toEqual([{ kind: "missing", id: 32, name: "Significant accounting judgements and estimates", count: 1 }]);
    expect(groups[4].items.map((i) => i.name)).toEqual(["Related parties, part 1", "Related parties, part 2"]);
    expect(groups[2].count).toBe(3);
  });

  it("flags a too long field, a reduced tier, a gap and a note not placed", () => {
    expect(noteFlags(summary(instruments), noteReports).tooLong).toBe(true);
    expect(noteFlags(summary(borrowings), noteReports).tier).toBe("Lite styling");
    expect(noteFlags(summary(receivables), noteReports).gaps).toHaveLength(1);
    expect(noteFlags(summary(contingent), noteReports).notPlaced).toBe(true);
    expect(noteParts(notes, summary(related2)).map((n) => n.id)).toEqual([8, 9]);
  });
});
