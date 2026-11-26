import type { NoteDifference, NoteFieldName } from "../../api";
import { Button } from "../../components/Button";
import { PagePicture } from "../../components/PagePicture";

export const NOTE_KIND: Record<NoteDifference["kind"], string> = {
  different_field: "Different field",
  missing: "Missing",
};

export const fieldNames = (fields: NoteFieldName[]) => fields.map((f) => f.label).join(", ");

export const noteKey = (d: NoteDifference) => `${d.kind}|${d.number}|${d.title}|${d.workbook_fields.map((f) => f.field_id).join(",")}`;

const pagesOf = (pages: number[]) => {
  const lo = Math.min(...pages);
  const hi = Math.max(...pages);
  return lo === hi ? `Page ${lo}` : `Pages ${lo} to ${hi}`;
};

/** A note the run placed in a different field from the workbook, or left out: both fields and its source page. */
export function CompareNoteSide({ runId, note, onClose, onOpenNote }: { runId: number; note: NoteDifference; onClose: () => void; onOpenNote: (noteId: number) => void }) {
  return (
    <div className="det">
      <div className="dh">
        <h3>{note.title}</h3>
        <Button variant="quiet" size="small" onClick={onClose}>
          Close
        </Button>
      </div>
      <div>
        <div className="frow">
          <span>Kind</span>
          <span>{NOTE_KIND[note.kind]}</span>
        </div>
        <div className="frow">
          <span>Run</span>
          <span>{fieldNames(note.run_fields) || "Not placed"}</span>
        </div>
        <div className="frow">
          <span>Workbook</span>
          <span>{fieldNames(note.workbook_fields)}</span>
        </div>
        {note.pages.length > 0 && (
          <div className="frow">
            <span>Source</span>
            <span>{pagesOf(note.pages)}</span>
          </div>
        )}
      </div>
      <PagePicture runId={runId} page={note.pages[0] ?? null} />
      {note.note_id !== null && (
        <div className="bar">
          <span className="spacer" />
          <Button onClick={() => onOpenNote(note.note_id!)}>Open note</Button>
        </div>
      )}
    </div>
  );
}
