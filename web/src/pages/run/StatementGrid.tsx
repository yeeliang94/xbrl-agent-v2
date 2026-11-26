import { useEffect, useRef, useState } from "react";
import type { Comment, Statement, StatementRow } from "../../api";
import { Icon, IconButton } from "../../components/IconButton";
import { Segmented } from "../../components/Segmented";
import { Status } from "../../components/Status";
import { Switch } from "../../components/Switch";
import {
  cellPlace,
  commentMarks,
  gridRows,
  hasValue,
  lineEntity,
  rowStatus,
  ruled,
  sameCell,
  type Selection,
} from "./runModel";
import { statementName } from "../setup/setupModel";
import { FigureTable } from "./FigureTable";

export type Order = "report" | "template";
export type Filter = "all" | "attention";

const ORDERS = [
  { value: "report" as const, label: "Report" },
  { value: "template" as const, label: "Template" },
];
const FILTERS = [
  { value: "all" as const, label: "All" },
  { value: "attention" as const, label: "Needs you" },
];

export interface StatementGridProps {
  statement: Statement | null;
  order: Order;
  filter: Filter;
  onOrder: (order: Order) => void;
  onFilter: (filter: Filter) => void;
  comments: Comment[];
  changed: Set<string>;
  selection: Selection;
  /** The selection was opened from a list: the grid marks it briefly, and with `focus` gives it the
   * keyboard once for that opening. */
  arrival?: { id: number; focus: boolean } | null;
  onSelect: (selection: Selection) => void;
  /** Escape in the grid. */
  onClear: () => void;
  busy: boolean;
  /** Opens the question before this statement is filled again. Without it there is no Redo button. */
  onRedo?: () => void;
  /** The agent is filling this statement again. */
  redoing?: boolean;
  /** The figures kept through the redo, by id: their lines say so while it runs. */
  kept?: Set<number>;
}

/** The statement as a grid. Template order hides the empty fields unless asked. */
export function StatementGrid({ statement, order, filter, onOrder, onFilter, comments, changed, selection, arrival = null, onSelect, onClear, busy, onRedo, redoing = false, kept }: StatementGridProps) {
  const name = statement ? statementName(statement.statement, statement.variant) : "";
  const body = useRef<HTMLDivElement>(null);
  const [empties, setEmpties] = useState(false);

  // A figure opened from a list is brought into view, and takes the keyboard once per opening, in the
  // order it was opened in: a later refresh must not pull the keyboard back from, say, the comment box.
  const focused = useRef(0);
  useEffect(() => {
    const target = body.current?.querySelector(".v.sel, tr.rsel");
    target?.scrollIntoView?.({ block: "nearest" });
    const button = target?.querySelector<HTMLButtonElement>("button");
    if (arrival?.focus && button && statement?.order === order && focused.current !== arrival.id) {
      focused.current = arrival.id;
      button.focus({ preventScroll: true });
    }
  }, [selection, statement, order, arrival]);
  const head = (
    <div className="wh">
      <h2>{name}</h2>
      {redoing && <Status kind="working">Redoing</Status>}
      <span className="spacer" />
      {onRedo && !redoing && (
        <IconButton label="Redo statement" disabled={busy} onClick={onRedo}>
          <Icon name="redo" />
        </IconButton>
      )}
      {order === "template" && filter === "all" && (
        <span className="switch-with-label">
          Empty fields
          <Switch label="Empty fields" checked={empties} onChange={setEmpties} />
        </span>
      )}
      <Segmented label="Order" options={ORDERS} value={order} onChange={onOrder} />
      <Segmented label="Show" options={FILTERS} value={filter} onChange={onFilter} />
    </div>
  );
  if (!statement) return head;

  const marks = commentMarks(comments, statement.statement);
  const attention = (row: StatementRow) =>
    rowStatus(statement, row, changed) !== null ||
    marks.line(row.concept_uuid, lineEntity(statement, row)) ||
    statement.columns.some((c) => marks.cell(cellPlace(statement, row, c)));
  // An empty field still shows when it needs you or is the one selected.
  const selected = (row: StatementRow) =>
    (selection?.kind === "line" && selection.concept_uuid === row.concept_uuid) ||
    statement.columns.some((c) => sameCell(selection, cellPlace(statement, row, c)));
  const drawn = gridRows(statement.rows, order, empties, (row) => attention(row) || selected(row));
  const rows = filter === "all" ? drawn : drawn.filter((r) => r.kind !== "heading" && attention(r));
  const empty = filter === "attention" ? "Nothing needs you" : busy ? "Figures appear here as the agent saves them" : "No figures";

  return (
    <>
      {head}
      <div className="wb" ref={body}>
        {rows.length === 0 ? (
          <div className="empty">{empty}</div>
        ) : (
          <FigureTable
            arrived={arrival !== null}
            onClear={onClear}
            columns={statement.columns}
            rows={rows}
            first={order === "report" ? "Line in report" : "Template field"}
            labels={(row) => row.label}
            ruled={(row) => ruled(row, order)}
            isOn={(row, column) => sameCell(selection, cellPlace(statement, row, column))}
            cellMarked={(row, column) => marks.cell(cellPlace(statement, row, column))}
            lineMarked={(row) => marks.line(row.concept_uuid, lineEntity(statement, row))}
            lineSelected={(row) => selection?.kind === "line" && selection.concept_uuid === row.concept_uuid && selection.entity_scope === lineEntity(statement, row)}
            status={(row) =>
              redoing && kept && Object.values(row.cells).some((c) => c.figure_id !== null && kept.has(c.figure_id))
                ? { kind: "neutral", word: "Kept" }
                : rowStatus(statement, row, changed)
            }
            faint={(row) => order === "template" && !hasValue(row)}
            onLine={(row) => onSelect({ kind: "line", statement: statement.statement, concept_uuid: row.concept_uuid, entity_scope: lineEntity(statement, row) })}
            onCell={(row, column) => onSelect({ kind: "cell", ...cellPlace(statement, row, column) })}
          />
        )}
      </div>
    </>
  );
}
