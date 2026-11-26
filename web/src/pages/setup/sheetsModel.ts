// An Excel run's sheets at setup (go-live plan C6). The server keeps a statement's
// source as reading-copy pages, and each sheet is laid out on pages of its own,
// so choosing a sheet sets the statement's pages to that sheet's pages.
import type { MapNote, RunDocument, WorkbookSheet } from "../../api";
import { MAX_STATEMENT_PAGES } from "./setupModel";

/** The sheets laid out in the reading copy, in page order. */
export function usedSheets(document: RunDocument): WorkbookSheet[] {
  return (document.sheets ?? []).filter((s) => s.used && s.first_page !== null).sort((a, b) => a.first_page! - b.first_page!);
}

const onSheet = (sheet: WorkbookSheet, page: number) => sheet.first_page !== null && sheet.last_page !== null && sheet.first_page <= page && page <= sheet.last_page;

/** The sheets these pages are on, in page order. */
export function sheetsOf(document: RunDocument, pages: number[]): string[] {
  return usedSheets(document)
    .filter((s) => pages.some((p) => onSheet(s, p)))
    .map((s) => s.name);
}

/** A sheet's pages, cut to what a statement may take. */
export function sheetPages(sheet: WorkbookSheet): number[] {
  const out: number[] = [];
  for (let p = sheet.first_page ?? 0; p >= 1 && p <= (sheet.last_page ?? 0) && out.length < MAX_STATEMENT_PAGES; p += 1) out.push(p);
  return out;
}

/** The notes' sheets, in page order. */
export function noteSheets(document: RunDocument, notes: MapNote[]): string[] {
  const pages = notes.flatMap((n) => {
    const out: number[] = [];
    for (let p = n.first_page; p <= n.last_page; p += 1) out.push(p);
    return out;
  });
  return sheetsOf(document, pages);
}

/** Sheets no statement and no note is on: the hidden ones and any others the Reader did not use. */
export function sheetsNotUsed(document: RunDocument, statementPages: number[][], notes: MapNote[]): WorkbookSheet[] {
  const taken = new Set([...statementPages.flatMap((pages) => sheetsOf(document, pages)), ...noteSheets(document, notes)]);
  return (document.sheets ?? []).filter((s) => !taken.has(s.name));
}
