import { useEffect, useRef } from "react";
import type { Comment, Statement, StatementRow } from "../../api";
import { Segmented } from "../../components/Segmented";
import {
  cellPlace,
  commentMarks,
  hasValue,
  lineEntity,
  rowLabels,
  rowStatus,
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
  { value: "attention" as const, label: "Needs attention" },
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
  onSelect: (selection: Selection) => void;
  busy: boolean;
}

/** The statement as a grid: headings banded, totals with a rule, figures in the mono font. */
export function StatementGrid({ statement, order, filter, onOrder, onFilter, comments, changed, selection, onSelect, busy }: StatementGridProps) {
  const name = statement ? statementName(statement.statement, statement.variant) : "";
  const body = useRef<HTMLDivElement>(null);

  // A figure opened from a list is brought into view.
  useEffect(() => {
    body.current?.querySelector(".v.sel, tr.rsel")?.scrollIntoView?.({ block: "nearest" });
  }, [selection, statement]);
  const head = (
    <div className="wh">
      <h2>{name}</h2>
      <span className="spacer" />
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
  const rows = filter === "all" ? statement.rows : statement.rows.filter((r) => r.kind !== "heading" && attention(r));
  const empty = filter === "attention" ? "Nothing needs attention" : busy ? "Figures appear here as the agent saves them" : "No figures";

  return (
    <>
      {head}
      <div className="wb" ref={body}>
        {rows.length === 0 ? (
          <div className="empty">{empty}</div>
        ) : (
          <FigureTable
            columns={statement.columns}
            rows={rows}
            first={order === "report" ? "Line in report" : "Template field"}
            labels={(row) => rowLabels(row, order)}
            isOn={(row, column) => sameCell(selection, cellPlace(statement, row, column))}
            cellMarked={(row, column) => marks.cell(cellPlace(statement, row, column))}
            lineMarked={(row) => marks.line(row.concept_uuid, lineEntity(statement, row))}
            lineSelected={(row) => selection?.kind === "line" && selection.concept_uuid === row.concept_uuid && selection.entity_scope === lineEntity(statement, row)}
            status={(row) => rowStatus(statement, row, changed)}
            faint={(row) => order === "template" && !hasValue(row)}
            onLine={(row) => onSelect({ kind: "line", statement: statement.statement, concept_uuid: row.concept_uuid, entity_scope: lineEntity(statement, row) })}
            onCell={(row, column) => onSelect({ kind: "cell", ...cellPlace(statement, row, column) })}
          />
        )}
      </div>
    </>
  );
}
