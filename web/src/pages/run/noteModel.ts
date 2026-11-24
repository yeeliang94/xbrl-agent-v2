// Plain helpers for the notes screens: what a selection covers, a look change
// on the block model (app/notes/blocks.py), the "not sure" looks, and labels.
// No React here. A look change never touches a word: it copies the blocks and
// changes only look values, so the server's "look only" rule always holds.
import type { Align, CellLook, NoteBlock, NotePart, TableBlock, TableRow, TextLook } from "../../api";

export type Scope = "cell" | "row" | "column" | "table";

export type NoteSelection =
  | { kind: "block"; block: number }
  | { kind: "table"; block: number; row: number; column: number; scope: Scope }
  | { kind: "gap"; report: number }
  | { kind: "figure"; row: number; column: string }
  | null;

export type LookAction =
  | { k: "bold" }
  | { k: "italic" }
  | { k: "underline" }
  | { k: "align"; v: "left" | "center" | "right" }
  | { k: "indent"; d: 1 | -1 }
  | { k: "border"; v: "top" | "bottom" | "thick" | "none" };

const MAX_TEXT_INDENT = 4;
const MAX_ROW_INDENT = 3;

const copyBlocks = (blocks: NoteBlock[]): NoteBlock[] => JSON.parse(JSON.stringify(blocks)) as NoteBlock[];
const drop = (list: string[], key: string) => list.filter((k) => k !== key);
const clamp = (n: number, low: number, high: number) => Math.max(low, Math.min(high, n));

/** A look value as drawn: one the agent was not sure of is drawn in the house style, as absent. */
export function setValue<T extends { unsure: string[] }, K extends keyof T>(look: T, key: K): T[K] | null {
  return look.unsure.includes(String(key)) ? null : look[key];
}

/** The cells a table selection covers, as [row, column]. */
export function cellTargets(table: TableBlock, sel: NoteSelection): [number, number][] {
  if (!sel || sel.kind !== "table") return [];
  const out: [number, number][] = [];
  table.rows.forEach((_, r) =>
    table.columns.forEach((__, c) => {
      const hit =
        sel.scope === "table" ||
        (sel.scope === "row" && r === sel.row) ||
        (sel.scope === "column" && c === sel.column) ||
        (sel.scope === "cell" && r === sel.row && c === sel.column);
      if (hit) out.push([r, c]);
    }),
  );
  return out;
}

/** Whether a block, or one cell of a table, is inside the selection. */
export function isSelected(blocks: NoteBlock[], sel: NoteSelection, block: number, row = 0, column = 0): boolean {
  if (!sel || (sel.kind !== "block" && sel.kind !== "table") || sel.block !== block) return false;
  const b = blocks[block];
  if (b.kind !== "table") return true;
  if (sel.kind !== "table" || row < 0 || row >= b.rows.length || column < 0 || column >= b.columns.length) return false;
  // The same rule as cellTargets, for one cell: no list is built per cell.
  return sel.scope === "table" || (sel.scope === "row" && row === sel.row) || (sel.scope === "column" && column === sel.column) || (sel.scope === "cell" && row === sel.row && column === sel.column);
}

/** A click on a cell keeps the scope already chosen for that table; anywhere else starts at the cell. */
export function selectCell(current: NoteSelection, block: number, row: number, column: number): NoteSelection {
  const scope = current?.kind === "table" && current.block === block ? current.scope : "cell";
  return { kind: "table", block, row, column, scope };
}

function setFlag(look: TextLook | CellLook, key: "bold" | "italic" | "underline", value: boolean) {
  look[key] = value;
  look.unsure = drop(look.unsure, key);
}

const lineColumns = (row: TableRow, width: number) =>
  row.line_below ? (row.line_below.columns.length ? row.line_below.columns : [...Array(width).keys()]) : [];

function putLine(row: TableRow, columns: number[], style: "single" | "double" | null, width: number) {
  const kept = new Set(columns);
  const sorted = [...kept].sort((a, b) => a - b);
  row.line_below = !style || sorted.length === 0 ? null : { style, columns: sorted.length === width ? [] : sorted };
  row.unsure = drop(row.unsure, "line_below");
}

/** Adds a line under `cols` of each row, or takes it away when every one already has it. */
function toggleLines(t: TableBlock, rows: Map<number, number[]>, style: "single" | "double") {
  const width = t.columns.length;
  const covered = [...rows].every(([r, cols]) => {
    const row = t.rows[r];
    return row.line_below?.style === style && cols.every((c) => lineColumns(row, width).includes(c));
  });
  for (const [r, cols] of rows) {
    const row = t.rows[r];
    const now = lineColumns(row, width);
    if (covered) putLine(row, now.filter((c) => !cols.includes(c)), style, width);
    else putLine(row, [...now, ...cols], style, width);
  }
}

function clearLines(t: TableBlock, rows: Map<number, number[]>) {
  const width = t.columns.length;
  for (const [r, cols] of rows) {
    const row = t.rows[r];
    if (row.line_below) putLine(row, lineColumns(row, width).filter((c) => !cols.includes(c)), row.line_below.style, width);
    else row.unsure = drop(row.unsure, "line_below");
  }
}

function byRow(cells: [number, number][], shift = 0): Map<number, number[]> {
  const rows = new Map<number, number[]>();
  for (const [r, c] of cells) {
    const at = r + shift;
    if (at < 0) continue;
    rows.set(at, [...(rows.get(at) ?? []), c]);
  }
  return rows;
}

/** The note's blocks with one look change made, or null when the change does not apply to the selection. */
export function applyLook(blocks: NoteBlock[], sel: NoteSelection, action: LookAction): NoteBlock[] | null {
  if (!sel || (sel.kind !== "block" && sel.kind !== "table")) return null;
  const next = copyBlocks(blocks);
  const b = next[sel.block];
  if (!b) return null;
  if (b.kind !== "table") {
    const look = b.look;
    if (action.k === "bold" || action.k === "italic" || action.k === "underline") {
      if (action.k === "bold" && b.kind === "heading") return null;
      setFlag(look, action.k, !look[action.k]);
    } else if (action.k === "align") {
      look.align = action.v;
      look.unsure = drop(look.unsure, "align");
    } else if (action.k === "indent") {
      look.indent = clamp(look.indent + action.d, 0, MAX_TEXT_INDENT);
      look.unsure = drop(look.unsure, "indent");
    } else return null;
    return next;
  }
  const cells = cellTargets(b, sel);
  if (!cells.length) return null;
  const [r0, c0] = cells[0];
  if (action.k === "bold" || action.k === "italic" || action.k === "underline") {
    const key = action.k;
    const first = b.rows[r0].cells[c0].look[key] || (key === "bold" && b.rows[r0].bold);
    for (const [r, c] of cells) setFlag(b.rows[r].cells[c].look, key, !first);
    if (key === "bold" && first) for (const r of byRow(cells).keys()) b.rows[r].bold = false;
  } else if (action.k === "align") {
    for (const [r, c] of cells) {
      const look = b.rows[r].cells[c].look;
      look.align = action.v;
      look.unsure = drop(look.unsure, "align");
    }
  } else if (action.k === "indent") {
    for (const r of byRow(cells).keys()) {
      const row = b.rows[r];
      row.indent = clamp(row.indent + action.d, 0, MAX_ROW_INDENT);
      row.unsure = drop(row.unsure, "indent");
    }
  } else if (action.v === "bottom" || action.v === "thick") {
    toggleLines(b, byRow(cells), action.v === "thick" ? "double" : "single");
  } else if (action.v === "top") {
    const above = byRow(cells, -1);
    if (!above.size) return null;
    toggleLines(b, above, "single");
  } else {
    clearLines(b, byRow(cells));
    clearLines(b, byRow(cells, -1));
    if (sel.kind === "table" && sel.scope === "table") {
      b.frame = "none";
      b.unsure = drop(b.unsure, "frame");
    }
  }
  return next;
}

export interface LookNow {
  bold: boolean;
  italic: boolean;
  underline: boolean;
  align: Align | null;
  top: boolean;
  bottom: "single" | "double" | null;
}

/** The pressed state of the toolbar: the look of the selection's first cell or its block. */
export function lookNow(blocks: NoteBlock[], sel: NoteSelection): LookNow {
  const none: LookNow = { bold: false, italic: false, underline: false, align: null, top: false, bottom: null };
  if (!sel || (sel.kind !== "block" && sel.kind !== "table")) return none;
  const b = blocks[sel.block];
  if (!b) return none;
  if (b.kind !== "table") {
    const l = b.look;
    return { ...none, bold: b.kind === "heading" || l.bold, italic: l.italic, underline: l.underline, align: setValue(l, "align") };
  }
  const cells = cellTargets(b, sel);
  if (!cells.length) return none;
  const [r, c] = cells[0];
  const row = b.rows[r];
  const look = row.cells[c].look;
  const width = b.columns.length;
  const above = r > 0 ? b.rows[r - 1] : null;
  return {
    bold: row.bold || look.bold,
    italic: look.italic,
    underline: look.underline,
    align: setValue(look, "align") ?? setValue(b.columns[c], "align"),
    top: above !== null && lineColumns(above, width).includes(c),
    bottom: lineColumns(row, width).includes(c) ? row.line_below!.style : null,
  };
}

/** What the toolbar may change for this selection. */
export function toolsFor(blocks: NoteBlock[], sel: NoteSelection) {
  const b = sel && (sel.kind === "block" || sel.kind === "table") ? blocks[sel.block] : undefined;
  const table = b?.kind === "table";
  const topRow = table && sel?.kind === "table" && cellTargets(b, sel).every(([r]) => r === 0);
  return { text: b !== undefined, bold: b !== undefined && b.kind !== "heading", borders: table, top: table && !topRow };
}

// Labels -------------------------------------------------------------------

const BLOCK_WORD = { heading: "Heading", paragraph: "Paragraph", list: "List", table: "Table" } as const;

/** The text of a column's heading row, if it has one. */
export function columnName(t: TableBlock, c: number): string {
  return t.rows.find((r) => r.role === "heading" && r.cells[c]?.text.trim())?.cells[c].text.trim() ?? "";
}

export function rowName(t: TableBlock, r: number): string {
  const row = t.rows[r];
  return row.cells[0]?.text.trim() || (row.role === "total" || row.role === "subtotal" ? "Total" : `Row ${r + 1}`);
}

/** "Row: Sale of hardware", "Column: 2025", "Trade goods, 2024", or the block's kind. */
export function selectionName(blocks: NoteBlock[], sel: NoteSelection): string {
  if (!sel) return "";
  if (sel.kind === "gap") return "Gap in source";
  if (sel.kind === "figure") return "";
  const b = blocks[sel.block];
  if (!b) return "";
  if (b.kind !== "table" || sel.kind !== "table") return BLOCK_WORD[b.kind];
  if (sel.scope === "table") return "Table";
  if (sel.scope === "column") return `Column: ${columnName(b, sel.column) || (sel.column === 0 ? "Labels" : String(sel.column + 1))}`;
  if (sel.scope === "row") return `Row: ${rowName(b, sel.row)}`;
  const col = sel.column > 0 ? columnName(b, sel.column) : "";
  return col ? `${rowName(b, sel.row)}, ${col}` : rowName(b, sel.row);
}

/** The part of the note a comment is about, or null for the whole note. */
export function notePart(blocks: NoteBlock[], sel: NoteSelection): NotePart | null {
  if (!sel || (sel.kind !== "block" && sel.kind !== "table")) return null;
  const b = blocks[sel.block];
  if (!b) return null;
  if (sel.kind === "block") return { block: b.id, scope: "block", row: null, column: null };
  const row = sel.scope === "cell" || sel.scope === "row" ? sel.row : null;
  const column = sel.scope === "cell" || sel.scope === "column" ? sel.column : null;
  return { block: b.id, scope: sel.scope, row, column };
}

/** Whether a comment's part covers this block or cell, for the orange dot. */
export function partCovers(part: NotePart, blocks: NoteBlock[], block: number, row?: number, column?: number): boolean {
  const b = blocks[block];
  if (!b || b.id !== part.block) return false;
  if (row === undefined || part.scope === "block" || part.scope === "table") return true;
  if (part.scope === "row") return part.row === row;
  if (part.scope === "column") return part.column === column;
  return part.row === row && part.column === column;
}

// "Not sure" looks -----------------------------------------------------------

const LOOK_WORD: Record<string, string> = {
  bold: "bold", italic: "italic", underline: "underline", align: "alignment", indent: "indent", valign: "vertical alignment",
  role: "row kind", shaded: "shading", line_below: "line below", width: "width", frame: "frame", font_pt: "font size",
};

export interface UnsureItem {
  /** Where the look sits, as the selection that shows it. */
  sel: Exclude<NoteSelection, null>;
  level: "block" | "table" | "column" | "row" | "cell";
  key: string;
  what: string;
}

/** Every look the agent could not tell from the page, in reading order. */
export function unsureItems(blocks: NoteBlock[]): UnsureItem[] {
  const out: UnsureItem[] = [];
  const word = (k: string) => LOOK_WORD[k] ?? k;
  blocks.forEach((b, i) => {
    if (b.kind !== "table") {
      for (const key of b.look.unsure) out.push({ sel: { kind: "block", block: i }, level: "block", key, what: `${BLOCK_WORD[b.kind]}, ${word(key)}` });
      return;
    }
    const at = (row: number, column: number, scope: Scope) => ({ kind: "table" as const, block: i, row, column, scope });
    for (const key of b.unsure) out.push({ sel: at(0, 0, "table"), level: "table", key, what: `Table, ${word(key)}` });
    b.columns.forEach((col, c) => {
      for (const key of col.unsure) out.push({ sel: at(0, c, "column"), level: "column", key, what: `Column ${columnName(b, c) || c + 1}, ${word(key)}` });
    });
    b.rows.forEach((row, r) => {
      for (const key of row.unsure) out.push({ sel: at(r, 0, "row"), level: "row", key, what: `${rowName(b, r)}, ${word(key)}` });
      row.cells.forEach((cell, c) => {
        const col = columnName(b, c);
        for (const key of cell.look.unsure) out.push({ sel: at(r, c, "cell"), level: "cell", key, what: `${rowName(b, r)}${col ? `, ${col}` : ""}, ${word(key)}` });
      });
    });
  });
  return out.map((x) => ({ ...x, what: x.what.charAt(0).toUpperCase() + x.what.slice(1) }));
}

/** Keeps a "not sure" look as it is drawn: it is no longer listed as unsure. */
export function keepUnsure(blocks: NoteBlock[], item: UnsureItem): NoteBlock[] {
  const next = copyBlocks(blocks);
  const sel = item.sel;
  if (sel.kind !== "block" && sel.kind !== "table") return next;
  const b = next[sel.block];
  if (b.kind !== "table") b.look.unsure = drop(b.look.unsure, item.key);
  else if (sel.kind === "table") {
    if (item.level === "table") b.unsure = drop(b.unsure, item.key);
    if (item.level === "column") b.columns[sel.column].unsure = drop(b.columns[sel.column].unsure, item.key);
    if (item.level === "row") b.rows[sel.row].unsure = drop(b.rows[sel.row].unsure, item.key);
    if (item.level === "cell") {
      const look = b.rows[sel.row].cells[sel.column].look;
      look.unsure = drop(look.unsure, item.key);
    }
  }
  return next;
}

/** Whether a block, or a cell of a table, carries a "not sure" look: it shows a hollow ring. */
export function unsureAt(b: NoteBlock, row = 0, column = 0): boolean {
  if (b.kind !== "table") return b.look.unsure.length > 0;
  const r = b.rows[row];
  if (r.cells[column].look.unsure.length || r.unsure.length || b.columns[column].unsure.length) return true;
  return row === 0 && column === 0 && b.unsure.length > 0;
}

/** The "not sure" looks inside the current selection. */
export function unsureIn(blocks: NoteBlock[], sel: NoteSelection): UnsureItem[] {
  if (!sel || (sel.kind !== "block" && sel.kind !== "table")) return [];
  return unsureItems(blocks).filter((item) => {
    if (item.sel.kind === "gap" || item.sel.kind === "figure" || item.sel.block !== sel.block) return false;
    const b = blocks[sel.block];
    if (b.kind !== "table") return true;
    const mine = cellTargets(b, sel);
    return cellTargets(b, item.sel).some(([r, c]) => mine.some(([r2, c2]) => r === r2 && c === c2));
  });
}
