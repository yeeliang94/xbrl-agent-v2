import { useRef, useState } from "react";
import { api, errorMessage, type NoteSummary } from "../../api";
import { noteTitle, type PlaceField } from "./placementModel";
import type { NoteData } from "./useNoteData";

export interface Done {
  text: string;
  noteId: number;
  historyId: number | null;
  /** The note's revision after this change. Undo holds only while the note is still at it. */
  revision: number;
}

export interface Placement {
  /** The last change, so it can be taken back. */
  done: Done | null;
  error: string;
  saving: boolean;
  /** Moves the note to the field, or out of its field with null. A move to the field it is in does nothing. */
  move: (note: NoteSummary, field: PlaceField | null) => Promise<void>;
  fieldIsRight: (note: NoteSummary, field: string) => Promise<void>;
  undo: () => Promise<void>;
  dismiss: () => void;
}

const name = (n: NoteSummary) => `${n.number} ${noteTitle(n)}`.trim();

/** Whether Undo of the last change still applies: nothing else has changed the note since. */
export const canUndo = (done: Done | null, notes: NoteSummary[]) =>
  !!done?.historyId &&
  notes.find((n) => n.id === done.noteId)?.revision === done.revision;

/** A person's changes on the placement map: move, take out, "Field is right", and undo of the last one. */
export function usePlacement(
  runId: number,
  notes: NoteData,
  onRunChanged: () => Promise<void>,
): Placement {
  const [done, setDone] = useState<Done | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  // One change at a time: a second click before the first returns is ignored, not sent.
  const inFlight = useRef(false);

  async function act(work: () => Promise<Done | null>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setSaving(true);
    setError("");
    try {
      setDone(await work());
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      inFlight.current = false;
      setSaving(false);
      await Promise.all([notes.reload(), onRunChanged()]).catch(
        () => undefined,
      );
    }
  }

  return {
    done,
    error,
    saving,
    move: async (note, field) => {
      if ((field?.id ?? null) === (note.field?.node_uuid ?? null)) return;
      await act(async () => {
        const r = await api.setNoteField(runId, note.id, field?.id ?? null);
        const text = field
          ? `Moved ${name(note)} to ${field.short}.`
          : `Took ${name(note)} out of its field.`;
        return {
          text,
          noteId: note.id,
          historyId: r.history_id ?? null,
          revision: r.note.revision,
        };
      });
    },
    fieldIsRight: (note, field) =>
      act(async () => {
        const r = await api.confirmField(runId, note.id);
        return {
          text: `Confirmed ${name(note)} belongs in ${field}.`,
          noteId: note.id,
          historyId: r.history_id,
          revision: r.note.revision,
        };
      }),
    undo: () =>
      act(async () => {
        if (canUndo(done, notes.notes))
          await api.undoNote(runId, done!.noteId, done!.historyId!);
        return null;
      }),
    dismiss: () => {
      setDone(null);
      setError("");
    },
  };
}
