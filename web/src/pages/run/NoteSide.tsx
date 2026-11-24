import { useEffect, useState, type ReactNode } from "react";
import { api, errorMessage, type Note, type NoteReport } from "../../api";
import { Button } from "../../components/Button";
import { PagePicture } from "../../components/PagePicture";
import { Segmented } from "../../components/Segmented";
import { Select } from "../../components/Select";
import { Status } from "../../components/Status";
import { CommentBox } from "./CommentBox";
import { noteFlags, noteName, TIER_WHY } from "./noteList";
import { cellTargets, keepUnsure, notePart, selectionName, unsureIn, unsureItems, type NoteSelection } from "./noteModel";
import { formatAmount } from "./runModel";
import type { NoteData } from "./useNoteData";
import type { NoteView } from "./NoteWork";

const NOTE_CHIPS = ["Columns misaligned", "Rows merged wrongly", "Text missing", "Heading level wrong", "Total line missing"];
const FIGURE_CHIPS = ["Recheck", "Wrong field", "Wrong category"];

export interface NoteSideProps {
  runId: number;
  data: NoteData;
  view: NoteView;
  sel: NoteSelection;
  onSelect: (sel: NoteSelection) => void;
  busy: boolean;
  working: boolean;
  onChanged: () => Promise<void>;
  onOpenNote: (id: number) => void;
}

const fmt = (n: number) => n.toLocaleString("en-US");

/** The PDF pages a selection's words come from; the whole note's pages with nothing selected. */
function sourcePages(note: Note, sel: NoteSelection): number[] {
  if (sel && (sel.kind === "block" || sel.kind === "table")) {
    const page = note.blocks[sel.block]?.source.page;
    if (page) return [page];
  }
  return note.pages;
}

function Pages({ runId, pages }: { runId: number; pages: number[] }) {
  return (
    <div className="pages">
      {pages.map((p) => (
        <PagePicture key={p} runId={runId} page={p} />
      ))}
    </div>
  );
}

/** A figure of a numeric note: its value, the line as printed, the agent's doubt, Right or Wrong. */
function FigureSide({ runId, note, sel, busy, onChanged }: { runId: number; note: Note; sel: Extract<NoteSelection, { kind: "figure" }>; busy: boolean; onChanged: () => Promise<void> }) {
  const row = note.figures?.rows[sel.row];
  const column = note.figures?.columns.find((c) => c.key === sel.column);
  const cell = row && column ? row.cells[column.key] : undefined;
  const [verdict, setVerdict] = useState("");
  const [error, setError] = useState("");
  useEffect(() => setVerdict(""), [sel.row, sel.column]);
  if (!row || !column) return null;
  const unsure = cell?.certainty === "unsure" ? cell.reason || row.reason : "";
  async function right() {
    setVerdict("right");
    if (!cell?.figure_id) return;
    setError("");
    try {
      await api.confirmFigure(runId, cell.figure_id);
      await onChanged();
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }
  async function comment(text: string) {
    if (!cell?.figure_id) return;
    await api.addComment(runId, { target: { kind: "figure", figure_id: cell.figure_id }, text });
    setVerdict("");
    await onChanged();
  }
  return (
    <div className="det">
      <div className="dh">
        <h3>{row.field_label}</h3>
        {unsure && <Status kind="attention">Unsure</Status>}
      </div>
      <div className="frow">
        <span>{column.label}</span>
        <span className="mono">{formatAmount(cell?.value) || "-"}</span>
      </div>
      {row.printed_label && row.printed_label !== row.field_label && (
        <div className="frow">
          <span>In note</span>
          <span>{row.printed_label}</span>
        </div>
      )}
      {unsure && <p className="why">{unsure}</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!busy && cell?.figure_id && row.kind !== "total" && (
        <div className="frow">
          <span>This figure</span>
          <Segmented label="This figure" options={[{ value: "right", label: "Right" }, { value: "wrong", label: "Wrong" }]} value={verdict} onChange={(v) => (v === "right" ? void right() : setVerdict(v))} />
        </div>
      )}
      {!busy && cell?.figure_id && (verdict === "wrong" || row.kind === "total") && <CommentBox chips={FIGURE_CHIPS} focus={verdict === "wrong"} onAdd={comment} />}
    </div>
  );
}

/** A mandatory field no note fills: why, a note to place in it, or leave it empty. */
function MissingSide({ runId, data, report, busy, onChanged, onOpenNote }: { runId: number; data: NoteData; report: NoteReport; busy: boolean; onChanged: () => Promise<void>; onOpenNote: (id: number) => void }) {
  if (report.status === "settled") {
    return (
      <div className="det">
        <div className="bar">
          <span>{`Left empty by ${report.settled_by ?? "a person"}`}</span>
          <span className="spacer" />
          {!busy && (
            <Button variant="quiet" size="small" onClick={() => void data.reopen(report.id)}>
              Undo
            </Button>
          )}
        </div>
      </div>
    );
  }
  const options = [{ value: "", label: "Choose a note" }, ...data.notes.map((n) => ({ value: String(n.id), label: noteName(n) }))];
  async function place(id: string) {
    if (!id || !report.node_uuid) return;
    await data.moveTo(Number(id), report.node_uuid);
    onOpenNote(Number(id));
  }
  async function comment(text: string) {
    await api.addComment(runId, { target: { kind: "statement", statement: "NOTES", report_id: report.id }, text });
    await onChanged();
  }
  return (
    <div className="det">
      <p className="why">{report.reason}</p>
      {!busy && (
        <>
          <div className="frow">
            <span>Place</span>
            <Select aria-label="Place" options={options} value="" onChange={(id) => void place(id)} />
          </div>
          <div className="bar">
            <span className="spacer" />
            <Button onClick={() => void data.leaveEmpty(report.id)}>Leave empty</Button>
          </div>
          <CommentBox onAdd={comment} />
        </>
      )}
    </div>
  );
}

/** The Source tab for a note: what is selected, why the note needs a look, Show or Keep, comments, and its pages. */
export function NoteSide({ runId, data, view, sel, onSelect, busy, working, onChanged, onOpenNote }: NoteSideProps) {
  if (view.kind === "missing") {
    const report = data.reports.find((r) => r.id === view.id);
    return report ? <MissingSide runId={runId} data={data} report={report} busy={busy || working} onChanged={onChanged} onOpenNote={onOpenNote} /> : null;
  }
  const note = view.kind === "note" && data.note?.id === view.id ? data.note : null;
  if (!note) return null;
  if (sel?.kind === "figure") {
    return (
      <>
        <FigureSide runId={runId} note={note} sel={sel} busy={busy} onChanged={onChanged} />
        <Pages runId={runId} pages={note.pages} />
      </>
    );
  }

  const flags = noteFlags(note, data.reports);
  const blocks = note.blocks;
  let info: ReactNode[] = [];
  if (sel?.kind === "gap") {
    const gap = flags.gaps.find((g) => g.id === sel.report);
    if (gap) info = [<p key="gap" className="why">{gap.reason}</p>];
  } else if (sel) {
    const b = blocks[sel.block];
    const double = b?.kind === "table" && sel.kind === "table" && (sel.scope === "cell" || sel.scope === "row") && cellTargets(b, sel).some(([r]) => b.rows[r].line_below?.style === "double");
    if (double) {
      const drawn = data.review?.double_underline === "single_bottom_border" ? "single" : "thick";
      info.push(<p key="double" className="why">{`Double underline shown as ${drawn} border`}</p>);
    }
    for (const item of unsureIn(blocks, sel)) info.push(<p key={`ns-${item.what}`} className="why">{`Not sure: ${item.what.toLowerCase()}.`}</p>);
  } else if (!working) {
    const fit = note.fit;
    if (fit && (flags.tooLong || flags.tier)) {
      info.push(
        <div key="size" className="frow">
          <span>Size</span>
          <span className="mono">{`${fmt(fit.chars)} of ${fmt(fit.limit)}`}</span>
        </div>,
      );
    }
    if (flags.tooLong) info.push(<p key="long" className="why">Over mTool's limit with all styling dropped. Nothing was cut.</p>);
    else if (fit && TIER_WHY[fit.tier]) info.push(<p key="tier" className="why">{TIER_WHY[fit.tier]}</p>);
    if (note.format_state !== "fine" && note.format_reason) info.push(<p key="reason" className="why">{note.format_reason}</p>);
    if (flags.placement) info.push(<p key="placement" className="why">{note.certainty_reason || "The notes agent was not sure this note belongs in this field."}</p>);
    for (const gap of flags.gaps) info.push(<p key={`gap-${gap.id}`} className="why">{gap.reason}</p>);
    unsureItems(blocks).forEach((item, i) =>
      info.push(
        <div key={`gl-${i}`} className="gl">
          <span>{item.what}</span>
          <Button variant="quiet" size="small" onClick={() => onSelect(item.sel)}>
            Show
          </Button>
          {!busy && (
            <Button size="small" onClick={() => void data.changeLook(keepUnsure(blocks, item))}>
              Keep
            </Button>
          )}
        </div>,
      ),
    );
  }

  async function comment(text: string) {
    await api.addComment(runId, { target: { kind: "note", note_id: note!.id, note_part: notePart(blocks, sel) }, text });
    await onChanged();
  }
  async function redo() {
    await api.addComment(runId, { target: { kind: "note", note_id: note!.id, note_part: null }, text: "Redo from source" });
    await onChanged();
  }
  const title = selectionName(blocks, sel);
  const chips = flags.tooLong ? ["Split into two fields", ...NOTE_CHIPS] : NOTE_CHIPS;

  return (
    <>
      <div className="det">
        {title && (
          <div className="dh">
            <h3>{title}</h3>
          </div>
        )}
        {info}
        {!busy && !working && <CommentBox chips={chips} onRedo={redo} onAdd={comment} />}
      </div>
      <Pages runId={runId} pages={sourcePages(note, sel)} />
    </>
  );
}
