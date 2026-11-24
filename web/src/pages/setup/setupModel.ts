// The setup form's values, made from the Reader's suggestion and turned into
// the payload of POST /api/runs/{id}/setup (docs/api-contract.md).
import type {
  ConfirmedSetup,
  DocumentMap,
  LayoutChoice,
  Level,
  MapNote,
  Standard,
  StatementCode,
  SuggestedSetup,
  SuggestedStatement,
  Unit,
} from "../../api";

export const NOT_PRINTED = "NotPrepared";

/** The order the prototype lists the statements in. */
export const DISPLAY_ORDER: StatementCode[] = ["SOFP", "SOPL", "SOCI", "SOCIE", "SOCF"];

export const STATEMENT_NAMES: Record<StatementCode, string> = {
  SOFP: "Financial position",
  SOPL: "Profit or loss",
  SOCI: "Comprehensive income",
  SOCIE: "Changes in equity",
  SOCF: "Cash flows",
};

/** Each statement's layout, by statement. */
export type Layouts = Partial<Record<StatementCode, string>>;

/** A statement's name, by its layout where the layout renames it: MPERS's
 * statement of retained earnings files in the changes-in-equity slot. */
export function statementName(code: StatementCode, layout?: string | null): string {
  return code === "SOCIE" && layout === "SoRE" ? "Retained earnings" : STATEMENT_NAMES[code];
}

export interface StatementRow {
  statement: StatementCode;
  layout: string;
  included: boolean;
  pages: number[];
  reason: string;
  unsure: boolean;
  /** The layouts under each standard, with their labels, as the server sends them. */
  choices: Record<Standard, LayoutChoice[]>;
}

/** The layouts a person may choose for this statement under a standard. */
export function choicesFor(row: StatementRow, standard: Standard): LayoutChoice[] {
  return row.choices[standard] ?? [];
}

const firstPrinted = (row: StatementRow, standard: Standard) =>
  choicesFor(row, standard).find((c) => c.value !== NOT_PRINTED)?.value ?? row.layout;

export interface SetupForm {
  company: string;
  yearEnd: string;
  standard: Standard;
  level: Level;
  unit: Unit;
  statements: StatementRow[];
  notesIncluded: boolean;
  notes: MapNote[];
}

function statementRow(found: SuggestedStatement, standard: Standard): StatementRow {
  const values = (found.layouts[standard] ?? []).map((c) => c.value);
  const layout = found.layout && values.includes(found.layout) ? found.layout : values[0];
  return {
    statement: found.statement,
    layout,
    // A statement that is not printed starts switched off.
    included: found.found && layout !== NOT_PRINTED,
    pages: found.pages,
    reason: found.reason,
    unsure: found.unsure,
    choices: found.layouts,
  };
}

export function initialForm(setup: SuggestedSetup, map: DocumentMap): SetupForm {
  const standard: Standard = setup.standard.value === "MPERS" ? "MPERS" : "MFRS";
  const byCode = new Map(setup.statements.map((s) => [s.statement, s]));
  return {
    company: setup.company.value ?? "",
    yearEnd: setup.year_end.value ?? "",
    standard,
    level: setup.level.value === "Group" ? "Group" : "Company",
    unit: setup.unit.value === "RM'000" ? "RM'000" : "RM",
    statements: DISPLAY_ORDER.filter((code) => byCode.has(code)).map((code) => statementRow(byCode.get(code)!, standard)),
    notesIncluded: true,
    notes: map.notes.map(({ number, title, first_page, last_page }) => ({ number, title, first_page, last_page })),
  };
}

/** A new standard keeps each layout that still exists, else the first choice. */
export function withStandard(form: SetupForm, standard: Standard): SetupForm {
  const statements = form.statements.map((row) => {
    const values = choicesFor(row, standard).map((c) => c.value);
    return values.includes(row.layout) ? row : { ...row, layout: values[0] };
  });
  return { ...form, standard, statements };
}

/** Choosing "Not printed" switches the statement off; choosing a layout from it switches it on. */
export function withLayout(row: StatementRow, layout: string): StatementRow {
  if (layout === NOT_PRINTED) return { ...row, layout, included: false };
  if (row.layout === NOT_PRINTED) return { ...row, layout, included: true };
  return { ...row, layout };
}

/** Switching on a not-printed statement picks its first real layout. */
export function withIncluded(row: StatementRow, included: boolean, standard: Standard): StatementRow {
  if (included && row.layout === NOT_PRINTED) return { ...row, included, layout: firstPrinted(row, standard) };
  return { ...row, included };
}

export function toPayload(form: SetupForm): ConfirmedSetup {
  return {
    company: form.company.trim(),
    year_end: form.yearEnd,
    standard: form.standard,
    level: form.level,
    unit: form.unit,
    statements: form.statements.map(({ statement, layout, included, pages }) => ({ statement, layout, included, pages })),
    notes_included: form.notesIncluded,
    notes: form.notes,
  };
}

/** Open points about the notes list. The one about the unit is left out. */
export function notePoints(map: DocumentMap): string[] {
  return map.open_points.filter((point) => !point.startsWith("The unit "));
}

/** A statement's pages typed as "12", "12-13" or "12, 14": each page once, in order, or null. */
export function parseStatementPages(text: string, pageCount: number): number[] | null {
  const pages = new Set<number>();
  for (const piece of text.split(",").map((p) => p.trim()).filter(Boolean)) {
    const range = parsePages(piece, pageCount);
    if (!range) return null;
    for (let page = range[0]; page <= range[1]; page += 1) pages.add(page);
  }
  return pages.size > 0 && pages.size <= MAX_STATEMENT_PAGES ? [...pages].sort((a, b) => a - b) : null;
}

/** The server takes at most this many pages per statement. */
export const MAX_STATEMENT_PAGES = 10;

/** "23" or "23-24" (or "23–24") as first and last page, or null. */
export function parsePages(text: string, pageCount: number): [number, number] | null {
  const found = text.trim().match(/^(\d+)(?:\s*[-–]\s*(\d+))?$/);
  if (!found) return null;
  const first = Number(found[1]);
  const last = found[2] ? Number(found[2]) : first;
  return first >= 1 && first <= last && last <= pageCount ? [first, last] : null;
}

export function pagesText(note: MapNote): string {
  return note.first_page === note.last_page ? `p${note.first_page}` : `p${note.first_page}–${note.last_page}`;
}

/** Adds a note, or replaces the note with the same number, keeping number order. */
export function addNote(notes: MapNote[], note: MapNote): MapNote[] {
  const rest = notes.filter((n) => !note.number || n.number !== note.number);
  const order = (n: MapNote) => (n.number === "" ? Number.POSITIVE_INFINITY : parseFloat(n.number));
  return [...rest, note].sort((a, b) => order(a) - order(b) || a.number.localeCompare(b.number));
}
