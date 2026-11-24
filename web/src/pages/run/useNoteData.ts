import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage, type Note, type NoteBlock, type NoteField, type NoteReport, type NoteReview, type NoteSummary, type RunEvent } from "../../api";

export interface NoteData {
  notes: NoteSummary[];
  fields: NoteField[];
  reports: NoteReport[];
  /** The open note: its blocks, for selection and the toolbar. */
  note: Note | null;
  /** The open note's field text as review draws it: the prepared text, with marks. Null while it loads. */
  review: NoteReview | null;
  error: string;
  /** A look change or undo is on its way to the server: the next one waits for it. */
  looking: boolean;
  /** Whether this person may undo a look change they made to the open note. */
  canUndo: boolean;
  changeLook: (blocks: NoteBlock[]) => Promise<void>;
  undo: () => Promise<void>;
  moveTo: (noteId: number, nodeUuid: string | null) => Promise<void>;
  confirm: () => Promise<void>;
  leaveEmpty: (reportId: number) => Promise<void>;
  reopen: (reportId: number) => Promise<void>;
  reload: () => Promise<void>;
  /** Reads the open note's review text again. */
  refreshReview: () => Promise<void>;
}

/**
 * The run's notes, the open note and the changes a person makes to them.
 * Each change redraws the note at once, then from the server's answer, and
 * reads the list again so the labels and counts follow.
 */
/**
 * `filing` names the run's standard and level: a scope answer that changes them changes the note fields, so
 * the fields are read again then.
 */
export function useNoteData(runId: number, openId: number | null, events: RunEvent[], onRunChanged: () => Promise<void>, filing = ""): NoteData {
  const [notes, setNotes] = useState<NoteSummary[]>([]);
  const [fields, setFields] = useState<NoteField[]>([]);
  const [reports, setReports] = useState<NoteReport[]>([]);
  const [note, setNote] = useState<Note | null>(null);
  const [error, setError] = useState("");
  // This person's own look changes, by note, newest last: what Undo takes back.
  // Each list holds for one revision of its note only. Undo puts the whole
  // note back as it was, so once anything else changes the note (a field
  // change, Confirm, an agent) the list is dropped: Undo never takes that back.
  const undoable = useRef(new Map<number, { ids: number[]; revision: number }>());
  const [review, setReview] = useState<NoteReview | null>(null);
  // One look change or undo at a time, so the undo list and the note follow the server's order.
  const inFlight = useRef(false);
  const [looking, setLooking] = useState(false);
  const [, setVersion] = useState(0);
  const openRef = useRef(openId);
  openRef.current = openId;

  const loadList = useCallback(async () => {
    const [n, r] = await Promise.all([api.notes(runId), api.noteReports(runId)]);
    setNotes(n);
    setReports(r);
  }, [runId]);

  /** A note as the server now has it: the person's undo list is dropped if anything else changed it. */
  const seen = useCallback((n: Note) => {
    const mine = undoable.current.get(n.id);
    if (mine && mine.revision !== n.revision) undoable.current.delete(n.id);
    return n;
  }, []);

  const loadNote = useCallback(async () => {
    const id = openRef.current;
    if (id === null) return setNote(null);
    const found = await api.note(runId, id);
    if (openRef.current === id) setNote(seen(found));
  }, [runId, seen]);

  const reload = useCallback(async () => {
    try {
      await Promise.all([loadList(), loadNote()]);
      setError("");
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }, [loadList, loadNote]);

  useEffect(() => {
    api
      .noteFields(runId)
      .then(setFields)
      .catch((failure) => setError(errorMessage(failure)));
  }, [runId, filing]);

  useEffect(() => {
    setNote((old) => (old?.id === openId ? old : null));
    setReview((old) => (old?.note_id === openId ? old : null));
    loadNote().catch((failure) => setError(errorMessage(failure)));
  }, [openId, loadNote]);

  // The review text is the whole field's prepared text, so it is read again
  // whenever any note in the open note's field changes (another note in the
  // field can change its size tier), not only the open note. The open note
  // counts once, by its own revision, so one change reads the text once.
  const fieldUuid = note?.field?.node_uuid ?? null;
  const fieldKey = note
    ? [note.id, note.revision, fieldUuid ?? "", ...notes.filter((n) => n.id !== note.id && fieldUuid !== null && n.field?.node_uuid === fieldUuid).map((n) => `${n.id}.${n.revision}.${n.fit?.tier ?? ""}`)].join(":")
    : "";
  const refreshReview = useCallback(async () => {
    const id = openRef.current;
    if (id === null) return;
    try {
      const found = await api.noteReview(runId, id);
      if (openRef.current === id) setReview(found);
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }, [runId]);
  useEffect(() => {
    if (fieldKey) void refreshReview();
  }, [fieldKey, refreshReview]);

  // The notes agent's steps arrive as events with source "notes": each one reads the notes again.
  const noteEvents = events.filter((e) => e.source === "notes").length;
  useEffect(() => {
    void reload();
  }, [noteEvents, reload]);

  async function act(work: () => Promise<void>, before?: () => void, undoTo?: Note | null) {
    setError("");
    before?.();
    try {
      await work();
      await Promise.all([loadList(), onRunChanged()]);
    } catch (failure) {
      if (undoTo !== undefined) setNote(undoTo);
      setError(errorMessage(failure));
    }
  }

  const stack = (id: number) => undoable.current.get(id)?.ids ?? [];

  /** Runs one look change or undo; another that arrives meanwhile is refused, not raced. */
  async function oneAtATime(work: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setLooking(true);
    try {
      await work();
    } finally {
      inFlight.current = false;
      setLooking(false);
    }
  }

  async function changeLook(blocks: NoteBlock[]) {
    const was = note;
    if (!was) return;
    await oneAtATime(() =>
      act(
        async () => {
          const before = stack(seen(was).id);
          const { note: changed, history_id } = await api.setNoteLook(runId, was.id, blocks);
          // The server names the history row it wrote. Without that, this change gets no undo entry.
          undoable.current.set(was.id, { ids: history_id ? [...before, history_id] : before, revision: changed.revision });
          setNote(changed);
          setVersion((v) => v + 1);
        },
        () => setNote({ ...was, blocks }),
        was,
      ),
    );
  }

  async function undo() {
    const was = note;
    const ids = was ? stack(was.id) : [];
    if (!was || !ids.length) return;
    const last = ids[ids.length - 1];
    await oneAtATime(() =>
      act(async () => {
        const back = await api.undoNote(runId, was.id, last);
        undoable.current.set(was.id, { ids: ids.slice(0, -1), revision: back.revision });
        setNote(back);
        setVersion((v) => v + 1);
      }),
    );
  }

  async function moveTo(noteId: number, nodeUuid: string | null) {
    await act(async () => {
      const moved = seen((await api.setNoteField(runId, noteId, nodeUuid)).note);
      if (openRef.current === noteId) setNote(moved);
    });
  }

  async function confirm() {
    if (!note) return;
    const id = note.id;
    await act(async () => {
      setNote(seen(await api.confirmNote(runId, id)));
    });
  }

  const leaveEmpty = (reportId: number) => act(async () => void (await api.leaveFieldEmpty(runId, reportId)));
  const reopen = (reportId: number) => act(async () => void (await api.reopenField(runId, reportId)));

  return { notes, fields, reports, note, review, error, looking, refreshReview, canUndo: note !== null && stack(note.id).length > 0, changeLook, undo, moveTo, confirm, leaveEmpty, reopen, reload };
}
