import { useEffect, useState } from "react";
import { api, errorMessage, type Cell, type Comment, type CommentScope, type Statement, type StatementColumn, type StatementRow } from "../../api";
import { Button } from "../../components/Button";
import { Segmented } from "../../components/Segmented";
import { Select } from "../../components/Select";
import { Status } from "../../components/Status";
import { TextInput } from "../../components/TextInput";
import { CommentBox } from "./CommentBox";
import { cellPlace, formatAmount, parseAmount, rowStatus, type Selection } from "./runModel";

export interface DetailProps {
  runId: number;
  statement: Statement;
  busy: boolean;
  changed: Set<string>;
  /** Template lines a figure may move to, by field. */
  fields: { value: string; label: string }[];
  agentComments: Comment[];
  onChanged: () => Promise<void>;
  onSelect: (selection: Selection) => void;
  onComment: (text: string, scope: CommentScope) => Promise<void>;
}

/** Done on an agent's comment, shown where it points. */
export function AgentComments({ runId, comments, onChanged }: { runId: number; comments: Comment[]; onChanged: () => Promise<void> }) {
  const [error, setError] = useState("");
  async function done(id: number) {
    setError("");
    try {
      await api.commentDone(runId, id);
      await onChanged();
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }
  return (
    <>
      {comments.map((c) => (
        <div className="cm" key={c.id}>
          <div className="dh">
            <span className="loc">Agent</span>
            <Button size="small" onClick={() => done(c.id)}>
              Done
            </Button>
          </div>
          <p>{c.text}</p>
        </div>
      ))}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

/** Move a figure, or a whole line, to another template field. */
export function FieldSelect({ runId, figureId, current, wholeRow, fields, onMoved }: { runId: number; figureId: number; current: string; wholeRow: boolean; fields: DetailProps["fields"]; onMoved: (to: string) => Promise<void> }) {
  const [error, setError] = useState("");
  if (!fields.length) return null;
  const options = fields.some((f) => f.value === current) ? fields : [{ value: current, label: "This field" }, ...fields];
  async function move(to: string) {
    if (to === current) return;
    setError("");
    try {
      await api.moveFigure(runId, figureId, to, wholeRow);
      await onMoved(to);
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }
  return (
    <>
      <div className="frow">
        <span>Field</span>
        <Select aria-label="Field" options={options} value={current} onChange={move} />
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

/** A figure imported from the starting workbook: where it came from, the report's comparative and,
 * while that differs, the one way a person settles it: keep the workbook's figure (step 10e). */
function FromWorkbook({ cell, busy, onKeep }: { cell: Cell; busy: boolean; onKeep: () => void }) {
  const lastYear = cell.origin === "prior_workbook";
  const compared = cell.comparison;
  return (
    <>
      <p className="why">{lastYear ? "Kept as filed in last year's workbook." : "Kept as a person typed it in the workbook."}</p>
      {compared && (
        <div className="kv">
          <span>{lastYear ? "Last year's workbook" : "Workbook"}</span>
          <span className="mono">{formatAmount(cell.value)}</span>
          <span>{compared.page ? `Report, page ${compared.page}` : "Report"}</span>
          <span className="mono">{formatAmount(compared.report_value)}</span>
        </div>
      )}
      {compared?.open && (
        <div className="bar">
          <Button size="small" disabled={busy} onClick={onKeep}>
            Keep the workbook's
          </Button>
        </div>
      )}
    </>
  );
}

/** One figure: its value (editable by a person), its field, the agent's doubts, and Right or Wrong. */
export function FigureDetail({ row, column, ...props }: DetailProps & { row: StatementRow; column: StatementColumn }) {
  const { runId, statement, busy, changed, fields, agentComments, onChanged, onSelect, onComment } = props;
  const cell = row.cells[column.key];
  const place = cellPlace(statement, row, column);
  const status = rowStatus(statement, row, changed);
  const fromWorkbook = cell?.origin === "prior_workbook" || cell?.origin === "typed_in_workbook";
  // A failure on the row wins; then an open difference with last year's workbook; then the row's own status.
  const shownStatus =
    status?.kind === "failure"
      ? status
      : cell?.comparison?.open
        ? { kind: "attention" as const, word: "Needs a person" }
        : status ?? (fromWorkbook ? { kind: "finished" as const, word: "From workbook" } : null);
  const editable = !busy && row.kind === "line" && (cell?.writable ?? true);
  const [verdict, setVerdict] = useState<"" | "right" | "wrong">("");
  const [typed, setTyped] = useState(formatAmount(cell?.value));
  const [error, setError] = useState("");
  // A figure with no source line (a blank template field, or one cleared of its line) needs its
  // page, and may take the line as printed, before the store will save it.
  const needsSource = editable && row.page === null;
  const [page, setPage] = useState("");
  const [printedAs, setPrintedAs] = useState("");

  useEffect(() => {
    setTyped(formatAmount(cell?.value));
    setError("");
  }, [cell?.value, cell?.figure_id]);

  useEffect(() => setVerdict(""), [place.concept_uuid, place.period, place.entity_scope]);

  async function act(work: () => Promise<unknown>) {
    setError("");
    try {
      await work();
      await onChanged();
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }

  function save() {
    const value = parseAmount(typed);
    if (value === undefined) {
      setError("Write the amount as a number, such as 1,234 or (1,234).");
      return;
    }
    if (value === (cell?.value ?? null)) return;
    let source: { page?: number; printed_label?: string } = {};
    if (needsSource) {
      const pageNumber = Number(page.trim());
      if (!Number.isInteger(pageNumber) || pageNumber < 1) {
        setError("Give the page this amount is printed on.");
        return;
      }
      source = { page: pageNumber, ...(printedAs.trim() ? { printed_label: printedAs.trim() } : {}) };
    } else if (!cell?.figure_id) {
      source = { page: row.page ?? undefined, printed_label: row.printed_label ?? row.label };
    }
    void act(() => api.editFigure(runId, { concept_uuid: place.concept_uuid, period: place.period, entity_scope: place.entity_scope, value, ...source }));
  }

  function choose(next: "right" | "wrong") {
    setVerdict(next);
    if (next === "right" && cell?.figure_id) void act(() => api.confirmFigure(runId, cell.figure_id!));
  }

  return (
    <div className="det">
      <div className="dh">
        <h3>{row.field_label}</h3>
        {shownStatus && <Status kind={shownStatus.kind}>{shownStatus.word}</Status>}
      </div>
      <div className="frow">
        <span>{column.label}</span>
        {editable ? (
          <TextInput
            className="mono num-in"
            aria-label={`${row.field_label}, ${column.label}`}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            // With no source yet, the amount waits for its page: it is saved with Save or Enter.
            onBlur={needsSource ? undefined : save}
            onKeyDown={(e) => e.key === "Enter" && save()}
          />
        ) : (
          <span className="mono">{formatAmount(cell?.value) || "-"}</span>
        )}
      </div>
      {needsSource && (
        <>
          <div className="frow">
            <span>Page</span>
            <TextInput className="mono page-in" inputMode="numeric" aria-label="Page" value={page} onChange={(e) => setPage(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} />
          </div>
          <div className="frow">
            <span>Printed as</span>
            <TextInput aria-label="Printed as" value={printedAs} onChange={(e) => setPrintedAs(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} />
          </div>
          <div className="bar">
            <span className="spacer" />
            <Button size="small" disabled={!typed.trim() || !page.trim()} onClick={save}>
              Save
            </Button>
          </div>
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {editable && cell?.figure_id && (
        <FieldSelect
          runId={runId}
          figureId={cell.figure_id}
          current={place.concept_uuid}
          wholeRow={false}
          fields={fields}
          onMoved={async (to) => {
            onSelect({ kind: "cell", ...place, concept_uuid: to, figure_id: null });
            await onChanged();
          }}
        />
      )}
      {cell?.certainty === "unsure" && cell.reason && <p className="why">{cell.reason}</p>}
      {cell && fromWorkbook && <FromWorkbook cell={cell} busy={busy} onKeep={() => cell.figure_id && void act(() => api.confirmFigure(runId, cell.figure_id!))} />}
      {cell?.lines_sum !== null && cell?.lines_sum !== undefined && cell.lines_sum !== cell.value && (
        <p className="why">The lines saved under it add up to {formatAmount(cell.lines_sum)}.</p>
      )}
      <AgentComments runId={runId} comments={agentComments} onChanged={onChanged} />
      {!busy && editable && cell?.figure_id && (
        <div className="frow">
          <span>This figure</span>
          <Segmented
            label="This figure"
            options={[
              { value: "right", label: "Right" },
              { value: "wrong", label: "Wrong" },
            ]}
            value={verdict}
            onChange={(v) => choose(v as "right" | "wrong")}
          />
        </div>
      )}
      {!busy && (verdict === "wrong" || !editable || !cell?.figure_id) && (
        <CommentBox
          chips
          scoped={row.kind === "line"}
          focus={verdict === "wrong"}
          onAdd={async (text, scope) => {
            await onComment(text, scope);
            setVerdict("");
          }}
        />
      )}
    </div>
  );
}
