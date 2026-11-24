import { Fragment } from "react";
import type { StatementColumn, StatementRow } from "../../api";
import { Status, type StatusKind } from "../../components/Status";
import { formatAmount } from "./runModel";

export interface FigureTableProps {
  columns: StatementColumn[];
  rows: StatementRow[];
  /** The first column's heading, such as "Line in report". */
  first: string;
  labels: (row: StatementRow) => [string, string];
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
}

/** The figures grid: headings banded, totals with a rule, figures in the mono font. */
export function FigureTable({ columns, rows, first, labels, isOn, cellMarked, lineMarked, lineSelected, status, faint, onLine, onCell }: FigureTableProps) {
  const width = columns.length > 2 ? "var(--grid-num-narrow-w)" : "var(--grid-num-w)";
  const span = columns.length + 2;
  return (
    <table className="grid">
      <thead>
        <tr>
          <th scope="col">{first}</th>
          {columns.map((c) => (
            <th key={c.key} scope="col" className="n" style={{ width }}>
              {c.label}
            </th>
          ))}
          <th scope="col" style={{ width: "var(--grid-status-w)" }}>
            <span className="visually-hidden">Status</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => {
          const key = `${row.concept_uuid}|${row.label}|${index}`;
          if (row.kind === "heading") {
            return (
              <Fragment key={key}>
                {index > 0 && (
                  <tr className="gap">
                    <td colSpan={span} />
                  </tr>
                )}
                <tr className="hd">
                  <td colSpan={span}>{row.label}</td>
                </tr>
              </Fragment>
            );
          }
          const [label, second] = labels(row);
          const shown = status(row);
          const classes = [row.kind === "total" ? "tot" : "", lineSelected?.(row) ? "rsel" : "", faint?.(row) ? "emp" : ""];
          const text = (
            <>
              <div>{label}</div>
              {second && <div className="l2">{second}</div>}
            </>
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
                      {formatAmount(row.cells[column.key]?.value)}
                    </button>
                  </td>
                );
              })}
              <td className="st">{shown && <Status kind={shown.kind}>{shown.word}</Status>}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
