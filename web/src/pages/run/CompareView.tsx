import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage, type Comparison, type StatementCode, type Difference, type DifferenceKind, type FigurePlace, type FilledWorkbook, type NotAssessed, type NoteDifference, type NotesComparison, type Score } from "../../api";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Segmented } from "../../components/Segmented";
import { Table, type Column } from "../../components/Table";
import { STATEMENT_NAMES, statementName, type Layouts } from "../setup/setupModel";
import { NOTE_KIND, fieldNames, noteKey } from "./CompareNoteSide";
import { formatAmount, placeName } from "./runModel";

const KIND: Record<DifferenceKind, string> = {
  extra: "Extra",
  sign_only: "Sign only",
  scale: "Scale",
  different: "Different",
  missing: "Missing",
  zero_left_blank: "Zero left blank",
};

/** 95% from 0.95. A score with nothing to divide by is a dash, never 0 or 100%. */
export const percent = (value: number | null) => (value === null ? "–" : `${Math.round(value * 1000) / 10}%`);

const nameOf = (code: string | null, layouts: Layouts) =>
  code && code in STATEMENT_NAMES ? statementName(code as StatementCode, layouts[code as StatementCode]) : "Outside the statements";

function Stats({ score, notes }: { score: Score; notes: NotesComparison | null }) {
  return (
    <div className={notes ? "stats two" : "stats"}>
      <div className="stat">
        <b>{percent(score.complete_and_accurate)}</b>
        <span>Complete and accurate</span>
      </div>
      <div className="stat">
        <b>{percent(score.completeness)}</b>
        <span>Completeness</span>
      </div>
      <div className="stat">
        <b>{percent(score.accuracy)}</b>
        <span>Accuracy</span>
      </div>
      {notes && (
        <div className="stat">
          <b>{percent(notes.score)}</b>
          <span>Notes in the same field</span>
        </div>
      )}
    </div>
  );
}

const scoreColumns = (layouts: Layouts): Column<{ statement: string; score: Score }>[] => [
  { key: "statement", header: "Statement", render: (s) => nameOf(s.statement, layouts) },
  { key: "filled", header: "Filled", align: "right", render: (s) => <span className="mono">{s.score.person_filled}</span> },
  { key: "completeness", header: "Completeness", align: "right", render: (s) => <span className="mono">{percent(s.score.completeness)}</span> },
  { key: "accuracy", header: "Accuracy", align: "right", render: (s) => <span className="mono">{percent(s.score.accuracy)}</span> },
  { key: "both", header: "Complete and accurate", align: "right", render: (s) => <span className="mono">{percent(s.score.complete_and_accurate)}</span> },
];

const DIFF_COLUMNS: Column<Difference>[] = [
  { key: "field", header: "Field", render: (d) => placeName(d.field_label, d.period) },
  { key: "run", header: "Run", align: "right", render: (d) => <span className="mono">{formatAmount(d.run_value) || "-"}</span> },
  { key: "person", header: "Workbook", align: "right", render: (d) => <span className="mono">{formatAmount(d.person_value) || "-"}</span> },
  { key: "kind", header: "Kind", render: (d) => KIND[d.kind] ?? d.kind },
];

const mono = (value: number) => <span className="mono">{value}</span>;

const NOTE_COUNT_COLUMNS: Column<NotesComparison>[] = [
  { key: "workbook", header: "Notes in workbook", align: "right", render: (n) => mono(n.in_workbook) },
  { key: "same", header: "Same field", align: "right", render: (n) => mono(n.same_field) },
  { key: "different", header: "Different field", align: "right", render: (n) => mono(n.different_field) },
  { key: "missing", header: "Missing", align: "right", render: (n) => mono(n.missing) },
];

const NOTE_COLUMNS: Column<NoteDifference>[] = [
  { key: "note", header: "Note", render: (d) => d.title },
  { key: "run", header: "Run’s field", render: (d) => fieldNames(d.run_fields) || "–" },
  { key: "workbook", header: "Workbook’s field", render: (d) => fieldNames(d.workbook_fields) },
  { key: "kind", header: "Kind", nowrap: true, render: (d) => NOTE_KIND[d.kind] },
];

type CompareTab = "figures" | "notes";

const diffKey = (d: Difference) => `${d.kind}|${d.concept_uuid}|${d.period}|${d.entity_scope}|${d.dimension_key}|${d.matrix_col}`;

function FiguresTab({ comparison, layouts, onOpen }: { comparison: Comparison; layouts: Layouts; onOpen: (row: Difference | NotAssessed) => void }) {
  return (
    <>
      <Table columns={scoreColumns(layouts)} rows={comparison.statements} rowKey={(s) => s.statement} />
      <section className="det">
        <h3>Differences</h3>
        <Table columns={DIFF_COLUMNS} rows={comparison.differences} rowKey={diffKey} onRowClick={onOpen} empty={<p className="empty">No differences</p>} />
      </section>
      {comparison.totals.differences.length > 0 && (
        <section className="det">
          <h3>Totals</h3>
          <Table columns={DIFF_COLUMNS} rows={comparison.totals.differences} rowKey={diffKey} onRowClick={onOpen} />
        </section>
      )}
      {comparison.not_assessed.length > 0 && (
        <section className="det">
          <h3>Not assessed</h3>
          <Table
            columns={[
              { key: "statement", header: "Statement", render: (n: NotAssessed) => nameOf(n.statement, layouts) },
              { key: "sentence", header: "Why", render: (n: NotAssessed) => n.sentence },
            ]}
            rows={comparison.not_assessed}
            rowKey={(n) => `${n.reason}|${n.workbook_cell}|${n.concept_uuid}|${n.period}`}
            onRowClick={onOpen}
            rowClickable={(n) => n.concept_uuid !== null}
          />
        </section>
      )}
    </>
  );
}

function NotesTab({ notes, note, onNote }: { notes: NotesComparison | null; note: NoteDifference | null; onNote?: (note: NoteDifference | null) => void }) {
  if (!notes) return <p className="empty">The workbook has no notes</p>;
  return (
    <>
      <Table columns={NOTE_COUNT_COLUMNS} rows={[notes]} rowKey={() => "notes"} />
      <section className="det">
        <h3>Different field or missing</h3>
        <Table
          columns={NOTE_COLUMNS}
          rows={notes.differences}
          rowKey={noteKey}
          onRowClick={onNote}
          selected={(d) => note !== null && noteKey(d) === noteKey(note)}
          empty={<p className="empty">Every note is in the same field</p>}
        />
      </section>
    </>
  );
}

export interface CompareViewProps {
  runId: number;
  layouts?: Layouts;
  onOpen: (place: FigurePlace) => void;
  /** The note whose detail is open in the side panel. */
  note?: NoteDifference | null;
  onNote?: (note: NoteDifference | null) => void;
}

/** The run against a workbook a person filled for the same document: the scores, then each difference, figures and notes. */
export function CompareView({ runId, layouts = {}, onOpen, note = null, onNote }: CompareViewProps) {
  const [tab, setTab] = useState<CompareTab>("figures");
  const [workbook, setWorkbook] = useState<FilledWorkbook | null | undefined>(undefined);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const attached = await api.filledWorkbook(runId);
      setWorkbook(attached);
      setComparison(attached ? await api.comparison(runId) : null);
    } catch (failure) {
      setError(errorMessage(failure));
      setWorkbook((old) => (old === undefined ? null : old));
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(work: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    onNote?.(null);
    try {
      await work();
      setComparison(null);
      await load();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  const attach = (file: File | undefined) => file && void act(() => api.attachWorkbook(runId, file));
  const open = (d: Difference | NotAssessed) => onOpen({ statement: d.statement, concept_uuid: d.concept_uuid, period: d.period, entity_scope: d.entity_scope, figure_id: d.figure_id });

  return (
    <>
      <div className="wh">
        <h2>Compare</h2>
        {error && (
          <span className="error" role="alert">
            {error}
          </span>
        )}
        <span className="spacer" />
        {workbook && <span className="meta">{workbook.filename}</span>}
        {workbook && (
          <Button variant="quiet" size="small" disabled={busy} onClick={() => setRemoving(true)}>
            Remove
          </Button>
        )}
        {workbook !== undefined && (
          <Button size="small" disabled={busy} onClick={() => input.current?.click()}>
            {workbook ? "Replace" : "Attach workbook"}
          </Button>
        )}
        <input ref={input} type="file" hidden accept=".xlsx,.xlsm" aria-label="Filled workbook" onChange={(e) => attach(e.target.files?.[0])} />
      </div>
      <div className="wb compare">
        {workbook === undefined && <p className="empty">Loading the workbook</p>}
        {workbook === null && !busy && <p className="empty">No filled workbook</p>}
        {busy && <p className="empty">Reading the workbook</p>}
        {workbook && !comparison && !busy && !error && <p className="empty">Loading the comparison</p>}
        {comparison && !busy && (
          <>
            <Stats score={comparison.overall} notes={comparison.notes} />
            <div>
              <Segmented
                label="Compare"
                options={[
                  { value: "figures", label: "Figures", count: comparison.differences.length },
                  { value: "notes", label: "Notes", count: comparison.notes?.differences.length ?? 0 },
                ]}
                value={tab}
                onChange={(next) => {
                  setTab(next);
                  onNote?.(null);
                }}
              />
            </div>
            {tab === "notes" && <NotesTab notes={comparison.notes} note={note} onNote={onNote} />}
            {tab === "figures" && <FiguresTab comparison={comparison} layouts={layouts} onOpen={open} />}
          </>
        )}
      </div>
      <Dialog
        open={removing}
        title="Remove the filled workbook?"
        onClose={() => setRemoving(false)}
        actions={
          <>
            <Button variant="quiet" onClick={() => setRemoving(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                setRemoving(false);
                void act(() => api.removeWorkbook(runId));
              }}
            >
              Remove
            </Button>
          </>
        }
      >
        <p>The score goes with it. The run's figures are not changed.</p>
      </Dialog>
    </>
  );
}
