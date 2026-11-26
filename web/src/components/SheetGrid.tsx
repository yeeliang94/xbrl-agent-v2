import { useEffect, useState } from "react";
import { api, errorMessage, type SheetGrid as Grid } from "../api";
import "./SheetGrid.css";
import { PagePicture } from "./PagePicture";
import "./PagePicture.css";

/** A sheet of an Excel run's workbook, loaded once per run and name. `error` is one plain sentence. */
export function useSheet(runId: number, name: string | null): { sheet: Grid | null; error: string } {
  const [got, setGot] = useState<{ key: string; sheet: Grid | null; error: string } | null>(null);
  const key = `${runId}|${name ?? ""}`;
  useEffect(() => {
    if (name === null) return;
    let live = true;
    api.sheet(runId, name).then(
      (sheet) => live && setGot({ key, sheet, error: "" }),
      (failure) => live && setGot({ key, sheet: null, error: errorMessage(failure) }),
    );
    return () => {
      live = false;
    };
  }, [runId, name, key]);
  return got?.key === key ? got : { sheet: null, error: "" };
}

const NUMBER = /^\(?-?[\d][\d,]*(\.\d+)?\)?%?$|^[-–—]$/;

/** One sheet's filled cells as a grid with its column letters and row numbers, so a person names a cell
 * the way the agent does. `row` is drawn shaded, or `cell` (such as "B9") marked. */
export function SheetGrid({ sheet, row = null, cell = null }: { sheet: Grid; row?: number | null; cell?: string | null }) {
  return (
    <div className="sheet-scroll">
      <table className="sheet">
        <thead>
          <tr>
            <th />
            {sheet.columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sheet.rows.map((r) => (
            <tr key={r.row} className={r.row === row && cell === null ? "hl" : undefined}>
              <td className="rn">{r.row}</td>
              {sheet.columns.map((c) => {
                const text = r.cells[c] ?? "";
                const classes = [NUMBER.test(text.trim()) ? "n" : "", `${c}${r.row}` === cell ? "mk" : ""].filter(Boolean).join(" ");
                return (
                  <td key={c} className={classes || undefined} title={text || undefined}>
                    {text}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A sheet in its frame: where it sits in the workbook above the grid. A sheet with pictures on it (a
 * statement pasted as a picture) also shows its reading-copy pages, where the pictures are drawn. */
export function SheetView({ runId, name, place, row = null, cell = null }: { runId: number; name: string; place?: string; row?: number | null; cell?: string | null }) {
  const { sheet, error } = useSheet(runId, name);
  if (error)
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  if (!sheet) return null;
  return (
    <div className="pgwrap">
      <div className="pgh">
        <span>{place ?? sheet.name}</span>
        <span className="mono">
          Sheet {sheet.position} of {sheet.count}
        </span>
      </div>
      {sheet.rows.length > 0 && <SheetGrid sheet={sheet} row={row} cell={cell} />}
      {sheet.pictures > 0 &&
        Array.from({ length: sheet.last_page - sheet.first_page + 1 }, (_, i) => sheet.first_page + i).map((page) => (
          <PagePicture key={page} runId={runId} page={page} kind="excel" />
        ))}
    </div>
  );
}
