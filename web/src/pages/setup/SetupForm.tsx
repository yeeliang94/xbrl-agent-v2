import { useRef, useState, type MouseEvent } from "react";
import { api, errorMessage, type DocumentMap, type Finding, type ScopeChoice, type SetupQuestion, type Level, type RunDocument, type Standard, type SuggestedSetup, type Unit } from "../../api";
import { Panel } from "../../components/Panel";
import { Segmented } from "../../components/Segmented";
import { Select } from "../../components/Select";
import { Failure } from "../../components/Failure";
import { PageDialog } from "../../components/PagePicture";
import { QuestionCard } from "../../components/QuestionCard";
import { Switch } from "../../components/Switch";
import { TextInput } from "../../components/TextInput";
import { navigate } from "../../router";
import { SetupGuidance } from "../guidance/CompanyGuidance";
import { DocumentPanel, SetupHeader } from "./SetupParts";
import {
  choicesFor,
  initialForm,
  notePoints,
  statementName,
  toPayload,
  withIncluded,
  withLayout,
  withStandard,
  type SetupForm as Form,
  type StatementRow,
} from "./setupModel";
import { NotesPanel, SourcePanel, StatementPanel } from "./SidePanels";
import { StartingWorkbookPanel } from "./StartingWorkbookPanel";
import { Unsure } from "./Unsure";

const STANDARDS = [
  { value: "MFRS" as Standard, label: "MFRS" },
  { value: "MPERS" as Standard, label: "MPERS" },
];
const LEVELS = [
  { value: "Company" as Level, label: "Company" },
  { value: "Group" as Level, label: "Group" },
];
const UNITS = [
  { value: "RM", label: "RM" },
  { value: "RM'000", label: "RM thousands" },
];

type Selected = number | "notes" | null;

function Label({ text, finding }: { text: string; finding?: Finding }) {
  return (
    <span>
      {text}
      {finding?.unsure && <Unsure reason={finding.reason} />}
    </span>
  );
}

/** Clicks on a line's own controls do not also open its side panel. */
const fromControl = (event: MouseEvent) => (event.target as HTMLElement).closest("select, button, input") !== null;

/** The setup form after a question card's choice: the field it asks about takes the chosen value.
 * A layout choice says what it sets: the layout and whether the statement is switched on. */
function answered(form: Form, card: SetupQuestion, choice: ScopeChoice): Form {
  const value = choice.value ?? "";
  switch (card.field) {
    case "standard":
      return withStandard(form, value as Standard);
    case "level":
      return { ...form, level: value as Level };
    case "unit":
      return { ...form, unit: value as Unit };
    case "layout":
      return {
        ...form,
        statements: form.statements.map((row) =>
          row.statement === card.statement ? { ...row, layout: choice.layout ?? row.layout, included: choice.included ?? row.included } : row,
        ),
      };
  }
}

export function SetupForm({ runId, document, setup, map }: { runId: number; document: RunDocument; setup: SuggestedSetup; map: DocumentMap }) {
  const [form, setForm] = useState<Form>(() => initialForm(setup, map));
  const [selected, setSelected] = useState<Selected>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<Set<number>>(new Set());
  const [page, setPage] = useState<number | null>(null);
  const formTop = useRef<HTMLDivElement>(null);
  const [workbookBusy, setWorkbookBusy] = useState(false);
  const cards = setup.questions ?? [];
  const waiting = cards.map((card, index) => ({ card, index })).filter(({ index }) => !done.has(index));
  const open = waiting[0];
  /** A field with an unanswered card stays locked until the card is answered. */
  const locked = (field: SetupQuestion["field"], statement: string | null = null) =>
    waiting.some(({ card }) => card.field === field && (field !== "layout" || card.statement === statement));
  const answer = (index: number, choice: ScopeChoice | null) => {
    if (choice !== null) setForm((old) => answered(old, cards[index], choice));
    setDone((old) => new Set(old).add(index));
  };
  const points = notePoints(map);
  const notesUnsure = points.length > 0 || form.notes.some((note) => !note.number);

  const setRow = (index: number, row: StatementRow) =>
    setForm((old) => ({ ...old, statements: old.statements.map((r, i) => (i === index ? row : r)) }));
  const pick = (next: Selected) => setSelected((old) => (old === next ? null : next));

  async function start() {
    setStarting(true);
    setError("");
    try {
      await api.confirmSetup(runId, toPayload(form));
      navigate({ name: "runs" });
    } catch (failure) {
      setError(errorMessage(failure));
      setStarting(false);
      // The refusal is drawn at the top of the form: bring it into view.
      formTop.current?.scrollTo?.({ top: 0 });
    }
  }

  let side = <SourcePanel />;
  if (selected === "notes") {
    side = <NotesPanel notes={form.notes} points={points} pageCount={document.page_count} onChange={(notes) => setForm((old) => ({ ...old, notes }))} />;
  } else if (selected !== null) {
    side = (
      <StatementPanel
        key={form.statements[selected].statement}
        runId={runId}
        row={form.statements[selected]}
        pageCount={document.page_count}
        onPages={(pages) => setRow(selected, { ...form.statements[selected], pages })}
      />
    );
  }

  return (
    <>
      <SetupHeader ready={form.company.trim() !== "" && form.yearEnd !== "" && waiting.length === 0 && !workbookBusy} starting={starting} onStart={start} />
      <div className="setup">
        <div className="setup-form" ref={formTop}>
          {error && <Failure label="Not started">{error}</Failure>}
          {open && (
            <QuestionCard
              key={open.index}
              question={open.card.question}
              evidence={open.card.reason ? [{ text: open.card.reason, pages: open.card.pages }] : []}
              choices={open.card.choices}
              onChoose={(i) => answer(open.index, open.card.choices[i])}
              // The person's own words leave the field for them to set by hand.
              onOther={() => answer(open.index, null)}
              onPage={setPage}
            />
          )}
          <DocumentPanel runId={runId} document={document} />
          <Panel title="Filing">
            <div className="g2">
              <label className="field">
                <Label text="Company" finding={setup.company} />
                <TextInput value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
              </label>
              <label className="field">
                <Label text="Year end" finding={setup.year_end} />
                <TextInput type="date" value={form.yearEnd} onChange={(e) => setForm({ ...form, yearEnd: e.target.value })} />
              </label>
              <div className="field">
                <Label text="Standard" finding={setup.standard} />
                <div>
                  <Segmented label="Standard" disabled={locked("standard")} options={STANDARDS} value={form.standard} onChange={(v) => setForm(withStandard(form, v))} />
                </div>
              </div>
              <div className="field">
                <Label text="Level" finding={setup.level} />
                <div>
                  <Segmented label="Level" disabled={locked("level")} options={LEVELS} value={form.level} onChange={(v) => setForm({ ...form, level: v })} />
                </div>
              </div>
              <label className="field">
                <Label text="Amounts in" finding={setup.unit} />
                <Select disabled={locked("unit")} options={UNITS} value={form.unit} onChange={(v) => setForm({ ...form, unit: v as Unit })} />
              </label>
            </div>
          </Panel>
          <StartingWorkbookPanel runId={runId} onBusy={setWorkbookBusy} />
          <Panel title="Statements">
            {form.statements.map((row, index) => {
              const name = statementName(row.statement, row.layout);
              const options = choicesFor(row, form.standard);
              return (
                <div
                  key={row.statement}
                  className={selected === index ? "line pick sel" : "line pick"}
                  onClick={(event) => !fromControl(event) && pick(index)}
                >
                  <span>
                    <button type="button" className="pick-name" aria-pressed={selected === index} onClick={() => pick(index)}>
                      {name}
                    </button>
                    {row.unsure && <Unsure reason={row.reason} />}
                  </span>
                  <span className="pg">{row.pages.length ? `p${row.pages[0]}` : ""}</span>
                  <div className="ctl">
                    <Select aria-label={`${name} layout`} disabled={locked("layout", row.statement)} options={options} value={row.layout} onChange={(v) => setRow(index, withLayout(row, v))} />
                  </div>
                  <Switch label={name} checked={row.included} onChange={(on) => setRow(index, withIncluded(row, on, form.standard))} />
                </div>
              );
            })}
            <div className={selected === "notes" ? "line pick sel" : "line pick"} onClick={(event) => !fromControl(event) && pick("notes")}>
              <span>
                <button type="button" className="pick-name" aria-pressed={selected === "notes"} onClick={() => pick("notes")}>
                  Notes
                </button>
                {notesUnsure && <Unsure />}
              </span>
              <span className="meta">{form.notes.length} notes</span>
              <Switch label="Notes" checked={form.notesIncluded} onChange={(on) => setForm({ ...form, notesIncluded: on })} />
            </div>
          </Panel>
          <SetupGuidance runId={runId} />
        </div>
        <div className="setup-side">{side}</div>
      </div>
      <PageDialog runId={runId} page={page} onClose={() => setPage(null)} />
    </>
  );
}
