import type { KeyboardEvent } from "react";
import type { StatementColumn, StatementRow } from "../../api";
import { Status, type StatusKind } from "../../components/Status";
import { formatAmount } from "./runModel";

export interface FigureTableProps {
  columns: StatementColumn[];
  rows: StatementRow[];
  /** The first column's heading, such as "Line in report". */
  first: string;
  labels: (row: StatementRow) => string;
  /** A total drawn with a rule above its figures. */
  ruled?: (row: StatementRow) => boolean;
  isOn: (row: StatementRow, column: StatementColumn) => boolean;
  cellMarked: (row: StatementRow, column: StatementColumn) => boolean;
  lineMarked?: (row: StatementRow) => boolean;
  lineSelected?: (row: StatementRow) => boolean;
  status: (row: StatementRow) => { kind: StatusKind; word: string } | null;
  /** A row drawn faint: a template field with no value. */
  faint?: (row: StatementRow) => boolean;
  /** Without it, a line's label is not a button. */
  onLine?: (row: StatementRow) => void;
  onCell: (row: StatementRow, column: StatementColumn) => void;
  /** The selection was opened from a list: it is marked briefly. */
  arrived?: boolean;
  /** Escape clears the selection. */
  onClear?: () => void;
}

/** The arrow keys move from a focused figure or line to its neighbour and open it, skipping headings. */
function move(event: KeyboardEvent<HTMLTableSectionElement>, onClear?: () => void) {
  const cell = (event.target as HTMLElement).closest("td");
  const row = cell?.parentElement as HTMLTableRowElement | null;
  if (!cell || !row) return;
  // Escape clears the selection but keeps the keyboard where it is, so the arrows carry on from there.
  if (event.key === "Escape" && onClear) {
    event.preventDefault();
    onClear();
    return;
  }
  let target: HTMLTableCellElement | null | undefined = null;
  if (event.key === "ArrowLeft") target = cell.previousElementSibling as HTMLTableCellElement | null;
  else if (event.key === "ArrowRight") target = cell.nextElementSibling as HTMLTableCellElement | null;
  else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
    let next = (event.key === "ArrowUp" ? row.previousElementSibling : row.nextElementSibling) as HTMLTableRowElement | null;
    while (next?.classList.contains("hd")) next = (event.key === "ArrowUp" ? next.previousElementSibling : next.nextElementSibling) as HTMLTableRowElement | null;
    target = next?.cells[cell.cellIndex];
  } else return;
  const button = target?.querySelector<HTMLButtonElement>("button");
  if (!button) return;
  event.preventDefault();
  button.focus();
  button.click();
}

/** Above this many figure columns the table scrolls sideways and the line names stay pinned on the left. */
const WIDE = 4;

/** The figures grid: headings as text, totals in medium weight, figures in the mono font. No row lines:
 * space separates the rows. The figure columns share the panel's width, so they reach its right edge. */
export function FigureTable({ columns, rows, first, labels, ruled, isOn, cellMarked, lineMarked, lineSelected, status, faint, onLine, onCell, arrived = false, onClear }: FigureTableProps) {
  const wide = columns.length > WIDE;
  const span = columns.length + 1;
  // Few columns: each takes a share of the panel, so the figures widen with it and end at its right edge;
  // the table never gets narrower than the line names' minimum plus each figure's own minimum.
  const number = wide ? "var(--grid-num-narrow-w)" : `${Math.round(36 / columns.length)}%`;
  const each = wide ? "var(--grid-num-narrow-w)" : "var(--grid-num-w)";
  const floor = `calc(var(--grid-label-min-w) + ${columns.length} * ${each})`;
  return (
    <table className={["grid", wide ? "wide" : "", arrived ? "arrived" : ""].filter(Boolean).join(" ")} style={{ minWidth: floor }}>
      <thead>
        <tr>
          <th scope="col" className="lab">{first}</th>
          {columns.map((c) => (
            <th key={c.key} scope="col" className="n" style={{ width: number }}>
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody onKeyDown={(event) => move(event, onClear)}>
        {rows.map((row, index) => {
          const key = `${row.concept_uuid}|${row.label}|${index}`;
          if (row.kind === "heading") {
            return (
              <tr key={key} className={index === 0 ? "hd first" : "hd"}>
                <td colSpan={span}>{row.label}</td>
              </tr>
            );
          }
          const label = labels(row);
          const shown = status(row);
          const classes = [row.kind === "total" ? "tot" : "", ruled?.(row) ? "rule" : "", lineSelected?.(row) ? "rsel" : "", faint?.(row) ? "emp" : ""];
          // A row's status sits after its name, so the figures keep the panel's full width.
          const text = (
            <div>
              <span className="lab-name">{label}</span>
              {shown && (
                <span className="row-status">
                  <Status kind={shown.kind}>{shown.word}</Status>
                </span>
              )}
            </div>
          );
          return (
            <tr key={key} className={classes.filter(Boolean).join(" ") || undefined}>
              <td className={lineMarked?.(row) ? "lab mk" : "lab"}>
                {onLine ? (
                  <button type="button" className="lab-btn" onClick={() => onLine(row)}>
                    {text}
                  </button>
                ) : (
                  <div className="lab-btn lab-text">{text}</div>
                )}
              </td>
              {columns.map((column) => {
                const on = isOn(row, column);
                const cls = ["v", on ? "sel" : "", cellMarked(row, column) ? "mk" : ""].filter(Boolean).join(" ");
                return (
                  <td key={column.key} className={cls}>
                    <button type="button" className="cell-btn" aria-label={`${label}, ${column.label}`} aria-pressed={on} onClick={() => onCell(row, column)}>
                      <span>{formatAmount(row.cells[column.key]?.value)}</span>
                    </button>
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
