import { useEffect, useState } from "react";
import { api, type Comment, type CommentScope, type Statement, type StatementCode } from "../../api";
import { Status } from "../../components/Status";
import { statementName } from "../setup/setupModel";
import { CommentBox } from "./CommentBox";
import { AgentComments, FieldSelect, FigureDetail, type DetailProps } from "./FigureDetail";
import { SourceLine, SourceView, sourcePlace } from "./SourceView";
import { cellPlace, commentIsOn, findCell, findLine, formatAmount, rowLabels, rowStatus, targetFor, type Selection } from "./runModel";

/** Template lines a figure may move to: loaded once per statement. */
function useFields(runId: number, code: StatementCode, wanted: boolean) {
  const [fields, setFields] = useState<{ code: StatementCode; list: DetailProps["fields"] } | null>(null);
  useEffect(() => {
    if (!wanted || fields?.code === code) return;
    let live = true;
    api.statement(runId, code, "template").then(
      (s) => live && setFields({ code, list: s.rows.filter((r) => r.kind === "line").map((r) => ({ value: r.concept_uuid, label: r.field_label })) }),
      () => live && setFields({ code, list: [] }),
    );
    return () => {
      live = false;
    };
  }, [runId, code, wanted, fields?.code]);
  return fields?.code === code ? fields.list : [];
}

export interface SourceTabProps {
  runId: number;
  statement: Statement;
  selection: Selection;
  /** Why this figure was opened from Needs you or Checks, said above it. */
  why?: string | null;
  comments: Comment[];
  busy: boolean;
  changed: Set<string>;
  onSelect: (selection: Selection) => void;
  onChanged: () => Promise<void>;
}

/** The Source tab: the selected figure, line or statement, then its page. */
export function SourceTab({ runId, statement, selection, why, comments, busy, changed, onSelect, onChanged }: SourceTabProps) {
  const found = findCell(statement, selection);
  const line = findLine(statement, selection);
  const fields = useFields(runId, statement.statement, !busy && (found !== null || line !== null));
  const agentComments = comments.filter((c) => c.author_kind === "agent" && c.status === "open" && commentIsOn(c, selection));
  const kind = statement.source_kind;
  const firstRow = statement.rows.find((r) => r.page !== null) ?? null;
  const firstPage = firstRow?.page ?? null;
  // A line with no page of its own shows the statement's first page or sheet, with nothing marked on it.
  const fallback = firstRow?.source ? { ...firstRow, source: { ...firstRow.source, row: null } } : firstRow;

  async function comment(text: string, scope: CommentScope) {
    await api.addComment(runId, { target: targetFor(found || line ? selection : null, statement.statement), text, ...(found || line ? { scope } : {}) });
    await onChanged();
  }

  const props: DetailProps = { runId, statement, busy, changed, fields, agentComments, onChanged, onSelect, onComment: comment };

  if (found) {
    return (
      <>
        {why && <p className="why">{why}</p>}
        <FigureDetail key={`${found.row.concept_uuid}|${found.column.key}`} row={found.row} column={found.column} {...props} />
        <SourceView runId={runId} kind={kind} row={found.row.page !== null ? found.row : fallback} page={found.row.page ?? firstPage} cell={found.row.cells[found.column.key]?.source_cell ?? null} />
      </>
    );
  }

  if (line) {
    const status = rowStatus(statement, line, changed);
    const [, second] = rowLabels(line, "template");
    const withFigure = statement.columns.map((c) => cellPlace(statement, line, c)).find((p) => p.figure_id !== null);
    return (
      <>
        {why && <p className="why">{why}</p>}
        <div className="det">
          <div className="dh">
            <h3>{line.field_label}</h3>
            {status && <Status kind={status.kind}>{status.word}</Status>}
          </div>
          {second && (
            <div className="frow">
              <span>In report</span>
              <span>{line.printed_label}</span>
            </div>
          )}
          {statement.columns.map((c) => (
            <div className="frow" key={c.key}>
              <span>{c.label}</span>
              <span className="mono">{formatAmount(line.cells[c.key]?.value) || "-"}</span>
            </div>
          ))}
          {!busy && line.kind === "line" && withFigure && (
            <FieldSelect
              runId={runId}
              figureId={withFigure.figure_id!}
              current={line.concept_uuid}
              wholeRow
              fields={fields}
              onMoved={async (to) => {
                onSelect({ kind: "line", statement: statement.statement, concept_uuid: to, entity_scope: withFigure.entity_scope });
                await onChanged();
              }}
            />
          )}
          <SourceLine kind={kind} place={sourcePlace(kind, line, line.page)} />
          <AgentComments runId={runId} comments={agentComments} onChanged={onChanged} />
          {!busy && <CommentBox chips scoped={line.kind === "line"} onAdd={comment} />}
        </div>
        <SourceView runId={runId} kind={kind} row={line.page !== null ? line : fallback} page={line.page ?? firstPage} />
      </>
    );
  }

  return (
    <>
      {why && <p className="why">{why}</p>}
      {!busy && (
        <div className="det">
          <div className="dh">
            <h3>{statementName(statement.statement, statement.variant)}</h3>
          </div>
          <SourceLine kind={kind} place={firstRow?.source ? firstRow.source.sheet : sourcePlace(kind, null, firstPage)} />
          <CommentBox onAdd={comment} />
        </div>
      )}
      <SourceView runId={runId} kind={kind} row={fallback} page={firstPage} />
    </>
  );
}
