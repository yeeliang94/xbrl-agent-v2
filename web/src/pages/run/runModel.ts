// Plain helpers for the run screen: number formats, where a figure sits,
// row statuses and comment markers. No React here.
import type {
  Comment,
  CommentTarget,
  EntityScope,
  FigurePlace,
  Period,
  Run,
  RoundReport,
  Statement,
  StatementCode,
  StatementColumn,
  StatementRow,
} from "../../api";
import type { StatusKind } from "../../components/Status";

export const STATEMENT_ORDER: StatementCode[] = ["SOFP", "SOPL", "SOCI", "SOCF", "SOCIE"];

/** True while an agent works on the run: no edits or comments then. */
export const isBusy = (run: Run) => isExtracting(run) || run.status === "correcting";
/** Extraction is under way, or stopped to ask a scope question. */
export const isExtracting = (run: Run) => run.status === "ready" || run.status === "extracting" || run.status === "needs_answer";
export const extractionFailed = (run: Run) => run.status === "failed" && run.failed_stage === "extract";

/** 1,234 and (1,234) for a negative. A missing line is blank, never zero. */
export function formatAmount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const text = Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 2 });
  return value < 0 ? `(${text})` : text;
}

/** Reads what a person typed: "1,234", "(1,234)" or "-1234". Blank clears. Undefined when it is not a number. */
export function parseAmount(text: string): number | null | undefined {
  const raw = text.trim();
  if (raw === "" || raw === "-") return raw === "" ? null : undefined;
  const negative = /^\(.*\)$/.test(raw) || raw.startsWith("-");
  const digits = raw.replace(/[(),\s]/g, "").replace(/^-/, "");
  if (!/^\d+(\.\d+)?$/.test(digits)) return undefined;
  const value = Number(digits);
  return negative ? -value : value;
}

/** One figure's place: its field, period and entity. */
export interface CellPlace {
  statement: StatementCode;
  concept_uuid: string;
  period: Period;
  entity_scope: EntityScope;
  figure_id: number | null;
}

export type Selection =
  | ({ kind: "cell" } & CellPlace)
  | { kind: "line"; statement: StatementCode; concept_uuid: string; entity_scope: EntityScope }
  | null;

export function cellPlace(statement: Statement, row: StatementRow, column: StatementColumn): CellPlace {
  const cell = row.cells[column.key];
  return {
    statement: statement.statement,
    concept_uuid: cell?.concept_uuid ?? row.concept_uuid,
    period: column.period ?? row.period ?? "CY",
    entity_scope: column.entity_scope ?? row.entity_scope ?? "Company",
    figure_id: cell?.figure_id ?? null,
  };
}

export function lineEntity(statement: Statement, row: StatementRow): EntityScope {
  return row.entity_scope ?? statement.columns[0]?.entity_scope ?? "Company";
}

const cellKey = (p: { concept_uuid?: string | null; period?: Period | null; entity_scope?: EntityScope | null }) =>
  `${p.concept_uuid}|${p.period}|${p.entity_scope ?? "Company"}`;

export function sameCell(selection: Selection, place: CellPlace): boolean {
  if (!selection || selection.kind !== "cell" || selection.statement !== place.statement) return false;
  if (selection.figure_id !== null && place.figure_id !== null) return selection.figure_id === place.figure_id;
  return cellKey(selection) === cellKey(place);
}

/** A selection for something a list points at (a Needs you item, a check, a change). */
export function selectionFor(place: FigurePlace, fallback: StatementCode): Selection {
  if (!place.concept_uuid) return null;
  return {
    kind: "cell",
    statement: place.statement && place.statement !== "NOTES" ? place.statement : fallback,
    concept_uuid: place.concept_uuid,
    period: place.period ?? "CY",
    entity_scope: place.entity_scope ?? "Company",
    figure_id: place.figure_id ?? null,
  };
}

/** The cell a selection points at in a loaded statement, if it is shown. */
export function findCell(statement: Statement, selection: Selection): { row: StatementRow; column: StatementColumn } | null {
  if (!selection || selection.kind !== "cell") return null;
  for (const row of statement.rows) {
    if (row.kind === "heading") continue;
    for (const column of statement.columns) {
      if (sameCell(selection, cellPlace(statement, row, column))) return { row, column };
    }
  }
  return null;
}

export function findLine(statement: Statement, selection: Selection): StatementRow | null {
  if (!selection || selection.kind !== "line") return null;
  return statement.rows.find((r) => r.kind !== "heading" && r.concept_uuid === selection.concept_uuid) ?? null;
}

const plain = (text: string | null) => (text ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "");

/** The row's first line and, when the printed line and the field differ, the second. */
export function rowLabels(row: StatementRow, order: "report" | "template"): [string, string] {
  const printed = row.printed_label;
  if (!printed || plain(printed) === plain(row.field_label)) return [row.label, ""];
  return order === "report" ? [row.label, `Filed as ${row.field_label}`] : [row.label, `Printed as ${printed}`];
}

export const hasValue = (row: StatementRow) => Object.values(row.cells).some((c) => c.value !== null);

/** A line the report prints as a total: "Total assets", "Net cash from operating activities", "Profit for the year".
 * Read from the printed wording because the figures carry no "printed as a total" mark: the agent saves which
 * template field a line goes to, and a template total (such as "Total cash and cash equivalents") often holds
 * a plain printed line ("Cash and bank balances"). It only decides the drawn weight and rule, never a figure. */
const PRINTED_TOTAL = /^(total|net|gross|profit|loss)\b/i;

/** The rows as the grid draws them. Report order: the report's own section names, said once, and a line is
 * a total only where the report prints one (a template total such as "Total cash and cash equivalents" can
 * hold a plain printed line). Template order: empty fields left out unless asked for, and a heading kept
 * only where lines follow it (of headings in a row, the last, the closest one). */
export function gridRows(rows: StatementRow[], order: "report" | "template", empties = false,
                         keep: (row: StatementRow) => boolean = () => false): StatementRow[] {
  const out: StatementRow[] = [];
  if (order === "report") {
    let section = "";
    for (const row of rows) {
      if (row.kind === "heading") {
        // The section as the agent saved it, outermost first ("Current assets › Trade receivables"): its top.
        const name = row.label.split("›")[0].trim();
        if (name && name !== section) out.push({ ...row, label: name });
        section = name || section;
      } else {
        out.push(row.kind === "total" && !PRINTED_TOTAL.test(row.label.trim()) ? { ...row, kind: "line" } : row);
      }
    }
    return out;
  }
  let heading: StatementRow | null = null;
  let skipped = false;
  for (const row of rows) {
    if (row.kind === "heading") {
      // A block title of a many-column statement (its period or entity, from the server) is never replaced.
      if (heading && !heading.concept_uuid) out.push(heading);
      heading = row;
      skipped = false;
      continue;
    }
    if (!empties && !hasValue(row) && !row.status && !keep(row)) {
      skipped = true;
      continue;
    }
    // A total after a heading whose lines were all hidden closes an outer group, not that heading's.
    if (heading && row.kind === "total" && skipped && /^total\b/i.test(row.label.trim())) heading = null;
    if (heading) {
      const last = out[out.length - 1];
      if (last?.kind !== "heading" || last.label !== heading.label) out.push(heading);
      heading = null;
    }
    out.push(row);
  }
  return out;
}

/** A total drawn with a rule above its figures: every total the report prints; in template order, the fields
 * named "Total …" (a sub-sheet's total, such as property, plant and equipment, is medium weight only). */
export const ruled = (row: StatementRow, order: "report" | "template") =>
  row.kind === "total" && (order === "report" || /^total\b/i.test(row.label.trim()));

/** Cells the latest round changed, by field, period and entity. */
export function changedCells(report: RoundReport | null): Set<string> {
  const keys = new Set<string>();
  if (!report) return keys;
  for (const change of [...report.comments.flatMap((c) => c.figures), ...report.other]) {
    if (change.changed) keys.add(cellKey(change));
  }
  return keys;
}

export function rowStatus(statement: Statement, row: StatementRow, changed: Set<string>): { kind: StatusKind; word: string } | null {
  if (row.status === "does_not_tally") return { kind: "failure", word: "Does not tally" };
  if (row.status === "differs_from_report") return { kind: "attention", word: "Differs from report" };
  if (row.status === "unsure" || row.certainty === "unsure") return { kind: "attention", word: "Unsure" };
  if (statement.columns.some((c) => changed.has(cellKey(cellPlace(statement, row, c))))) return { kind: "neutral", word: "Changed" };
  if (row.status === "edited" || row.edited) return { kind: "neutral", word: "Edited" };
  return null;
}

/** A comment still in play: not accepted, undone or marked done. */
export const isLive = (c: Comment) => c.status !== "accepted" && c.status !== "undone" && c.status !== "done";

/** The orange dots: which cells and lines carry a live comment. */
export function commentMarks(comments: Comment[], statement: StatementCode) {
  const cells = new Set<string>();
  const lines = new Set<string>();
  let whole = false;
  for (const c of comments) {
    if (!isLive(c) || c.target.statement !== statement) continue;
    if (c.target.kind === "figure") cells.add(cellKey(c.target));
    if (c.target.kind === "line") lines.add(`${c.target.concept_uuid}|${c.target.entity_scope ?? "Company"}`);
    if (c.target.kind === "statement") whole = true;
  }
  return {
    cell: (p: CellPlace) => cells.has(cellKey(p)),
    line: (concept: string, entity: EntityScope) => lines.has(`${concept}|${entity}`),
    whole,
  };
}

/** The comment target for a selection, or the statement as a whole. */
export function targetFor(selection: Selection, statement: StatementCode): CommentTarget {
  if (!selection) return { kind: "statement", statement };
  if (selection.kind === "line") {
    return { kind: "line", statement: selection.statement, concept_uuid: selection.concept_uuid, entity_scope: selection.entity_scope };
  }
  if (selection.figure_id !== null) return { kind: "figure", figure_id: selection.figure_id };
  const { concept_uuid, period, entity_scope } = selection;
  return { kind: "figure", statement: selection.statement, concept_uuid, period, entity_scope };
}

/** Whether a comment points at this selection: the figure, or the line. */
export function commentIsOn(c: Comment, selection: Selection): boolean {
  if (!selection || c.target.statement !== selection.statement || c.target.concept_uuid !== selection.concept_uuid) return false;
  if (selection.kind === "line") return c.target.kind === "line";
  return c.target.kind === "figure" && c.target.period === selection.period && (c.target.entity_scope ?? "Company") === selection.entity_scope;
}

/** "Other payables, last year": a change or comment by field and period. */
export function placeName(field: string | null, period: Period | null): string {
  if (!field) return "";
  if (!period) return field;
  return `${field}, ${period === "CY" ? "this year" : "last year"}`;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** "01:12" between two times. */
export function clock(from: string | number, to: string | number): string {
  const seconds = Math.max(0, Math.round((new Date(to).getTime() - new Date(from).getTime()) / 1000));
  return `${pad(Math.floor(seconds / 60))}:${pad(seconds % 60)}`;
}
