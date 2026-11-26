import { useState } from "react";
import { api, errorMessage, type MapNote, type RunDocument } from "../../api";
import { Button } from "../../components/Button";
import { Failure } from "../../components/Failure";
import { Panel } from "../../components/Panel";
import { Segmented } from "../../components/Segmented";
import { Select } from "../../components/Select";
import { SheetView } from "../../components/SheetGrid";
import { Status } from "../../components/Status";
import { Icon, IconButton } from "../../components/IconButton";
import { Table, type Column } from "../../components/Table";
import { notesCount, statementName, type StatementRow } from "./setupModel";
import { noteSheets, sheetPages, sheetsNotUsed, sheetsOf, usedSheets } from "./sheetsModel";

/** An Excel run's statement at setup: the sheet the Reader proposed, drawn as its cells, and a choice of
 * another sheet (source-file-prototype.html). */
export function SheetStatementPanel({ runId, document, row, onPages }: { runId: number; document: RunDocument; row: StatementRow; onPages: (pages: number[]) => void }) {
  const names = sheetsOf(document, row.pages);
  const [shown, setShown] = useState<string | null>(null);
  const current = shown !== null && names.includes(shown) ? shown : names[0] ?? null;
  const name = statementName(row.statement, row.layout);
  const sheets = usedSheets(document);
  const options = [...(current ? [] : [{ value: "", label: "Choose a sheet" }]), ...sheets.map((s) => ({ value: s.name, label: s.name }))];

  function choose(value: string) {
    const sheet = sheets.find((s) => s.name === value);
    if (!sheet) return;
    onPages(sheetPages(sheet));
    setShown(sheet.name);
  }

  return (
    <Panel className="sec">
      <div className="line">
        <h2>{name}</h2>
        <span className="meta mono">{current ?? "No sheet"}</span>
      </div>
      {current && row.reason && <p>{row.reason}</p>}
      {names.length > 1 && (
        <div>
          <Segmented label={`${name} sheets`} options={names.map((n) => ({ value: n, label: n }))} value={current ?? ""} onChange={setShown} />
        </div>
      )}
      {current && <SheetView key={current} runId={runId} name={current} />}
      <div className="line">
        <span>Sheet</span>
        <div className="ctl">
          <Select aria-label={`${name} sheet`} options={options} value={current ?? ""} onChange={choose} />
        </div>
      </div>
    </Panel>
  );
}

const NOT_USED = "";
export const NOTES_TARGET = "notes";

/** The notes' sheets with how many notes each holds; removing one drops its notes from the list. */
export function NoteSheets({ document, notes, onChange }: { document: RunDocument; notes: MapNote[]; onChange: (notes: MapNote[]) => void }) {
  const on = (sheet: string) => (n: MapNote) => sheetsOf(document, [n.first_page]).includes(sheet);
  const columns: Column<string>[] = [
    { key: "name", header: "Sheet", render: (s) => s },
    { key: "count", header: "Notes", align: "right", muted: true, render: (s) => notesCount(notes.filter(on(s)).length) },
    {
      key: "remove",
      header: "",
      render: (s) => (
        <IconButton label={`Do not use ${s}`} onClick={() => onChange(notes.filter((n) => !on(s)(n)))}>
          <Icon name="close" />
        </IconButton>
      ),
    },
  ];
  return <Table columns={columns} rows={noteSheets(document, notes)} header={false} rowKey={(s) => s} />;
}

/** The sheets no statement or note is on. A sheet in the reading copy can be given to a statement; a hidden
 * sheet is brought in first, which reads its new pages and comes back to setup. */
export function SheetsNotUsedPanel({ runId, document, statements, notes, onAssign, onRead }: {
  runId: number;
  document: RunDocument;
  statements: StatementRow[];
  notes: MapNote[];
  /** A statement's index, or `NOTES_TARGET`. */
  onAssign: (sheet: string, target: number | typeof NOTES_TARGET) => void;
  onRead: (document: RunDocument) => void;
}) {
  const [bringing, setBringing] = useState("");
  const [error, setError] = useState("");
  const left = sheetsNotUsed(document, statements.map((s) => s.pages), notes);
  const targets = [{ value: NOT_USED, label: "Not used" }, ...statements.map((s, i) => ({ value: String(i), label: statementName(s.statement, s.layout) })), { value: NOTES_TARGET, label: "Notes" }];

  async function bringIn(sheet: string) {
    setBringing(sheet);
    setError("");
    try {
      const { document: next } = await api.bringInSheet(runId, sheet);
      onRead(next);
    } catch (failure) {
      setError(errorMessage(failure));
      setBringing("");
    }
  }

  if (!document.sheets?.length) return null;
  return (
    <>
      {error && <Failure label="Not brought in">{error}</Failure>}
      <Panel title="Sheets not used">
        {left.length === 0 && <p className="meta">Every sheet is in use</p>}
        {left.map((sheet) => (
          <div className="line" key={sheet.name}>
            <span>{sheet.name}</span>
            <span className="meta">{sheet.hidden ? "Hidden sheet" : sheet.used ? "" : "Nothing on it"}</span>
            <div className="ctl">
              {sheet.used ? (
                <Select aria-label={`Use ${sheet.name} for`} options={targets} value={NOT_USED} onChange={(v) => v !== NOT_USED && onAssign(sheet.name, v === NOTES_TARGET ? NOTES_TARGET : Number(v))} />
              ) : sheet.hidden ? (
                bringing === sheet.name ? (
                  <Status kind="working">Bringing in</Status>
                ) : (
                  <Button size="small" disabled={bringing !== ""} onClick={() => void bringIn(sheet.name)}>
                    Bring in
                  </Button>
                )
              ) : null}
            </div>
          </div>
        ))}
      </Panel>
    </>
  );
}
