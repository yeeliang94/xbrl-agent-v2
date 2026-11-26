import type { ReactNode } from "react";
import "./Table.css";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  /** Numbers are right-aligned. */
  align?: "left" | "right";
  muted?: boolean;
  /** Keeps the cell on one line, e.g. a page range. */
  nowrap?: boolean;
  /** Long text on one line, cut with an ellipsis where the column ends. */
  cut?: boolean;
  /** A fixed column width, e.g. "24%". Columns without one share what is left. */
  width?: string;
}

export interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  /** Which rows open something. Without it, every row does when onRowClick is given. */
  rowClickable?: (row: T) => boolean;
  /** The row whose detail is open beside the table. */
  selected?: (row: T) => boolean;
  /** False leaves out the header row. */
  header?: boolean;
  /** Shown in place of the rows when there are none. */
  empty?: ReactNode;
}

/** No row or vertical lines. Only a row that opens something looks clickable. */
export function Table<T>({ columns, rows, rowKey, onRowClick, rowClickable, selected, header = true, empty }: TableProps<T>) {
  const clickable = (row: T) => onRowClick !== undefined && (rowClickable ? rowClickable(row) : true);
  return (
    <table className="tbl">
      {columns.some((column) => column.width) && (
        <colgroup>
          {columns.map((column) => (
            <col key={column.key} style={column.width ? { width: column.width } : undefined} />
          ))}
        </colgroup>
      )}
      {header && (
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} className={column.align === "right" ? "r" : undefined} scope="col">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
      )}
      <tbody>
        {rows.length === 0 && empty ? (
          <tr className="tbl-empty">
            <td colSpan={columns.length}>{empty}</td>
          </tr>
        ) : (
          rows.map((row) => {
            const opens = clickable(row);
            return (
              <tr key={rowKey(row)} className={[opens ? "click" : "", selected?.(row) ? "sel" : ""].filter(Boolean).join(" ") || undefined} onClick={opens ? () => onRowClick?.(row) : undefined}>
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={[column.align === "right" ? "r" : "", column.muted ? "meta" : "", column.nowrap ? "nw" : "", column.cut ? "cut" : ""].filter(Boolean).join(" ") || undefined}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            );
          })
        )}
      </tbody>
    </table>
  );
}
