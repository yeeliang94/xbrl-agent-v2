import type { SourceKind, StatementRow } from "../../api";
import { PagePicture } from "../../components/PagePicture";
import { SheetView } from "../../components/SheetGrid";

/** Where a figure or line comes from, said the same way everywhere (source-file-prototype.html):
 * a page; a reading-copy page for a Word run; a sheet, row or cell for an Excel run. */
export function sourcePlace(kind: SourceKind | undefined, row: StatementRow | null, page: number | null, cell?: string | null): string {
  const source = row?.source;
  if (kind === "excel" && source) {
    if (cell) return `${source.sheet}, cell ${cell}`;
    return source.row !== null ? `${source.sheet}, row ${source.row}` : source.sheet;
  }
  if (page === null) return "";
  return kind === "word" || kind === "excel" ? `Reading copy, page ${page}` : `Page ${page}`;
}

/** The "Source" line of a figure's or a line's detail, for a run that started from Word or Excel. A PDF
 * run's page shows above its picture, as before. */
export function SourceLine({ kind, place }: { kind: SourceKind | undefined; place: string }) {
  if ((kind !== "word" && kind !== "excel") || !place) return null;
  return (
    <div className="frow">
      <span>Source</span>
      <span>{place}</span>
    </div>
  );
}

/** The source itself: the sheet with the row or cell marked for an Excel run whose line was found on its
 * sheet, otherwise the page picture. */
export function SourceView({ runId, kind, row, page, cell = null }: { runId: number; kind: SourceKind | undefined; row: StatementRow | null; page: number | null; cell?: string | null }) {
  const source = row?.source;
  // A line not found among the sheet's cells (a statement pasted as a picture) is shown on its page.
  if (kind === "excel" && source && source.row !== null) {
    return <SheetView key={source.sheet} runId={runId} name={source.sheet} place={sourcePlace(kind, row, page, cell)} row={source.row} cell={cell} />;
  }
  return <PagePicture runId={runId} page={page} kind={kind} />;
}
