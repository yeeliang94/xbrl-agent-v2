import { useEffect, useRef, useState } from "react";
import { api, errorMessage, type Comment, type Note, type NoteFigures, type StatementRow } from "../../api";
import { Button } from "../../components/Button";
import { Icon } from "../../components/IconButton";
import { Segmented } from "../../components/Segmented";
import { Select } from "../../components/Select";
import { Status } from "../../components/Status";
import { FigureTable } from "./FigureTable";
import { fieldOptions, noteFlags, noteParts, NOT_PLACED } from "./noteList";
import { applyLook, lookNow, partCovers, toolsFor, type LookAction, type NoteSelection } from "./noteModel";
import { NotePaper, NoteSkeleton } from "./NotePaper";
import { NoteToolbar } from "./NoteToolbar";
import { isLive } from "./runModel";
import type { NoteData } from "./useNoteData";
import "./NoteWork.css";

export type NoteView = { kind: "note"; id: number } | { kind: "missing"; id: number } | { kind: "template"; templateId: string; name: string };

export interface NoteWorkProps {
  runId: number;
  data: NoteData;
  view: NoteView;
  sel: NoteSelection;
  onSelect: (sel: NoteSelection) => void;
  /** An agent works on the run: nothing can change. */
  busy: boolean;
  /** The notes agent is placing notes: notes show as a skeleton. */
  working: boolean;
  comments: Comment[];
  onOpenNote: (id: number) => void;
}

const COPIED_MS = 2000;

/** A note split into more parts than this picks its part from a dropdown, so the header keeps its room. */
const MAX_PART_BUTTONS = 3;

const NOT_COPIED = "The browser did not allow copying, so nothing was copied. Try again.";

/** The older way to copy: a copy event that carries both forms of the text. */
function copyByEvent(html: string, plain: string): boolean {
  const fill = (e: ClipboardEvent) => {
    e.clipboardData?.setData("text/html", html);
    e.clipboardData?.setData("text/plain", plain);
    e.preventDefault();
  };
  document.addEventListener("copy", fill);
  try {
    return document.execCommand("copy");
  } finally {
    document.removeEventListener("copy", fill);
  }
}

const STALE = "The field changed since it was drawn. It is drawn again now: check it, then copy.";

/**
 * Copies the field's prepared text as mTool gets it: HTML for the note editor, and plain text.
 * Only the revision on screen is copied; a newer one is drawn first, so nothing unseen is copied.
 */
async function copyPrepared(runId: number, noteId: number, shown: string | null, onStale: () => Promise<void>) {
  const prepared = await api.preparedNote(runId, noteId);
  if (prepared.revision !== shown) {
    await onStale();
    throw new Error(STALE);
  }
  const plain = new DOMParser().parseFromString(prepared.html, "text/html").body.textContent ?? "";
  try {
    if (typeof ClipboardItem === "undefined" || !navigator.clipboard?.write) throw new Error("No clipboard");
    await navigator.clipboard.write([new ClipboardItem({ "text/html": new Blob([prepared.html], { type: "text/html" }), "text/plain": new Blob([plain], { type: "text/plain" }) })]);
  } catch {
    if (!copyByEvent(prepared.html, plain)) throw new Error(NOT_COPIED);
  }
}

const figureUnsure = (row: StatementRow) => row.certainty === "unsure" || Object.values(row.cells).some((c) => c.certainty === "unsure");

function NoteFiguresTable({ figures, sel, comments, onSelect }: { figures: NoteFigures; sel: NoteSelection; comments: Comment[]; onSelect: NoteWorkProps["onSelect"] }) {
  const marked = new Set(comments.filter((c) => isLive(c) && c.target.kind === "figure").map((c) => c.target.figure_id));
  return (
    <div className="figs">
      <h3>Figures</h3>
      <FigureTable
        columns={figures.columns}
        rows={figures.rows}
        first="Line in note"
        labels={(row) => row.printed_label || row.label}
        isOn={(row, column) => sel?.kind === "figure" && sel.row === figures.rows.indexOf(row) && sel.column === column.key}
        cellMarked={(row, column) => marked.has(row.cells[column.key]?.figure_id ?? -1)}
        status={(row) => (figureUnsure(row) ? { kind: "attention", word: "Unsure" } : null)}
        onCell={(row, column) => onSelect({ kind: "figure", row: figures.rows.indexOf(row), column: column.key })}
      />
    </div>
  );
}

function CopyButton({ runId, note, shown, onStale, disabled }: { runId: number; note: Note; shown: string | null; onStale: () => Promise<void>; disabled: boolean }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => setCopied(false), [note.id]);
  async function copy() {
    setError("");
    try {
      await copyPrepared(runId, note.id, shown, onStale);
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), COPIED_MS);
    } catch (failure) {
      setError(failure instanceof Error && [NOT_COPIED, STALE].includes(failure.message) ? failure.message : errorMessage(failure));
    }
  }
  return (
    <>
      {error && (
        <span className="error" role="alert">
          {error}
        </span>
      )}
      <Button icon={<Icon name={copied ? "done" : "copy"} />} disabled={disabled} onClick={copy}>
        {copied ? "Copied" : "Copy for mTool"}
      </Button>
    </>
  );
}

/** The open note: its labels, field and Copy; the format toolbar; the note on the A4 page; figures for a numeric note. */
export function NoteWork({ runId, data, view, sel, onSelect, busy, working, comments, onOpenNote }: NoteWorkProps) {
  const { note } = data;
  const shown = view.kind === "note" && note?.id === view.id ? note : null;

  // Cmd or Ctrl+Z takes back the person's own last look change, outside a text field.
  const undoRef = useRef(() => {});
  undoRef.current = () => {
    if (!busy && data.canUndo) void data.undo();
  };
  useEffect(() => {
    if (view.kind !== "note") return;
    function onKey(e: KeyboardEvent) {
      const field = /^(TEXTAREA|INPUT|SELECT)$/.test((e.target as HTMLElement | null)?.tagName ?? "");
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === "z" && !field) {
        e.preventDefault();
        undoRef.current();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view.kind]);

  if (view.kind === "missing") {
    const report = data.reports.find((r) => r.id === view.id);
    return (
      <>
        <div className="wh">
          <h2>{report?.field_label ?? "Missing field"}</h2>
          {!working && report && (report.status === "settled" ? <Status kind="neutral">Left empty</Status> : <Status kind="attention">Missing</Status>)}
        </div>
        <div className="stage">
          <div className="a4 short">{working ? <NoteSkeleton lines={[60]} /> : <div className="empty">No note in the report fills this field</div>}</div>
        </div>
      </>
    );
  }

  if (view.kind === "template" || !shown) {
    const title = view.kind === "template" ? view.name : data.notes.find((n) => n.id === view.id)?.title ?? "";
    return (
      <>
        <div className="wh">
          <h2>{title}</h2>
        </div>
        <div className="stage">
          <div className="a4">{working ? <NoteSkeleton /> : view.kind === "note" ? <NoteSkeleton label="Loading the note" /> : <div className="empty">No notes in this template</div>}</div>
        </div>
      </>
    );
  }

  const flags = noteFlags(shown, data.reports);
  const parts = noteParts(data.notes, shown);
  const table = sel?.kind === "table" ? sel : null;
  const marks = comments.filter((c) => isLive(c) && c.author_kind === "person" && c.target.kind === "note" && c.target.note_id === shown.id && c.target.note_part);
  const marked = (block: number, row?: number, column?: number) => marks.some((c) => partCovers(c.target.note_part!, shown.blocks, block, row, column));
  const look = (action: LookAction) => {
    const next = applyLook(shown.blocks, sel, action);
    if (next) void data.changeLook(next);
  };
  const choose = (value: string) => {
    if (value.includes(":") || value === (shown.field?.node_uuid ?? NOT_PLACED)) return;
    void data.moveTo(shown.id, value || null);
  };

  return (
    <>
      <div className="wh note-head">
        <h2 title={shown.title}>{shown.title}</h2>
        {!working && (
          <>
            {flags.tooLong && <Status kind="failure">Too long for mTool</Status>}
            {flags.check && <Status kind="attention">Check formatting</Status>}
            {flags.placement && <Status kind="attention">Check field</Status>}
            {flags.gaps.length > 0 && <Status kind="attention">Gap in source</Status>}
            {flags.notPlaced && <Status kind="attention">Not placed</Status>}
            {!flags.tooLong && flags.tier && <Status kind="neutral">{flags.tier}</Status>}
          </>
        )}
        <div className="wh-tools">
          {parts.length > 1 && parts.length <= MAX_PART_BUTTONS && (
            <Segmented
              label="Part"
              options={parts.map((p) => ({ value: String(p.id), label: `Part ${p.part}` }))}
              value={String(shown.id)}
              onChange={(id) => onOpenNote(Number(id))}
            />
          )}
          {parts.length > MAX_PART_BUTTONS && (
            <Select
              className="part-select"
              aria-label="Part"
              options={parts.map((p) => ({ value: String(p.id), label: `Part ${p.part} of ${parts.length}` }))}
              value={String(shown.id)}
              onChange={(id) => onOpenNote(Number(id))}
            />
          )}
          <Select className="field-select" aria-label="Field" disabled={busy || working} options={fieldOptions(data.fields, shown.field)} value={shown.field?.node_uuid ?? NOT_PLACED} onChange={choose} />
          {(flags.check || flags.placement || flags.gaps.length > 0) && !busy && !working && <Button onClick={() => void data.confirm()}>Confirm</Button>}
          <CopyButton runId={runId} note={shown} shown={data.review?.note_id === shown.id ? data.review.revision : null} onStale={data.refreshReview} disabled={working || flags.tooLong || flags.notPlaced} />
        </div>
      </div>
      <NoteToolbar
        now={lookNow(shown.blocks, sel)}
        tools={toolsFor(shown.blocks, sel)}
        scope={table?.scope ?? null}
        canUndo={data.canUndo}
        disabled={busy || working || data.looking}
        onScope={(scope) => table && onSelect({ ...table, scope })}
        onLook={look}
        onUndo={() => void data.undo()}
      />
      {data.error && (
        <p className="work-note-error error" role="alert">
          {data.error}
        </p>
      )}
      <div className="stage">
        <div className={shown.figures && !working ? "a4 short" : "a4"}>
          {working ? <NoteSkeleton /> : <NotePaper note={shown} review={data.review?.note_id === shown.id ? data.review : null} sel={sel} gaps={flags.gaps} marked={marked} onSelect={onSelect} />}
        </div>
        {shown.figures && !working && <NoteFiguresTable figures={shown.figures} sel={sel} comments={comments} onSelect={onSelect} />}
      </div>
    </>
  );
}
